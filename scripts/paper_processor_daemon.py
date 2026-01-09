#!/usr/bin/env python3
"""
Paper processor daemon - watches for new scanned papers and processes them.

Features:
- File watching with watchdog library
- Automatic metadata extraction
- Zotero integration
- Clean shutdown handling
- PID file management

Usage:
    python paper_processor_daemon.py [--debug]
"""

import sys
import time
import signal
import logging
import shutil
import configparser
import os
import json
import io
from typing import Optional, Tuple, List, Dict
import subprocess
import socket
import threading
import re
from pathlib import Path
try:
    import select
    HAS_SELECT = True
except ImportError:
    HAS_SELECT = False
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
from shared_tools.zotero.local_search import ZoteroLocalSearch
from shared_tools.utils.filename_generator import FilenameGenerator

# Import book lookup service for book chapters
from add_or_remove_books_zotero import DetailedISBNLookupService

# Import national library manager for thesis, book chapter, and book searches
from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
from shared_tools.utils.isbn_matcher import ISBNMatcher

# Import border remover for scanned documents
from shared_tools.pdf.border_remover import BorderRemover

# Import color utilities
from shared_tools.ui.colors import ColorScheme, Colors

# Import daemon modules
from shared_tools.daemon.service_manager import ServiceManager
from shared_tools.daemon.config_loader import SecureConfigLoader
from shared_tools.daemon.scanned_papers_logger import ScannedPapersLogger


class PaperProcessorDaemon:
    """Main daemon class."""
    
    def __init__(self, watch_dir: Path, debug: bool = False):
        """Initialize daemon.
        
        Args:
            watch_dir: Directory to watch for new PDFs
            debug: Enable debug logging
        """
        self.watch_dir = Path(watch_dir)
        self.pid_file = self.watch_dir / ".daemon.pid"
        self.publications_cache_file = self.watch_dir / ".publications_cache.json"
        self.publications_copy_count = 0  # Track PDF copies for cache refresh
        self.debug = debug
        
        # Setup logging first (needed for config loading)
        self.setup_logging()
        
        # Load configuration for publications directory
        self.load_config()
        
        # Initialize processors
        self.metadata_processor = PaperMetadataProcessor()
        self.zotero_processor = ZoteroPaperProcessor()
        
        # Initialize book lookup service (for book chapters)
        self.book_lookup_service = DetailedISBNLookupService()
        
        # Initialize national library manager (for thesis, book chapters, books)
        self.national_library_manager = ConfigDrivenNationalLibraryManager()
        
        # Initialize border remover (for dark border removal from scanned PDFs)
        # Note: border_max_width is set in load_config() which is called before this
        self.border_remover = BorderRemover({'max_border_width': self.border_max_width})
        
        # Initialize content detector (for content-aware border removal and gutter detection)
        from shared_tools.pdf.content_detector import ContentDetector
        self.content_detector = ContentDetector()
        
        # Initialize service manager (replaces direct service management)
        print("🚀 Initializing services...")
        self.service_manager = ServiceManager(self.config, logger=self.logger)
        
        # Initialize services using ServiceManager
        self._initialize_services()
        
        # Keep service state for backward compatibility (delegates to ServiceManager)
        self.grobid_ready = self.service_manager.grobid_ready
        self.ollama_ready = self.service_manager.ollama_ready
        self.grobid_client = self.service_manager.grobid_client
        self.ollama_process = self.service_manager.ollama_process
        
        # Window management
        self._terminal_window_handle = None  # Store terminal window handle for positioning
        
        # Initialize local Zotero search (read-only) - this is fast
        try:
            self.local_zotero = ZoteroLocalSearch()
            self.logger.info("✅ Connected to live Zotero database (read-only mode)")
        except Exception as e:
            self.logger.error(f"❌ Failed to connect to Zotero database: {e}")
            self.local_zotero = None
        
        # Initialize author validator for recognizing Zotero authors
        try:
            from shared_tools.utils.author_validator import AuthorValidator
            self.author_validator = AuthorValidator()
            # Refresh is now handled in __init__ if needed
            self.logger.info("✅ Author validator ready")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize author validator: {e}")
            self.author_validator = None
        
        # Initialize journal validator for recognizing Zotero journals
        try:
            from shared_tools.utils.journal_validator import JournalValidator
            self.journal_validator = JournalValidator()
            # Refresh is now handled in __init__ if needed
            self.logger.info("✅ Journal validator ready")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize journal validator: {e}")
            self.journal_validator = None
        
        # Load tag groups from configuration
        self.tag_groups = self._load_tag_groups()
        self.logger.debug(f"Loaded {len(self.tag_groups)} tag groups")
        
        # Setup signal handlers for clean shutdown
        signal.signal(signal.SIGINT, self.shutdown)
        signal.signal(signal.SIGTERM, self.shutdown)
        
        # Store terminal window handle for PDF viewer positioning
        self._store_terminal_window_handle()
        
        # Observer will be set in start()
        self.observer = None
    
    def load_config(self):
        """Load configuration with secure loader (supports environment variables)."""
        root_dir = Path(__file__).parent.parent
        
        # Use SecureConfigLoader for environment variable support
        config_loader = SecureConfigLoader(logger=self.logger if hasattr(self, 'logger') else None)
        self.config = config_loader.load_config(
            config_path=root_dir / 'config.conf',
            personal_config_path=root_dir / 'config.personal.conf',
            check_permissions=True
        )
        
        # Get publications directory - normalize to WSL path
        publications_path = self.config.get('PATHS', 'publications_dir', 
                                           fallback='/mnt/g/My Drive/publications')
        self.publications_dir = Path(self._normalize_path(publications_path))
        
        # Get Ollama configuration
        self.ollama_auto_start = self.config.getboolean('OLLAMA', 'auto_start', fallback=True)
        self.ollama_auto_stop = self.config.getboolean('OLLAMA', 'auto_stop', fallback=True)
        self.ollama_startup_timeout = self.config.getint('OLLAMA', 'startup_timeout', fallback=30)
        self.ollama_shutdown_timeout = self.config.getint('OLLAMA', 'shutdown_timeout', fallback=10)
        self.ollama_port = self.config.getint('OLLAMA', 'port', fallback=11434)
        
        # Get DAEMON configuration
        self.remote_check_host = self.config.get('DAEMON', 'remote_check_host', fallback='').strip()
        
        # Get GROBID configuration
        self.grobid_host = self.config.get('GROBID', 'host', fallback='localhost').strip()
        self.grobid_port = self.config.getint('GROBID', 'port', fallback=8070)
        self.grobid_auto_start = self.config.getboolean('GROBID', 'auto_start', fallback=True)
        self.grobid_auto_stop = self.config.getboolean('GROBID', 'auto_stop', fallback=True)
        self.grobid_container_name = self.config.get('GROBID', 'container_name', fallback='grobid')
        self.grobid_max_pages = self.config.getint('GROBID', 'max_pages', fallback=2)
        
        # Get border detection configuration
        self.border_max_width = self.config.getint('BORDER', 'max_border_width', fallback=600)
        
        # Get UX configuration
        self.page_offset_timeout = self.config.getint('UX', 'page_offset_timeout', fallback=10)
        self.prompt_timeout = self.config.getint('UX', 'prompt_timeout', fallback=10)
        
        # Check if publications directory is accessible
        self._validate_publications_directory()
        
        # Get log folder path from config
        log_folder = self.config.get('PATHS', 'log_folder', fallback='./data/logs')
        log_folder_path = Path(self._normalize_path(log_folder))
        # Initialize scanned papers CSV logger
        log_file = log_folder_path / 'scanned_papers_log.csv'
        self.scanned_papers_logger = ScannedPapersLogger(log_file)
    
    @staticmethod
    def _normalize_path(path_str: str) -> str:
        """Normalize a path string to WSL format (static method).
        
        Handles both WSL paths (/mnt/c/...) and Windows paths (C:\...)
        - Windows paths like "G:\My Drive\publications" -> "/mnt/g/My Drive/publications"
        - WSL paths already in correct format are returned as-is
        
        Args:
            path_str: Path string that may be in WSL or Windows format
            
        Returns:
            Normalized WSL path string
        """
        # Sanitize quotes and whitespace
        if path_str is None:
            return path_str
        path_str = path_str.strip().strip('"\'')
        path_str = path_str.replace('"', '').replace("'", '')
        
        # If already a WSL path (starts with /), normalize duplicate slashes and return
        if path_str.startswith('/'):
            while '//' in path_str:
                path_str = path_str.replace('//', '/')
            return path_str
        
        # If Windows path (contains : or starts with letter), convert to WSL
        if ':' in path_str or (len(path_str) > 1 and path_str[1].isalpha() and path_str[1] != ':'):
            # Handle Windows paths like "G:\My Drive\publications" or "G:/My Drive/publications"
            # Convert backslashes to forward slashes
            path_str = path_str.replace('\\', '/')
            
            # Extract drive letter (first character before :)
            if ':' in path_str:
                drive_letter = path_str[0].lower()
                # Remove drive letter and colon: "G:/My Drive/publications" -> "/My Drive/publications"
                remainder = path_str.split(':', 1)[1].lstrip('/')
                # Convert to WSL format: /mnt/g/My Drive/publications
                wsl_path = f'/mnt/{drive_letter}/{remainder}'
                while '//' in wsl_path:
                    wsl_path = wsl_path.replace('//', '/')
                return wsl_path
        
        # If no clear format, return as-is
        return path_str
    
    def _validate_publications_directory(self):
        """Validate that publications directory is accessible and handle setup.
        
        For cloud drives (accessed via PowerShell), we only validate that the path
        can be normalized. Actual file operations will use PowerShell which handles
        cloud drive access properly.
        """
        try:
            # Check if this is a cloud drive path (G: drive or other cloud drives)
            # Cloud drives are accessed via PowerShell, not directly from WSL
            path_str = str(self.publications_dir)
            is_cloud_drive = path_str.startswith('/mnt/g/') or 'My Drive' in path_str
            
            if is_cloud_drive:
                # For cloud drives, just verify the path can be normalized
                # Actual operations will use PowerShell which handles cloud access
                normalized = self._normalize_path(str(self.publications_dir))
                if normalized:
                    print(f"✅ Publications directory configured (cloud drive, will use PowerShell): {self.publications_dir}")
                    return
                else:
                    self._handle_missing_publications_directory()
                    return
            
            # For local paths, do full validation
            # Try to access the parent directory first
            parent_dir = self.publications_dir.parent
            if not parent_dir.exists():
                self._handle_missing_publications_directory()
                return
            
            # Check if we can write to the parent directory
            if not os.access(parent_dir, os.W_OK):
                self._handle_unwritable_publications_directory()
                return
                
            # Try to create the publications directory
            try:
                self.publications_dir.mkdir(parents=True, exist_ok=True)
            except Exception as e:
                self._handle_unwritable_publications_directory()
                return
            
            # Verify we can write to it
            test_file = self.publications_dir / '.daemon_test'
            try:
                test_file.write_text('test')
                test_file.unlink()
                print(f"✅ Publications directory accessible: {self.publications_dir}")
            except Exception as e:
                self._handle_unwritable_publications_directory()
                
        except Exception as e:
            # If it's a cloud drive, don't fail on WSL access errors
            path_str = str(self.publications_dir)
            is_cloud_drive = path_str.startswith('/mnt/g/') or 'My Drive' in path_str
            if is_cloud_drive:
                print(f"✅ Publications directory configured (cloud drive, will use PowerShell): {self.publications_dir}")
                return
            self._handle_missing_publications_directory()
    
    def _handle_missing_publications_directory(self):
        """Handle case where publications directory path doesn't exist."""
        parent_dir = self.publications_dir.parent
        print("="*60)
        print("❌ PUBLICATIONS DIRECTORY NOT ACCESSIBLE")
        print("="*60)
        print(f"Configured path: {self.publications_dir}")
        print("")
        print("Possible causes:")
        print("• Cloud drive not mounted in WSL (Google Drive, OneDrive, etc.)")
        print("• Typo in config file path")
        print("• Drive letter changed")
        print("• Network drive disconnected")
        print("• Path contains spaces or special characters")
        print("")
        print("Solutions:")
        print(f"• Mount your cloud drive: sudo mount -t drvfs [DRIVE]: {parent_dir}")
        print("• Check config file: config.personal.conf")
        print("• Use local directory: ./data/publications")
        print("• Fix path in config (remove spaces, use forward slashes)")
        print("")
        print("Would you like me to use a local directory instead?")
        print("="*60)
        
        # Ask user what to do
        while True:
            choice = input("\nChoose an option:\n[1] Use local directory (./data/publications)\n[2] Exit and fix the path\n[3] Continue anyway (may fail later)\nChoice: ").strip()
            
            if choice == '1':
                # Use local directory
                self.publications_dir = Path('./data/publications').resolve()
                self.publications_dir.mkdir(parents=True, exist_ok=True)
                print(f"✅ Using local directory: {self.publications_dir}")
                break
            elif choice == '2':
                print("Exiting. Please fix the publications_dir path in config.personal.conf")
                sys.exit(1)
            elif choice == '3':
                print("⚠️  Continuing with potentially inaccessible directory")
                break
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")
    
    def _handle_unwritable_publications_directory(self):
        """Handle case where publications directory exists but isn't writable."""
        print("="*60)
        print("❌ PUBLICATIONS DIRECTORY NOT WRITABLE")
        print("="*60)
        print(f"Path: {self.publications_dir}")
        print("")
        print("Possible causes:")
        print("• Insufficient permissions")
        print("• Read-only filesystem")
        print("• Cloud drive sync issues")
        print("• Directory is locked by another process")
        print("")
        print("Solutions:")
        print("• Check file permissions")
        print("• Use local directory instead")
        print("• Fix cloud drive sync")
        print("• Close applications that might be using the directory")
        print("")
        
        # Ask user what to do
        while True:
            choice = input("\nChoose an option:\n[1] Use local directory (./data/publications)\n[2] Exit and fix permissions\n[3] Continue anyway (may fail later)\nChoice: ").strip()
            
            if choice == '1':
                # Use local directory
                self.publications_dir = Path('./data/publications').resolve()
                self.publications_dir.mkdir(parents=True, exist_ok=True)
                print(f"✅ Using local directory: {self.publications_dir}")
                break
            elif choice == '2':
                print("Exiting. Please fix the permissions or path in config.personal.conf")
                sys.exit(1)
            elif choice == '3':
                print("⚠️  Continuing with potentially unwritable directory")
                break
            else:
                print("Invalid choice. Please enter 1, 2, or 3.")
    
    def setup_logging(self):
        """Setup logging configuration."""
        log_level = logging.DEBUG if self.debug else logging.INFO
        
        # Get the root logger
        logger = logging.getLogger()
        logger.setLevel(log_level)
        
        # Remove any existing handlers
        logger.handlers.clear()
        
        # Console handler - simple format (no timestamp/level)
        console_handler = logging.StreamHandler(sys.stderr)  # Write to stderr
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(console_handler)
        
        # File handler - detailed format with timestamp (if file logging is needed later)
        # For now, we only use console output
        
        self.logger = logging.getLogger(__name__)
    
    def _initialize_services(self):
        """Initialize services with GROBID as primary, Ollama as lazy fallback.
        
        Uses ServiceManager for centralized service lifecycle management.
        """
        print("  🔍 Checking GROBID...")
        
        # Initialize GROBID using ServiceManager
        grobid_available = self.service_manager.initialize_grobid()
        
        if grobid_available:
            location = "Local" if self.service_manager.is_local_grobid else f"Remote ({self.grobid_host})"
            print(f"    📍 GROBID: {location}")
            print("    ✅ GROBID: Available")
        else:
            location = "local" if self.service_manager.is_local_grobid else f"remote ({self.grobid_host})"
            print(f"    📍 GROBID: {location}")
            print("    ❌ GROBID: Not available (will use fallback methods)")
            if not self.service_manager.is_local_grobid:
                print(f"      💡 Tip: Check network connectivity and ensure GROBID is running on {self.grobid_host}")
            else:
                print("      💡 Tip: Check if Docker is running and port 8070 is free")
        
        # Initialize Ollama (lazy - just check availability, don't start yet)
        ollama_available = self.service_manager.initialize_ollama()
        
        if ollama_available:
            location = "Local" if self.service_manager.is_local_ollama else f"Remote ({self.service_manager.ollama_host})"
            print(f"    📍 Ollama: {location}")
            print("    ✅ Ollama: Available")
        else:
            print("    ⏭️  Ollama: Will start when needed")
        
        # Update service state for backward compatibility
        self.grobid_ready = self.service_manager.grobid_ready
        self.ollama_ready = self.service_manager.ollama_ready
        self.grobid_client = self.service_manager.grobid_client
        
        print("  ✅ Services initialized")
        print()
    
    def _ensure_ollama_ready(self) -> bool:
        """Ensure Ollama is ready, starting it if necessary.
        
        Uses ServiceManager for centralized service management.
        
        Returns:
            True if Ollama is ready, False if failed to start
        """
        # Use ServiceManager to ensure Ollama is ready
        is_ready = self.service_manager.ensure_ollama_ready()
        
        # Update state for backward compatibility
        self.ollama_ready = self.service_manager.ollama_ready
        self.ollama_process = self.service_manager.ollama_process
        
        if is_ready:
            print("    ✅ Ollama: Ready")
        else:
            print("    ❌ Ollama: Not ready")
        
        return is_ready
    
    # _start_grobid_container and _stop_grobid_container methods removed
    # ServiceManager now handles all GROBID lifecycle management
    # Use service_manager.initialize_grobid() or service_manager.shutdown() instead
    
    def _show_ollama_progress(self, found_info: dict, elapsed_time: int):
        """Show progress indicator during Ollama processing with found information.
        
        Args:
            found_info: Information found before Ollama processing
            elapsed_time: Time elapsed in seconds
        """
        # Display found information on first call
        if elapsed_time == 0 and found_info:
            self._display_found_information(found_info)
        
        # Clear line and show progress
        print(f"\r  🔄 Analyzing document... [{'█' * (elapsed_time % 10)}{'░' * (10 - (elapsed_time % 10))}] {elapsed_time}s elapsed", end="", flush=True)
    
    def _display_found_information(self, found_info: dict):
        """Display information found before Ollama processing.
        
        Args:
            found_info: Dictionary with found information
        """
        print("\n  📋 Found Information:")
        
        if found_info.get('title'):
            print(f"    📄 Title: {found_info['title']}")
        
        if found_info.get('authors'):
            authors = ', '.join(found_info['authors'][:3])
            if len(found_info['authors']) > 3:
                authors += f" (+{len(found_info['authors'])-3} more)"
            print(f"    👥 Authors: {authors}")
        
        if found_info.get('institution'):
            print(f"    🏢 Institution: {found_info['institution']}")
        
        if found_info.get('urls'):
            for i, url in enumerate(found_info['urls'][:2], 1):
                print(f"    🔗 URL {i}: {url}")
        
        if found_info.get('doi'):
            print(f"    🆔 DOI: {found_info['doi']}")
        
        if found_info.get('context_hint'):
            print(f"    📝 Context: {found_info['context_hint']}")
        
        print()
    
    # Note: is_ollama_running() and _start_ollama_background() methods removed
    # ServiceManager now handles all Ollama lifecycle management
    # Use service_manager.check_ollama_health() or service_manager.ensure_ollama_ready() instead
    
    def start_ollama_if_needed(self):
        """Start Ollama server if it's not already running.
        
        Uses ServiceManager for centralized service management.
        
        This ensures the daemon can use Ollama for metadata extraction
        without requiring manual startup.
        """
        # Check if already ready
        if self.service_manager.ollama_ready:
            self.logger.info("✅ Ollama server is already running")
            return
        
        self.logger.info("🤖 Starting Ollama server...")
        print("🤖 Starting Ollama server...")
        
        # Use ServiceManager to ensure Ollama is ready
        is_ready = self.service_manager.ensure_ollama_ready()
        
        # Update state for backward compatibility
        self.ollama_ready = self.service_manager.ollama_ready
        self.ollama_process = self.service_manager.ollama_process
        
        if is_ready:
            self.logger.info("✅ Ollama server started successfully")
            print("✅ Ollama server started successfully")
        else:
            self.logger.warning("⚠️  Ollama failed to start")
            print("⚠️  Ollama failed to start")
            print("   You may need to start it manually: ollama serve")
    
    def stop_ollama_if_started(self):
        """Stop Ollama server if we started it.
        
        Uses ServiceManager for centralized service management.
        This is called during daemon shutdown to clean up.
        """
        # ServiceManager handles shutdown automatically via shutdown() method
        # This method is kept for backward compatibility but delegates to ServiceManager
        pass
    
    def display_metadata(self, metadata: dict, pdf_path: Path, extraction_time: float):
        """Display extracted metadata to user with universal field handling.
        
        Shows all non-empty fields with smart grouping and labeling.
        Works for any document type and metadata source.
        
        Args:
            metadata: Extracted metadata dict
            pdf_path: Path to PDF file
            extraction_time: Time taken for extraction
        """
        print("\n" + "="*60)
        print(Colors.colorize(f"SCANNED DOCUMENT: {pdf_path.name}", ColorScheme.PAGE_TITLE))
        print("="*60)
        print(Colors.colorize(f"\nMetadata extracted in {extraction_time:.1f}s", ColorScheme.ACTION))
        
        # Show data source
        source = metadata.get('source', 'OCR extraction')
        method = metadata.get('method', 'unknown')
        print(Colors.colorize(f"Data source: {source} ({method})", ColorScheme.ACTION))
        
        # Show filtering notice if authors were cleaned
        if metadata.get('_filtered'):
            print(Colors.colorize(f"📝 Note: {metadata.get('_filtering_reason', 'Authors filtered')}", ColorScheme.ACTION))
        
        print(Colors.colorize("\nEXTRACTED METADATA:", ColorScheme.PAGE_TITLE))
        print("-" * 40)
        
        # Universal field display using smart grouping
        self._display_metadata_universal(metadata)
        
        print("-" * 40)
        print(Colors.colorize("💡 Tip: You can edit any field (including year) by choosing option [2] Edit metadata", ColorScheme.ACTION))
    
    def prompt_for_year(self, metadata: dict, allow_back: bool = False, force_prompt: bool = False) -> dict:
        """Prompt user for publication year if missing.
        
        Args:
            metadata: Metadata dict
            allow_back: If True, allows 'z' to go back
            force_prompt: If True, prompts even if year is already set (allows changing)
            
        Returns:
            Updated metadata with year, or special string 'BACK'/'RESTART'
        """
        # Skip if already confirmed earlier in this session (unless forcing)
        if not force_prompt and metadata.get('_year_confirmed'):
            return metadata
        
        current_year = metadata.get('year', '')
        if current_year and not force_prompt:
            metadata['_year_confirmed'] = True
            return metadata
        
        if current_year:
            print(Colors.colorize(f"\n📅 Current publication year: {current_year}", ColorScheme.ACTION), flush=True)
            hint = "(Enter to keep current"
        else:
            print(Colors.colorize("\n📅 Publication year not found in scan", ColorScheme.ACTION), flush=True)
            hint = "(or press Enter to skip"
        
        if allow_back:
            hint += ", 'z' to back, 'r' to restart"
        if current_year:
            hint += ", or enter new year to change"
        hint += ")"
        
        try:
            year_input = input(f"Enter publication year {hint}: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return 'BACK'  # Allow user to go back/cancel
        
        if year_input == 'z' and allow_back:
            return 'BACK'
        elif year_input == 'r':
            return 'RESTART'
        elif year_input == '':
            # Enter pressed - keep current or skip
            if current_year:
                print(f"✅ Keeping current year: {current_year}")
                metadata['_year_confirmed'] = True
            return metadata
        elif year_input and year_input != '':
            # Validate year format
            if year_input.isdigit() and len(year_input) == 4:
                metadata['year'] = year_input
                metadata['_year_confirmed'] = True
                if current_year:
                    print(f"✅ Year changed from {current_year} to {year_input}")
                else:
                    print(f"✅ Year set to: {year_input}")
                self.logger.info(f"User provided year: {year_input}")
            else:
                print("⚠️  Invalid year format (expected 4 digits, e.g., '2024')")
                if current_year:
                    print(f"   Keeping current year: {current_year}")
        
        return metadata
    
    def filter_garbage_authors(self, metadata: dict, pdf_path: Path = None) -> dict:
        """Filter out garbage authors, keeping only those found in Zotero and/or document text.
        
        When extraction quality is poor (e.g., regex fallback finds junk like
        "Working Paper", "Series Working", etc.), this filters to keep only
        real authors that exist in your Zotero collection.
        
        For GROBID authors, also validates against document text to filter hallucinations.
        
        Args:
            metadata: Metadata dict with 'authors' field
            pdf_path: Optional path to PDF for document text validation (for GROBID hallucinations)
            
        Returns:
            Updated metadata dict with filtered authors
        """
        if not metadata.get('authors'):
            return metadata
        
        original_authors = metadata['authors']
        extraction_method = metadata.get('extraction_method', metadata.get('method', ''))
        
        # Apply OCR correction to all authors before filtering/display
        # This fixes OCR errors like "Tu$ey" -> "Tukey" before they're shown to user
        corrected_authors = []
        if self.author_validator:
            for author in original_authors:
                corrected = False
                # Strategy 1: Try lastname matching first (fast, handles cases like "Tu$ey, John W" -> "Tukey, John W")
                try:
                    validation = self.author_validator.validate_authors([author])
                    if validation['known_authors']:
                        # Found exact or lastname match - use it
                        corrected_authors.append(validation['known_authors'][0]['name'])
                        corrected = True
                        self.logger.debug(f"Author matched via lastname: '{author}' -> '{validation['known_authors'][0]['name']}'")
                    elif validation['ocr_corrections']:
                        # Found OCR correction suggestion
                        corrected_authors.append(validation['ocr_corrections'][0]['corrected_name'])
                        corrected = True
                        self.logger.debug(f"OCR correction via validate: '{author}' -> '{validation['ocr_corrections'][0]['corrected_name']}'")
                except Exception as e:
                    self.logger.debug(f"Author validation failed for '{author}': {e}")
                
                # Strategy 2: If no match, try direct OCR correction (more aggressive, handles special chars)
                if not corrected:
                    try:
                        # Try with higher max_distance and lower similarity threshold
                        suggestion = self.author_validator.suggest_ocr_correction(author, max_distance=3)
                        if suggestion and suggestion.get('corrected_name'):
                            corrected_authors.append(suggestion['corrected_name'])
                            self.logger.debug(f"OCR correction: '{author}' -> '{suggestion['corrected_name']}'")
                            corrected = True
                    except Exception as e:
                        self.logger.debug(f"OCR correction failed for '{author}': {e}")
                
                # If no correction found, keep original
                if not corrected:
                    corrected_authors.append(author)
        else:
            corrected_authors = original_authors
        
        # Update metadata with corrected authors
        metadata['authors'] = corrected_authors
        original_authors = corrected_authors  # Use corrected authors for filtering
        
        # For GROBID: validate against document text first (filter hallucinations)
        if extraction_method == 'grobid' and pdf_path:
            # Get document text for validation
            doc_text = ""
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pdf:
                    # Check first 3 pages for author mentions
                    for page in pdf.pages[:min(3, len(pdf.pages))]:
                        page_text = page.extract_text()
                        if page_text:
                            doc_text += page_text.lower()
            except Exception as e:
                self.logger.debug(f"Could not extract text for validation: {e}")
                doc_text = ""
            
            if doc_text:
                # Validate GROBID authors against document text using word boundaries
                import re
                authors_in_text = []
                authors_not_in_text = []
                for author in original_authors:
                    author_lower = author.lower()
                    name_parts = author_lower.split(',')
                    last_name = name_parts[0].strip() if name_parts else ""
                    
                    found_in_text = False
                    # Try last name with word boundaries (prevents false positives)
                    if last_name and len(last_name) > 2:
                        last_name_escaped = re.escape(last_name)
                        pattern = r'\b' + last_name_escaped + r'\b'
                        if re.search(pattern, doc_text):
                            found_in_text = True
                    
                    # Try full name if last name not found
                    if not found_in_text and author_lower:
                        author_escaped = re.escape(author_lower)
                        pattern = r'\b' + author_escaped + r'\b'
                        if re.search(pattern, doc_text):
                            found_in_text = True
                    
                    if found_in_text:
                        authors_in_text.append(author)
                    else:
                        authors_not_in_text.append(author)
                
                # If most GROBID authors don't appear in document, filter them out
                total = len(original_authors)
                if total > 0:
                    ratio_found = len(authors_in_text) / total
                    
                    # Filter out authors that don't appear in document text (strict filtering)
                    # This is the primary filter - if author doesn't appear in text, it's a hallucination
                    if authors_not_in_text:
                        self.logger.info(f"Filtering {len(authors_not_in_text)} GROBID author(s) that don't appear in document: {authors_not_in_text}")
                    
                    # PRIMARY FILTER: Keep only authors that appear in document text
                    # GROBID hallucinates authors (even ones in Zotero) if they don't appear in the PDF
                    # So PDF text presence is the ONLY reliable filter - Zotero validation is secondary
                    metadata['authors'] = authors_in_text
                    
                    if len(authors_in_text) < total:
                        self.logger.info(f"Filtered GROBID authors: kept {len(authors_in_text)}/{total} that appear in document text")
                        if authors_not_in_text:
                            self.logger.info(f"  Filtered out (not in PDF): {authors_not_in_text}")
                    
                    if not authors_in_text:
                        # No authors found in text - clear them all (all were hallucinations)
                        metadata['authors'] = []
                        self.logger.warning(f"All GROBID authors filtered out - none appear in document text")
                        return metadata
                    
                    # SECONDARY: Optional Zotero validation for authors that DO appear in text
                    # This is just for logging/preference, not filtering - we already filtered by PDF text
                    if self.author_validator:
                        authors_in_zotero = []
                        authors_not_in_zotero = []
                        for author in authors_in_text:
                            validation = self.author_validator.validate_authors([author])
                            if validation['known_authors'] or validation['ocr_corrections']:
                                authors_in_zotero.append(author)
                            else:
                                authors_not_in_zotero.append(author)
                        
                        if authors_not_in_zotero:
                            self.logger.debug(f"GROBID authors appear in PDF but not in Zotero: {authors_not_in_zotero}")
                        if authors_in_zotero:
                            self.logger.debug(f"GROBID authors appear in PDF and are in Zotero: {authors_in_zotero}")
        
        # Zotero-based filtering (for non-reliable extraction methods)
        if not self.author_validator:
            return metadata
        
        # Skip filtering if extraction method is reliable (CrossRef, arXiv, DOI)
        # Note: GROBID already filtered above if pdf_path provided
        reliable_methods = ['crossref', 'arxiv', 'doi']
        if extraction_method in reliable_methods:
            return metadata
        
        # Validate authors against Zotero
        validation = self.author_validator.validate_authors(metadata.get('authors', []))
        known_authors = validation['known_authors']
        unknown_authors = validation['unknown_authors']
        
        # Decision logic: Filter if we have many unknowns and some known authors
        total = len(metadata.get('authors', []))
        known_count = len(known_authors)
        unknown_count = len(unknown_authors)
        
        # If we have 5+ total authors and 70%+ are unknown, but we found some known authors
        # This indicates garbage extraction (like the regex fallback)
        should_filter = (
            total >= 5 and 
            known_count >= 1 and 
            (unknown_count / total) >= 0.7
        )
        
        if should_filter:
            self.logger.info(f"🧹 Filtering authors: {total} extracted, {known_count} known, {unknown_count} unknown")
            
            # Keep only known authors
            filtered_authors = [author['name'] for author in known_authors]
            
            # Update metadata
            metadata['authors'] = filtered_authors
            metadata['_original_author_count'] = total
            metadata['_filtered'] = True
            metadata['_filtering_reason'] = f"Kept {known_count} known authors from {total} extracted"
            
            self.logger.info(f"✅ Filtered to {len(filtered_authors)} known authors")
        
        return metadata
    
    def confirm_document_type_early(self, metadata: dict) -> dict:
        """Confirm or select document type early in the workflow.
        
        This helps guide which APIs to search and which fields are relevant.
        Happens right after extraction, before manual entry.
        
        Args:
            metadata: Metadata dict (may already have document_type from extraction)
            
        Returns:
            Updated metadata dict with confirmed document_type, or None if cancelled
        """
        # Document type mapping (same as handle_failed_extraction for consistency)
        doc_type_map = {
            '1': ('journal_article', 'Journal Article'),
            '2': ('book_chapter', 'Book Chapter'),
            '3': ('conference_paper', 'Conference Paper'),
            '4': ('book', 'Book'),
            '5': ('thesis', 'Thesis'),
            '6': ('report', 'Report'),
            '7': ('news_article', 'News Article'),
            '8': ('working_paper', 'Working Paper'),
            '9': ('unknown', 'Other'),
            '0': ('unknown', 'Other')  # Alias for 9
        }
        
        # Reverse mapping: document_type -> number choice
        reverse_map = {v[0]: k for k, v in doc_type_map.items()}
        
        current_type = metadata.get('document_type', '').lower()
        
        print("\n" + "="*60, flush=True)
        print(Colors.colorize("📚 DOCUMENT TYPE", ColorScheme.PAGE_TITLE), flush=True)
        print("="*60, flush=True)
        print(Colors.colorize("Getting the document type right helps guide search strategies.", ColorScheme.ACTION), flush=True)
        print(Colors.colorize("This ensures we search the right APIs and ask for relevant fields.", ColorScheme.ACTION), flush=True)
        print(flush=True)
        
        if current_type and current_type in reverse_map:
            # Show detected type and ask for confirmation
            current_name = next(name for num, (typ, name) in doc_type_map.items() 
                              if typ == current_type)
            print(f"📄 Detected type: {current_name}")
            print()
            print(Colors.colorize("[Enter] = Keep this type", ColorScheme.LIST))
            print(Colors.colorize("[1-9] = Change to a different type", ColorScheme.LIST))
            print(Colors.colorize("[q] = Cancel and skip this document", ColorScheme.LIST))
            print()
            
            print("Document types:")
            for num, (typ, name) in doc_type_map.items():
                if num == '0':  # Skip 0, it's just an alias
                    continue
                marker = " ← detected" if typ == current_type else ""
                print(Colors.colorize(f"  [{num}] {name}{marker}", ColorScheme.LIST))
            print()
            
            try:
                choice = input("Your choice: ").strip().lower()
                
                if choice == 'q' or choice == 'quit':
                    return None
                elif choice == '':
                    # Keep detected type
                    print(f"✅ Keeping: {current_name}")
                    metadata['_type_confirmed'] = True
                    return metadata
                elif choice in doc_type_map:
                    # Change type
                    new_type, new_name = doc_type_map[choice]
                    metadata['document_type'] = new_type
                    print(f"✅ Changed to: {new_name}")
                    metadata['_type_confirmed'] = True
                    return metadata
                else:
                    print("⚠️  Invalid choice, keeping detected type")
                    return metadata
                    
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
        else:
            # No type detected - ask user to select
            print(Colors.colorize("No document type detected. Please select:", ColorScheme.ACTION))
            print()
            print(Colors.colorize("[1] Journal Article", ColorScheme.LIST))
            print(Colors.colorize("[2] Book Chapter", ColorScheme.LIST))
            print(Colors.colorize("[3] Conference Paper", ColorScheme.LIST))
            print(Colors.colorize("[4] Book", ColorScheme.LIST))
            print(Colors.colorize("[5] Thesis/Dissertation", ColorScheme.LIST))
            print(Colors.colorize("[6] Report", ColorScheme.LIST))
            print(Colors.colorize("[7] News Article", ColorScheme.LIST))
            print(Colors.colorize("[8] Working Paper/preprint", ColorScheme.LIST))
            print(Colors.colorize("[9] Other", ColorScheme.LIST))
            print()
            
            try:
                while True:
                    choice = input("Document type: ").strip()
                    if choice in doc_type_map:
                        doc_type, doc_type_name = doc_type_map[choice]
                        metadata['document_type'] = doc_type
                        print(f"✅ Selected: {doc_type_name}")
                        metadata['_type_confirmed'] = True
                        return metadata
                    elif choice.lower() in ['q', 'quit', 'cancel']:
                        return None
                    else:
                        print("⚠️  Invalid choice. Please enter 1-9 or 'q' to cancel.")
                        
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
    
    def _display_metadata_universal(self, metadata: dict):
        """Universal metadata display that handles any document type and source.
        
        Args:
            metadata: Metadata dictionary to display
        """
        # Define field groups and their display order
        field_groups = [
            ('BASIC INFORMATION', self._get_basic_info_fields()),
            ('PUBLICATION DETAILS', self._get_publication_fields()),
            ('IDENTIFIERS', self._get_identifier_fields()),
            ('CONTENT INFO', self._get_content_fields()),
            ('ZOTERO STATUS', self._get_zotero_fields()),
            ('TECHNICAL INFO', self._get_technical_fields())
        ]
        
        # Check if metadata is confirmed (from Zotero or has item_key)
        is_confirmed = metadata.get('item_key') or metadata.get('from_zotero', False)
        
        # Display each group if it has non-empty fields
        for group_name, field_mapping in field_groups:
            group_fields = self._extract_group_fields(metadata, field_mapping)
            if group_fields:
                print(Colors.colorize(f"\n{group_name}:", ColorScheme.PAGE_TITLE))
                for field_name, field_value in group_fields.items():
                    self._display_field(field_name, field_value, metadata, is_confirmed)
    
    def _get_basic_info_fields(self) -> dict:
        """Get field mapping for basic information."""
        return {
            'title': 'Title',
            'authors': 'Authors',
            'year': 'Year',
            'document_type': 'Type',
            'language': 'Language'
        }
    
    def _get_publication_fields(self) -> dict:
        """Get field mapping for publication details."""
        return {
            'journal': 'Journal',
            'conference': 'Conference',
            'book_title': 'Book Title',
            'book_editors': 'Book Editors',
            'publisher': 'Publisher',
            'volume': 'Volume',
            'issue': 'Issue',
            'pages': 'Pages',
            'edition': 'Edition',
            'series': 'Series',
            'location': 'Location',
            'date_published': 'Date Published',
            'university': 'University',
            'advisor': 'Advisor',
            'degree_type': 'Degree Type'
        }
    
    def _get_identifier_fields(self) -> dict:
        """Get field mapping for identifiers."""
        return {
            'doi': 'DOI',
            'isbn': 'ISBN',
            'issn': 'ISSN',
            'pmid': 'PMID',
            'arxiv_id': 'arXiv ID',
            'url': 'URL',
            'report_number': 'Report Number',
            'patent_number': 'Patent Number',
            'case_number': 'Case Number'
        }
    
    def _get_content_fields(self) -> dict:
        """Get field mapping for content information."""
        return {
            'abstract': 'Abstract',
            'keywords': 'Keywords',
            'tags': 'Tags',
            'subjects': 'Subjects',
            'summary': 'Summary'
        }
    
    def _get_zotero_fields(self) -> dict:
        """Get field mapping for Zotero-specific information."""
        return {
            'item_key': 'Item Key',
            'has_attachment': 'Has PDF',
            'similarity': 'Match Confidence',
            'method': 'Match Method',
            'from_zotero': 'From Zotero'
        }
    
    def _get_technical_fields(self) -> dict:
        """Get field mapping for technical information."""
        return {
            'source': 'Data Source',
            'confidence': 'Confidence',
            'processing_time': 'Processing Time',
            'extraction_method': 'Extraction Method',
            'raw_type': 'Raw Type'
        }
    
    def _extract_group_fields(self, metadata: dict, field_mapping: dict) -> dict:
        """Extract non-empty fields for a group.
        
        Args:
            metadata: Full metadata dictionary
            field_mapping: Field mapping for this group
            
        Returns:
            Dictionary of non-empty fields in this group
        """
        group_fields = {}
        
        for field_key, field_label in field_mapping.items():
            if field_key in metadata:
                value = metadata[field_key]
                if self._is_non_empty_value(value):
                    # Adjust label based on document type for ambiguous fields
                    if field_key == 'journal':
                        doc_type = metadata.get('document_type', '').lower()
                        item_type = metadata.get('item_type', '').lower()
                        
                        # Check both document_type and item_type for books
                        if (doc_type in ['book', 'book_section', 'book_chapter'] or 
                            item_type in ['book', 'bookSection']):
                            field_label = 'Book Title'
                        elif doc_type == 'conference_paper' or item_type == 'conferencePaper':
                            field_label = 'Conference'
                        # Otherwise keep 'Journal' for articles/papers
                    
                    group_fields[field_label] = value
        
        return group_fields
    
    def _is_non_empty_value(self, value) -> bool:
        """Check if a value is considered non-empty for display."""
        if value is None:
            return False
        if isinstance(value, (list, tuple)):
            return len(value) > 0
        if isinstance(value, str):
            return value.strip() != ''
        if isinstance(value, bool):
            return True  # Always show boolean values
        if isinstance(value, (int, float)):
            return True  # Always show numeric values
        return True  # Default to showing other types
    
    def _display_field(self, field_name: str, field_value, metadata: dict = None, is_confirmed: bool = False):
        """Display a single field with appropriate formatting and colors.
        
        Args:
            field_name: Display name for the field
            field_value: Value to display
            metadata: Full metadata dict (for checking confirmation status)
            is_confirmed: Whether metadata is confirmed (from Zotero)
        """
        # Determine color for main metadata fields (Title, Authors, Year)
        if field_name in ['Title', 'Authors', 'Year']:
            if is_confirmed:
                color = ColorScheme.METADATA_CONFIRMED
            else:
                color = ColorScheme.METADATA_UNCONFIRMED
        else:
            color = None
        
        if field_name == 'Authors':
            field_label = Colors.colorize(f"  {field_name}:", color) if color else f"  {field_name}:"
            if isinstance(field_value, list):
                # Validate authors against Zotero if validator available
                if self.author_validator:
                    validation = self.author_validator.validate_authors(field_value)
                    print(field_label)
                    for author_info in validation['known_authors']:
                        author_name = author_info['name']
                        author_display = Colors.colorize(author_name, color) if color else author_name
                        print(f"    ✅ {author_display} (in Zotero)")
                        if author_info.get('alternatives'):
                            alts = ', '.join(author_info['alternatives'][:2])
                            print(f"       Other options: {alts}")
                    for author_info in validation['unknown_authors']:
                        author_display = Colors.colorize(author_info['name'], color) if color else author_info['name']
                        print(f"    🆕 {author_display} (new author)")
                else:
                    # Fallback if validator not available
                    if len(field_value) > 3:
                        author_str = ', '.join(field_value[:3]) + f" (+{len(field_value)-3} more)"
                    else:
                        author_str = ', '.join(field_value)
                    author_display = Colors.colorize(author_str, color) if color else author_str
                    print(f"{field_label} {author_display}")
            else:
                value_display = Colors.colorize(str(field_value), color) if color else str(field_value)
                print(f"{field_label} {value_display}")
        
        elif field_name == 'Title':
            field_label = Colors.colorize(f"  {field_name}:", color) if color else f"  {field_name}:"
            value_display = Colors.colorize(str(field_value), color) if color else str(field_value)
            print(f"{field_label} {value_display}")
        
        elif field_name == 'Year':
            field_label = Colors.colorize(f"  {field_name}:", color) if color else f"  {field_name}:"
            value_display = Colors.colorize(str(field_value), color) if color else str(field_value)
            print(f"{field_label} {value_display}")
        
        elif field_name == 'Abstract':
            if isinstance(field_value, str):
                abstract = field_value[:150]
                if len(field_value) > 150:
                    print(f"  {field_name}: {abstract}...")
                else:
                    print(f"  {field_name}: {abstract}")
            else:
                print(f"  {field_name}: {field_value}")
        
        elif field_name == 'Has PDF':
            print(f"  {field_name}: {'✅ Yes' if field_value else '❌ No'}")
        
        elif field_name == 'Match Confidence':
            if isinstance(field_value, (int, float)):
                print(f"  {field_name}: {field_value:.1f}%")
        elif field_name == 'From Zotero':
            print(f"  {field_name}: {'✅ Yes' if field_value else '❌ No'}")
        
        elif field_name == 'Journal':
            # Validate journal against Zotero if validator available
            if self.journal_validator and isinstance(field_value, str) and field_value.strip():
                validation = self.journal_validator.validate_journal(field_value)
                if validation['matched']:
                    journal_name = validation['journal_name']
                    paper_count = validation['paper_count']
                    match_type = validation['match_type']
                    confidence = validation['confidence']
                    
                    if match_type == 'exact':
                        print(f"  {field_name}: ✅ {journal_name} (in Zotero, {paper_count} papers)")
                    elif match_type == 'fuzzy':
                        print(f"  {field_name}: {field_value}")
                        print(f"    💡 Did you mean '{journal_name}'? ({paper_count} papers, {confidence}% confidence)")
                else:
                    print(f"  {field_name}: {field_value}")
                    print(f"    🆕 New journal (not in Zotero collection)")
            else:
                # Fallback if validator not available or no journal value
                print(f"  {field_name}: {field_value}")
        
        elif isinstance(field_value, list):
            if len(field_value) == 0:
                print(f"  {field_name}: (empty)")
            elif len(field_value) <= 3:
                print(f"  {field_name}: {', '.join(str(v) for v in field_value)}")
            else:
                items = ', '.join(str(v) for v in field_value[:3])
                print(f"  {field_name}: {items} (+{len(field_value)-3} more)")
        
        else:
            print(f"  {field_name}: {field_value}")
    
    def display_zotero_match_menu(self) -> str:
        """Display menu when Zotero matches are found.
        
        Returns:
            User's menu choice as string
        """
        print(Colors.colorize("\n🎯 ZOTERO MATCH FOUND!", ColorScheme.PAGE_TITLE))
        print(Colors.colorize("What would you like to do with the scanned PDF?", ColorScheme.ACTION))
        print()
        print(Colors.colorize("[1] 📎 Attach PDF to existing Zotero item", ColorScheme.LIST))
        print(Colors.colorize("[2] ✏️  Edit metadata before attaching", ColorScheme.LIST))
        print(Colors.colorize("[3] 🔍 Search Zotero again with different info", ColorScheme.LIST))
        print(Colors.colorize("[4] 📄 Create new Zotero item (ignore match)", ColorScheme.LIST))
        print(Colors.colorize("[5] ❌ Skip document", ColorScheme.LIST))
        print(Colors.colorize("  (q) Quit daemon", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', 'q']:
                return choice
            else:
                print("⚠️  Invalid choice. Please enter 1-5 or 'q' to quit.")
    
    def display_interactive_menu(self) -> str:
        """Display interactive menu and get user choice.
        
        Returns:
            User's menu choice as string
        """
        print(Colors.colorize("\nWHAT WOULD YOU LIKE TO DO?", ColorScheme.PAGE_TITLE))
        print()
        print(Colors.colorize("[1] 📄 Create new Zotero item with extracted metadata", ColorScheme.LIST))
        print(Colors.colorize("[2] ✏️  Edit metadata before creating item", ColorScheme.LIST))
        print(Colors.colorize("[3] 🔍 Search Zotero with additional info", ColorScheme.LIST))
        print(Colors.colorize("[4] ❌ Skip document (not academic)", ColorScheme.LIST))
        print(Colors.colorize("[5] 📝 Manual processing later", ColorScheme.LIST))
        print(Colors.colorize("  (q) Quit daemon", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', 'q']:
                return choice
            else:
                print("⚠️  Invalid choice. Please enter 1-5 or 'q' to quit.")
    
    def search_and_display_local_zotero(self, metadata: dict) -> tuple:
        """Interactive Zotero search with author selection and item selection.
        
        SAFETY: This method only performs READ operations on the database.
        No write operations are possible.
        
        New workflow:
        1. Prompt for year if missing
        2. Let user select which authors to search by (and in what order)
        3. Search Zotero with ordered author search + year filter
        4. Display matches with number labels (1-N)
        5. Let user select item or take action
        
        Args:
            metadata: Metadata to search with
            
        Returns:
            Tuple of (action, selected_item, updated_metadata):
            - action: 'select', 'search', 'edit', 'create', 'skip', 'quit', or 'none'
            - selected_item: The selected Zotero item dict (if action='select')
            - updated_metadata: Metadata dict with any edits made during author selection
        """
        if not self.local_zotero:
            print("❌ Zotero database not available")
            return ('none', None, metadata)
        
        try:
            # Step 1: Ensure we have a year (prompt if missing, only once per session)
            year_result = self.prompt_for_year(metadata)
            # Handle special return values
            if year_result == 'BACK':
                return ('back', None, metadata)
            elif year_result == 'RESTART':
                return ('restart', None, metadata)
            else:
                metadata = year_result  # Year was added/updated in metadata
            year = metadata.get('year', None)
            
            # Step 2: Try quick title/DOI search first (but don't return early - show after author selection)
            quick_matches = []
            if metadata.get('title') or metadata.get('doi'):
                print("\n🔍 Quick Zotero search using found info...")
                quick_matches = self.local_zotero.search_by_metadata(metadata, max_matches=10)
                if quick_matches:
                    print(f"   Found {len(quick_matches)} potential match(es) - will show after author selection")
            
            # Preserve full author list for future re-search cycles
            if metadata.get('authors') and not metadata.get('_all_authors'):
                metadata['_all_authors'] = metadata['authors'].copy()

            # Step 3: Author-based search (always required)
            if not metadata.get('authors'):
                # If we have year/document_type but no authors, prompt for author input
                # This happens when GROBID filtered out all authors (hallucinations)
                if metadata.get('year') or metadata.get('document_type'):
                    print("\n📝 No authors found from extraction - please provide author name")
                    print("   (GROBID may have filtered out hallucinated authors)")
                    author_input = input("First author's last name (or 'z' to skip, 'r' to restart): ").strip()
                    
                    if author_input.lower() == 'r':
                        return ('restart', None, metadata)
                    elif author_input.lower() == 'z':
                        # Skip - will move to manual review
                        print("❌ No authors provided - cannot search")
                        return ('none', None, metadata)
                    elif author_input:
                        # Add author to metadata and continue
                        metadata['authors'] = [author_input]
                        self.logger.info(f"User provided author: {author_input}")
                    else:
                        # Empty input - move to manual review
                        print("❌ No authors provided - cannot search")
                        return ('none', None, metadata)
                else:
                    # No year/document_type either - move to manual review
                    print("❌ No authors found - cannot search")
                    return ('none', None, metadata)
            
            # Let user select which authors to search by
            # Note: This may edit author names
            selected_authors = self.select_authors_for_search(metadata['authors'].copy())
            
            # Check for back/restart commands
            if selected_authors == 'BACK':
                # Restore full filtered author list if available
                if metadata.get('_all_authors'):
                    metadata['authors'] = metadata['_all_authors'].copy()
                return ('back', None, metadata)
            elif selected_authors == 'RESTART':
                return ('restart', None, metadata)  # Will cause restart from outer loop
            
            if not selected_authors:
                print("❌ No authors selected")
                return ('none', None, metadata)
            
            # Update metadata with edited/selected authors
            # This preserves any author edits made in select_authors_for_search()
            metadata['authors'] = selected_authors
            
            # Update _all_authors to include manually added authors so they're preserved for option 'a'
            if metadata.get('_all_authors'):
                # Merge current authors with _all_authors, preserving manually added ones
                all_authors_set = set(metadata['_all_authors'])
                selected_authors_set = set(selected_authors)
                # Add any new authors that were manually added
                new_authors = selected_authors_set - all_authors_set
                if new_authors:
                    metadata['_all_authors'].extend(list(new_authors))
            else:
                # First time - save the selected authors (including manually added ones)
                metadata['_all_authors'] = selected_authors.copy()
            
            # Step 4: Show quick search results first (if any), then fall back to author-based search
            if quick_matches:
                search_info = "by title/DOI"
                if year:
                    search_info += f" in {year}"
                
                action, item = self.display_and_select_zotero_matches(quick_matches, search_info)
                if action == 'select':
                    return (action, item, metadata)
                # If user doesn't select from quick matches, continue to author-based search below
            
            # Step 5: Search by selected authors with year filter
            # Extract last names for search
            author_lastnames = []
            for author in selected_authors:
                # Handle "Lastname, FirstName" or "FirstName Lastname" format
                if ',' in author:
                    # "Schultz, P" -> "Schultz"
                    lastname = author.split(',')[0].strip()
                elif ' ' in author:
                    # "P. Wesley Schultz" -> "Schultz"
                    lastname = author.split()[-1]
                else:
                    # "Schultz" -> "Schultz"
                    lastname = author
                
                # Normalize lastname: remove OCR error characters (bullets, unusual punctuation)
                # Keep alphanumeric, spaces, hyphens, apostrophes, and periods
                lastname = re.sub(r'[^\w\s\-\'\.]', '', lastname).strip()
                
                author_lastnames.append(lastname)
            
            # Show search query before executing
            # Arrow indicates author order: first → second → third, etc.
            author_display = ' & '.join(author_lastnames)
            year_str = f" (year: {year})" if year else " (any year)"
            doc_type = metadata.get('document_type')
            doc_type_str = f" [type: {doc_type}]" if doc_type else ""
            print(f"\n🔍 Searching Zotero database for authors (in order): {author_display}{year_str}{doc_type_str}")
            
            attempt_specs = [
                {'year': year, 'document_type': doc_type, 'notice': None}
            ]
            if doc_type:
                attempt_specs.append({
                    'year': year,
                    'document_type': None,
                    'notice': "ℹ️  No matches with document type filter; including all Zotero item types."
                })
            if year:
                attempt_specs.append({
                    'year': None,
                    'document_type': doc_type,
                    'notice': "ℹ️  No matches with year filter; showing any publication year."
                })
            if doc_type and year:
                attempt_specs.append({
                    'year': None,
                    'document_type': None,
                    'notice': "ℹ️  No matches with year/type filters; showing any publication year and item type."
                })
            
            # Remove duplicate attempts while preserving order
            seen_attempts = set()
            attempts: List[Dict] = []
            for spec in attempt_specs:
                key = (spec['year'], spec['document_type'])
                if key in seen_attempts:
                    continue
                seen_attempts.add(key)
                attempts.append(spec)
            
            author_arrow_str = ' → '.join([a.split()[-1] for a in selected_authors])
            
            for spec in attempts:
                target_year = spec['year']
                target_type = spec['document_type']
                if spec['notice']:
                    print(f"\n{spec['notice']}")
                
                matches = self.local_zotero.search_by_authors_ordered(
                    author_lastnames,
                    year=target_year,
                    limit=10,
                    document_type=target_type
                )
                normalized_matches = [self._normalize_search_result(item) for item in matches]
                
                if normalized_matches:
                    search_info = f"by {author_arrow_str}"
                    if target_year:
                        search_info += f" in {target_year}"
                    elif year:
                        search_info += " (any year)"
                    if target_type and target_type != doc_type:
                        search_info += f" [{target_type}]"
                    elif target_type is None and doc_type:
                        search_info += " [all types]"
                    
                    action, item = self.display_and_select_zotero_matches(normalized_matches, search_info)
                    return (action, item, metadata)
            
            # Fallback: search broadly by first author's last name
            if author_lastnames:
                broad_name = author_lastnames[0]
                print(f"\nℹ️  No ordered matches; searching broadly for last name '{broad_name}'...")
                broad_matches = self.local_zotero.search_by_author(broad_name, limit=10)
                normalized_broad = [self._normalize_search_result(item) for item in broad_matches]
                if normalized_broad:
                    search_info = f"by last name {broad_name}"
                    action, item = self.display_and_select_zotero_matches(normalized_broad, search_info)
                    return (action, item, metadata)
            
            # No matches after all fallbacks
            print(f"\n❌ No matches found in Zotero after trying relaxed filters for: {author_display}")
            print()
            print(Colors.colorize("Options:", ColorScheme.ACTION))
            print(Colors.colorize("[1] Enter a different year and search again", ColorScheme.LIST))
            print(Colors.colorize("[2] Proceed to create new Zotero item", ColorScheme.LIST))
            print(Colors.colorize("[3] Move to manual review", ColorScheme.LIST))
            print(Colors.colorize("  (z) Back to previous step", ColorScheme.LIST))
            print()
            
            while True:
                final_choice = input("Enter your choice: ").strip().lower()
                if final_choice == '1':
                    new_year = input("Enter different year (blank to clear): ").strip()
                    if new_year:
                        metadata['year'] = new_year
                    else:
                        metadata.pop('year', None)
                    return ('search', None, metadata)
                elif final_choice == '2':
                    return ('create', None, metadata)
                elif final_choice == '3':
                    return ('none', None, metadata)
                elif final_choice == 'z':
                    return ('back', None, metadata)
                else:
                    print("⚠️  Invalid choice. Please enter 1-3 or 'z' to go back.")
            
        except Exception as e:
            self.logger.error(f"Error searching Zotero database: {e}")
            print(f"❌ Error searching Zotero database: {e}")
            return ('none', None, metadata)
    
    def _normalize_search_result(self, item: dict) -> dict:
        """Normalize search result from search_by_author to expected format.
        
        Converts:
        - 'creators' list to 'authors' list of name strings
        - 'hasAttachment' to 'has_attachment'
        
        Args:
            item: Item dict from search_by_author
            
        Returns:
            Normalized item dict compatible with display methods
        """
        normalized = item.copy()
        # Ensure a standard 'key' field exists (map from item_key if needed)
        if 'key' not in normalized and 'item_key' in normalized:
            normalized['key'] = normalized['item_key']
        
        # Convert creators list to authors list
        if 'creators' in item and 'authors' not in item:
            authors = []
            for creator in item['creators']:
                if creator.get('creatorType') == 'author':
                    first = creator.get('firstName', '')
                    last = creator.get('lastName', '')
                    if first and last:
                        authors.append(f"{first} {last}")
                    elif last:
                        authors.append(last)
            normalized['authors'] = authors
        
        # Normalize attachment flag
        if 'hasAttachment' in item and 'has_attachment' not in normalized:
            normalized['has_attachment'] = item['hasAttachment']
        
        # Ensure container_info, journal, doi, and abstract are passed through
        # Handle container_info (type-aware: journal/book/conference)
        if 'container_info' in item:
            normalized['container_info'] = item['container_info']
        
        # Handle both 'publicationTitle' and 'journal' field names (backward compat)
        if 'journal' not in normalized:
            if 'container_info' in item and item['container_info']:
                normalized['journal'] = item['container_info'].get('value')
            elif 'publicationTitle' in item:
                normalized['journal'] = item['publicationTitle']
            elif 'journal' in item:
                normalized['journal'] = item['journal']
        
        # Ensure item_type is passed through
        if 'item_type' in item:
            normalized['item_type'] = item['item_type']
        elif 'itemType' in item:
            normalized['item_type'] = item['itemType']
        
        # Ensure DOI and abstract are passed through
        if 'doi' not in normalized and 'DOI' in item:
            normalized['doi'] = item['DOI']
        elif 'doi' not in normalized and 'doi' in item:
            normalized['doi'] = item['doi']
        
        if 'abstract' not in normalized:
            if 'abstractNote' in item:
                normalized['abstract'] = item['abstractNote']
            elif 'abstract' in item:
                normalized['abstract'] = item['abstract']
        
        # Ensure tags are passed through
        if 'tags' in item:
            normalized['tags'] = item['tags']
        
        return normalized
    
    def _get_script_path_win(self, script_name: str) -> str:
        """Get the Windows path to any PowerShell script in scripts directory.
        
        Args:
            script_name: Name of PowerShell script (e.g., 'path_utils.ps1', 'move_to_recycle_bin.ps1')
            
        Returns:
            Windows path to the PowerShell script
            
        Raises:
            Exception if script path cannot be converted
        """
        script_dir = Path(__file__).parent
        ps_script = script_dir / script_name
        
        # Convert script path to Windows format
        try:
            ps_script_win = subprocess.check_output(
                ['wslpath', '-w', str(ps_script)],
                text=True,
                stderr=subprocess.DEVNULL
            ).strip()
        except:
            # If wslpath fails, try direct conversion for script path
            if str(ps_script).startswith('/mnt/'):
                ps_script_win = str(ps_script).replace('/mnt/', '').replace('/', '\\')
                parts = ps_script_win.split('\\', 1)
                if len(parts) == 2:
                    drive = parts[0][0].upper()
                    ps_script_win = f"{drive}:\\{parts[1]}"
            else:
                raise Exception(f"Cannot convert script path: {ps_script}")
        
        return ps_script_win
    
    def _get_path_utils_script_win(self) -> str:
        """Get the Windows path to path_utils.ps1 script."""
        return self._get_script_path_win('path_utils.ps1')
    
    def _convert_wsl_to_windows_path(self, wsl_path: str) -> str:
        r"""Convert WSL path to Windows path using PowerShell utility.
        
        This avoids wslpath failures with cloud drives that aren't accessible from WSL.
        
        The function returns different Windows path formats depending on the WSL path type:
        - For /mnt/ paths: Returns drive letter format (e.g., /mnt/i/... -> I:\...)
        - For /tmp/ and other non-/mnt/ paths: Returns UNC network path format 
          (e.g., /tmp/... -> \\wsl.localhost\Ubuntu-22.04\tmp\...)
        
        Both formats are valid Windows paths and work with Windows programs (PDF viewers,
        PowerShell, Zotero API, etc.). The UNC format is the correct format for WSL paths
        that aren't mounted as Windows drives.
        
        Args:
            wsl_path: WSL path (e.g., /mnt/g/My Drive/publications or /tmp/pdf_splits/file.pdf)
            
        Returns:
            Windows path in appropriate format:
            - Drive letter format for /mnt/ paths (e.g., G:\My Drive\publications)
            - UNC network path format for /tmp/ and other paths (e.g., \\wsl.localhost\...\tmp\...)
            
        Raises:
            Exception if conversion fails
        """
        # Get script path
        ps_script_win = self._get_path_utils_script_win()
        # Use PowerShell to convert path
        result = subprocess.run(
            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win, 
             'convert-wsl-to-windows', wsl_path],
            capture_output=True,
            text=True,
            timeout=10
        )
        if result.returncode != 0:
            raise Exception(f"Path conversion failed: {result.stderr}")
        
        return result.stdout.strip()
    
    def _validate_path_via_powershell(self, path: str, is_directory: bool = True) -> Tuple[bool, Optional[str]]:
        """Validate that a path exists and is accessible using PowerShell.
        
        This works for cloud drives that may not be accessible from WSL.
        
        Args:
            path: Path to validate (Windows or WSL format)
            is_directory: If True, validate as directory; if False, validate as file
            
        Returns:
            Tuple of (is_valid: bool, error_message: Optional[str])
        """
        
        # Get script path
        try:
            ps_script_win = self._get_path_utils_script_win()
        except Exception as e:
            return (False, f"Cannot get script path: {e}")
        
        # Convert path to Windows format if needed
        if path.startswith('/'):
            try:
                path = self._convert_wsl_to_windows_path(path)
            except Exception as e:
                return (False, f"Path conversion failed: {e}")
        
        # Use PowerShell to validate path
        command = 'test-directory' if is_directory else 'test-path'
        result = subprocess.run(
            ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win, 
             command, path],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            return (False, f"Validation failed: {result.stderr}")
        
        try:
            result_data = json.loads(result.stdout.strip())
            if is_directory:
                return (result_data.get('exists', False) and result_data.get('accessible', False), 
                       result_data.get('error'))
            else:
                return (result_data.get('exists', False) and result_data.get('accessible', False),
                       result_data.get('error'))
        except json.JSONDecodeError:
            return (False, f"Invalid JSON response: {result.stdout}")
    
    def _copy_file_universal(self, source_path: Path, target_path: Path, replace_existing: bool = False) -> tuple:
        """Universal file copy method that tries native Python first, falls back to PowerShell.
        
        This method intelligently chooses the best copy method:
        1. Tries native Python shutil.copy2 (fast, works for WSL-accessible paths)
        2. Falls back to PowerShell if native copy fails (for cloud drives not accessible from WSL)
        
        Args:
            source_path: Path to source file (WSL or Windows path)
            target_path: Full target path including filename
            replace_existing: If True, replace existing file if it differs (default: False)
            
        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        # First, verify source file exists
        if not source_path.exists():
            return (False, f"Source file not found: {source_path}")
        
        # First, try native Python copy (fastest, works for most paths)
        try:
            # Ensure target directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if target exists and handle replacement
            if target_path.exists():
                if not replace_existing:
                    # Check if files are identical
                    try:
                        source_size = source_path.stat().st_size
                        target_size = target_path.stat().st_size
                        if source_size == target_size:
                            # Files might be identical - could check hash, but for now assume OK
                            self.logger.debug(f"Target already exists with same size: {target_path}")
                            return (True, None)
                    except Exception:
                        pass
                    return (False, f"Target file already exists: {target_path}")
                else:
                    # Remove existing file for replacement
                    target_path.unlink()
            
            # Perform native copy
            shutil.copy2(source_path, target_path)
            
            # Verify copy
            if not target_path.exists():
                return (False, "Target file not found after copy")
            
            source_size = source_path.stat().st_size
            target_size = target_path.stat().st_size
            if source_size != target_size:
                target_path.unlink()  # Clean up bad copy
                return (False, f"Size mismatch (source: {source_size}, target: {target_size})")
            
            self.logger.debug(f"Native copy successful: {source_path} → {target_path}")
            return (True, None)
            
        except (OSError, PermissionError, FileNotFoundError) as e:
            # Native copy failed - likely a cloud drive not accessible from WSL
            # Fall back to PowerShell
            self.logger.debug(f"Native copy failed ({e}), trying PowerShell fallback...")
            return self._copy_file_via_powershell(source_path, target_path, replace_existing)
        except Exception as e:
            # Other errors - try PowerShell as fallback
            self.logger.debug(f"Unexpected error in native copy ({e}), trying PowerShell fallback...")
            return self._copy_file_via_powershell(source_path, target_path, replace_existing)
    
    def _copy_file_via_powershell(self, source_path: Path, target_path: Path, replace_existing: bool = False) -> tuple:
        """Copy file using PowerShell (for cloud drives not accessible from WSL).
        
        Args:
            source_path: Path to source file
            target_path: Full target path including filename
            replace_existing: If True, replace existing file if it differs
            
        Returns:
            Tuple of (success: bool, error_msg: Optional[str])
        """
        try:
            # Normalize source path to WSL format first
            source_str = str(source_path)
            if ':' in source_str and not source_str.startswith('/'):
                source_str = self._normalize_path(source_str)
            
            # Check if source is in a temp directory that might not be accessible from Windows
            # If validation fails but file exists in WSL, copy to Windows-accessible location first
            is_valid, error = self._validate_path_via_powershell(source_str, is_directory=False)
            temp_source_path = None
            
            if not is_valid:
                # File might be in WSL temp directory - check if it exists in WSL
                if source_path.exists():
                    # Check if it's in a temp directory
                    source_str_lower = source_str.lower()
                    is_temp_path = ('/tmp/' in source_str_lower or 
                                   source_str_lower.startswith('/tmp/') or
                                   '/temp/' in source_str_lower)
                    
                    if is_temp_path:
                        # Copy temp file to Windows-accessible location first
                        # Use watch directory's temp subdirectory
                        temp_dir = self.watch_dir / 'temp_for_copy'
                        temp_dir.mkdir(parents=True, exist_ok=True)
                        temp_source_path = temp_dir / source_path.name
                        
                        try:
                            self.logger.debug(f"Copying temp file to Windows-accessible location: {temp_source_path}")
                            shutil.copy2(source_path, temp_source_path)
                            # Update source to use the Windows-accessible copy
                            source_str = str(temp_source_path)
                            source_path = temp_source_path
                            # Re-validate the new path
                            is_valid, error = self._validate_path_via_powershell(source_str, is_directory=False)
                            if not is_valid:
                                # Clean up temp file
                                if temp_source_path.exists():
                                    temp_source_path.unlink()
                                return (False, f"Source file not accessible even after copying to temp location: {error or 'Unknown error'}")
                        except Exception as e:
                            # Clean up temp file if copy failed
                            if temp_source_path and temp_source_path.exists():
                                try:
                                    temp_source_path.unlink()
                                except:
                                    pass
                            return (False, f"Failed to copy temp file to Windows-accessible location: {e}")
                    else:
                        # Not a temp path, but validation failed
                        return (False, f"Source file not found or not accessible: {error or 'Unknown error'}")
                else:
                    # File doesn't exist in WSL either
                    return (False, f"Source file not found or not accessible: {error or 'Unknown error'}")
            
            # Convert source WSL path to Windows path using PowerShell utility
            try:
                source_win = self._convert_wsl_to_windows_path(source_str)
            except Exception as e:
                # Clean up temp file if we created one
                if temp_source_path and temp_source_path.exists():
                    try:
                        temp_source_path.unlink()
                    except:
                        pass
                return (False, f"Failed to convert source path {source_path}: {e}")
            
            # Convert target path
            target_str = str(target_path)
            if ':' in target_str and not target_str.startswith('/'):
                target_str = self._normalize_path(target_str)
            
            try:
                target_win = self._convert_wsl_to_windows_path(target_str)
            except Exception as e:
                # Clean up temp file if we created one
                if temp_source_path and temp_source_path.exists():
                    try:
                        temp_source_path.unlink()
                    except:
                        pass
                return (False, f"Failed to convert target path: {e}")
            
            # Get script path
            try:
                ps_script_win = self._get_path_utils_script_win()
            except Exception as e:
                # Clean up temp file if we created one
                if temp_source_path and temp_source_path.exists():
                    try:
                        temp_source_path.unlink()
                    except:
                        pass
                return (False, f"Failed to get script path: {e}")
            
            # Copy file using path_utils.ps1
            self.logger.debug(f"Copying via PowerShell: {source_win} → {target_win}")
            
            # Build command with optional replace flag
            cmd = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win, 
                   'copy-file', source_win, target_win]
            if replace_existing:
                cmd.append('-Replace')
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120  # 120 second timeout for large files
            )
            
            if result.returncode == 0:
                # Parse JSON response
                try:
                    result_data = json.loads(result.stdout.strip())
                    if result_data.get('success', False):
                        self.logger.debug(f"PowerShell copy successful: {target_path}")
                        # Clean up temp file if we created one
                        if temp_source_path and temp_source_path.exists():
                            try:
                                temp_source_path.unlink()
                                self.logger.debug(f"Cleaned up temp file: {temp_source_path}")
                            except Exception as e:
                                self.logger.warning(f"Failed to clean up temp file {temp_source_path}: {e}")
                        return (True, None)
                    else:
                        # Clean up temp file on failure
                        if temp_source_path and temp_source_path.exists():
                            try:
                                temp_source_path.unlink()
                            except:
                                pass
                        return (False, result_data.get('error', 'Unknown error'))
                except json.JSONDecodeError:
                    # If JSON parsing fails, check if copy actually succeeded
                    if 'SUCCESS' in result.stdout or 'success' in result.stdout.lower():
                        # Clean up temp file if we created one
                        if temp_source_path and temp_source_path.exists():
                            try:
                                temp_source_path.unlink()
                                self.logger.debug(f"Cleaned up temp file: {temp_source_path}")
                            except Exception as e:
                                self.logger.warning(f"Failed to clean up temp file {temp_source_path}: {e}")
                        return (True, None)
                    # Clean up temp file on failure
                    if temp_source_path and temp_source_path.exists():
                        try:
                            temp_source_path.unlink()
                        except:
                            pass
                    return (False, f"Invalid response: {result.stdout}")
            else:
                # Try to parse error from JSON
                try:
                    result_data = json.loads(result.stdout.strip())
                    error_msg = result_data.get('error', f'PowerShell copy failed with code {result.returncode}')
                except:
                    error_msg = result.stdout + result.stderr
                    if not error_msg:
                        error_msg = f"PowerShell copy failed with code {result.returncode}"
                # Clean up temp file on failure
                if temp_source_path and temp_source_path.exists():
                    try:
                        temp_source_path.unlink()
                    except:
                        pass
                return (False, error_msg)
                
        except subprocess.TimeoutExpired:
            # Clean up temp file on timeout
            if temp_source_path and temp_source_path.exists():
                try:
                    temp_source_path.unlink()
                except:
                    pass
            return (False, "Copy timeout (file too large or network issue)")
        except Exception as e:
            # Clean up temp file on error
            if temp_source_path and temp_source_path.exists():
                try:
                    temp_source_path.unlink()
                except:
                    pass
            return (False, f"Copy error: {e}")
    
    def _copy_to_publications_via_windows(self, pdf_path: Path, target_filename: str, replace_existing: bool = False) -> tuple:
        """Copy PDF to publications directory using universal copy method.
        
        This method uses intelligent copy that tries native Python first,
        then falls back to PowerShell for cloud drives not accessible from WSL.
        
        Args:
            pdf_path: Path to source PDF (WSL or Windows path)
            target_filename: Target filename (just the name, not full path)
            replace_existing: If True, replace existing file if it differs (default: False)
            
        Returns:
            Tuple of (success: bool, target_path: Path or None, error_msg: str)
        """
        target_path = self.publications_dir / target_filename
        
        # Use universal copy method
        success, error_msg = self._copy_file_universal(pdf_path, target_path, replace_existing)
        
        if success:
            # Increment copy counter and refresh cache after every 10 copies
            self.publications_copy_count += 1
            if self.publications_copy_count >= 10:
                self._refresh_publications_cache()
                self.publications_copy_count = 0
            return (True, target_path, None)
        else:
            return (False, None, error_msg)
    
    def handle_failed_extraction(self, pdf_path: Path) -> dict:
        """Handle failed metadata extraction with guided workflow.
        
        Args:
            pdf_path: Path to PDF
            
        Returns:
            Manually entered metadata dict
        """
        print(Colors.colorize("\n⚠️  METADATA EXTRACTION FAILED", ColorScheme.PAGE_TITLE))
        print(Colors.colorize("Let's gather information manually to help identify this document.", ColorScheme.ACTION))
        print()
        
        # Step 1: Document type selection
        # TODO: later to maximize portability this could be moved to a config file       
        print(Colors.colorize("📚 What type of document is this?", ColorScheme.ACTION))
        print()
        print(Colors.colorize("[1] Journal Article", ColorScheme.LIST))
        print(Colors.colorize("[2] Book Chapter", ColorScheme.LIST))
        print(Colors.colorize("[3] Conference Paper", ColorScheme.LIST))
        print(Colors.colorize("[4] Book", ColorScheme.LIST))
        print(Colors.colorize("[5] Thesis/Dissertation", ColorScheme.LIST))
        print(Colors.colorize("[6] Report", ColorScheme.LIST))
        print(Colors.colorize("[7] News Article", ColorScheme.LIST))
        print(Colors.colorize("[8] Working Paper/preprint", ColorScheme.LIST))
        print(Colors.colorize("[9] Handwritten Note", ColorScheme.LIST))
        print(Colors.colorize("[0] Other", ColorScheme.LIST))
        print()
        
        doc_type_map = {
            '1': ('journal_article', 'Journal Article'),
            '2': ('book_chapter', 'Book Chapter'),
            '3': ('conference_paper', 'Conference Paper'),
            '4': ('book', 'Book'),
            '5': ('thesis', 'Thesis'),
            '6': ('report', 'Report'),
            '7': ('news_article', 'News Article'),
            '8': ('working_paper', 'Working Paper'),
            '9': ('handwritten_note', 'Handwritten Note'),
            '0': ('unknown', 'Other')
        }
        
        while True:
            type_choice = input("Document type: ").strip()
            if type_choice in doc_type_map:
                doc_type, doc_type_name = doc_type_map[type_choice]
                break
            print("Invalid choice. Please try again.")
        
        print(f"\n✅ Document type: {doc_type_name}")
        
        # Step 2: Try to get unique identifier
        metadata = {'document_type': doc_type}
        
        print("\n🔍 Let's try to find this document with a unique identifier.")
        print("(If you don't have one, press Enter to skip)")
        print()
        
        # Ask for DOI
        doi = input("DOI (e.g., 10.1234/example): ").strip()
        if doi:
            metadata['doi'] = doi
            print("\n⏳ Searching for metadata with DOI...")
            # Try metadata search again
            search_result = self.metadata_processor.search_by_doi(doi)
            if search_result and search_result.get('success'):
                print("✅ Found metadata!")
                return search_result['metadata']
            else:
                print("❌ No metadata found with this DOI")
        
        # Ask for ISBN (for books/chapters)
        if doc_type in ['book', 'book_chapter']:
            isbn = input("ISBN (if visible): ").strip()
            if isbn:
                metadata['isbn'] = isbn
                print("\n⏳ Searching for metadata with ISBN...")
                search_result = self.metadata_processor.search_by_isbn(isbn)
                if search_result and search_result.get('success'):
                    print("✅ Found metadata!")
                    return search_result['metadata']
                else:
                    print("❌ No metadata found with this ISBN")
        
        # No unique identifier worked - proceed to manual entry
        return self.manual_metadata_entry(metadata, doc_type)
    
    def manual_metadata_entry(self, partial_metadata: dict, doc_type: str) -> dict:
        """Guide user through manual metadata entry.
        
        Args:
            partial_metadata: Already collected metadata (document type, etc.)
            doc_type: Document type code
            
        Returns:
            Complete metadata dict
        """
        print(Colors.colorize("\n📝 MANUAL METADATA ENTRY", ColorScheme.PAGE_TITLE))
        print("We'll search local Zotero as you type to help find matches.")
        print()
        
        metadata = partial_metadata.copy()
        
        # Get author
        author = input("First author's last name (or 'z' to skip, 'r' to restart): ").strip()
        if author.lower() == 'z':
            # Skip author entry
            pass
        elif author.lower() == 'r':
            # Restart - return special marker
            return {'_restart': True}
        elif author:
            metadata['authors'] = [author]
            
            # Search local Zotero by author
            print(f"\n🔍 Searching Zotero for papers by '{author}'...")
            author_matches = self.local_zotero.search_by_author(author)
            
            if author_matches:
                print(f"Found {len(author_matches)} paper(s) by this author in Zotero:")
                print()
                
                for i, match in enumerate(author_matches[:10], 1):
                    print(f"[{i}] {match.get('title', 'Unknown')}")
                    print(f"    Year: {match.get('year', '?')}")
                    print(f"    Type: {match.get('itemType', '?')}")
                    print()
                
                print("[0] None of these - continue manual entry")
                print()
                
                match_choice = input("Is this your paper? (0-10): ").strip()
                
                if match_choice.isdigit():
                    idx = int(match_choice)
                    if 1 <= idx <= min(10, len(author_matches)):
                        # User selected a match
                        selected = author_matches[idx - 1]
                        print(f"\n✅ Using: {selected.get('title')}")
                        return self.convert_zotero_item_to_metadata(selected)
        
        # Continue with manual entry
        title = input("\nPaper title (or 'z' to skip, 'r' to restart): ").strip()
        if title.lower() == 'r':
            return {'_restart': True}
        elif title and title.lower() != 'z':
            metadata['title'] = title
        
        year = input("Publication year (or 'z' to skip, 'r' to restart): ").strip()
        if year.lower() == 'r':
            return {'_restart': True}
        elif year and year.lower() != 'z':
            metadata['year'] = year
        
        # Type-specific fields
        if doc_type in ['journal_article', 'conference_paper']:
            journal = input("Journal/Conference name (or 'z' to skip, 'r' to restart): ").strip()
            if journal.lower() == 'r':
                return {'_restart': True}
            elif journal and journal.lower() != 'z':
                metadata['journal'] = journal
        
        elif doc_type == 'book_chapter':
            book_title = input("Book title: ").strip()
            if book_title:
                metadata['book_title'] = book_title
        
        print("\n✅ Manual metadata entry complete")
        return metadata
    
    def convert_zotero_item_to_metadata(self, zotero_item: dict) -> dict:
        """Convert Zotero item to our metadata format.
        
        Args:
            zotero_item: Item from local Zotero DB
            
        Returns:
            Metadata dict in our format
        """
        metadata = {
            'title': zotero_item.get('title', ''),
            'year': zotero_item.get('year', ''),
            'document_type': zotero_item.get('itemType', 'unknown'),
            'zotero_key': zotero_item.get('key'),
            'from_zotero': True
        }
        
        # Extract authors
        creators = zotero_item.get('creators', [])
        authors = []
        for creator in creators:
            if creator.get('creatorType') == 'author':
                last = creator.get('lastName', '')
                first = creator.get('firstName', '')
                if last:
                    authors.append(f"{last}, {first}" if first else last)
        metadata['authors'] = authors
        
        # Copy other fields if present
        if zotero_item.get('DOI'):
            metadata['doi'] = zotero_item['DOI']
        if zotero_item.get('publicationTitle'):
            metadata['journal'] = zotero_item['publicationTitle']
        if zotero_item.get('abstractNote'):
            metadata['abstract'] = zotero_item['abstractNote']
        
        return metadata
    
    def use_metadata_as_is(self, pdf_path: Path, metadata: dict) -> bool:
        """Process paper using extracted/entered metadata.
        
        Args:
            pdf_path: Path to PDF
            metadata: Metadata to use
            
        Returns:
            True if successful
        """
        # Generate filename
        proposed_filename = self.generate_filename(metadata)
        
        print(f"\n📄 Proposed filename: {proposed_filename}")
        
        confirm = input("Use this filename? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':  # Enter or 'y' = use, anything else = custom
            new_name = input("Enter custom filename (without .pdf): ").strip()
            if new_name:
                proposed_filename = f"{new_name}.pdf"
            else:
                print("❌ Cancelled")
                return False
        
        # Check for duplicates in publications directory
        final_path = self.publications_dir / proposed_filename
        
        if final_path.exists():
            print(Colors.colorize(f"\n⚠️  FILE ALREADY EXISTS: {proposed_filename}", ColorScheme.PAGE_TITLE))
            print(f"   Existing: {self.get_file_info(final_path)}")
            print(f"   Scanned:  {self.get_file_info(pdf_path)}")
            print()
            print(Colors.colorize("What would you like to do?", ColorScheme.ACTION))
            print(Colors.colorize("[1] Keep both (rename scan with _scanned suffix)", ColorScheme.LIST))
            print(Colors.colorize("[2] Replace original with scan", ColorScheme.LIST))
            print(Colors.colorize("[3] Keep original, discard scan", ColorScheme.LIST))
            print(Colors.colorize("[4] Manual review later", ColorScheme.LIST))
            
            dup_choice = input("\nChoice: ").strip()
            
            if dup_choice == '1':
                # Rename with suffix
                stem = final_path.stem
                suffix = final_path.suffix
                final_path = self.publications_dir / f"{stem}_scanned{suffix}"
                proposed_filename = final_path.name
                print(f"✅ Will save as: {proposed_filename}")
                
            elif dup_choice == '2':
                # Backup and replace
                backup_path = self.publications_dir / f"{final_path.stem}_original{final_path.suffix}"
                shutil.move(str(final_path), str(backup_path))
                print(f"📦 Original backed up as: {backup_path.name}")
                
            elif dup_choice == '3':
                # Keep original
                self.move_to_done(pdf_path)
                print("✅ Kept original, moved scan to done/")
                return True
                
            else:  # Manual review
                print("📋 Leaving in scanner directory for manual review")
                return False
        
        # Copy to publications
        try:
            success, error_msg = self._copy_file_universal(pdf_path, final_path, replace_existing=False)
            if not success:
                self.logger.error(f"Error copying file: {error_msg}")
                print(f"❌ Error: {error_msg}")
                return False
            
            print(f"✅ Copied to: {final_path}")
            
            # Check if we should add to Zotero
            if metadata.get('from_zotero'):
                # This came from Zotero - just attach PDF
                print("\n📖 Attaching PDF to existing Zotero item...")
                zotero_key = metadata.get('zotero_key')
                if zotero_key:
                    attach_result = self.zotero_processor.attach_pdf_to_existing(zotero_key, final_path)
                    if attach_result:
                        print("✅ PDF attached to Zotero item")
                    else:
                        print("⚠️  Could not attach PDF to Zotero")
            else:
                # New metadata - ask about Zotero
                # Ensure language is detected from filename and added to metadata if not already present
                if not metadata.get('language'):
                    detected_language = self._detect_language_from_filename(pdf_path)
                    if detected_language:
                        metadata['language'] = detected_language
                
                add_zotero = input("\nAdd to Zotero? (y/n): ").strip().lower()
                if add_zotero == 'y':
                    print("📖 Adding to Zotero...")
                    zotero_result = self.zotero_processor.add_paper(metadata, final_path)
                    if zotero_result['success']:
                        print(f"✅ Added to Zotero")
                    else:
                        print(f"⚠️  Zotero error: {zotero_result.get('error')}")
            
            # Move original to done/
            self.move_to_done(pdf_path)
            print("✅ Processing complete!")
            return True
            
        except Exception as e:
            self.logger.error(f"Error copying file: {e}")
            print(f"❌ Error: {e}")
            return False
    
    def get_file_info(self, file_path: Path) -> str:
        """Get file size and modification time.
        
        Args:
            file_path: Path to file
            
        Returns:
            Formatted string with file info
        """
        try:
            stat = file_path.stat()
            size_mb = stat.st_size / (1024 * 1024)
            from datetime import datetime
            mod_time = datetime.fromtimestamp(stat.st_mtime).strftime('%Y-%m-%d %H:%M')
            return f"{size_mb:.1f} MB, modified {mod_time}"
        except Exception:
            return "unknown"
    
    def edit_metadata_interactively(self, metadata: dict, online_metadata: dict = None, local_metadata: dict = None, online_source: str = None, zotero_item: dict = None) -> dict:
        """Allow user to edit metadata fields with intelligent merging from multiple sources.
        
        Args:
            metadata: Current metadata (from extraction or user input)
            online_metadata: Optional metadata from online libraries (CrossRef, arXiv, etc.)
            local_metadata: Optional metadata from local Zotero database
            online_source: Source of online metadata (e.g., 'crossref_api', 'arxiv_api')
            zotero_item: Optional Zotero item dict - if provided and titles differ, will prompt for filename title override
            
        Returns:
            Edited metadata dict
        """
        edited = metadata.copy()
        
        print("\n✏️  EDIT METADATA")
        print("All changes will be applied via Zotero API")
        print("-" * 60)
        
        # Check if we have both online and local metadata for bulk operations
        has_online = online_metadata and any(online_metadata.values())
        has_local = local_metadata and any(local_metadata.values())
        
        if has_online and has_local:
            print("\n🔀 BULK OPERATIONS AVAILABLE:")
            print("(o) Overwrite all Zotero metadata with online metadata")
            print("(f) Fill gaps in Zotero metadata with online metadata (merge)")
            print("(number) Choose specific fields to overwrite (see numbered list below)")
            print("(s) Skip all changes - keep Zotero metadata as it is")
            print("(Enter) Continue with current metadata")
            print()
            
            # Show numbered field comparison
            self._display_numbered_field_comparison(edited, online_metadata, local_metadata, online_source)
            
            while True:
                bulk_choice = input("Bulk operation choice: ").strip().lower()
                
                if bulk_choice == 'o':
                    print("🔄 Overwriting all Zotero metadata with online metadata...")
                    edited = self._overwrite_all_with_online(edited, online_metadata)
                    break
                elif bulk_choice == 'f':
                    print("🔗 Filling gaps in Zotero metadata with online metadata...")
                    edited = self._fill_gaps_from_online(edited, online_metadata)
                    break
                elif bulk_choice == 's':
                    print("⏭️  Skipping all changes - keeping Zotero metadata as it is")
                    # edited remains unchanged (current metadata)
                    break
                elif bulk_choice.isdigit() or any(c in bulk_choice for c in [',', '-']):
                    field_numbers = self._parse_field_numbers(bulk_choice)
                    print(f"🔄 Overwriting fields {field_numbers} with online metadata...")
                    edited = self._overwrite_specific_fields(edited, online_metadata, field_numbers)
                    
                    # Ask if user wants to make more changes
                    more_changes = input("\nMake more field changes? (y/n or Enter to finish): ").strip().lower()
                    if more_changes in ['n', '']:
                        break
                    # Otherwise continue the loop for more changes
                elif bulk_choice == '':
                    # Enter pressed - finish editing
                    print("✅ Continuing with current metadata")
                    break
                else:
                    print("❌ Invalid choice. Please try again.")
        
        else:
            # No online metadata AND no local metadata - but still allow manual editing
            print("\n⚠️  NO AUTOMATIC METADATA SOURCES AVAILABLE")
            print("You can still manually edit fields below.")
            print()
        
        # Helper function to display field with multiple sources
        def display_field_with_sources(field_name: str, current_value, online_value=None, local_value=None):
            print(f"\n{field_name}:")
            if current_value:
                print(f"  [Current] {current_value}")
            if online_value:
                print(f"  [Online]  {online_value}")
            if local_value:
                print(f"  [Local]   {local_value}")
            
            # Suggest smart merge
            suggestions = []
            if online_value and not current_value:
                suggestions.append(f"Use online: {online_value}")
            if local_value and not current_value:
                suggestions.append(f"Use local: {local_value}")
            if online_value and local_value and online_value != local_value:
                suggestions.append("Conflict detected - choose manually")
            
            if suggestions:
                print(f"  💡 Suggestions: {' | '.join(suggestions)}")
        
        # Title
        display_field_with_sources(
            "Title", 
            edited.get('title', ''),
            online_metadata.get('title') if online_metadata else None,
            local_metadata.get('title') if local_metadata else None
        )
        new_value = input("New title (or Enter to keep current): ").strip()
        if new_value:
            edited['title'] = new_value
        elif online_metadata and online_metadata.get('title') and not edited.get('title'):
            edited['title'] = online_metadata['title']
            print(f"✅ Auto-filled from online: {online_metadata['title']}")
        elif local_metadata and local_metadata.get('title') and not edited.get('title'):
            edited['title'] = local_metadata['title']
            print(f"✅ Auto-filled from local: {local_metadata['title']}")
        
        # Filename title override: if Zotero item provided and titles differ, ask which to use for filename
        if zotero_item:
            zotero_title = zotero_item.get('title', '').strip()
            metadata_title = edited.get('title', '').strip()
            if zotero_title and metadata_title and zotero_title != metadata_title:
                print("\n" + "-" * 60)
                print("📄 FILENAME TITLE")
                print("-" * 60)
                print(f"Zotero item title: {zotero_title}")
                print(f"Metadata title:     {metadata_title}")
                print()
                print("The PDF filename can use either title, or a custom title.")
                print("  (z) Use Zotero title for filename (default)")
                print("  (m) Use metadata title for filename")
                print("  (c) Enter custom title for filename")
                print("  (Enter) Skip - use Zotero title")
                print()
                
                while True:
                    choice = input("Filename title choice [z/m/c/Enter]: ").strip().lower()
                    if choice == '' or choice == 'z':
                        # Use Zotero title (default) - don't set override
                        print("✅ Will use Zotero title for filename")
                        break
                    elif choice == 'm':
                        # Use metadata title for filename
                        edited['_filename_title_override'] = metadata_title
                        print(f"✅ Will use metadata title for filename: {metadata_title}")
                        break
                    elif choice == 'c':
                        # Custom title
                        custom_title = input("Enter custom title for filename: ").strip()
                        if custom_title:
                            edited['_filename_title_override'] = custom_title
                            print(f"✅ Will use custom title for filename: {custom_title}")
                            break
                        else:
                            print("⚠️  Custom title cannot be empty. Please enter a title or choose another option.")
                    else:
                        print("⚠️  Invalid choice. Please enter 'z', 'm', 'c', or press Enter.")
        
        # Authors
        current_authors = ', '.join(edited.get('authors', []))
        online_authors = ', '.join(online_metadata.get('authors', [])) if online_metadata else ''
        local_authors = ', '.join(local_metadata.get('authors', [])) if local_metadata else ''
        
        display_field_with_sources(
            "Authors",
            current_authors,
            online_authors if online_authors else None,
            local_authors if local_authors else None
        )
        
        # Show author count and quick options if there are many authors
        author_count = len(edited.get('authors', []))
        if author_count > 5:
            print(f"\n⚠️  Found {author_count} authors. Quick options:")
            print("  (clear)  Delete all authors")
            print("  (first)  Use only first author")
            print("  (last)   Use only last author")
        
        new_value = input("New authors (comma-separated, Enter to keep, 'clear', 'first', or 'last'): ").strip()
        if new_value:
            if new_value.lower() == 'clear':
                edited['authors'] = []
                print("✅ All authors deleted")
            elif new_value.lower() == 'first':
                if edited.get('authors'):
                    edited['authors'] = [edited['authors'][0]]
                    print(f"✅ Using only first author: {edited['authors'][0]}")
                else:
                    print("⚠️  No authors to select from")
            elif new_value.lower() == 'last':
                if edited.get('authors'):
                    last_author = edited['authors'][-1]
                    edited['authors'] = [last_author]
                    print(f"✅ Using only last author: {last_author}")
                else:
                    print("⚠️  No authors to select from")
            else:
                edited['authors'] = [a.strip() for a in new_value.split(',')]
        elif online_metadata and online_metadata.get('authors') and not edited.get('authors'):
            edited['authors'] = online_metadata['authors']
            print(f"✅ Auto-filled from online: {', '.join(online_metadata['authors'])}")
        elif local_metadata and local_metadata.get('authors') and not edited.get('authors'):
            edited['authors'] = local_metadata['authors']
            print(f"✅ Auto-filled from local: {', '.join(local_metadata['authors'])}")
        
        # Year
        display_field_with_sources(
            "Year",
            edited.get('year', ''),
            online_metadata.get('year') if online_metadata else None,
            local_metadata.get('year') if local_metadata else None
        )
        current_year = edited.get('year', '')
        if current_year:
            prompt_text = f"New year (current: {current_year}, Enter to keep, or 'clear' to remove): "
        else:
            prompt_text = "New year (Enter to skip, or 'clear' to remove): "
        new_value = input(prompt_text).strip()
        if new_value:
            if new_value.lower() == 'clear':
                edited['year'] = ''
                edited.pop('_year_confirmed', None)  # Clear confirmation flag if year is cleared
                print("✅ Year cleared")
            elif new_value.isdigit() and len(new_value) == 4:
                edited['year'] = new_value
                edited.pop('_year_confirmed', None)  # Clear confirmation flag to allow re-editing
                print(f"✅ Year updated to: {new_value}")
            else:
                print("⚠️  Invalid year format (expected 4 digits, e.g., '2024'). Year not changed.")
        elif online_metadata and online_metadata.get('year') and not edited.get('year'):
            edited['year'] = online_metadata['year']
            edited.pop('_year_confirmed', None)  # Clear confirmation flag
            print(f"✅ Auto-filled from online: {online_metadata['year']}")
        elif local_metadata and local_metadata.get('year') and not edited.get('year'):
            edited['year'] = local_metadata['year']
            edited.pop('_year_confirmed', None)  # Clear confirmation flag
            print(f"✅ Auto-filled from local: {local_metadata['year']}")
        
        # Journal/Source
        display_field_with_sources(
            "Journal/Source",
            edited.get('journal', ''),
            online_metadata.get('journal') if online_metadata else None,
            local_metadata.get('journal') if local_metadata else None
        )
        
        # Show journal validation if validator available
        current_journal = edited.get('journal', '').strip()
        if self.journal_validator and current_journal:
            validation = self.journal_validator.validate_journal(current_journal)
            if validation['matched']:
                journal_name = validation['journal_name']
                paper_count = validation['paper_count']
                match_type = validation['match_type']
                
                if match_type == 'exact':
                    print(f"  ✅ Recognized: {journal_name} ({paper_count} papers in your collection)")
                elif match_type == 'fuzzy':
                    print(f"  💡 Suggestion: '{current_journal}' → '{journal_name}' ({paper_count} papers, {validation['confidence']}% confidence)")
                    accept = input("  Use suggestion? [Y/n]: ").strip().lower()
                    if not accept or accept == 'y':
                        edited['journal'] = journal_name
                        print(f"  ✅ Using: {journal_name}")
            else:
                print(f"  🆕 New journal (not in your Zotero collection)")
        
        new_value = input("New journal/source (or Enter to keep current): ").strip()
        if new_value:
            # Validate newly entered journal
            edited['journal'] = new_value
            if self.journal_validator:
                validation = self.journal_validator.validate_journal(new_value)
                if validation['matched']:
                    if validation['match_type'] == 'fuzzy':
                        print(f"  💡 Did you mean '{validation['journal_name']}'? ({validation['paper_count']} papers, {validation['confidence']}% confidence)")
                        use_suggestion = input("  Use suggestion? [Y/n]: ").strip().lower()
                        if not use_suggestion or use_suggestion == 'y':
                            edited['journal'] = validation['journal_name']
                            print(f"  ✅ Using: {validation['journal_name']}")
                    elif validation['match_type'] == 'exact':
                        print(f"  ✅ Recognized: {validation['journal_name']} ({validation['paper_count']} papers)")
                else:
                    print(f"  🆕 New journal (not in your Zotero collection)")
        elif online_metadata and online_metadata.get('journal') and not edited.get('journal'):
            edited['journal'] = online_metadata['journal']
            print(f"✅ Auto-filled from online: {online_metadata['journal']}")
            # Validate auto-filled journal
            if self.journal_validator:
                validation = self.journal_validator.validate_journal(edited['journal'])
                if validation['matched']:
                    print(f"  ✅ Recognized: {validation['journal_name']} ({validation['paper_count']} papers)")
        elif local_metadata and local_metadata.get('journal') and not edited.get('journal'):
            edited['journal'] = local_metadata['journal']
            print(f"✅ Auto-filled from local: {local_metadata['journal']}")
            # Local journal is already from Zotero, so it should be recognized
            if self.journal_validator:
                validation = self.journal_validator.validate_journal(edited['journal'])
                if validation['matched']:
                    print(f"  ✅ Recognized: {validation['journal_name']} ({validation['paper_count']} papers)")
        
        # DOI - Always allow manual entry, even without Zotero items
        display_field_with_sources(
            "DOI",
            edited.get('doi', ''),
            online_metadata.get('doi') if online_metadata else None,
            local_metadata.get('doi') if local_metadata else None
        )
        print("You can enter DOI manually (supports: 10.1234/example, https://doi.org/10.1234/example, doi:10.1234/example)")
        new_value = input("New DOI (or Enter to keep current): ").strip()
        
        if new_value:
            # Validate and normalize the entered DOI
            validator = self.metadata_processor.validator
            is_valid, cleaned_doi, reason = validator.validate_doi(new_value)
            
            if is_valid and cleaned_doi:
                edited['doi'] = cleaned_doi
                print(f"✅ Valid DOI: {cleaned_doi}")
                
                # If no metadata was found yet, offer to fetch it using the DOI
                if not has_online and not has_local:
                    fetch_choice = input(f"Fetch metadata for this DOI? [y/n]: ").strip().lower()
                    if fetch_choice == 'y':
                        print(f"🔍 Fetching metadata for DOI: {cleaned_doi}...")
                        # Try to fetch metadata using the DOI (using private method - it's the right interface)
                        fetched_metadata = self.metadata_processor._try_apis_for_doi(cleaned_doi, ['crossref', 'openalex', 'pubmed'])
                        if fetched_metadata:
                            source = fetched_metadata.get('source', 'unknown')
                            print(f"✅ Found metadata from {source}")
                            # Ask if user wants to merge fetched metadata
                            merge_choice = input("Merge fetched metadata with current? [y/n]: ").strip().lower()
                            if merge_choice == 'y':
                                # Fill gaps with fetched metadata (don't overwrite existing values)
                                for key, value in fetched_metadata.items():
                                    if value and not edited.get(key) and key not in ['source', 'raw_type']:
                                        edited[key] = value
                                        # Show brief summary for key fields
                                        if key in ['title', 'authors', 'year', 'journal', 'abstract']:
                                            display_val = str(value)
                                            if key == 'authors' and isinstance(value, list):
                                                display_val = ', '.join(value[:3])
                                            elif key == 'abstract' and len(str(value)) > 50:
                                                display_val = str(value)[:50] + "..."
                                            print(f"  ✅ Added {key}: {display_val}")
                                has_online = True  # Now we have online metadata
                                online_metadata = fetched_metadata
                                online_source = source
                        else:
                            print("❌ No metadata found for this DOI in any API")
            else:
                print(f"❌ {reason}")
                retry = input("Retry with different DOI? [y/n]: ").strip().lower()
                if retry == 'y':
                    # Re-prompt for DOI (don't recurse through entire function)
                    retry_value = input("Enter DOI again: ").strip()
                    if retry_value:
                        is_valid, cleaned_doi, reason = validator.validate_doi(retry_value)
                        if is_valid and cleaned_doi:
                            edited['doi'] = cleaned_doi
                            print(f"✅ Valid DOI: {cleaned_doi}")
                        else:
                            print(f"❌ {reason} - skipping DOI")
                # Otherwise keep original or empty
        elif online_metadata and online_metadata.get('doi') and not edited.get('doi'):
            edited['doi'] = online_metadata['doi']
            print(f"✅ Auto-filled from online: {online_metadata['doi']}")
        elif local_metadata and local_metadata.get('doi') and not edited.get('doi'):
            edited['doi'] = local_metadata['doi']
            print(f"✅ Auto-filled from local: {local_metadata['doi']}")
        
        # Abstract
        current_abstract = edited.get('abstract', '')
        online_abstract = online_metadata.get('abstract') if online_metadata else None
        local_abstract = local_metadata.get('abstract') if local_metadata else None
        
        print(f"\nAbstract:")
        if current_abstract:
            # Truncate long abstracts for display
            display_abstract = current_abstract[:200] + "..." if len(current_abstract) > 200 else current_abstract
            print(f"  [Current] {display_abstract}")
        if online_abstract:
            display_abstract = online_abstract[:200] + "..." if len(online_abstract) > 200 else online_abstract
            print(f"  [Online]  {display_abstract}")
        if local_abstract:
            display_abstract = local_abstract[:200] + "..." if len(local_abstract) > 200 else local_abstract
            print(f"  [Local]   {display_abstract}")
        
        # Suggest smart merge for abstract
        suggestions = []
        if online_abstract and not current_abstract:
            suggestions.append("Use online abstract")
        if local_abstract and not current_abstract:
            suggestions.append("Use local abstract")
        if online_abstract and local_abstract and online_abstract != local_abstract:
            suggestions.append("Conflict detected - choose manually")
        
        if suggestions:
            print(f"  💡 Suggestions: {' | '.join(suggestions)}")
        
        print(Colors.colorize("Options:", ColorScheme.ACTION))
        print(Colors.colorize("[Enter] Keep current", ColorScheme.LIST))
        print(Colors.colorize("[o] Use online abstract", ColorScheme.LIST))
        print(Colors.colorize("[l] Use local abstract", ColorScheme.LIST))
        print(Colors.colorize("[e] Edit manually", ColorScheme.LIST))
        
        abstract_choice = input("Abstract choice: ").strip().lower()
        
        if abstract_choice == 'o' and online_abstract:
            edited['abstract'] = online_abstract
            print(f"✅ Using online abstract ({len(online_abstract)} characters)")
        elif abstract_choice == 'l' and local_abstract:
            edited['abstract'] = local_abstract
            print(f"✅ Using local abstract ({len(local_abstract)} characters)")
        elif abstract_choice == 'e':
            print("Enter new abstract (end with 'END' on a new line):")
            lines = []
            while True:
                line = input()
                if line.strip() == 'END':
                    break
                lines.append(line)
            new_abstract = '\n'.join(lines)
            if new_abstract.strip():
                edited['abstract'] = new_abstract.strip()
                print(f"✅ Abstract updated ({len(new_abstract)} characters)")
        elif online_metadata and online_metadata.get('abstract') and not edited.get('abstract'):
            edited['abstract'] = online_metadata['abstract']
            print(f"✅ Auto-filled from online: {len(online_metadata['abstract'])} characters")
        elif local_metadata and local_metadata.get('abstract') and not edited.get('abstract'):
            edited['abstract'] = local_metadata['abstract']
            print(f"✅ Auto-filled from local: {len(local_metadata['abstract'])} characters")
        
        # Document type
        print("\nDocument type:")
        print("[1] journal_article  [2] book_chapter  [3] conference_paper")
        print("[4] book  [5] thesis  [6] report  [7] news_article")
        current = edited.get('document_type', 'unknown')
        online_type = online_metadata.get('document_type') if online_metadata else None
        local_type = local_metadata.get('document_type') if local_metadata else None
        
        if current:
            print(f"  [Current] {current}")
        if online_type:
            print(f"  [Online]  {online_type}")
        if local_type:
            print(f"  [Local]   {local_type}")
        
        new_value = input(f"Type (1-7, or Enter for '{current}'): ").strip()
        
        type_map = {
            '1': 'journal_article',
            '2': 'book_chapter',
            '3': 'conference_paper',
            '4': 'book',
            '5': 'thesis',
            '6': 'report',
            '7': 'news_article'
        }
        if new_value in type_map:
            edited['document_type'] = type_map[new_value]
        elif online_metadata and online_metadata.get('document_type') and not edited.get('document_type'):
            edited['document_type'] = online_metadata['document_type']
            print(f"✅ Auto-filled from online: {online_metadata['document_type']}")
        elif local_metadata and local_metadata.get('document_type') and not edited.get('document_type'):
            edited['document_type'] = local_metadata['document_type']
            print(f"✅ Auto-filled from local: {local_metadata['document_type']}")
        
        # Tags - offer to edit if we have tag sources
        current_tags = edited.get('tags', [])
        online_tags_list = online_metadata.get('tags', []) if online_metadata else []
        local_tags_list = local_metadata.get('tags', []) if local_metadata else []
        
        if current_tags or online_tags_list or local_tags_list:
            print("\n🏷️  Tags:")
            if current_tags:
                print(f"  [Current] {', '.join(current_tags)}")
            if online_tags_list:
                print(f"  [Online]  {', '.join(online_tags_list)}")
            if local_tags_list:
                print(f"  [Local]   {', '.join(local_tags_list)}")
            
            print(Colors.colorize("\nTag editing options:", ColorScheme.ACTION))
            print(Colors.colorize("  [Enter] = Keep current tags (or none)", ColorScheme.LIST))
            print(Colors.colorize("  [t]     = Edit tags interactively", ColorScheme.LIST))
            
            tag_choice = input("Choice: ").strip().lower()
            if tag_choice == 't':
                edited['tags'] = self.edit_tags_interactively(
                    current_tags=current_tags,
                    online_tags=online_tags_list,
                    local_tags=local_tags_list
                )
            # If user presses Enter, tags stay as they are in edited dict
        
        # Notes
        current_note = edited.get('note', '')
        online_note = online_metadata.get('note', '') if online_metadata else None
        local_note = local_metadata.get('note', '') if local_metadata else None
        
        if current_note or online_note or local_note:
            print("\n📝 Note:")
            if current_note:
                display_note = current_note[:200] + "..." if len(current_note) > 200 else current_note
                print(f"  [Current] {display_note}")
            if online_note:
                display_note = online_note[:200] + "..." if len(online_note) > 200 else online_note
                print(f"  [Online]  {display_note}")
            if local_note:
                display_note = local_note[:200] + "..." if len(local_note) > 200 else local_note
                print(f"  [Local]   {display_note}")
            
            print(Colors.colorize("\nNote editing options:", ColorScheme.ACTION))
            print(Colors.colorize("  [Enter] = Keep current note (or none)", ColorScheme.LIST))
            print(Colors.colorize("  [o]     = Use online note", ColorScheme.LIST))
            print(Colors.colorize("  [l]     = Use local note", ColorScheme.LIST))
            print(Colors.colorize("  [e]     = Edit note manually", ColorScheme.LIST))
            
            note_choice = input("Choice: ").strip().lower()
            
            if note_choice == 'o' and online_note:
                edited['note'] = online_note
                print(f"✅ Using online note ({len(online_note)} characters)")
            elif note_choice == 'l' and local_note:
                edited['note'] = local_note
                print(f"✅ Using local note ({len(local_note)} characters)")
            elif note_choice == 'e':
                print("Enter new note (end with 'END' on a new line):")
                lines = []
                while True:
                    line = input()
                    if line.strip() == 'END':
                        break
                    lines.append(line)
                new_note = '\n'.join(lines)
                if new_note.strip():
                    edited['note'] = new_note.strip()
                    print(f"✅ Note updated ({len(new_note)} characters)")
        
        print("\n✅ Metadata editing complete")
        print()
        
        # Show summary
        print("Updated metadata:")
        print(f"  Title: {edited.get('title', 'Unknown')}")
        print(f"  Authors: {'; '.join(edited.get('authors', ['Unknown']))}")
        print(f"  Year: {edited.get('year', 'Unknown')}")
        print(f"  Journal: {edited.get('journal', 'Unknown')}")
        print(f"  DOI: {edited.get('doi', 'Unknown')}")
        print(f"  Type: {edited.get('document_type', 'unknown')}")
        if edited.get('abstract'):
            abstract_preview = edited['abstract'][:100] + "..." if len(edited['abstract']) > 100 else edited['abstract']
            print(f"  Abstract: {abstract_preview}")
        if edited.get('tags'):
            print(f"  Tags: {', '.join(edited['tags'])}")
        if edited.get('note'):
            note_preview = edited['note'][:100] + "..." if len(edited['note']) > 100 else edited['note']
            print(f"  Note: {note_preview}")
        print()
        
        return edited
    
    def _display_numbered_field_comparison(self, current: dict, online: dict, local: dict, online_source: str = None):
        """Display numbered field comparison for bulk operations."""
        print(Colors.colorize("\n📋 FIELD COMPARISON:", ColorScheme.PAGE_TITLE))
        print("=" * 80)
        
        # Map method names to display names
        source_map = {
            'crossref_api': 'CrossRef',
            'arxiv_api': 'arXiv',
            'ollama_fallback': 'Ollama (AI)',
            'ollama_web_article': 'Ollama (Web)',
            'isbn_found': 'ISBN',
            None: 'Online Lib'
        }
        online_label = source_map.get(online_source, online_source or 'Online Lib')
        
        field_map = [
            (1, 'title', 'Title'),
            (2, 'authors', 'Authors'),
            (3, 'year', 'Year'),
            (4, 'journal', 'Journal'),
            (5, 'doi', 'DOI'),
            (6, 'abstract', 'Abstract'),
            (7, 'document_type', 'Document Type')
        ]
        
        for num, field_key, field_name in field_map:
            current_val = current.get(field_key, '')
            online_val = online.get(field_key, '') if online else ''
            local_val = local.get(field_key, '') if local else ''
            
            print(f"\n[{num}] {field_name}:")
            
            # Special handling for tags
            if field_key == 'tags':
                current_tags = self._format_tags_for_display(current_val)
                online_tags = self._format_tags_for_display(online_val)
                local_tags = self._format_tags_for_display(local_val)
                
                if current_tags:
                    print(f"    {'Scan:':<12} {current_tags}")
                if online_tags:
                    print(f"    {online_label + ':':<12} {online_tags}")
                if local_tags:
                    print(f"    {'Zotero:':<12} {local_tags}")
                    
                # Show tag differences (following book script logic)
                if online_tags and local_tags:
                    current_tag_set = set(current_tags.split(', ')) if current_tags else set()
                    online_tag_set = set(online_tags.split(', ')) if online_tags else set()
                    local_tag_set = set(local_tags.split(', ')) if local_tags else set()
                    
                    online_only = online_tag_set - local_tag_set
                    local_only = local_tag_set - online_tag_set
                    
                    if online_only:
                        print(f"    Only online: {', '.join(sorted(online_only))}")
                    if local_only:
                        print(f"    Only local: {', '.join(sorted(local_only))}")
            else:
                # Regular field handling
                if current_val:
                    if field_key == 'abstract':
                        display_val = current_val[:100] + "..." if len(str(current_val)) > 100 else current_val
                    else:
                        display_val = current_val
                    print(f"    {'Scan:':<12} {display_val}")
                
                if online_val:
                    if field_key == 'abstract':
                        display_val = online_val[:100] + "..." if len(str(online_val)) > 100 else online_val
                    else:
                        display_val = online_val
                    print(f"    {online_label + ':':<12} {display_val}")
                
                if local_val:
                    if field_key == 'abstract':
                        display_val = local_val[:100] + "..." if len(str(local_val)) > 100 else local_val
                    else:
                        display_val = local_val
                    print(f"    {'Zotero:':<12} {display_val}")
        
        print("\n" + "=" * 80)
    
    def _parse_field_numbers(self, input_str: str) -> list:
        """Parse field numbers from user input (e.g., '1,3,5' or '1-3,5')."""
        numbers = []
        for part in input_str.split(','):
            part = part.strip()
            if '-' in part:
                start, end = map(int, part.split('-'))
                numbers.extend(range(start, end + 1))
            else:
                numbers.append(int(part))
        return numbers
    
    def _overwrite_all_with_online(self, current: dict, online: dict) -> dict:
        """Overwrite all current metadata (except tags) with online metadata."""
        edited = current.copy()
        
        field_map = ['title', 'authors', 'year', 'journal', 'doi', 'abstract', 'document_type']
        
        for field in field_map:
            if online.get(field):
                edited[field] = online[field]
                print(f"  ✅ {field}: {online[field]}")
        
        # Special handling for tags - merge instead of overwrite
        current_tags = edited.get('tags', [])
        online_tags = online.get('tags', [])
        
        if online_tags:
            merged_tags = self._merge_tags(current_tags, online_tags)
            edited['tags'] = merged_tags
            print(f"  ✅ tags: merged tags ({len(merged_tags)} total)")
        
        return edited
    
    def _fill_gaps_from_online(self, current: dict, online: dict) -> dict:
        """Fill gaps in current metadata with online metadata."""
        edited = current.copy()
        
        field_map = ['title', 'authors', 'year', 'journal', 'doi', 'abstract', 'document_type']
        
        for field in field_map:
            current_val = current.get(field, '')
            online_val = online.get(field, '')
            
            # Fill if current is empty but online has value
            if not current_val and online_val:
                edited[field] = online_val
                print(f"  ✅ {field}: {online_val}")
            elif current_val and online_val:
                print(f"  ⏭️  {field}: keeping current (already has value)")
            else:
                print(f"  ⏭️  {field}: no online value available")
        
        # Special handling for tags - fill gaps (merge if current is empty)
        current_tags = edited.get('tags', [])
        online_tags = online.get('tags', [])
        
        if not current_tags and online_tags:
            edited['tags'] = online_tags
            print(f"  ✅ tags: added online tags ({len(online_tags)} tags)")
        elif current_tags and online_tags:
            # Merge tags without duplicates
            merged_tags = self._merge_tags(current_tags, online_tags)
            if len(merged_tags) > len(current_tags):
                edited['tags'] = merged_tags
                added_count = len(merged_tags) - len(current_tags)
                print(f"  ✅ tags: merged {added_count} new tags from online")
            else:
                print(f"  ⏭️  tags: no new tags to add from online")
        elif not online_tags:
            print(f"  ⏭️  tags: no online tags available")
        
        return edited
    
    def _overwrite_specific_fields(self, current: dict, online: dict, field_numbers: list) -> dict:
        """Overwrite specific fields with online metadata."""
        edited = current.copy()
        
        field_map = {
            1: 'title',
            2: 'authors', 
            3: 'year',
            4: 'journal',
            5: 'doi',
            6: 'abstract',
            7: 'document_type'
        }
        
        for num in field_numbers:
            if num in field_map:
                field = field_map[num]
                if online.get(field):
                    edited[field] = online[field]
                    print(f"  ✅ {field}: {online[field]}")
                else:
                    print(f"  ❌ {field}: no online value available")
            else:
                print(f"  ❌ Invalid field number: {num}")
        
        return edited
    
    def _display_single_source_fields(self, current: dict, source: dict, source_name: str):
        """Display fields for single source editing."""
        field_map = [
            ('title', 'Title'),
            ('authors', 'Authors'),
            ('year', 'Year'),
            ('journal', 'Journal'),
            ('doi', 'DOI'),
            ('abstract', 'Abstract'),
            ('document_type', 'Document Type')
        ]
        
        for field_key, field_name in field_map:
            current_val = current.get(field_key, '')
            source_val = source.get(field_key, '') if source else ''
            
            print(f"\n{field_name}:")
            if current_val:
                if field_key == 'abstract':
                    display_val = current_val[:100] + "..." if len(str(current_val)) > 100 else current_val
                else:
                    display_val = current_val
                print(f"  Current: {display_val}")
            
            if source_val:
                if field_key == 'abstract':
                    display_val = source_val[:100] + "..." if len(str(source_val)) > 100 else source_val
                else:
                    display_val = source_val
                print(f"  {source_name.title()}: {display_val}")
            
            # Simple field editing
            new_value = input(f"New {field_name.lower()} (or Enter to keep current): ").strip()
            if new_value:
                if field_key == 'authors':
                    current['authors'] = [a.strip() for a in new_value.split(',')]
                else:
                    current[field_key] = new_value
                print(f"✅ Updated {field_name.lower()}")
            elif source_val and not current_val:
                # Auto-fill from source if current is empty
                current[field_key] = source_val
                print(f"✅ Auto-filled from {source_name}: {source_val}")
    
    def _format_tags_for_display(self, tags) -> str:
        """Format tags for display (following book script logic)."""
        if not tags:
            return ''
        
        if isinstance(tags, list):
            # Handle both dict format {'tag': 'name'} and string format
            tag_list = []
            for tag in tags:
                if isinstance(tag, dict):
                    tag_list.append(tag.get('tag', ''))
                else:
                    tag_list.append(str(tag))
            return ', '.join([t for t in tag_list if t])
        else:
            return str(tags)
    
    def _merge_tags(self, current_tags, new_tags):
        """Merge tags without duplicates (following book script logic)."""
        # Convert all tags to standard format
        current_tag_names = set()
        if current_tags:
            for tag in current_tags:
                if isinstance(tag, dict):
                    current_tag_names.add(tag.get('tag', ''))
                else:
                    current_tag_names.add(str(tag))
        
        new_tag_names = set()
        if new_tags:
            for tag in new_tags:
                if isinstance(tag, dict):
                    new_tag_names.add(tag.get('tag', ''))
                else:
                    new_tag_names.add(str(tag))
        
        # Merge without duplicates
        all_tag_names = current_tag_names.union(new_tag_names)
        
        # Convert back to dict format
        return [{'tag': tag_name} for tag_name in all_tag_names if tag_name]
    
    def _load_tag_groups(self) -> dict:
        """Load tag groups from configuration (following daemon pattern)."""
        from pathlib import Path
        import configparser
        
        # Use same root_dir pattern as load_config()
        root_dir = Path(__file__).parent.parent
        
        config = configparser.ConfigParser()
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        tag_groups = {}
        
        try:
            if 'TAG_GROUPS' in config:
                for key, value in config['TAG_GROUPS'].items():
                    # Parse enhanced syntax: "add:tag1,tag2 remove:tag3" or simple "tag1,tag2"
                    tags = self._parse_tag_group_syntax(value)
                    tag_groups[key] = tags
        except Exception as e:
            self.logger.warning(f"Could not load tag groups: {e}")
        
        return tag_groups
    
    def _parse_tag_group_syntax(self, value: str) -> list:
        """Parse tag group value with enhanced syntax support.
        
        Supports:
        - "tag1,tag2" - simple comma-separated list
        - "add:tag1,tag2" - explicit add
        - "add:tag1,tag2 remove:tag3" - add and remove
        - "remove:tag1,tag2" - explicit remove only
        
        Returns list of tag operations dict with 'add' and/or 'remove' keys.
        """
        if not value:
            return []
        
        # Dictionary to store add and remove operations
        operations = {'add': [], 'remove': []}
        
        # Check if we have add: or remove: prefixes
        if 'add:' in value or 'remove:' in value:
            # Parse enhanced syntax - split by add: and remove: markers
            import re
            
            # Split on 'add:' or 'remove:' while keeping the delimiters
            # This handles tags with spaces properly
            parts = re.split(r'(add:|remove:)', value)
            
            current_operation = None
            
            for part in parts:
                part = part.strip()
                if part == 'add:':
                    current_operation = 'add'
                elif part == 'remove:':
                    current_operation = 'remove'
                elif part and current_operation:
                    # Parse comma-separated tags
                    tags = [tag.strip() for tag in part.split(',') if tag.strip()]
                    operations[current_operation].extend(tags)
        else:
            # Simple syntax: just comma-separated tags
            operations['add'] = [tag.strip() for tag in value.split(',') if tag.strip()]
        
        return operations
    
    def edit_tags_interactively(self, current_tags: list = None, online_tags: list = None, local_tags: list = None) -> list:
        """Interactive tag editing interface with separate menu system."""
        print("\n" + "="*80)
        print("🏷️  TAG EDITING")
        print("="*80)
        
        # Convert tags to standard format for display
        current_tag_names = self._extract_tag_names(current_tags)
        online_tag_names = self._extract_tag_names(online_tags)
        local_tag_names = self._extract_tag_names(local_tags)
        
        # Show current tag sources
        print(Colors.colorize("\n📋 CURRENT TAG SOURCES:", ColorScheme.PAGE_TITLE))
        if current_tag_names:
            print(f"  {'Scan:':<12} {', '.join(current_tag_names)}")
        if online_tag_names:
            print(f"  {'Online:':<12} {', '.join(online_tag_names)}")
        if local_tag_names:
            print(f"  {'Zotero:':<12} {', '.join(local_tag_names)}")
        
        # Start with current tags as base
        working_tags = current_tag_names.copy()
        
        while True:
            print(f"\n📝 CURRENT TAGS: {', '.join(working_tags) if working_tags else '(none)'}")
            print("=" * 60)
            print("\n🔧 TAG ACTIONS:")
            
            # Show tag groups with their actual tags
            group1_tags = self._format_tag_group_display(self.tag_groups.get('group1', {}))
            group2_tags = self._format_tag_group_display(self.tag_groups.get('group2', {}))
            group3_tags = self._format_tag_group_display(self.tag_groups.get('group3', {}))
            
            print("  (s) Skip tag editing")
            print(f"  1. Add tag group 1: {group1_tags}")
            print(f"  2. Add tag group 2: {group2_tags}")
            print(f"  3. Add tag group 3: {group3_tags}")
            print("  4. Add online metadata tags")
            print("  5. Add local Zotero tags")
            print("  6. Add custom tag")
            print("  7. Remove specific tag")
            print("  8. Clear all tags")
            print("  9. Edit all tags at once")
            print("  10. Show tag group details")
            print("  (W) Write (apply) and return")
            print("  (s) Skip (return without changes)")
            print("=" * 60)
            print(f"📋 FINAL TAGS: {', '.join(working_tags) if working_tags else '(none)'}")
            
            choice = input("\nEnter your choice [Enter=write]: ").strip().lower()
            
            # Default to 'w' (write) if Enter is pressed
            if not choice:
                choice = 'w'
            
            if choice == 'w':
                break
            elif choice == 's':
                return current_tags  # Return original tags
            elif choice == '1':
                working_tags = self._add_tag_group(working_tags, 'group1')
            elif choice == '2':
                working_tags = self._add_tag_group(working_tags, 'group2')
            elif choice == '3':
                working_tags = self._add_tag_group(working_tags, 'group3')
            elif choice == '4':
                working_tags = self._add_online_tags(working_tags, online_tag_names)
            elif choice == '5':
                working_tags = self._add_local_tags(working_tags, local_tag_names)
            elif choice == '6':
                working_tags = self._add_custom_tag(working_tags)
            elif choice == '7':
                working_tags = self._remove_tag(working_tags)
            elif choice == '8':
                working_tags = self._clear_all_tags(working_tags)
            elif choice == '9':
                working_tags = self._edit_all_tags_at_once(working_tags)
            elif choice == '10':
                self._show_tag_group_details()
            else:
                print("❌ Invalid choice. Please try again.")
        
        # Convert back to dict format for Zotero
        return [{'tag': tag_name} for tag_name in working_tags if tag_name]
    
    def _extract_tag_names(self, tags) -> list:
        """Extract tag names from various tag formats."""
        if not tags:
            return []
        
        tag_names = []
        for tag in tags:
            if isinstance(tag, dict):
                tag_names.append(tag.get('tag', ''))
            else:
                tag_names.append(str(tag))
        
        return [name for name in tag_names if name.strip()]
    
    def _format_tag_group_display(self, group_ops: dict) -> str:
        """Format tag group operations for display.
        
        Args:
            group_ops: Dict with 'add' and/or 'remove' keys containing lists of tags
            
        Returns:
            Formatted string like "tag1, tag2" or "add:tag1, tag2 | remove:tag3"
        """
        if not group_ops or isinstance(group_ops, list):
            # Backward compatibility: if it's a list, display as-is
            if isinstance(group_ops, list):
                return ', '.join(group_ops) if group_ops else '(empty)'
            return '(empty)'
        
        add_tags = group_ops.get('add', [])
        remove_tags = group_ops.get('remove', [])
        
        parts = []
        if add_tags:
            if remove_tags:
                parts.append(f"add: {', '.join(add_tags)}")
            else:
                parts.append(', '.join(add_tags))
        if remove_tags:
            parts.append(f"remove: {', '.join(remove_tags)}")
        
        return ' | '.join(parts) if parts else '(empty)'
    
    def _add_tag_group(self, working_tags: list, group_name: str) -> list:
        """Apply tag group operations (add and/or remove tags)."""
        group_ops = self.tag_groups.get(group_name, {})
        if not group_ops:
            print(f"❌ No tags configured for {group_name}")
            return working_tags
        
        # Handle add operations
        add_tags = group_ops.get('add', [])
        remove_tags = group_ops.get('remove', [])
        
        # Add tags without duplicates
        for tag in add_tags:
            if tag not in working_tags:
                working_tags.append(tag)
        
        # Remove tags
        for tag in remove_tags:
            if tag in working_tags:
                working_tags.remove(tag)
        
        # Format summary message
        msg_parts = []
        if add_tags:
            msg_parts.append(f"Added: {', '.join(add_tags)}")
        if remove_tags:
            msg_parts.append(f"Removed: {', '.join(remove_tags)}")
        
        if msg_parts:
            print(f"✅ {group_name} tags: {' | '.join(msg_parts)}")
        
        return working_tags
    
    def _add_online_tags(self, working_tags: list, online_tag_names: list) -> list:
        """Add tags from online metadata."""
        if not online_tag_names:
            print("❌ No online tags available")
            return working_tags
        
        for tag in online_tag_names:
            if tag not in working_tags:
                working_tags.append(tag)
        print(f"✅ Added online tags: {', '.join(online_tag_names)}")
        
        return working_tags
    
    def _add_local_tags(self, working_tags: list, local_tag_names: list) -> list:
        """Add tags from local Zotero metadata."""
        if not local_tag_names:
            print("❌ No local tags available")
            return working_tags
        
        for tag in local_tag_names:
            if tag not in working_tags:
                working_tags.append(tag)
        print(f"✅ Added local tags: {', '.join(local_tag_names)}")
        
        return working_tags
    
    def _add_custom_tag(self, working_tags: list) -> list:
        """Add a custom tag entered by user."""
        tag = input("\nEnter custom tag: ").strip()
        if tag:
            if tag not in working_tags:
                working_tags.append(tag)
                print(f"✅ Added custom tag: {tag}")
            else:
                print(f"❌ Tag '{tag}' already exists")
        else:
            print("❌ No tag entered")
        
        return working_tags
    
    def _remove_tag(self, working_tags: list) -> list:
        """Remove a specific tag."""
        if not working_tags:
            print("❌ No tags to remove")
            return working_tags
        
        print(f"\n📋 CURRENT TAGS: {', '.join(working_tags)}")
        tag = input("Enter tag to remove: ").strip()
        
        if tag in working_tags:
            working_tags.remove(tag)
            print(f"✅ Removed tag: {tag}")
        else:
            print(f"❌ Tag '{tag}' not found")
        
        return working_tags
    
    def _clear_all_tags(self, working_tags: list) -> list:
        """Clear all tags."""
        confirm = input("\n⚠️  Clear ALL tags? (y/n): ").strip().lower()
        if confirm == 'y':
            print("✅ All tags cleared")
            return []
        else:
            print("❌ Tags not cleared")
            return working_tags
    
    def _edit_all_tags_at_once(self, working_tags: list) -> list:
        """Edit all tags at once by showing them on a line for direct editing."""
        print(f"\n📝 CURRENT TAGS: {', '.join(working_tags) if working_tags else '(none)'}")
        print("\n💡 Tip: You can add, remove, or reorder tags. Type 'cancel' to abort.")
        print("   Example: tag1, tag2, tag3")
        
        new_tags_str = input("\nEnter all tags (comma-separated): ").strip()
        
        if new_tags_str.lower() == 'cancel':
            print("❌ Tag editing cancelled")
            return working_tags
        
        if not new_tags_str:
            print("⚠️  Empty input - clearing all tags")
            confirm = input("Confirm clear all tags? (y/n): ").strip().lower()
            if confirm == 'y':
                print("✅ All tags cleared")
                return []
            else:
                print("❌ Tags not cleared")
                return working_tags
        
        # Parse comma-separated tags
        new_tags = [tag.strip() for tag in new_tags_str.split(',') if tag.strip()]
        
        print(f"✅ Updated tags: {', '.join(new_tags) if new_tags else '(none)'}")
        return new_tags
    
    def _show_tag_group_details(self):
        """Show details of all configured tag groups."""
        print("\n📋 CONFIGURED TAG GROUPS:")
        print("=" * 50)
        
        for group_name, tags in self.tag_groups.items():
            if tags:
                print(f"\n{group_name.upper()}:")
                for i, tag in enumerate(tags, 1):
                    print(f"  {i}. {tag}")
            else:
                print(f"\n{group_name.upper()}: (empty)")
        
        print("\n" + "=" * 50)
    
    def write_pid_file(self):
        """Write daemon PID to file."""
        import os
        with open(self.pid_file, 'w') as f:
            f.write(str(os.getpid()))
        self.logger.debug(f"PID file written: {self.pid_file}")
    
    def _check_existing_instance(self) -> bool:
        """Return True and exit gracefully if a running instance is detected.
        
        Behavior:
        - If local PID file exists and PID is alive, print message and exit(0)
        - If local PID file exists but PID is stale, remove PID file and continue
        - If remote_check_host is configured, check for remote daemon
        - If no PID file, continue
        """
        try:
            # Check local PID file
            if self.pid_file.exists():
                try:
                    existing_pid_str = self.pid_file.read_text().strip()
                    existing_pid = int(existing_pid_str)
                except Exception:
                    # Corrupt PID file; remove and continue
                    self.pid_file.unlink(missing_ok=True)
                    return False
                
                # Check if process is alive
                try:
                    os.kill(existing_pid, 0)
                    # Quiet: no console output; log at debug only
                    if self.debug:
                        self.logger.debug(f"Daemon already running (PID {existing_pid}). Exiting launcher.")
                    sys.exit(0)
                except Exception:
                    # Stale PID; remove and continue
                    self.logger.warning("Stale PID file found. Removing and starting new instance.")
                    self.pid_file.unlink(missing_ok=True)
                    return False
            
            # Check remote daemon if configured
            if self.remote_check_host:
                if self._check_remote_daemon():
                    print(f"❌ Daemon already running on {self.remote_check_host}")
                    print("   Please stop the remote daemon before starting a new instance.")
                    sys.exit(1)
        except Exception:
            # On any unexpected error, continue without blocking startup
            return False
        return False
    
    def _check_remote_daemon(self) -> bool:
        """Check if daemon is running on remote machine.
        
        Returns:
            True if remote daemon is running, False otherwise
        """
        try:
            # Try to check remote PID file via SSH
            # Format: ssh user@host "cat /path/to/.daemon.pid 2>/dev/null"
            remote_pid_file_path = str(self.pid_file)
            # Extract username from remote_check_host if format is user@host
            if '@' in self.remote_check_host:
                ssh_target = self.remote_check_host
            else:
                # Use default username (e.g., eero_22) or get from config
                # For now, assume format is just hostname, user will configure as user@host if needed
                ssh_target = self.remote_check_host
            
            # Try to read remote PID file
            cmd = ['ssh', ssh_target, f'cat "{remote_pid_file_path}" 2>/dev/null']
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            
            if result.returncode == 0 and result.stdout.strip():
                try:
                    remote_pid = int(result.stdout.strip())
                    # Check if process is alive on remote machine
                    check_cmd = ['ssh', ssh_target, f'kill -0 {remote_pid} 2>/dev/null']
                    check_result = subprocess.run(check_cmd, capture_output=True, timeout=5)
                    if check_result.returncode == 0:
                        return True
                except (ValueError, subprocess.TimeoutExpired):
                    pass
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            # SSH not available or connection failed - assume no remote daemon
            if self.debug:
                self.logger.debug(f"Could not check remote daemon: {e}")
        return False

    def remove_pid_file(self):
        """Remove PID file on shutdown."""
        if self.pid_file.exists():
            self.pid_file.unlink()
            self.logger.debug("PID file removed")
    
    def should_process(self, filename: str) -> bool:
        """Check if file should be processed.
        
        Args:
            filename: Name of file
            
        Returns:
            True if file should be processed (academic paper)
        """
        # Only process files with academic paper prefixes
        prefixes = ['NO_', 'EN_', 'DE_', 'SV_', 'FI_', 'DA_']
        name_lower = filename.lower()
        # Ignore our own generated split artifacts to prevent double-processing
        if name_lower.endswith('_split.pdf'):
            return False
        return any(filename.startswith(p) for p in prefixes)
    
    def process_paper(self, pdf_path: Path):
        """Process a single paper with full user interaction.
        
        Args:
            pdf_path: Path to PDF file
        """
        # Check if file exists before processing
        if not pdf_path.exists():
            self.logger.warning(f"File no longer exists, cannot process: {pdf_path}")
            return
        
        self.logger.info(f"New scan: {pdf_path.name}")
        
        # Close previous PDF file in viewer before opening new one
        self._close_previous_pdf_file()
        
        # Open PDF in default viewer (non-blocking)
        self._open_pdf_in_viewer(pdf_path)
        
        # Return focus to terminal after opening PDF
        time.sleep(0.5)  # Small delay to ensure PDF viewer is ready
        self._return_focus_to_terminal()
        
        # Remember the original scan path for final move operations
        self._original_scan_path = Path(pdf_path)
        
        # Ask user if document starts at a different page (early prompt to avoid wrong extraction)
        page_offset = self._prompt_for_page_offset(pdf_path)
        if page_offset is None:
            # User cancelled
            self.move_to_failed(pdf_path)
            return
        
        # Create temporary PDF without first pages if needed
        pdf_to_use = pdf_path
        temp_pdf_path = None
        effective_page_offset = 0  # Will be 0 if temp PDF created successfully
        if page_offset > 0:
            temp_pdf_path = self._create_pdf_from_page_offset(pdf_path, page_offset)
            if temp_pdf_path:
                pdf_to_use = temp_pdf_path
                effective_page_offset = 0  # Temp PDF already starts at correct page
                # Store temp PDF path for later use in _process_selected_item
                self._temp_pdf_path = temp_pdf_path
                self.logger.info(f"Using temporary PDF starting from page {page_offset + 1}")
            else:
                effective_page_offset = page_offset  # Use offset parameter if temp PDF creation failed
                self.logger.warning(f"Failed to create temporary PDF, using original with page offset {page_offset + 1}")
                self._temp_pdf_path = None
        else:
            # No page offset, clear any previous temp PDF
            self._temp_pdf_path = None
        
        try:
            # Step 1: Extract metadata
            self.logger.info("Extracting metadata...")
            
            # Step 1a: Try GREP first (fast identifier extraction + API lookup)
            # This is much faster (2-4 seconds) when identifiers are found
            self.logger.info("Step 1: Trying fast GREP identifier extraction + API lookup...")
            result = self.metadata_processor.process_pdf(pdf_to_use, use_ollama_fallback=False, page_offset=effective_page_offset)
            result = self._handle_isbn_lookup_result(result)
            
            # Check if we got metadata with authors from GREP + API
            has_metadata = result.get('success') and result.get('metadata')
            has_authors = has_metadata and result['metadata'].get('authors')
            
            # Preserve identifiers_found (contains years, etc.) from GREP step
            identifiers_found = result.get('identifiers_found', {})
            
            # Step 1b: If GREP + API succeeded, we're done (fast path)
            if has_authors:
                method = result.get('method', 'unknown')
                self.logger.info(f"✅ Fast path succeeded via {method}: {len(result['metadata'].get('authors', []))} authors")
            
            # Step 2: Fallback to GROBID if:
            # - No metadata found, OR
            # - No authors found, OR
            # - API lookup returned no results
            elif not has_authors and self.service_manager.ensure_grobid_ready():
                # Update state for backward compatibility
                self.grobid_ready = self.service_manager.grobid_ready
                self.grobid_client = self.service_manager.grobid_client
                
                self.logger.info("Step 2: No identifiers found or API lookup failed - trying GROBID...")
                metadata = self.grobid_client.extract_metadata(pdf_to_use)
                
                if metadata and metadata.get('authors'):
                    # GROBID succeeded - preserve identifiers_found from GREP
                    result = {
                        'success': True,
                        'metadata': metadata,
                        'method': 'grobid',
                        'processing_time_seconds': 0,  # GROBID timing not tracked here
                        'identifiers_found': identifiers_found  # Preserve GREP years
                    }
                    self.logger.info(f"✅ GROBID extracted: {len(metadata.get('authors', []))} authors")
                    
                    # If we have a JSTOR ID, try to fetch full metadata from CrossRef/OpenAlex
                    jstor_ids = identifiers_found.get('jstor_ids', [])
                    
                    # Normalize empty values to None BEFORE condition check (empty strings cause query issues)
                    # Stricter validation: ensure values are not empty after stripping
                    title_raw = metadata.get('title', '')
                    title = title_raw.strip() if title_raw and title_raw.strip() else None
                    
                    authors_raw = metadata.get('authors', [])
                    authors = authors_raw if (authors_raw and isinstance(authors_raw, list) and len(authors_raw) > 0) else None
                    # Ensure authors list contains non-empty strings
                    if authors:
                        authors = [a for a in authors if a and str(a).strip()]
                        if not authors:
                            authors = None
                    
                    year_raw = metadata.get('year') or identifiers_found.get('best_year')
                    year_str = None
                    year_int = None
                    if year_raw:
                        try:
                            year_str = str(year_raw).strip()
                            if year_str and year_str.isdigit():
                                year_int = int(year_str)
                                # Validate year is reasonable (1900-2100)
                                if 1900 <= year_int <= 2100:
                                    year_str = year_str  # Keep as string for CrossRef
                                else:
                                    year_str = None
                                    year_int = None
                            else:
                                year_str = None
                                year_int = None
                        except (ValueError, TypeError):
                            year_str = None
                            year_int = None
                    
                    journal_raw = metadata.get('journal', '')
                    journal = journal_raw.strip() if journal_raw and journal_raw.strip() else None
                    
                    # Check for non-empty search parameters (normalized values)
                    has_search_params = any([title, authors, year_str, journal])
                    
                    if jstor_ids and has_search_params:
                        jstor_id = jstor_ids[0]
                        self.logger.info(f"JSTOR ID {jstor_id} found - trying to fetch metadata from CrossRef/OpenAlex")
                        print(f"\n🔍 JSTOR ID found ({jstor_id}) - searching CrossRef/OpenAlex for full metadata...")
                        
                        # Ensure we have at least one search parameter (double-check after normalization)
                        if not any([title, authors, year_str, journal]):
                            self.logger.warning(f"JSTOR ID {jstor_id} found but no searchable metadata available")
                            print(f"  ⚠️  No searchable metadata (title/authors/year/journal) - skipping CrossRef/OpenAlex search")
                        else:
                            # Try CrossRef first (uses year_str)
                            try:
                                crossref_results = self.metadata_processor.crossref.search_by_metadata(
                                    title=title,
                                    authors=authors,
                                    year=year_str,  # Pass as string for CrossRef
                                    journal=journal,
                                    max_results=3
                                )
                                if crossref_results:
                                    # Use the first (most relevant) result
                                    api_metadata = crossref_results[0]
                                    # Merge tags/keywords from both sources
                                    grobid_keywords = metadata.get('keywords', [])
                                    api_tags = api_metadata.get('tags', [])
                                    api_keywords = api_metadata.get('keywords', [])
                                    
                                    # Combine all tags/keywords
                                    combined_tags = []
                                    if grobid_keywords:
                                        combined_tags.extend([str(k) for k in grobid_keywords if k])
                                    if api_tags:
                                        combined_tags.extend([str(t) if not isinstance(t, dict) else t.get('tag', '') for t in api_tags if t])
                                    if api_keywords:
                                        combined_tags.extend([str(k) for k in api_keywords if k and str(k) not in combined_tags])
                                    
                                    # Merge with existing metadata (prefer API data)
                                    metadata.update(api_metadata)
                                    # Preserve combined tags/keywords
                                    if combined_tags:
                                        metadata['tags'] = list(set(combined_tags))  # Remove duplicates
                                    metadata['jstor_id'] = jstor_id  # Preserve JSTOR ID
                                    result['metadata'] = metadata
                                    result['method'] = 'grobid+crossref'
                                    print(f"  ✅ Found metadata in CrossRef - merged with GROBID extraction")
                                    self.logger.info("JSTOR article: Found metadata in CrossRef")
                                else:
                                    # Try OpenAlex as fallback (uses year_int)
                                    try:
                                        openalex_results = self.metadata_processor.openalex.search_by_metadata(
                                            title=title,
                                            authors=authors,
                                            year=year_int,  # Pass as integer for OpenAlex
                                            journal=journal,
                                            max_results=3
                                        )
                                        if openalex_results:
                                            api_metadata = openalex_results[0]
                                            # Merge tags/keywords from both sources
                                            grobid_keywords = metadata.get('keywords', [])
                                            api_tags = api_metadata.get('tags', [])
                                            api_keywords = api_metadata.get('keywords', [])
                                            
                                            # Combine all tags/keywords
                                            combined_tags = []
                                            if grobid_keywords:
                                                combined_tags.extend([str(k) for k in grobid_keywords if k])
                                            if api_tags:
                                                combined_tags.extend([str(t) if not isinstance(t, dict) else t.get('tag', '') for t in api_tags if t])
                                            if api_keywords:
                                                combined_tags.extend([str(k) for k in api_keywords if k and str(k) not in combined_tags])
                                            
                                            # Merge with existing metadata (prefer API data)
                                            metadata.update(api_metadata)
                                            # Preserve combined tags/keywords
                                            if combined_tags:
                                                metadata['tags'] = list(set(combined_tags))  # Remove duplicates
                                            metadata['jstor_id'] = jstor_id
                                            result['metadata'] = metadata
                                            result['method'] = 'grobid+openalex'
                                            print(f"  ✅ Found metadata in OpenAlex - merged with GROBID extraction")
                                            self.logger.info("JSTOR article: Found metadata in OpenAlex")
                                        else:
                                            print(f"  ⚠️  No metadata found in CrossRef/OpenAlex - using GROBID extraction only")
                                            metadata['jstor_id'] = jstor_id
                                            result['metadata'] = metadata
                                    except Exception as e:
                                        self.logger.warning(f"OpenAlex search failed for JSTOR ID {jstor_id}: {e}")
                                        metadata['jstor_id'] = jstor_id
                                        result['metadata'] = metadata
                            except Exception as e:
                                self.logger.warning(f"CrossRef search failed for JSTOR ID {jstor_id}: {e}")
                                metadata['jstor_id'] = jstor_id
                                result['metadata'] = metadata
                else:
                    self.logger.info("GROBID did not find authors")
            
            # Step 3: Last resort - try Ollama if still no authors
            if not result.get('success') or not result.get('metadata', {}).get('authors'):
                self.logger.info("Step 3: No authors found from GREP/API/GROBID - trying Ollama as last resort...")
                if self._ensure_ollama_ready():
                    # Try with Ollama fallback
                    ollama_result = self.metadata_processor.process_pdf(pdf_to_use, use_ollama_fallback=True, 
                                                                       progress_callback=self._show_ollama_progress,
                                                                       page_offset=effective_page_offset)
                    if ollama_result['success'] and ollama_result.get('metadata', {}).get('authors'):
                        # Preserve identifiers_found from GREP
                        ollama_result['identifiers_found'] = identifiers_found
                        result = ollama_result
                        # Only log "Ollama found authors" if Ollama was actually used (not regex fallback)
                        method = ollama_result.get('method', '')
                        if method == 'ollama_fallback':
                            self.logger.info("✅ Ollama found authors")
                        elif method == 'regex_fallback':
                            self.logger.info(f"✅ Regex found authors (during Ollama fallback step)")
                        else:
                            self.logger.info(f"✅ Found authors via {method}")
                    else:
                        self.logger.warning("Ollama also failed to find authors")
                else:
                    self.logger.warning("Ollama not available - limited extraction methods only")
            
            extraction_time = result.get('processing_time_seconds', 0)
            
            # Step 2: Check if extraction succeeded
            if result['success'] and result['metadata']:
                metadata = result['metadata']
                
                # Filter garbage authors (keeps only known authors when extraction is poor)
                # For GROBID, also validates against document text to filter hallucinations
                metadata = self.filter_garbage_authors(metadata, pdf_path=pdf_to_use)

                # Check if we should skip year prompt (valid DOI + successful API lookup)
                identifiers = result.get('identifiers_found', {})
                method = result.get('method', '')
                has_valid_doi = bool(identifiers.get('dois'))
                api_succeeded = method.endswith('_api')  # crossref_api, openalex_api, pubmed_api, arxiv_api
                
                # Skip year prompt if valid DOI was found and API lookup succeeded
                # The API-provided year is reliable and doesn't need confirmation
                if has_valid_doi and api_succeeded and metadata.get('year'):
                    # Use year from API metadata directly
                    metadata['year'] = metadata.get('year')
                    metadata['_year_source'] = 'api'
                    metadata['_year_confirmed'] = True
                    self.logger.info(f"Using year from API ({method}): {metadata.get('year')}")
                    print(f"✅ Using year from API: {metadata.get('year')}")
                else:
                    # Prompt user to confirm or enter year manually
                    # First, check what year sources we have
                    grep_year = identifiers.get('best_year')
                    grobid_year = metadata.get('year')
                    
                    # Build year sources list for display
                    year_sources = []
                    if grep_year:
                        year_sources.append(('GREP (scan)', grep_year))
                    if grobid_year:
                        year_sources.append(('GROBID/API', grobid_year))
                    
                    # Prompt user to confirm or enter year
                    if year_sources:
                        # Show all year sources that were found
                        if len(year_sources) > 1:
                            # Multiple sources - check for conflicts
                            years = [source[1] for source in year_sources]
                            if len(set(years)) > 1:
                                # Conflict detected - show both and pick first as default
                                print(f"\n⚠️  Year conflict detected:")
                                for source_name, year_val in year_sources:
                                    print(f"   {source_name}:      {year_val}")
                                # Use first year as suggested default
                                suggested_year = years[0]
                                suggested_source = year_sources[0][0]
                            else:
                                # No conflict - both sources agree
                                print(f"\n📅 Year found by multiple sources:")
                                for source_name, _ in year_sources:
                                    print(f"   {source_name}:      {years[0]}")
                                suggested_year = years[0]
                                suggested_source = 'consensus'
                        else:
                            # Single source
                            suggested_source, suggested_year = year_sources[0]
                            print(f"\n📅 Year found by {suggested_source}: {suggested_year}")
                        
                        # Simple prompt: press Enter to confirm or type a different year
                        print("💡 You can type a 4-digit year to change it, or press Enter to confirm")
                        while True:
                            try:
                                prompt_text = Colors.colorize(f"Year [{suggested_year}] (Enter=confirm, type new year, 'm'=manual entry, or 'r'=restart): ", ColorScheme.ACTION)
                                year_input = self._input_with_timeout(
                                    prompt_text,
                                    timeout_seconds=self.prompt_timeout,
                                    default="",
                                    clear_buffered=True
                                )
                                if year_input is None:
                                    # Timeout - use suggested year
                                    year_input = ""
                                year_input = year_input.strip()
                            except (KeyboardInterrupt, EOFError):
                                print("\n❌ Cancelled")
                                self.move_to_failed(pdf_path)
                                return
                            
                            if not year_input:
                                # User pressed Enter - use suggested year
                                metadata['year'] = suggested_year
                                metadata['_year_source'] = suggested_source
                                print(f"✅ Using {suggested_source}: {suggested_year}")
                                self.logger.info(f"User confirmed year from {suggested_source}: {suggested_year}")
                                metadata['_year_confirmed'] = True
                                break
                            elif year_input.lower() == 'r':
                                # User wants to restart - go back to beginning of process_paper
                                print("🔄 Restarting from beginning...")
                                print("   (This will re-extract metadata and prompt for year again)")
                                self.process_paper(pdf_path)
                                return
                            elif year_input.lower() == 'm':
                                # User wants manual entry - clear suggested year and use manual prompt
                                print("📝 Manual year entry...")
                                metadata.pop('year', None)
                                # Fall through to manual entry prompt below
                                break
                            elif year_input.isdigit() and len(year_input) == 4:
                                # User entered a different year
                                metadata['year'] = year_input
                                metadata['_year_source'] = 'manual'
                                print(f"✅ Year changed to: {year_input}")
                                self.logger.info(f"User entered manual year: {year_input}")
                                metadata['_year_confirmed'] = True
                                break
                            else:
                                print("⚠️  Invalid year format (expected 4 digits, e.g., '2024')")
                                print("   Press Enter to confirm suggested year, type a 4-digit year to change it,")
                                print("   'm' for manual entry prompt, or 'r' to restart from beginning")
                
                # Prompt for year BEFORE document type, so numeric input isn't misrouted
                # (This will only prompt if no year was found by any source, or if user chose 'm' for manual entry)
                # Check if user requested manual entry (year was cleared above)
                if not metadata.get('year') or not metadata.get('_year_confirmed'):
                    year_result = self.prompt_for_year(metadata, allow_back=True)
                    # Handle special return values
                    if year_result == 'BACK':
                        # User cancelled - return gracefully, daemon continues watching
                        print("\n⏸️  Returning to watch mode - ready for next scan")
                        return
                    elif year_result == 'RESTART':
                        # User wants to restart processing this file
                        print("🔄 Restarting from beginning...")
                        self.process_paper(pdf_path)
                        return
                    else:
                        metadata = year_result  # Year was added/updated in metadata
                
                # Check if JSTOR ID was found - automatically set as journal article
                if identifiers.get('jstor_ids') and not metadata.get('document_type'):
                    metadata['document_type'] = 'journal_article'
                    self.logger.info("JSTOR ID detected - automatically set as journal article")
                    print("ℹ️  JSTOR ID detected - treating as journal article")
                
                # Check if API succeeded - skip document type prompt if already set
                # API metadata is reliable and doesn't need confirmation
                api_succeeded = method.endswith('_api')  # crossref_api, openalex_api, pubmed_api, arxiv_api
                has_document_type = bool(metadata.get('document_type'))
                
                if api_succeeded and has_document_type:
                    # API provided document type - skip prompt, mark as confirmed
                    metadata['_type_confirmed'] = True
                    self.logger.info(f"API provided document type: {metadata.get('document_type')} - skipping confirmation")
                else:
                    # Confirm/select document type early (after year entry)
                    metadata = self.confirm_document_type_early(metadata)
                    if metadata is None:
                        # User cancelled
                        self.move_to_failed(pdf_path)
                        return
                
                self.display_metadata(metadata, pdf_path, extraction_time)
            else:
                # Extraction failed - use guided workflow
                self.logger.warning("Metadata extraction failed - starting guided workflow")
                metadata = self.handle_failed_extraction(pdf_path)
                
                # Check for restart request
                if metadata and metadata.get('_restart'):
                    print("🔄 Restarting from beginning...")
                    self.process_paper(pdf_path)
                    return
                
                if metadata:
                    # Document type was already set during handle_failed_extraction
                    # (No need to confirm again)
                    
                    # Display what we gathered
                    self.display_metadata(metadata, pdf_path, extraction_time)
                else:
                    # User gave up
                    self.move_to_failed(pdf_path)
                    self.logger.info("User cancelled - moved to failed/")
                    return
            
            # Step 3: Interactive Zotero search (with author selection and item selection)
            action = 'none'
            selected_item = None
            updated_metadata = metadata.copy()  # Track any edits made during search
            should_restart_search = False
            
            if self.local_zotero:
                while True:
                    action, selected_item, updated_metadata = self.search_and_display_local_zotero(updated_metadata)
                    
                    # Handle back/restart actions - allow user to go back and restart
                    if action == 'back':
                        print("⬅️  Going back to author selection...")
                        # Loop will restart and prompt again
                        continue
                    elif action == 'restart':
                        # User wants to restart processing this file from the very beginning
                        print("🔄 Restarting from beginning...")
                        self.process_paper(pdf_path)
                        return
                    
                    break
            
            # Step 4: Handle action from Zotero search
            if action == 'select' and selected_item:
                # User selected an item - offer to attach PDF
                self.handle_item_selected(pdf_path, updated_metadata, selected_item)
            elif action == 'search':
                # User wants to search again - allow year editing by clearing confirmation flag
                if updated_metadata.get('_year_confirmed'):
                    updated_metadata.pop('_year_confirmed', None)
                # Reset authors to full set if available, then recursive call
                if updated_metadata.get('_all_authors'):
                    updated_metadata['authors'] = updated_metadata['_all_authors'].copy()
                action2, selected_item2, updated_metadata = self.search_and_display_local_zotero(updated_metadata)
                if action2 == 'select' and selected_item2:
                    result = self.handle_item_selected(pdf_path, updated_metadata, selected_item2)
                    # Note: if user wants to go back, handle_item_selected already moved the file appropriately
                elif action2 == 'back' or action2 == 'restart':
                    # User went back during search - restart
                    print("⬅️  Going back to manual processing...")
                    self.move_to_manual_review(pdf_path)
                elif action2 == 'quit':
                    print("🔚 Exiting current processing per user request")
                    return
                # Handle other actions from second search if needed
            elif action == 'edit':
                # Edit metadata then search again
                print("\n✏️  Editing metadata...")
                edited_metadata = self.edit_metadata_interactively(updated_metadata)
                
                if edited_metadata:
                    # Re-run Zotero search with edited metadata
                    print("\n🔍 Searching Zotero with edited metadata...")
                    action2, selected_item2, final_metadata = self.search_and_display_local_zotero(edited_metadata)
                    
                    if action2 == 'select' and selected_item2:
                        result = self.handle_item_selected(pdf_path, final_metadata, selected_item2)
                        # Note: if user wants to go back, handle_item_selected already moved the file appropriately
                    elif action2 == 'create':
                        # User wants to create new item after editing
                        success = self.handle_create_new_item(pdf_path, final_metadata)
                        if not success:
                            self.logger.info("Item creation cancelled or failed")
                    elif action2 == 'back' or action2 == 'restart':
                        print("⬅️  Going back...")
                        self.move_to_manual_review(pdf_path)
                    elif action2 == 'quit':
                        print("🔚 Exiting current processing per user request")
                        return
                    else:
                        # No action or skip
                        self.move_to_manual_review(pdf_path)
                else:
                    # User cancelled editing
                    print("❌ Metadata editing cancelled")
                    self.move_to_manual_review(pdf_path)
            elif action == 'create':
                # Create new Zotero item with online library check
                # Use updated_metadata which includes any edited authors
                success = self.handle_create_new_item(pdf_path, updated_metadata)
                if not success:
                    # User cancelled or error occurred
                    self.logger.info("Item creation cancelled or failed")
            elif action == 'skip':
                # User wants to skip this document
                self.move_to_skipped(pdf_path)
            elif action == 'quit':
                # User wants to quit current processing
                print("🔚 Exiting current processing per user request")
                return
            else:  # action == 'none' or unknown
                # No matches found - move to manual
                print("📝 Moving to manual review...")
                self.move_to_manual_review(pdf_path)
            
        except Exception as e:
            self.logger.error(f"Processing error: {e}", exc_info=self.debug)
            self.move_to_failed(pdf_path)
        finally:
            # Close PDF viewer when processing completes
            self._close_pdf_viewer()
            
            # Clean up temporary PDF if created
            temp_to_cleanup = temp_pdf_path if 'temp_pdf_path' in locals() else getattr(self, '_temp_pdf_path', None)
            if temp_to_cleanup and temp_to_cleanup.exists():
                try:
                    temp_to_cleanup.unlink()
                    self.logger.info(f"Cleaned up temporary PDF: {temp_to_cleanup.name}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up temporary PDF {temp_to_cleanup}: {e}")
            # Clear the instance variable
            self._temp_pdf_path = None
    
    def handle_user_choice(self, choice: str, pdf_path: Path, metadata: dict, 
                          local_matches: list, result: dict):
        """Handle user choice based on context (Zotero matches found or not).
        
        Args:
            choice: User's menu choice
            pdf_path: Path to PDF file
            metadata: Extracted metadata
            local_matches: List of Zotero matches (empty if none found)
            result: Original extraction result
        """
        if choice == 'q':
            self.logger.info("User requested quit")
            self.shutdown(None, None)
            return
        
        if local_matches:
            # Zotero matches were found - handle attachment-focused choices
            self.handle_zotero_match_choice(choice, pdf_path, metadata, local_matches, result)
        else:
            # No matches - handle standard choices
            self.handle_standard_choice(choice, pdf_path, metadata, result)
    
    def handle_zotero_match_choice(self, choice: str, pdf_path: Path, metadata: dict, 
                                  local_matches: list, result: dict):
        """Handle choices when Zotero matches were found."""
        if choice == '1':  # Attach PDF to existing Zotero item
            # Select which match to use
            if len(local_matches) == 1:
                selected_match = local_matches[0]
                print(f"\n📎 Attaching to: {selected_match.get('title', 'Unknown')}")
            else:
                print(f"\n📎 Multiple matches found. Select which one:")
                for i, match in enumerate(local_matches[:5], 1):
                    print(f"[{i}] {match.get('title', 'Unknown')} ({match.get('year', '?')})")
                
                while True:
                    try:
                        idx = int(input("Select match (1-5): ").strip())
                        if 1 <= idx <= min(5, len(local_matches)):
                            selected_match = local_matches[idx - 1]
                            break
                        else:
                            print("Invalid selection. Please try again.")
                    except ValueError:
                        print("Please enter a number.")
            
            success = self.attach_to_existing_zotero_item(pdf_path, selected_match, metadata)
            if success:
                self.logger.info("Successfully attached to existing Zotero item")
            else:
                self.logger.info("Failed to attach to Zotero item")
        
        elif choice == '2':  # Edit metadata before attaching
            edited_metadata = self.edit_metadata_interactively(metadata)
            if edited_metadata:
                # Re-run Zotero search with edited metadata
                print("\n🔍 Searching Zotero with edited metadata...")
                new_matches = self.search_and_display_local_zotero(edited_metadata)
                if new_matches:
                    # Show attachment menu again
                    new_choice = self.display_zotero_match_menu()
                    self.handle_zotero_match_choice(new_choice, pdf_path, edited_metadata, new_matches, result)
                else:
                    # No matches with edited metadata - create new item
                    print("No matches found with edited metadata. Creating new item...")
                    success = self.use_metadata_as_is(pdf_path, edited_metadata)
                    if not success:
                        self.logger.info("Processing cancelled or failed")
            else:
                self.logger.info("Metadata editing cancelled")
        
        elif choice == '3':  # Search Zotero again with different info
            print("\n🔍 Additional Zotero search")
            print("Provide additional information to help find the item:")
            additional_info = input("Author name, title keywords, or year: ").strip()
            
            # Enhance metadata with additional info
            enhanced_metadata = metadata.copy()
            if additional_info:
                # Simple enhancement - could be more sophisticated
                if any(char.isdigit() for char in additional_info):
                    enhanced_metadata['year'] = additional_info
                elif len(additional_info.split()) > 2:
                    enhanced_metadata['title'] = additional_info
                else:
                    enhanced_metadata['authors'] = [additional_info]
            
            new_matches = self.search_and_display_local_zotero(enhanced_metadata)
            if new_matches:
                new_choice = self.display_zotero_match_menu()
                self.handle_zotero_match_choice(new_choice, pdf_path, enhanced_metadata, new_matches, result)
            else:
                print("Still no matches found. Creating new item...")
                success = self.use_metadata_as_is(pdf_path, enhanced_metadata)
                if not success:
                    self.logger.info("Processing cancelled or failed")
        
        elif choice == '4':  # Create new Zotero item (ignore match)
            print("Creating new Zotero item with extracted metadata...")
            success = self.use_metadata_as_is(pdf_path, metadata)
            if not success:
                self.logger.info("Processing cancelled or failed")
        
        elif choice == '5':  # Skip document
            self.move_to_skipped(pdf_path)
            self.logger.info("Document skipped by user")
    
    def handle_standard_choice(self, choice: str, pdf_path: Path, metadata: dict, result: dict):
        """Handle choices when no Zotero matches were found."""
        if choice == '1':  # Create new Zotero item
            success = self.use_metadata_as_is(pdf_path, metadata)
            if not success:
                self.logger.info("Processing cancelled or failed")
                        
        elif choice == '2':  # Edit metadata before creating
            edited_metadata = self.edit_metadata_interactively(metadata)
            if edited_metadata:
                success = self.use_metadata_as_is(pdf_path, edited_metadata)
                if not success:
                    self.logger.info("Processing cancelled or failed")
            else:
                self.logger.info("Metadata editing cancelled")
        
        elif choice == '3':  # Search Zotero with additional info
            print("\n🔍 Zotero search with additional information")
            print("Provide additional information to help find the item:")
            additional_info = input("Author name, title keywords, or year: ").strip()
            
            # Enhance metadata with additional info
            enhanced_metadata = metadata.copy()
            if additional_info:
                if any(char.isdigit() for char in additional_info):
                    enhanced_metadata['year'] = additional_info
                elif len(additional_info.split()) > 2:
                    enhanced_metadata['title'] = additional_info
                else:
                    enhanced_metadata['authors'] = [additional_info]
                            
            new_matches = self.search_and_display_local_zotero(enhanced_metadata)
            if new_matches:
                # Found matches - switch to attachment workflow
                new_choice = self.display_zotero_match_menu()
                self.handle_zotero_match_choice(new_choice, pdf_path, enhanced_metadata, new_matches, result)
            else:
                print("No matches found. Creating new item...")
                success = self.use_metadata_as_is(pdf_path, enhanced_metadata)
                if not success:
                    self.logger.info("Processing cancelled or failed")
        
        elif choice == '4':  # Skip document
            self.move_to_skipped(pdf_path)
            self.logger.info("Document skipped by user")
        
        elif choice == '5':  # Manual processing
            self.logger.info("Left for manual processing")
            
    def generate_filename(self, metadata: dict, original_filename: str = None) -> str:
        """Generate filename from metadata using configurable patterns.
        
        Args:
            metadata: Paper metadata
            original_filename: Original filename to extract extension from (optional)
            
        Returns:
            Generated filename
        """
        # Reuse logic from process_scanned_papers.py
        from scripts.process_scanned_papers import ScannedPaperProcessor
        processor = ScannedPaperProcessor(self.watch_dir)
        return processor._generate_filename(metadata, original_filename)
    
    def _prompt_filename_edit(self, target_filename: str, zotero_metadata: dict, extracted_metadata: dict = None) -> str:
        """Prompt user to edit filename with options for Zotero-based or OCR-based title.
        
        Args:
            target_filename: Current filename (Zotero-based)
            zotero_metadata: Dict with Zotero title, authors, year
            extracted_metadata: Dict with OCR/extracted title (optional)
            
        Returns:
            Final filename (edited or approved)
        """
        print("\n" + "="*70)
        print("📄 FILENAME")
        print("="*70)
        print(f"Generated filename: {target_filename}")
        print()
        print("  [Enter] = Use this filename")
        print("  [e] = Edit filename")
        print()
        
        choice = input("Your choice: ").strip().lower()
        
        if choice == '' or choice == 'y':
            # User approved, return as-is
            return target_filename
        
        if choice != 'e':
            # Invalid choice, default to approve
            return target_filename
        
        # User wants to edit - show options
        print()
        print(Colors.colorize("Choose filename source:", ColorScheme.ACTION))
        print(Colors.colorize("  [a] Default: Zotero-based filename (current)", ColorScheme.LIST))
        print(Colors.colorize("  [b] OCR-based: Use extracted title from PDF", ColorScheme.LIST))
        print()
        
        source_choice = input("Your choice [a/b]: ").strip().lower()
        
        if source_choice == 'b' and extracted_metadata:
            # Generate OCR-based filename
            ocr_title = extracted_metadata.get('title', '').strip()
            if ocr_title:
                # Build metadata with OCR title but Zotero authors/year
                ocr_metadata = {
                    'title': ocr_title,
                    'authors': zotero_metadata.get('authors', []),
                    'year': zotero_metadata.get('year', 'Unknown'),
                    'document_type': zotero_metadata.get('document_type', 'journalArticle')
                }
                filename_gen = FilenameGenerator()
                proposed_filename = filename_gen.generate(ocr_metadata, is_scan=True) + '.pdf'
                print()
                print(f"OCR-based filename: {proposed_filename}")
            else:
                print("⚠️  No extracted title available, using Zotero-based filename")
                proposed_filename = target_filename
        else:
            # Use Zotero-based (option a or fallback)
            proposed_filename = target_filename
            print()
            print(f"Zotero-based filename: {proposed_filename}")
        
        # Allow terminal editing
        print()
        print("Edit filename (or press Enter to use as-is):")
        edited = input(f"{proposed_filename} -> ").strip()
        
        if edited:
            # Validate and clean edited filename
            # Ensure .pdf extension
            if not edited.endswith('.pdf'):
                edited = edited + '.pdf'
            
            # Basic validation - remove invalid characters
            from pathvalidate import sanitize_filename
            # Remove extension for sanitization
            if edited.endswith('.pdf'):
                base = edited[:-4]
                ext = '.pdf'
            else:
                base = edited
                ext = ''
            
            # Sanitize base name
            sanitized_base = sanitize_filename(base, replacement_text='_', platform='universal')
            final_filename = sanitized_base + ext
            
            if final_filename != edited:
                print(f"⚠️  Filename sanitized: {final_filename}")
            
            return final_filename
        else:
            return proposed_filename

    def _to_windows_path(self, path: Path) -> str:
        """Convert WSL path to Windows path for linked files.
        
        Uses PowerShell utility for robust conversion, handles all path types.
        If path is already Windows format, returns as-is.
        """
        path_str = str(path)
        # Already Windows style
        if ":\\" in path_str or ":/" in path_str:
            return path_str
        # Use helper method for conversion
        try:
            return self._convert_wsl_to_windows_path(path_str)
        except Exception as e:
            # Fallback to simple conversion if helper fails
            if path_str.startswith('/mnt/') and len(path_str) > 6:
                drive_letter = path_str[5].upper()
                rest = path_str[7:]
                return f"{drive_letter}:\\" + rest.replace('/', '\\')
            # Try wslpath directly for /tmp/ and other non-/mnt/ paths
            if path_str.startswith('/tmp/') or (not path_str.startswith('/mnt/') and path_str.startswith('/')):
                try:
                    result = subprocess.run(['wslpath', '-w', path_str], 
                                           capture_output=True, text=True, timeout=2)
                    if result.returncode == 0 and result.stdout.strip():
                        return result.stdout.strip()
                except (FileNotFoundError, subprocess.TimeoutExpired, Exception):
                    pass
            return path_str

    def _sha256_file(self, file_path: Path, chunk_size: int = 1024 * 1024) -> str:
        """Compute SHA-256 hash of a file efficiently in chunks."""
        import hashlib
        h = hashlib.sha256()
        with open(file_path, 'rb') as f:
            while True:
                chunk = f.read(chunk_size)
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()

    def _are_files_identical(self, path_a: Path, path_b: Path) -> bool:
        """Quick identical check: size first, then SHA-256 if sizes match."""
        try:
            if not path_a.exists() or not path_b.exists():
                return False
            if path_a.stat().st_size != path_b.stat().st_size:
                return False
            # Sizes match; verify by hash
            return self._sha256_file(path_a) == self._sha256_file(path_b)
        except Exception:
            return False

    def _find_identical_in_publications(self, incoming_pdf: Path) -> Optional[Path]:
        """Search publications directory for an existing file identical to incoming_pdf.
        Compares by size first, then SHA-256 if sizes match. Returns the first identical path or None.
        """
        try:
            target_size = incoming_pdf.stat().st_size
        except Exception:
            return None
        try:
            for candidate in self.publications_dir.glob('*.pdf'):
                try:
                    if candidate.stat().st_size != target_size:
                        continue
                    if self._are_files_identical(candidate, incoming_pdf):
                        return candidate
                except Exception:
                    continue
        except Exception:
            return None
        return None
    
    def copy_to_publications(self, source: Path, new_filename: str) -> Path:
        """Copy PDF to final publications directory.
        
        Args:
            source: Source PDF path
            new_filename: New filename
            
        Returns:
            Final path or None if failed
        """
        final_path = self.publications_dir / new_filename
        
        # Handle duplicate filenames
        if final_path.exists():
            stem = final_path.stem
            suffix = final_path.suffix
            counter = 2
            while final_path.exists():
                final_path = self.publications_dir / f"{stem}{counter}{suffix}"
                counter += 1
        
        success, error_msg = self._copy_file_universal(source, final_path, replace_existing=False)
        if success:
            self.logger.debug(f"Copied to: {final_path}")
            # Increment copy counter and refresh cache after every 10 copies
            self.publications_copy_count += 1
            if self.publications_copy_count >= 10:
                self._refresh_publications_cache()
                self.publications_copy_count = 0
            return final_path
        else:
            self.logger.error(f"Copy failed: {error_msg}")
            return None
    
    def move_to_done(self, pdf_path: Path, log_entry: Optional[Dict] = None):
        """Move processed PDF to done/ directory.
        
        Args:
            pdf_path: PDF to move
            log_entry: Optional dict with logging info (will be logged if not already logged)
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        
        # Check if source file exists before attempting to move
        if not Path(src).exists():
            self.logger.warning(f"Cannot move to done/: file no longer exists: {src}")
            return
        
        done_dir = self.watch_dir / "done"
        done_dir.mkdir(exist_ok=True)
        
        dest = done_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.debug(f"Moved to done/")
        
        # Log if entry provided and not already logged
        if log_entry and hasattr(self, 'scanned_papers_logger'):
            original_filename = Path(src).name
            if not self.scanned_papers_logger.entry_exists(original_filename):
                self.scanned_papers_logger.log_processing(
                    original_filename=original_filename,
                    status=log_entry.get('status', 'success'),
                    final_filename=log_entry.get('final_filename'),
                    split=log_entry.get('split'),
                    borders=log_entry.get('borders'),
                    trim=log_entry.get('trim'),
                    zotero_item_code=log_entry.get('zotero_item_code')
                )
    
    def move_to_failed(self, pdf_path: Path):
        """Move failed PDF to failed/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        
        # Check if source file exists before attempting to move
        if not Path(src).exists():
            self.logger.warning(f"Cannot move to failed/: file no longer exists: {src}")
            return
        
        failed_dir = self.watch_dir / "failed"
        failed_dir.mkdir(exist_ok=True)
        
        dest = failed_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to failed/")
        
        # Log to CSV
        if hasattr(self, 'scanned_papers_logger'):
            original_filename = Path(src).name
            if not self.scanned_papers_logger.entry_exists(original_filename):
                self.scanned_papers_logger.log_processing(
                    original_filename=original_filename,
                    status='failed'
                )
    
    def move_to_skipped(self, pdf_path: Path):
        """Move non-academic PDF to skipped/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        
        # Check if source file exists before attempting to move
        if not Path(src).exists():
            self.logger.warning(f"Cannot move to skipped/: file no longer exists: {src}")
            return
        
        skipped_dir = self.watch_dir / "skipped"
        skipped_dir.mkdir(exist_ok=True)
        
        dest = skipped_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to skipped/")
        
        # Log to CSV
        if hasattr(self, 'scanned_papers_logger'):
            original_filename = Path(src).name
            if not self.scanned_papers_logger.entry_exists(original_filename):
                self.scanned_papers_logger.log_processing(
                    original_filename=original_filename,
                    status='skipped'
                )
    
    # ------------------------
    # Two-up split pre-processing
    # ------------------------
    def _preprocess_split_if_needed(self, pdf_path: Path) -> Optional[Path]:
        """Detect and split two-up pages when appropriate.
        
        Rules:
        - If filename ends with _double.pdf: split unconditionally and return new path
        - Else if page is wide (AR > 1.3): run gutter/spine detector on page 1
          - If likely two-up: prompt user to split; if yes, split and return new path
        - Otherwise: return None
        """
        name = pdf_path.name.lower()
        try:
            import pdfplumber
        except Exception:
            # If pdfplumber not available, only honor _double.pdf
            if name.endswith('_double.pdf'):
                return self._split_with_mutool(pdf_path)
            return None
        
        # Obtain first page size to evaluate aspect ratio
        try:
            with pdfplumber.open(str(pdf_path)) as pdf:
                if len(pdf.pages) == 0:
                    return None
                first = pdf.pages[0]
                width, height = first.width, first.height
        except Exception:
            width = height = 0
        
        # Unconditional split by filename suffix
        if name.endswith('_double.pdf'):
            self.logger.info("Auto-splitting due to filename suffix _double.pdf")
            return self._split_with_mutool(pdf_path, width=width, height=height)
        
        # Aspect ratio pre-filter
        if width and height and width / max(1.0, height) > 1.3:
            # Run lightweight two-up detection
            try:
                is_two_up, score, mode = self._detect_two_up_page(pdf_path)
            except Exception as e:
                self.logger.debug(f"Two-up detection failed: {e}")
                is_two_up, score, mode = (False, 0.0, 'none')
            
            if is_two_up:
                print("\nTwo-up candidate detected:")
                print(f"  Aspect ratio: {width/height:.2f}")
                print(f"  Center structure: {mode} score={score:.2f}")
                choice = input("Split this file into single pages? [y/n]: ").strip().lower()
                if choice == 'y':
                    return self._split_with_mutool(pdf_path, width=width, height=height)
        
        return None
    
    def _preprocess_pdf_with_options(
        self, 
        pdf_path: Path,
        border_removal: bool = True,
        split_method: str = 'auto',  # 'auto', '50-50', 'none'
        trim_leading: bool = True
    ) -> tuple[Optional[Path], dict]:
        """Preprocess PDF with specified options.
        
        Processes the original PDF with the specified options and returns
        the processed PDF path and preprocessing state.
        
        Args:
            pdf_path: Path to original PDF file
            border_removal: Whether to remove borders
            split_method: Split method - 'auto' (gutter detection), '50-50' (geometric), 'none' (no split)
            trim_leading: Whether to trim leading pages
        
        Returns:
            Tuple of (processed_pdf_path, preprocessing_state)
            preprocessing_state is a dict with keys: border_removal, split_method, trim_leading
        """
        current_pdf = pdf_path
        # Store original filename for _double.pdf detection (before any renaming)
        original_filename_lower = pdf_path.name.lower()
        
        preprocessing_state = {
            'border_removal': False,
            'split_method': 'none',
            'split_attempted': False,
            'trim_leading': False
        }
        
        # Step 1: Remove borders if requested
        if border_removal:
            # #region agent log
            try:
                import pdfplumber
                with pdfplumber.open(str(current_pdf)) as pdf:
                    if len(pdf.pages) > 0:
                        orig_width = pdf.pages[0].width
                        orig_height = pdf.pages[0].height
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({
                                'sessionId': 'debug-session',
                                'runId': 'run1',
                                'hypothesisId': 'B1',
                                'location': 'paper_processor_daemon.py:_preprocess_pdf_with_options',
                                'message': 'Before border removal - page dimensions',
                                'data': {
                                    'pdf_path': str(current_pdf),
                                    'page_width': float(orig_width),
                                    'page_height': float(orig_height),
                                    'aspect_ratio': float(orig_width / orig_height) if orig_height > 0 else 0.0
                                },
                                'timestamp': int(time.time() * 1000)
                            }) + '\n')
            except Exception:
                pass
            # #endregion
            border_removed_pdf, border_detection_stats = self._check_and_remove_dark_borders(current_pdf)
            if border_removed_pdf:
                current_pdf = border_removed_pdf
                preprocessing_state['border_removal'] = True
                self.logger.debug(f"Borders removed: {border_removed_pdf.name}")
            
            # Store border detection stats even if removal was rejected
            if border_detection_stats:
                preprocessing_state['border_detection_stats'] = border_detection_stats
                self.logger.debug(f"Border detection stats stored: {border_detection_stats}")
                # #region agent log
                try:
                    import pdfplumber
                    with pdfplumber.open(str(current_pdf)) as pdf:
                        if len(pdf.pages) > 0:
                            new_width = pdf.pages[0].width
                            new_height = pdf.pages[0].height
                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                            with open(log_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps({
                                    'sessionId': 'debug-session',
                                    'runId': 'run1',
                                    'hypothesisId': 'B1',
                                    'location': 'paper_processor_daemon.py:_preprocess_pdf_with_options',
                                    'message': 'After border removal - page dimensions',
                                    'data': {
                                        'pdf_path': str(current_pdf),
                                        'page_width': float(new_width),
                                        'page_height': float(new_height),
                                        'aspect_ratio': float(new_width / new_height) if new_height > 0 else 0.0,
                                        'width_change': float(new_width - orig_width) if 'orig_width' in locals() else None,
                                        'height_change': float(new_height - orig_height) if 'orig_height' in locals() else None
                                    },
                                    'timestamp': int(time.time() * 1000)
                                }) + '\n')
                except Exception:
                    pass
                # #endregion
        
        # Step 2: Check if splitting is needed and perform split
        if split_method != 'none':
            # Check if PDF is landscape/two-up
            # Use original filename for _double.pdf detection (before border removal renamed it)
            name_lower = original_filename_lower
            # Also check if '_double' appears anywhere in original filename, not just endswith
            needs_split = False
            landscape_width = None
            landscape_height = None
            
            if name_lower.endswith('_double.pdf') or '_double' in name_lower:
                # Always split on _double.pdf or files with _double in name
                needs_split = True
                self.logger.info(f"_double detected in original filename '{pdf_path.name}' - will split")
            else:
                # Check if page is landscape/two-up
                try:
                    import pdfplumber
                    with pdfplumber.open(str(current_pdf)) as pdf:
                        if len(pdf.pages) > 0:
                            first = pdf.pages[0]
                            width, height = first.width, first.height
                            if width and height:
                                aspect_ratio = width / max(1.0, height)
                                if aspect_ratio > 1.3:
                                    # Landscape detected - check if it's two-up
                                    is_two_up, score, mode = self._detect_two_up_page(current_pdf)
                                    if is_two_up or name_lower.endswith('_double.pdf'):
                                        needs_split = True
                                        landscape_width = width
                                        landscape_height = height
                                        self.logger.info(f"Landscape two-up detected: {width:.1f}x{height:.1f} (ratio: {aspect_ratio:.2f})")
                except Exception as e:
                    self.logger.debug(f"Landscape detection skipped: {e}")
            
            if needs_split:
                # Track that split is being attempted - update state BEFORE calling _split_with_mutool
                preprocessing_state['split_method'] = split_method
                preprocessing_state['split_attempted'] = True
                
                # #region agent log
                try:
                    import pdfplumber
                    with pdfplumber.open(str(current_pdf)) as pdf:
                        if len(pdf.pages) > 0:
                            split_input_width = pdf.pages[0].width
                            split_input_height = pdf.pages[0].height
                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                            with open(log_path, 'a', encoding='utf-8') as f:
                                f.write(json.dumps({
                                    'sessionId': 'debug-session',
                                    'runId': 'run1',
                                    'hypothesisId': 'G',
                                    'location': 'paper_processor_daemon.py:_preprocess_pdf_with_options',
                                    'message': 'Before split - page dimensions',
                                    'data': {
                                        'pdf_path': str(current_pdf),
                                        'page_width': float(split_input_width),
                                        'page_height': float(split_input_height),
                                        'landscape_width_param': float(landscape_width) if landscape_width else None,
                                        'landscape_height_param': float(landscape_height) if landscape_height else None,
                                        'split_method': split_method
                                    },
                                    'timestamp': int(time.time() * 1000)
                                }) + '\n')
                except Exception:
                    pass
                # #endregion
                
                # Perform split - pass border detection stats if available
                border_detection_stats = preprocessing_state.get('border_detection_stats')
                split_path = self._split_with_mutool(
                    current_pdf, 
                    width=landscape_width, 
                    height=landscape_height,
                    split_method=split_method,
                    border_detection_stats=border_detection_stats
                )
                if split_path:
                    current_pdf = split_path
                    # split_method already set above, just log success
                    self.logger.info(f"Split completed: {split_path.name}")
                else:
                    # Split was attempted but failed or was cancelled
                    # Keep split_method in state to show what was attempted
                    self.logger.info(f"Split attempted with method '{split_method}' but did not complete (user cancelled or failed)")
        
        # Step 3: Trim leading pages if requested
        if trim_leading:
            trimmed_pdf, trimmed = self._prompt_trim_leading_pages_for_attachment(current_pdf)
            if trimmed:
                current_pdf = trimmed_pdf
                preprocessing_state['trim_leading'] = True
                self.logger.debug(f"Leading pages trimmed: {trimmed_pdf.name}")
        
        return current_pdf, preprocessing_state
    
    def _preview_and_modify_preprocessing(
        self,
        original_pdf: Path,
        processed_pdf: Path,
        preprocessing_state: dict
    ) -> tuple[Optional[Path], dict]:
        """Show PDF preview and allow user to modify preprocessing options.
        
        Opens the processed PDF in viewer and shows a menu allowing user to:
        - Accept and proceed
        - Drop border removal
        - Drop split
        - Use 50/50 split instead
        - Drop trimming
        - Go back to metadata
        - Quit to manual review
        
        Args:
            original_pdf: Path to original PDF (before preprocessing)
            processed_pdf: Path to processed PDF (after preprocessing)
            preprocessing_state: Dict with keys: border_removal, split_method, trim_leading
        
        Returns:
            Tuple of (final_pdf_path, final_preprocessing_state) or (None, {}) if user quits
        """
        while True:
            # Open PDF in viewer
            print("\n" + "="*70)
            print("PDF PREVIEW")
            print("="*70)
            print(f"Opening processed PDF in viewer...")
            self._open_pdf_in_viewer(processed_pdf)
            
            # Display current preprocessing state
            print("\nCurrent preprocessing:")
            border_status = "✓ Applied" if preprocessing_state.get('border_removal', False) else "✗ Not applied"
            split_method = preprocessing_state.get('split_method', 'none')
            split_attempted = preprocessing_state.get('split_attempted', False)
            
            # Determine split status based on method and whether it was attempted/succeeded
            # If split_method is 'none' but split_attempted is True, user cancelled
            if split_method == 'manual' and split_attempted:
                manual_ratio = preprocessing_state.get('manual_split_ratio')
                if manual_ratio:
                    split_status = f"✓ Applied (manual {manual_ratio:.0f}/{100-manual_ratio:.0f})"
                else:
                    split_status = "✓ Applied (manual)"
            elif split_method == 'auto' and split_attempted:
                split_status = "✓ Applied (gutter detection)"
            elif split_method == '50-50' and split_attempted:
                split_status = "✓ Applied (50/50 geometric)"
            elif split_method != 'none' and split_attempted:
                # Split was attempted with a method but may have failed or been cancelled
                split_status = f"✗ Attempted ({split_method}) but failed/cancelled"
            elif split_attempted:
                # Split was attempted but method is 'none' (user cancelled)
                split_status = "✗ Attempted but cancelled"
            else:
                split_status = "✗ Not applied"
            
            trim_status = "✓ Applied" if preprocessing_state.get('trim_leading', False) else "✗ Not applied"
            
            print(f"  - Border removal: {border_status}")
            print(f"  - Split: {split_status}")
            print(f"  - Trimming: {trim_status}")
            print()
            
            # Show menu - build dynamically based on current state
            print(Colors.colorize("Options:", ColorScheme.ACTION))
            print(Colors.colorize("  [1] Accept and proceed to Zotero", ColorScheme.LIST))
            
            # Build dynamic options with sequential numbering
            option_num = 1
            option_map = {}  # Maps option number to action
            
            if preprocessing_state.get('border_removal', False):
                option_num += 1
                option_map[option_num] = 'drop_border'
                print(Colors.colorize(f"  [{option_num}] Drop border removal", ColorScheme.LIST))
            
            if preprocessing_state.get('split_method', 'none') != 'none':
                option_num += 1
                option_map[option_num] = 'drop_split'
                print(Colors.colorize(f"  [{option_num}] Drop split", ColorScheme.LIST))
            
            if preprocessing_state.get('split_method', 'none') == 'auto':
                option_num += 1
                option_map[option_num] = 'use_5050'
                print(Colors.colorize(f"  [{option_num}] Use 50/50 split instead", ColorScheme.LIST))
            
            # Show "Add trimming" if not applied, "Drop trimming" if applied
            if preprocessing_state.get('trim_leading', False):
                option_num += 1
                option_map[option_num] = 'drop_trim'
                print(Colors.colorize(f"  [{option_num}] Drop trimming", ColorScheme.LIST))
            else:
                option_num += 1
                option_map[option_num] = 'add_trim'
                print(Colors.colorize(f"  [{option_num}] Add trimming", ColorScheme.LIST))
            
            # Manual split option - always available
            option_num += 1
            manual_split_option_num = option_num
            manual_split_ratio = preprocessing_state.get('manual_split_ratio')
            if manual_split_ratio:
                option_map[option_num] = 'manual_split'
                print(Colors.colorize(f"  [{option_num}] Split by manual definition ({manual_split_ratio:.0f}/{100-manual_split_ratio:.0f})", ColorScheme.LIST))
            else:
                option_map[option_num] = 'manual_split'
                print(Colors.colorize(f"  [{option_num}] Split by manual definition (e.g., 55/45)", ColorScheme.LIST))
            
            print(Colors.colorize("  [z] Go back to metadata", ColorScheme.LIST))
            print(Colors.colorize("  [q] Quit - move to manual review", ColorScheme.LIST))
            print()
            
            try:
                choice = input("Enter your choice: ").strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None, {}
            
            if choice == '1' or choice == '':
                # Accept and proceed
                return processed_pdf, preprocessing_state
            
            # Handle numeric choices using option_map
            try:
                choice_num = int(choice)
                if choice_num in option_map:
                    action = option_map[choice_num]
                    
                    if action == 'drop_border':
                        # Drop border removal
                        new_state = preprocessing_state.copy()
                        new_state['border_removal'] = False
                        print("\n🔄 Restarting preprocessing without border removal...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=False,
                            split_method=new_state.get('split_method', 'auto'),
                            trim_leading=new_state.get('trim_leading', True)
                        )
                        preprocessing_state = new_state
                        # Continue loop to show preview again
                    
                    elif action == 'drop_split':
                        # Drop split
                        new_state = preprocessing_state.copy()
                        new_state['split_method'] = 'none'
                        print("\n🔄 Restarting preprocessing without split...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=new_state.get('border_removal', True),
                            split_method='none',
                            trim_leading=new_state.get('trim_leading', True)
                        )
                        preprocessing_state = new_state
                        # Continue loop to show preview again
                    
                    elif action == 'use_5050':
                        # Use 50/50 split instead
                        new_state = preprocessing_state.copy()
                        new_state['split_method'] = '50-50'
                        print("\n🔄 Restarting preprocessing with 50/50 split...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=new_state.get('border_removal', True),
                            split_method='50-50',
                            trim_leading=new_state.get('trim_leading', True)
                        )
                        preprocessing_state = new_state
                        # Continue loop to show preview again
                    
                    elif action == 'drop_trim':
                        # Drop trimming
                        new_state = preprocessing_state.copy()
                        new_state['trim_leading'] = False
                        print("\n🔄 Restarting preprocessing without trimming...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=new_state.get('border_removal', True),
                            split_method=new_state.get('split_method', 'auto'),
                            trim_leading=False
                        )
                        preprocessing_state = new_state
                        # Continue loop to show preview again
                    
                    elif action == 'add_trim':
                        # Add trimming
                        new_state = preprocessing_state.copy()
                        new_state['trim_leading'] = True
                        print("\n🔄 Restarting preprocessing with trimming...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=new_state.get('border_removal', True),
                            split_method=new_state.get('split_method', 'auto'),
                            trim_leading=True
                        )
                        preprocessing_state = new_state
                        # Continue loop to show preview again
                    
                    elif action == 'manual_split':
                        # Manual split definition
                        # CRITICAL: Always use original_pdf for manual split, not processed_pdf
                        # processed_pdf may already be split, which would give wrong dimensions
                        border_detection_stats = preprocessing_state.get('border_detection_stats')
                        
                        print("\n📐 Manual Split Definition")
                        print("=" * 60)
                        print("Enter the split ratio as a single number (e.g., 55 for 55/45 split).")
                        print("The number represents the percentage for the left page.")
                        print("Valid range: 30-70 (to ensure reasonable split)")
                        
                        while True:
                            try:
                                ratio_input = input("\nEnter split ratio (30-70, or 'c' to cancel): ").strip().lower()
                                
                                if ratio_input == 'c':
                                    print("Cancelled manual split")
                                    break  # Continue loop to show preview again
                                
                                ratio = float(ratio_input)
                                
                                if ratio < 30 or ratio > 70:
                                    print(f"⚠️  Ratio must be between 30 and 70. You entered {ratio:.1f}")
                                    continue
                                
                                # Get page width from ORIGINAL PDF (not processed_pdf which may be already split)
                                try:
                                    import fitz  # PyMuPDF
                                    doc = fitz.open(str(original_pdf))
                                    if len(doc) == 0:
                                        print("❌ Error: PDF has no pages")
                                        doc.close()
                                        break
                                    
                                    page_width = doc[0].rect.width
                                    doc.close()
                                except ImportError:
                                    print("❌ Error: PyMuPDF not available")
                                    break
                                except Exception as e:
                                    print(f"❌ Error reading PDF: {e}")
                                    break
                                
                                # Calculate split point
                                # #region agent log
                                try:
                                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                    with open(log_path, 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({
                                            'sessionId': 'debug-session',
                                            'runId': 'run1',
                                            'hypothesisId': 'A',
                                            'location': 'paper_processor_daemon.py:manual_split',
                                            'message': 'Before calculating split point',
                                            'data': {
                                                'ratio': float(ratio),
                                                'page_width': float(page_width),
                                                'has_border_stats': bool(border_detection_stats),
                                                'original_pdf': str(original_pdf),
                                                'original_pdf_exists': original_pdf.exists() if original_pdf else False,
                                                'processed_pdf': str(processed_pdf),
                                                'processed_pdf_is_split': '_split' in str(processed_pdf)
                                            },
                                            'timestamp': int(time.time() * 1000)
                                        }) + '\n')
                                except: pass
                                # #endregion
                                if border_detection_stats:
                                    avg_left = border_detection_stats.get('avg_left_border_px', 0)
                                    avg_right = border_detection_stats.get('avg_right_border_px', 0)
                                    page_width_px = border_detection_stats.get('page_width_px', 0)
                                    
                                    if page_width_px > 0:
                                        # Convert borders to PDF points
                                        left_border_pts = (avg_left / page_width_px) * page_width
                                        right_border_pts = (avg_right / page_width_px) * page_width
                                        
                                        # Calculate content center and manual offset
                                        content_center = page_width / 2 + (left_border_pts - right_border_pts) / 2
                                        manual_offset = (ratio - 50) / 100 * page_width
                                        split_x = content_center + manual_offset
                                        print(f"📊 Split point: {split_x:.1f} (content center: {content_center:.1f}, manual offset: {manual_offset:.1f})")
                                        # #region agent log
                                        try:
                                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                            with open(log_path, 'a', encoding='utf-8') as f:
                                                f.write(json.dumps({
                                                    'sessionId': 'debug-session',
                                                    'runId': 'run1',
                                                    'hypothesisId': 'B',
                                                    'location': 'paper_processor_daemon.py:manual_split',
                                                    'message': 'Calculated split_x with border stats',
                                                    'data': {
                                                        'split_x': float(split_x),
                                                        'page_width': float(page_width),
                                                        'gutter_ratio': float(split_x / page_width) if page_width > 0 else 0.0,
                                                        'content_center': float(content_center),
                                                        'manual_offset': float(manual_offset),
                                                        'left_border_pts': float(left_border_pts),
                                                        'right_border_pts': float(right_border_pts),
                                                        'avg_left_px': float(avg_left),
                                                        'avg_right_px': float(avg_right),
                                                        'page_width_px': float(page_width_px)
                                                    },
                                                    'timestamp': int(time.time() * 1000)
                                                }) + '\n')
                                        except: pass
                                        # #endregion
                                    else:
                                        # Fallback to simple calculation
                                        split_x = page_width * (ratio / 100)
                                        print(f"📊 Split point: {split_x:.1f} (page width: {page_width:.1f}, ratio: {ratio}%)")
                                        # #region agent log
                                        try:
                                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                            with open(log_path, 'a', encoding='utf-8') as f:
                                                f.write(json.dumps({
                                                    'sessionId': 'debug-session',
                                                    'runId': 'run1',
                                                    'hypothesisId': 'C',
                                                    'location': 'paper_processor_daemon.py:manual_split',
                                                    'message': 'Calculated split_x without border stats (page_width_px=0)',
                                                    'data': {
                                                        'split_x': float(split_x),
                                                        'page_width': float(page_width),
                                                        'gutter_ratio': float(split_x / page_width) if page_width > 0 else 0.0,
                                                        'ratio': float(ratio)
                                                    },
                                                    'timestamp': int(time.time() * 1000)
                                                }) + '\n')
                                        except: pass
                                        # #endregion
                                else:
                                    # No borders detected, use simple calculation
                                    split_x = page_width * (ratio / 100)
                                    print(f"📊 Split point: {split_x:.1f} (page width: {page_width:.1f}, ratio: {ratio}%)")
                                    # #region agent log
                                    try:
                                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                        with open(log_path, 'a', encoding='utf-8') as f:
                                            f.write(json.dumps({
                                                'sessionId': 'debug-session',
                                                'runId': 'run1',
                                                'hypothesisId': 'D',
                                                'location': 'paper_processor_daemon.py:manual_split',
                                                'message': 'Calculated split_x without border stats (no stats)',
                                                'data': {
                                                    'split_x': float(split_x),
                                                    'page_width': float(page_width),
                                                    'gutter_ratio': float(split_x / page_width) if page_width > 0 else 0.0,
                                                    'ratio': float(ratio)
                                                },
                                                'timestamp': int(time.time() * 1000)
                                            }) + '\n')
                                    except: pass
                                    # #endregion
                                
                                # Perform split on ORIGINAL PDF (not processed_pdf which may be already split)
                                print("\n🔄 Performing manual split...")
                                # #region agent log
                                try:
                                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                    with open(log_path, 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({
                                            'sessionId': 'debug-session',
                                            'runId': 'run1',
                                            'hypothesisId': 'E',
                                            'location': 'paper_processor_daemon.py:manual_split',
                                            'message': 'Before calling _split_with_custom_gutter',
                                            'data': {
                                                'original_pdf': str(original_pdf),
                                                'processed_pdf': str(processed_pdf),
                                                'using_original_for_split': True,
                                                'split_x': float(split_x),
                                                'page_width': float(page_width),
                                                'gutter_ratio': float(split_x / page_width) if page_width > 0 else 0.0
                                            },
                                            'timestamp': int(time.time() * 1000)
                                        }) + '\n')
                                except: pass
                                # #endregion
                                split_path, error_msg = self._split_with_custom_gutter(original_pdf, split_x)
                                # #region agent log
                                try:
                                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                                    with open(log_path, 'a', encoding='utf-8') as f:
                                        f.write(json.dumps({
                                            'sessionId': 'debug-session',
                                            'runId': 'run1',
                                            'hypothesisId': 'F',
                                            'location': 'paper_processor_daemon.py:manual_split',
                                            'message': 'After calling _split_with_custom_gutter',
                                            'data': {
                                                'split_path': str(split_path) if split_path else None,
                                                'split_path_exists': split_path.exists() if split_path else False,
                                                'split_succeeded': bool(split_path),
                                                'error_msg': error_msg
                                            },
                                            'timestamp': int(time.time() * 1000)
                                        }) + '\n')
                                except: pass
                                # #endregion
                                
                                if split_path:
                                    # Update preprocessing state
                                    preprocessing_state['split_method'] = 'manual'
                                    preprocessing_state['split_attempted'] = True
                                    preprocessing_state['manual_split_ratio'] = ratio
                                    preprocessing_state['border_detection_stats'] = border_detection_stats  # Preserve border stats
                                    
                                    processed_pdf = split_path
                                    print(f"✅ Manual split completed: {ratio:.0f}/{100-ratio:.0f}")
                                else:
                                    if error_msg:
                                        print(f"❌ Manual split failed: {error_msg}")
                                    else:
                                        print("❌ Manual split failed")
                                
                                break  # Exit ratio input loop
                            except ValueError:
                                print("⚠️  Please enter a valid number between 30 and 70")
                            except (KeyboardInterrupt, EOFError):
                                print("\n❌ Cancelled")
                                break  # Continue loop to show preview again
                        
                        # Continue loop to show preview again
                    
                    else:
                        print("⚠️  Invalid choice. Please try again.")
                else:
                    print("⚠️  Invalid choice. Please try again.")
            except ValueError:
                # Not a number, check for letter choices
                if choice == 'z':
                    # Go back to metadata (caller should handle this)
                    return None, {'back': True}
                
                elif choice == 'q':
                    # Quit to manual review
                    return None, {'quit': True}
                
                else:
                    print("⚠️  Invalid choice. Please try again.")
    
    def _detect_two_up_page(self, pdf_path: Path) -> tuple[bool, float, str]:
        """Heuristic detection of two-up layout on page 1.
        Returns (is_two_up, score, mode) where mode is 'gutter' or 'spine'.
        Uses pdfplumber to sample text density across vertical columns.
        """
        import pdfplumber
        import math
        with pdfplumber.open(str(pdf_path)) as pdf:
            page = pdf.pages[0]
            W, H = page.width, page.height
            # sample N columns across width, count characters per column
            N = 48
            column_counts = [0] * N
            for char in page.chars or []:
                x = char.get('x0', 0)
                idx = min(N - 1, max(0, int((x / max(1.0, W)) * N)))
                column_counts[idx] += 1
            # if no chars detected, fall back to not splitting
            total = sum(column_counts)
            if total < 20:
                return (False, 0.0, 'none')
            
            # smooth with small window
            smoothed = []
            win = 3
            for i in range(N):
                s = 0
                c = 0
                for j in range(i - win, i + win + 1):
                    if 0 <= j < N:
                        s += column_counts[j]
                        c += 1
                smoothed.append(s / max(1, c))
            
            # left/right averages and center band stats
            L = smoothed[: int(N * 0.3)]
            R = smoothed[int(N * 0.7) :]
            C = smoothed[int(N * 0.45) : int(N * 0.55)]
            Lavg = sum(L) / max(1, len(L))
            Ravg = sum(R) / max(1, len(R))
            Cavg = sum(C) / max(1, len(C))
            
            # balance check
            lr_ratio = (Lavg + 1e-6) / (Ravg + 1e-6)
            if lr_ratio < 0.5 or lr_ratio > 2.0:
                return (False, 0.0, 'none')
            
            # gutter (valley) criterion
            gutter = Cavg < 0.4 * min(Lavg, Ravg)
            # spine (peak) criterion: we approximate by peak-to-side ratio using raw center max
            Cmax = max(C) if C else 0.0
            spine = Cmax > 1.6 * max(Lavg, Ravg)
            
            if gutter:
                score = (min(Lavg, Ravg) - Cavg) / (min(Lavg, Ravg) + 1e-6)
                return (True, max(0.0, score), 'gutter')
            if spine:
                score = (Cmax - max(Lavg, Ravg)) / (max(Lavg, Ravg) + 1e-6)
                return (True, max(0.0, score), 'spine')
            return (False, 0.0, 'none')
    
    def _find_gutter_position(self, pdf_path: Path, sample_pages: int = 3) -> Optional[Dict]:
        """Find the actual gutter position between two pages using content-aware detection.
        
        Uses binary search edge detection to find gap between text columns.
        Returns per-page gutter positions to handle variation.
        
        Args:
            pdf_path: Path to PDF file (should already have borders removed)
            sample_pages: Number of pages to analyze for consistency
            
        Returns:
            Dict with per-page gutter positions, or None if detection fails
        """
        try:
            import fitz  # PyMuPDF
            import numpy as np
        except ImportError:
            self.logger.debug("PyMuPDF/numpy not available for gutter detection")
            return None
        
        try:
            # Use ContentDetector to find per-page gutter positions
            results = self.content_detector.detect_two_column_regions_binary_search(
                pdf_path, 
                density_threshold=None,  # Will auto-detect
                pages=None  # Process all pages
            )
            
            if not results:
                self.logger.debug("ContentDetector found no two-column regions")
                return None
            
            # Get page width from first page
            doc = fitz.open(str(pdf_path))
            if len(doc) == 0:
                doc.close()
                return None
            page_width = doc[0].rect.width
            
            # Extract per-page gutter positions and handle edge case: last page with only left column
            gutter_x_per_page = []
            left_column_boxes = []
            right_column_boxes = []
            
            for page_num, (left_box, right_box, gutter_x_pts) in enumerate(results):
                # Check if this page has only a left column (no right column detected)
                # This can happen on the last page of a document
                # right_box is (left, top, right, bottom)
                if page_num < len(doc):
                    page = doc[page_num]
                    page_width_pts = page.rect.width
                    
                    # Render page to get pixel dimensions for comparison
                    zoom = 2.0
                    mat = fitz.Matrix(zoom, zoom)
                    pix = page.get_pixmap(matrix=mat, alpha=False)
                    img_width_px = pix.width
                    
                    # Check if right column is missing by checking:
                    # 1. Right column's left edge is near page edge (>= 95% of width)
                    # 2. OR gap between columns is too small (< 5% of page width)
                    # Normal two-column pages have right column starting around 50-60% of page width
                    right_col_left_px = right_box[0] if len(right_box) > 0 else img_width_px
                    left_col_right_px = left_box[2] if len(left_box) > 2 else 0
                    gap_px = right_col_left_px - left_col_right_px
                    gap_pct = (gap_px / img_width_px * 100) if img_width_px > 0 else 0
                    right_col_left_pct = (right_col_left_px / img_width_px * 100) if img_width_px > 0 else 100
                    
                    # If right column starts at >= 95% of page width OR gap is < 5%, assume no right column
                    if img_width_px > 0 and (right_col_left_pct >= 95.0 or gap_pct < 5.0):
                            # Use previous page's gutter, or median, or 50% split
                            if gutter_x_per_page:
                                # Use previous page's gutter position
                                fallback_gutter = gutter_x_per_page[-1]
                                self.logger.info(
                                    f"Page {page_num + 1} has only left column - using previous page's gutter: {fallback_gutter:.1f}pts"
                                )
                                gutter_x_pts = fallback_gutter
                            elif len(results) > 1:
                                # Use median from other pages
                                other_gutters = [g for i, (_, _, g) in enumerate(results) if i != page_num]
                                if other_gutters:
                                    fallback_gutter = float(np.median(other_gutters))
                                    self.logger.info(
                                        f"Page {page_num + 1} has only left column - using median gutter: {fallback_gutter:.1f}pts"
                                    )
                                    gutter_x_pts = fallback_gutter
                            else:
                                # Fall back to 50% split
                                fallback_gutter = page_width_pts / 2
                                self.logger.info(
                                    f"Page {page_num + 1} has only left column - using 50% split: {fallback_gutter:.1f}pts"
                                )
                                gutter_x_pts = fallback_gutter
                
                gutter_x_per_page.append(gutter_x_pts)
                left_column_boxes.append(left_box)
                right_column_boxes.append(right_box)
            
            doc.close()
            
            if not gutter_x_per_page:
                return None
            
            # Calculate variation across pages
            if len(gutter_x_per_page) > 1:
                std_dev = np.std(gutter_x_per_page)
                mean_gutter = np.mean(gutter_x_per_page)
                cv = std_dev / (mean_gutter + 1e-6)  # Coefficient of variation
            else:
                cv = 0.0
            
            # If variation > 10%, warn but still use per-page values
            if cv > 0.10:
                self.logger.warning(f"Gutter position varies significantly across pages (CV: {cv:.1%}) - using per-page values")
            
            # Verify safety for each page, but always include all pages (even if safety check fails)
            # This ensures per-page gutters are available for all pages, preventing misalignment
            doc = fitz.open(str(pdf_path))
            safe_gutters = []
            safe_left_boxes = []
            safe_right_boxes = []
            
            for page_num, (left_box, right_box, gutter_x_pts) in enumerate(results):
                if page_num >= len(doc):
                    continue
                
                page = doc[page_num]
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                
                # Convert to grayscale
                if len(img.shape) == 3:
                    import cv2
                    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img
                
                # Convert gutter from PDF points to pixels
                gutter_x_px = int((gutter_x_pts / page_width) * gray.shape[1])
                
                # Verify safety (but don't exclude pages that fail - just warn)
                density_threshold = self.content_detector.detect_text_density_threshold(pdf_path, is_two_up=True)
                is_safe, warning = self.content_detector.verify_gutter_position_safety(
                    gray, gutter_x_px, density_threshold, page_width
                )
                
                # Always include the gutter, even if safety check fails
                # The threshold is conservative - 16-19% might still be valid
                # Better to include it than exclude it and cause misalignment
                safe_gutters.append(gutter_x_pts)
                safe_left_boxes.append(left_box)
                safe_right_boxes.append(right_box)
                
                if not is_safe:
                    self.logger.warning(f"Gutter position on page {page_num + 1} failed safety check: {warning}")
                    self.logger.warning(f"  Using detected gutter anyway ({gutter_x_pts:.1f} pts) - threshold may be too strict")
                elif warning:  # Warning but still safe (borderline case)
                    self.logger.debug(f"Gutter position on page {page_num + 1}: {warning}")
            
            doc.close()
            
            if not safe_gutters:
                self.logger.warning("No gutter positions found")
                return None
            
            # Return per-page results - ensure all pages have a gutter value
            return {
                'gutter_x_per_page': [float(x) for x in safe_gutters],
                'left_column_boxes': safe_left_boxes,
                'right_column_boxes': safe_right_boxes,
                'method': 'binary_search_columns_per_page',
                'variation': float(cv),
                'confidence': [1.0] * len(safe_gutters),  # TODO: Calculate actual confidence
                'gutter_x': float(np.median(safe_gutters)),  # Backward compatibility: median
                'gutter_positions': [float(x) for x in safe_gutters],  # Backward compatibility
                'page_width': float(page_width)
            }
            
        except Exception as e:
            self.logger.debug(f"Gutter detection failed: {e}")
            return None
    
    def _validate_gutter_detection(self, gutter_x: float, page_width: float,
                                    gutter_positions: List[float] = None,
                                    borders_per_page: List[dict] = None) -> Tuple[bool, List[str]]:
        """Validate gutter detection results and return (is_valid, warnings).
        
        Args:
            gutter_x: Detected gutter position in PDF points
            page_width: Page width in PDF points
            gutter_positions: List of gutter positions per page (for consistency check)
            borders_per_page: List of border info per page (for variation check)
            
        Returns:
            Tuple of (is_valid, warnings_list)
        """
        warnings = []
        is_valid = True
        
        if gutter_x is None or page_width <= 0:
            return False, ["Invalid gutter detection (gutter_x is None or page_width <= 0)"]
        
        # Check gutter position is reasonable (30-70% of page width)
        gutter_ratio = gutter_x / page_width
        if gutter_ratio < 0.3 or gutter_ratio > 0.7:
            warnings.append(f"⚠️  Gutter position ({gutter_ratio:.1%}) is outside normal range (30-70%)")
            is_valid = False
        
        # Check for thin pages
        left_width = gutter_x
        right_width = page_width - gutter_x
        min_page_ratio = min(left_width, right_width) / page_width
        if min_page_ratio < 0.1:
            warnings.append(f"⚠️  Split would create very thin page ({min_page_ratio:.1%} of page width)")
            is_valid = False
        
        # Check gutter position consistency across pages
        if gutter_positions and len(gutter_positions) > 1:
            import statistics
            if len(gutter_positions) >= 2:
                std_dev = statistics.stdev(gutter_positions)
                mean_gutter = statistics.mean(gutter_positions)
                cv = std_dev / mean_gutter if mean_gutter > 0 else 0
                if cv > 0.2:  # Coefficient of variation > 20%
                    warnings.append(f"⚠️  Gutter position varies significantly across pages (CV: {cv:.1%})")
                    is_valid = False
        
        # Check border variation
        if borders_per_page and len(borders_per_page) > 1:
            import statistics
            # Check if left/right borders vary significantly
            left_borders = [b.get('left', 0) for b in borders_per_page]
            right_borders = [b.get('right', 0) for b in borders_per_page]
            if left_borders and right_borders:
                left_cv = statistics.stdev(left_borders) / (statistics.mean(left_borders) + 1e-6)
                right_cv = statistics.stdev(right_borders) / (statistics.mean(right_borders) + 1e-6)
                if left_cv > 0.3 or right_cv > 0.3:
                    warnings.append("⚠️  Borders vary significantly across pages - detection may be inaccurate")
                    is_valid = False
        
        return is_valid, warnings
    
    def _split_with_custom_gutter(self, pdf_path: Path, gutter_x: float, gutter_x_per_page: Optional[List[float]] = None) -> Tuple[Optional[Path], Optional[str]]:
        """Split a two-up PDF at a custom X coordinate using PyMuPDF.
        
        Args:
            pdf_path: Path to input PDF
            gutter_x: X coordinate in PDF points where to split (used if gutter_x_per_page is None)
            gutter_x_per_page: Optional list of per-page gutter positions (one per page)
            
        Returns:
            Tuple of (Path to split PDF or None if failed, error message or None)
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            error_msg = "PyMuPDF not available for custom split"
            self.logger.warning(error_msg)
            return None, error_msg
        
        try:
            doc = fitz.open(str(pdf_path))
            original_page_count = len(doc)
            # #region agent log
            try:
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G',
                        'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                        'message': 'Starting split - original PDF',
                        'data': {
                            'pdf_path': str(pdf_path),
                            'original_page_count': original_page_count,
                            'gutter_x': float(gutter_x)
                        },
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            if len(doc) == 0:
                doc.close()
                return None, "PDF has no pages"
            
            # Create new document for split pages
            new_doc = fitz.open()
            
            pages_created = 0
            for page_num in range(len(doc)):
                try:
                    page = doc[page_num]
                except (IndexError, AttributeError) as e:
                    error_msg = f"Failed to access page {page_num}: {e}"
                    self.logger.error(error_msg)
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                if page is None:
                    error_msg = f"Page {page_num} is None"
                    self.logger.error(error_msg)
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                page_rect = page.rect
                page_width = page_rect.width
                page_height = page_rect.height
                
                # Use per-page gutter if available, otherwise use single gutter_x
                if gutter_x_per_page and page_num < len(gutter_x_per_page):
                    page_gutter_x = gutter_x_per_page[page_num]
                else:
                    page_gutter_x = gutter_x
                
                # Validate gutter position is reasonable (30-70% of page width)
                gutter_ratio = page_gutter_x / page_width
                
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'G',
                            'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                            'message': 'Validating gutter position',
                            'data': {
                                'page_num': page_num,
                                'gutter_x': float(page_gutter_x),
                                'page_width': float(page_width),
                                'gutter_ratio': float(gutter_ratio),
                                'ratio_valid': (0.3 <= gutter_ratio <= 0.7),
                                'min_page_width': float(min(gutter_x, page_width - gutter_x)),
                                'min_width_valid': (min(gutter_x, page_width - gutter_x) >= 0.3 * page_width)
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except: pass
                # #endregion
                
                if gutter_ratio < 0.3 or gutter_ratio > 0.7:
                    error_msg = f"Gutter position {gutter_ratio:.1%} outside reasonable range (30-70%). Calculated split at {page_gutter_x:.1f} points on page {page_num + 1} (page width: {page_width:.1f} points)."
                    self.logger.warning(error_msg)
                    # #region agent log
                    try:
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({
                                'sessionId': 'debug-session',
                                'runId': 'run1',
                                'hypothesisId': 'H',
                                'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                                'message': 'Gutter ratio validation failed',
                                'data': {
                                    'page_num': page_num,
                                    'gutter_ratio': float(gutter_ratio),
                                    'gutter_x': float(page_gutter_x),
                                    'page_width': float(page_width),
                                    'reason': 'gutter_ratio_outside_30_70_percent'
                                },
                                'timestamp': int(time.time() * 1000)
                            }) + '\n')
                    except: pass
                    # #endregion
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                min_page_width = min(page_gutter_x, page_width - page_gutter_x)
                if min_page_width < 0.3 * page_width:
                    error_msg = f"Split would create a page < 30% width on page {page_num + 1}. Left page: {page_gutter_x:.1f} points ({page_gutter_x/page_width:.1%}), right page: {page_width - page_gutter_x:.1f} points ({(page_width - page_gutter_x)/page_width:.1%})."
                    self.logger.warning(error_msg)
                    # #region agent log
                    try:
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({
                                'sessionId': 'debug-session',
                                'runId': 'run1',
                                'hypothesisId': 'I',
                                'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                                'message': 'Min page width validation failed',
                                'data': {
                                    'page_num': page_num,
                                    'min_page_width': float(min_page_width),
                                    'required_min': float(0.3 * page_width),
                                    'gutter_x': float(page_gutter_x),
                                    'page_width': float(page_width),
                                    'reason': 'min_page_width_less_than_30_percent'
                                },
                                'timestamp': int(time.time() * 1000)
                            }) + '\n')
                    except: pass
                    # #endregion
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'G',
                            'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                            'message': 'Splitting page at gutter position',
                            'data': {
                                'page_num': page_num,
                                'page_width': float(page_width),
                                'page_height': float(page_height),
                                'gutter_x': float(page_gutter_x),
                                'gutter_ratio': float(gutter_ratio),
                                'left_page_width': float(gutter_x),
                                'right_page_width': float(page_width - gutter_x),
                                'left_page_ratio': float(gutter_x / page_width) if page_width > 0 else 0.0,
                                'right_page_ratio': float((page_width - gutter_x) / page_width) if page_width > 0 else 0.0
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except: pass
                # #endregion
                
                # Log before split
                gutter_ratio_pct = (page_gutter_x / page_width) * 100 if page_width > 0 else 0
                self.logger.debug(
                    f"Page {page_num + 1} split: gutter={page_gutter_x:.1f}pts ({gutter_ratio_pct:.1f}%), "
                    f"page_width={page_width:.1f}pts, left_width={page_gutter_x:.1f}pts, right_width={page_width - page_gutter_x:.1f}pts"
                )
                
                # Create left page (from 0 to page_gutter_x)
                left_rect = fitz.Rect(0, 0, page_gutter_x, page_height)
                left_page = new_doc.new_page(width=page_gutter_x, height=page_height)
                left_page.show_pdf_page(left_rect, doc, page_num, clip=left_rect)
                
                # Create right page (from page_gutter_x to page_width)
                right_rect = fitz.Rect(page_gutter_x, 0, page_width, page_height)
                right_page = new_doc.new_page(width=page_width - page_gutter_x, height=page_height)
                right_page.show_pdf_page(right_rect, doc, page_num, clip=right_rect)
                pages_created += 2
                
                # Diagnostic logging: Check content immediately after creation
                left_text = left_page.get_text()
                right_text = right_page.get_text()
                left_text_length = len(left_text.strip()) if left_text else 0
                right_text_length = len(right_text.strip()) if right_text else 0
                
                # Check image content density for left page
                try:
                    import numpy as np
                    import cv2
                    zoom = 1.0
                    mat = fitz.Matrix(zoom, zoom)
                    left_pix = left_page.get_pixmap(matrix=mat, alpha=False)
                    left_img = np.frombuffer(left_pix.samples, dtype=np.uint8).reshape(left_pix.h, left_pix.w, 3)
                    if len(left_img.shape) == 3:
                        left_gray = cv2.cvtColor(left_img, cv2.COLOR_RGB2GRAY)
                    else:
                        left_gray = left_img
                    left_content_pixels = np.sum(left_gray < 240)
                    left_total_pixels = left_gray.size
                    left_content_ratio = (left_content_pixels / left_total_pixels) if left_total_pixels > 0 else 0.0
                except Exception:
                    left_content_ratio = None
                
                # Check image content density for right page
                try:
                    right_pix = right_page.get_pixmap(matrix=mat, alpha=False)
                    right_img = np.frombuffer(right_pix.samples, dtype=np.uint8).reshape(right_pix.h, right_pix.w, 3)
                    if len(right_img.shape) == 3:
                        right_gray = cv2.cvtColor(right_img, cv2.COLOR_RGB2GRAY)
                    else:
                        right_gray = right_img
                    right_content_pixels = np.sum(right_gray < 240)
                    right_total_pixels = right_gray.size
                    right_content_ratio = (right_content_pixels / right_total_pixels) if right_total_pixels > 0 else 0.0
                except Exception:
                    right_content_ratio = None
                
                self.logger.debug(
                    f"Page {page_num + 1} after split: "
                    f"left=[text={left_text_length}chars, content={left_content_ratio:.1%}], "
                    f"right=[text={right_text_length}chars, content={right_content_ratio:.1%}]"
                )
                
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'K',
                            'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                            'message': 'After creating left and right pages',
                            'data': {
                                'page_num': page_num,
                                'left_page_idx': len(new_doc) - 2,
                                'right_page_idx': len(new_doc) - 1,
                                'left_text_length': left_text_length,
                                'right_text_length': right_text_length,
                                'left_content_ratio': float(left_content_ratio) if left_content_ratio is not None else None,
                                'right_content_ratio': float(right_content_ratio) if right_content_ratio is not None else None,
                                'gutter_x': float(page_gutter_x),
                                'page_width': float(page_width),
                                'left_page_width': float(page_gutter_x),
                                'right_page_width': float(page_width - page_gutter_x)
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except: pass
                # #endregion
            
            # Check if we have the expected number of pages (2 per original)
            expected_pages = len(doc) * 2
            actual_pages = len(new_doc)
            
            # #region agent log
            try:
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G',
                        'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                        'message': 'After creating all split pages',
                        'data': {
                            'original_page_count': original_page_count,
                            'expected_pages': expected_pages,
                            'actual_pages': actual_pages,
                            'pages_created': pages_created,
                            'pages_match_expected': (actual_pages == expected_pages)
                        },
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            
            # Empty page detection removed: A clean split should produce exactly 2 pages per original page.
            # If a page is empty, that indicates a bug in gutter detection or split logic, not a valid edge case.
            # We'll rely on diagnostic logging to identify and fix root causes instead of masking the problem.
            
            # Legacy cleanup for 3-page pattern (if somehow we have extra pages)
            if actual_pages > expected_pages:
                # We have extra pages - remove every 3rd page starting from index 1
                # (assuming pattern: left, gutter, right, left, gutter, right, ...)
                extra_pages = actual_pages - expected_pages
                if extra_pages == len(doc):  # One extra per original
                    pages_to_remove_legacy = []
                    for i in range(len(doc)):
                        gutter_page_idx = i * 3 + 1  # Middle page of each 3-page group
                        if gutter_page_idx < actual_pages:
                            pages_to_remove_legacy.append(gutter_page_idx)
                    
                    # Remove in reverse order
                    for page_idx in reversed(pages_to_remove_legacy):
                        new_doc.delete_page(page_idx)
                    
                    self.logger.info(f"Removed {len(pages_to_remove_legacy)} gutter page(s) (legacy cleanup)")
            
            # Save to temp directory
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_split.pdf"
            
            # #region agent log
            try:
                file_existed_before = out_path.exists()
                file_size_before = out_path.stat().st_size if file_existed_before else 0
                with open(r'f:\prog\research-tools\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G',
                        'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                        'message': 'Before saving split PDF',
                        'data': {
                            'out_path': str(out_path),
                            'file_existed_before': file_existed_before,
                            'file_size_before': file_size_before,
                            'gutter_x': float(page_gutter_x),
                            'source_pdf': str(pdf_path)
                        },
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            
            new_doc.save(str(out_path))
            
            # #region agent log
            try:
                file_size_after = out_path.stat().st_size if out_path.exists() else 0
                with open(r'f:\prog\research-tools\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G',
                        'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                        'message': 'After saving split PDF',
                        'data': {
                            'out_path': str(out_path),
                            'file_size_after': file_size_after,
                            'file_was_overwritten': file_existed_before,
                            'size_changed': (file_size_after != file_size_before) if file_existed_before else True
                        },
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Split PDF created with custom gutter: {out_path.name}")
            return out_path, None
            
        except Exception as e:
            error_msg = f"Custom split failed: {e}"
            self.logger.error(error_msg)
            # #region agent log
            try:
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'J',
                        'location': 'paper_processor_daemon.py:_split_with_custom_gutter',
                        'message': 'Exception in _split_with_custom_gutter',
                        'data': {
                            'exception_type': type(e).__name__,
                            'exception_message': str(e),
                            'pdf_path': str(pdf_path),
                            'gutter_x': float(gutter_x) if 'gutter_x' in locals() else None
                        },
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            return None, error_msg
    
    def _split_with_mutool(self, pdf_path: Path, width: Optional[float] = None, height: Optional[float] = None, split_method: str = 'auto', border_detection_stats: Optional[dict] = None) -> Optional[Path]:
        """Split a two-up PDF using intelligent gutter detection or geometric split as fallback.
        
        First attempts to detect the actual gutter position using image analysis.
        If detection fails, falls back to geometric split at content center (if borders detected) or page center.
        Always uses _split_with_custom_gutter() for actual splitting.
        
        Args:
            pdf_path: Path to PDF file
            width: Optional page width (for geometric split)
            height: Optional page height (for geometric split)
            split_method: Split method - 'auto' (gutter detection with fallback),
                         '50-50' (geometric split directly), 'none' (skip splitting)
            border_detection_stats: Optional dict with avg_left_border_px, avg_right_border_px, page_width_px
        
        Returns:
            Path to split PDF or None if skipped/failed
        """
        try:
            # Handle split_method parameter
            if split_method == 'none':
                # Skip splitting entirely
                self.logger.info("Split method is 'none' - skipping split")
                return None
            
            if split_method == '50-50':
                # Skip gutter detection, use geometric split directly
                self.logger.info("Split method is '50-50' - using geometric split directly")
                gutter_result = None
            else:
                # Default 'auto' - try to detect actual gutter position first
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'G',
                            'location': 'paper_processor_daemon.py:_split_with_mutool',
                            'message': 'Before calling _find_gutter_position',
                            'data': {
                                'pdf_path': str(pdf_path),
                                'split_method': split_method,
                                'pdf_exists': pdf_path.exists() if pdf_path else False
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except Exception as e:
                    pass  # Don't fail on logging errors
                # #endregion
                gutter_result = self._find_gutter_position(pdf_path)
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'G',
                            'location': 'paper_processor_daemon.py:_split_with_mutool',
                            'message': 'After calling _find_gutter_position',
                            'data': {
                                'gutter_result_is_none': gutter_result is None,
                                'gutter_result_type': type(gutter_result).__name__ if gutter_result else None,
                                'gutter_x': float(gutter_result.get('gutter_x')) if (gutter_result and isinstance(gutter_result, dict)) else None,
                                'gutter_positions_count': len(gutter_result.get('gutter_positions', [])) if (gutter_result and isinstance(gutter_result, dict)) else None
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except Exception as e:
                    pass  # Don't fail on logging errors
                # #endregion
            
            # Handle new dict return format or legacy float format
            if gutter_result is None:
                # 50-50 split requested or detection skipped
                gutter_x = None
                gutter_x_per_page = None
                gutter_positions = None
                borders_per_page = None
                page_width = None
            elif isinstance(gutter_result, dict):
                gutter_x = gutter_result.get('gutter_x')  # Backward compatibility: median
                gutter_x_per_page = gutter_result.get('gutter_x_per_page')  # Per-page gutters
                gutter_positions = gutter_result.get('gutter_positions', [])
                borders_per_page = gutter_result.get('borders_per_page', [])
                page_width = gutter_result.get('page_width')
            else:
                # Legacy format (float or None)
                gutter_x = gutter_result
                gutter_x_per_page = None
                gutter_positions = None
                borders_per_page = None
                page_width = None
            
            if gutter_x is not None:
                # Check if gutter is reasonable - if not, use 50/50 split automatically
                if page_width:
                    gutter_ratio = gutter_x / page_width
                    if gutter_ratio < 0.3 or gutter_ratio > 0.7:
                        # Gutter is outside reasonable range - use 50/50 split automatically
                        self.logger.info(f"Gutter position {gutter_ratio:.1%} outside 30-70% range - using 50/50 geometric split")
                        gutter_x = None  # Fall through to geometric split
                
                # Validate gutter detection and prompt user if needed
                if gutter_x is not None and page_width:
                    validation_result = self._validate_gutter_detection(
                        gutter_x, page_width, gutter_positions, borders_per_page
                    )
                    is_valid, warnings = validation_result
                    
                    if not is_valid or warnings:
                        # Show warnings
                        print("\n" + "="*60, flush=True)
                        print("⚠️  GUTTER DETECTION WARNINGS", flush=True)
                        print("="*60, flush=True)
                        for warning in warnings:
                            print(warning, flush=True)
                        print(flush=True)
                        print("Large images or complex layouts can confuse gutter detection.", flush=True)
                        print("Options:", flush=True)
                        print("  [1] Proceed with detected gutter (may create poor results)", flush=True)
                        print("  [2] Use geometric split (50% - safer fallback)", flush=True)
                        print("  [3] Skip splitting (keep landscape format)", flush=True)
                        print(flush=True)
                        
                        try:
                            choice = input("Your choice [1/2/3]: ").strip()
                            if choice == '2':
                                # Use geometric split instead
                                gutter_x = None  # Fall through to geometric split
                            elif choice == '3':
                                # Skip splitting entirely
                                print("Skipping split - keeping landscape format", flush=True)
                                return None
                            # else choice == '1' or default: proceed with detected gutter
                        except (KeyboardInterrupt, EOFError):
                            print("\n❌ Cancelled", flush=True)
                            return None
                
                # Use custom split at detected gutter (with per-page gutters if available)
                result, error_msg = self._split_with_custom_gutter(pdf_path, gutter_x, gutter_x_per_page)
                if result:
                    return result
                if error_msg:
                    self.logger.warning(f"Custom split failed: {error_msg}")
                # If custom split failed, fall through to geometric split
            
            # Fallback to geometric split (50/50 or content center)
            if width is None or height is None:
                try:
                    import pdfplumber
                    with pdfplumber.open(str(pdf_path)) as pdf:
                        if len(pdf.pages) > 0:
                            width, height = pdf.pages[0].width, pdf.pages[0].height
                except Exception:
                    width = height = 0
            
            if not width:
                self.logger.error("Cannot determine page width for split")
                return None
            
            # Calculate split point: content center if borders detected, page center otherwise
            if border_detection_stats:
                avg_left = border_detection_stats.get('avg_left_border_px', 0)
                avg_right = border_detection_stats.get('avg_right_border_px', 0)
                page_width_px = border_detection_stats.get('page_width_px', 0)
                
                if page_width_px > 0:
                    # Convert borders to PDF points
                    left_border_pts = (avg_left / page_width_px) * width
                    right_border_pts = (avg_right / page_width_px) * width
                    
                    # Calculate content center: page_center + (left_border - right_border) / 2
                    page_center = width / 2
                    split_x = page_center + (left_border_pts - right_border_pts) / 2
                    self.logger.info(f"Using content center for split: {split_x:.1f} (page center: {page_center:.1f}, adjustment: {(left_border_pts - right_border_pts) / 2:.1f})")
                else:
                    # Fallback to page center if conversion fails
                    split_x = width / 2
                    self.logger.warning("Border stats available but page_width_px is 0, using page center")
            else:
                # No borders detected, use page center
                split_x = width / 2
                self.logger.info(f"Using page center for split: {split_x:.1f}")
            
            # Always use _split_with_custom_gutter() for splitting
            result, error_msg = self._split_with_custom_gutter(pdf_path, split_x)
            if result:
                self.logger.info(f"Split PDF created (geometric): {result.name}")
            elif error_msg:
                self.logger.warning(f"Geometric split failed: {error_msg}")
            return result
        except FileNotFoundError:
            self.logger.warning("mutool not found; skipping two-up split")
            # #region agent log
            try:
                with open(r'f:\prog\research-tools\.cursor\debug.log', 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'A,B,C,D,E',
                        'location': 'paper_processor_daemon.py:4663',
                        'message': '_split_with_mutool exit - mutool not found',
                        'data': {},
                        'timestamp': int(time.time() * 1000)
                    }) + '\n')
            except: pass
            # #endregion
            return None
        except Exception as e:
            self.logger.error(f"Split failed: {e}")
            return None
    
    def _input_with_timeout(self, prompt: str, timeout_seconds: int = None, 
                           default: str = None, clear_buffered: bool = True) -> Optional[str]:
        """Get user input with optional timeout.
        
        Args:
            prompt: Prompt text to display
            timeout_seconds: Timeout in seconds (None = use config default, 0 = no timeout)
            default: Default value to return on timeout (None = return None)
            clear_buffered: If True, attempt to clear any buffered input before waiting
            
        Returns:
            User input string, default value on timeout, or None if cancelled
        """
        if timeout_seconds is None:
            timeout_seconds = self.prompt_timeout
        
        # Clear any buffered input before waiting (prevents leftover input from previous prompts)
        if clear_buffered and timeout_seconds > 0 and HAS_SELECT:
            # Check if there's any input waiting without blocking
            ready, _, _ = select.select([sys.stdin], [], [], 0)
            if ready:
                # There's buffered input - read and discard it
                try:
                    # Read available input without blocking
                    import termios
                    import tty
                    old_settings = termios.tcgetattr(sys.stdin)
                    tty.setcbreak(sys.stdin.fileno())
                    cleared_chars = []
                    # Read all available characters
                    while ready:
                        ch = sys.stdin.read(1)
                        if not ch or ch == '\n':
                            break
                        cleared_chars.append(ch)
                        ready, _, _ = select.select([sys.stdin], [], [], 0)
                    termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old_settings)
                except (ImportError, OSError, AttributeError):
                    # termios not available - try simpler approach
                    # Just read one line if available
                    try:
                        sys.stdin.readline()
                    except:
                        pass
        
        # Silent timeout - no warning message (only show message when timeout occurs)
        try:
            if timeout_seconds > 0 and HAS_SELECT:
                # Use select-based timeout for Unix/WSL
                print(prompt, end='', flush=True)
                
                # Wait for input with timeout using select
                ready, _, _ = select.select([sys.stdin], [], [], timeout_seconds)
                if ready:
                    # Input is available - read it
                    user_input = sys.stdin.readline().strip()
                    return user_input if user_input else default
                else:
                    # Timeout - use default (low-contrast message)
                    if default is not None:
                        timeout_msg = Colors.colorize("⏱️  Timeout reached - proceeding with default", ColorScheme.TIMEOUT)
                        print(f"\n{timeout_msg}")
                        return default
                    else:
                        timeout_msg = Colors.colorize("⏱️  Timeout reached", ColorScheme.TIMEOUT)
                        print(f"\n{timeout_msg}")
                        return None
            else:
                # No timeout or select not available - use regular input
                user_input = input(prompt).strip()
                return user_input if user_input else default
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return None
    
    def _prompt_for_page_offset(self, pdf_path: Path) -> Optional[int]:
        """Prompt user to specify which page the document actually starts on.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Page offset (0-indexed: 0 = page 1, 1 = page 2, etc.) or None if cancelled
        """
        try:
            # Get total page count for validation
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                total_pages = len(pdf.pages)
        except Exception:
            total_pages = None
        
        print("\n" + "="*80)
        print("📄 Document Starting Page")
        print("="*80)
        if total_pages:
            print(f"This PDF scan has {total_pages} physical page(s).")
        print()
        print("⚠️  IMPORTANT: We're counting the SCAN PAGES (physical pages in this PDF file),")
        print("    NOT the page numbers printed on the journal or book pages.")
        print()
        print("Sometimes scans include extra pages before the actual document starts")
        print("(cover pages, previous chapters, etc.).")
        print()
        print("If your document starts on scan page 2, 3, 4, etc., enter that number now.")
        print()
        
        # Use timeout if configured
        timeout_seconds = self.page_offset_timeout
        
        # Small delay to ensure any previous input is cleared
        time.sleep(0.3)
        
        while True:
            try:
                prompt_text = "Enter starting scan page number (1-{}) or press Enter for page 1: ".format(total_pages if total_pages else "N")
                user_input = self._input_with_timeout(
                    prompt_text,
                    timeout_seconds=timeout_seconds,
                    default="",
                    clear_buffered=True
                )
                if user_input is None:
                    print("\n❌ Cancelled")
                    return None
                user_input = user_input.strip()
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
            
            if not user_input:
                # User pressed Enter - document starts at page 1
                return 0
            
            if user_input.isdigit():
                page_num = int(user_input)
                if page_num < 1:
                    print("⚠️  Page number must be at least 1")
                    continue
                if total_pages and page_num > total_pages:
                    print(f"⚠️  Page number cannot exceed {total_pages} (total pages in PDF)")
                    continue
                # Convert to 0-indexed offset (page 1 -> offset 0, page 2 -> offset 1, etc.)
                offset = page_num - 1
                if offset == 0:
                    print("✅ Document starts at scan page 1")
                else:
                    print(f"✅ Document will start from scan page {page_num} (skipping first {offset} scan page(s))")
                return offset
            else:
                print("⚠️  Please enter a number or press Enter for page 1")
    
    def _create_pdf_from_page_offset(self, pdf_path: Path, page_offset: int) -> Optional[Path]:
        """Create a temporary PDF starting from a specific page offset.
        
        Args:
            pdf_path: Path to original PDF file
            page_offset: 0-indexed page offset (0 = page 1, 1 = page 2, etc.)
            
        Returns:
            Path to temporary PDF starting from specified page, or None if failed
        """
        if page_offset < 1:
            # No offset needed, return None (use original)
            return None
        
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.error("PyMuPDF (fitz) not available - cannot create PDF from page offset")
            return None
        
        doc = None
        new_doc = None
        try:
            # Open the PDF
            doc = fitz.open(pdf_path)
            
            # Check if PDF has enough pages
            if len(doc) <= page_offset:
                self.logger.warning(f"PDF has only {len(doc)} page(s) - cannot start from page {page_offset + 1}")
                doc.close()
                return None
            
            # Create new PDF starting from page_offset
            new_doc = fitz.open()
            
            # Copy pages starting from page_offset
            pages_copied = []
            for page_num in range(page_offset, len(doc)):
                page = doc[page_num]
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.show_pdf_page(new_page.rect, doc, page_num)
                pages_copied.append(page_num)
            
            # Save to a temporary file
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_from_page{page_offset + 1}.pdf"
            
            new_doc.save(str(out_path))
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Created PDF starting from page {page_offset + 1}: {out_path.name}")
            return out_path
            
        except Exception as e:
            self.logger.error(f"Failed to create PDF from page offset {page_offset + 1}: {e}")
            # Ensure both documents are closed to prevent resource leaks
            if new_doc is not None:
                try:
                    new_doc.close()
                except Exception:
                    pass
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            return None
    
    def _extract_page_preview_text(self, pdf_path: Path, page_offset: int, max_chars: int = 180) -> Tuple[Optional[str], Optional[int]]:
        """Extract a short preview of text from the page at page_offset.
        
        Args:
            pdf_path: Path to PDF file
            page_offset: Zero-based page offset to preview after trimming
            max_chars: Maximum characters to include in preview
        
        Returns:
            Tuple of (preview_text, total_pages). preview_text may be None if text unavailable.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.warning("PyMuPDF (fitz) not available - cannot preview trimmed page text")
            return None, None
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            if page_offset >= total_pages:
                doc.close()
                return None, total_pages
            
            page = doc[page_offset]
            raw_text = page.get_text("text") or ""
            doc.close()
            
            preview = " ".join(raw_text.split())
            if preview and len(preview) > max_chars:
                preview = preview[: max_chars - 3].rstrip() + "..."
            return preview or None, total_pages
        except Exception as e:
            self.logger.debug(f"Failed to extract preview text for page {page_offset + 1}: {e}")
            return None, None
    
    def _extract_trailing_preview_text(self, pdf_path: Path, pages_to_drop: int, max_chars: int = 180) -> Optional[str]:
        """Extract a short preview of text from the last page that will remain after trimming trailing pages.
        
        Args:
            pdf_path: Path to PDF file
            pages_to_drop: Number of trailing pages to drop
            max_chars: Maximum characters to include in preview
        
        Returns:
            Preview text from the last remaining page, or None if text unavailable.
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.warning("PyMuPDF (fitz) not available - cannot preview trailing page text")
            return None
        
        try:
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            if pages_to_drop >= total_pages:
                doc.close()
                return None
            
            # Get the last page that will remain (total_pages - pages_to_drop - 1, 0-indexed)
            last_remaining_page_idx = total_pages - pages_to_drop - 1
            if last_remaining_page_idx < 0:
                doc.close()
                return None
            
            page = doc[last_remaining_page_idx]
            raw_text = page.get_text("text") or ""
            doc.close()
            
            # Get the end of the text (last part of the page)
            preview = " ".join(raw_text.split())
            if preview and len(preview) > max_chars:
                # Take the last max_chars characters
                preview = "..." + preview[-(max_chars - 3):].lstrip()
            return preview or None
        except Exception as e:
            self.logger.debug(f"Failed to extract trailing preview text: {e}")
            return None
    
    def _create_pdf_without_trailing_pages(self, pdf_path: Path, pages_to_drop: int) -> Optional[Path]:
        """Create a temporary PDF without the last N pages.
        
        Args:
            pdf_path: Path to original PDF file
            pages_to_drop: Number of trailing pages to drop
        
        Returns:
            Path to temporary PDF without trailing pages, or None if failed
        """
        if pages_to_drop < 1:
            return None
        
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.error("PyMuPDF (fitz) not available - cannot create PDF without trailing pages")
            return None
        
        doc = None
        new_doc = None
        try:
            # Open the PDF
            doc = fitz.open(pdf_path)
            total_pages = len(doc)
            
            # Check if PDF has enough pages
            if pages_to_drop >= total_pages:
                self.logger.warning(f"PDF has only {total_pages} page(s) - cannot drop {pages_to_drop} trailing pages")
                doc.close()
                return None
            
            # Create new PDF without trailing pages
            new_doc = fitz.open()
            
            # Copy all pages except the last N pages
            pages_to_keep = total_pages - pages_to_drop
            for page_num in range(pages_to_keep):
                page = doc[page_num]
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.show_pdf_page(new_page.rect, doc, page_num)
            
            # Save to a temporary file
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_trimmed_end_{pages_to_drop}.pdf"
            
            new_doc.save(str(out_path))
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Created PDF without last {pages_to_drop} page(s): {out_path.name}")
            return out_path
            
        except Exception as e:
            self.logger.error(f"Failed to create PDF without trailing pages: {e}")
            # Ensure both documents are closed to prevent resource leaks
            if new_doc is not None:
                try:
                    new_doc.close()
                except Exception:
                    pass  # Ignore errors during cleanup
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass  # Ignore errors during cleanup
            return None
    
    def _prompt_trim_leading_pages_for_attachment(self, pdf_path: Path) -> Tuple[Path, bool]:
        """Prompt user to optionally trim leading or trailing pages before attachment.
        
        Supports both positive numbers (trim from start) and negative numbers (trim from end).
        Example: "3" trims first 3 pages, "-2" trims last 2 pages.
        
        Args:
            pdf_path: Current working PDF path (after any splitting)
        
        Returns:
            Tuple of (path_to_use, trimmed_flag). If trimmed_flag is True, path_to_use
            points to a temporary PDF with pages trimmed.
        """
        if not pdf_path.exists():
            return pdf_path, False
        
        print("\n" + "=" * 70)
        print(Colors.colorize("OPTIONAL: TRIM PAGES", ColorScheme.PAGE_TITLE))
        print("=" * 70)
        print(Colors.colorize("Press Enter to keep the PDF exactly as it is.", ColorScheme.ACTION))
        print(Colors.colorize("Enter a positive number to drop that many leading pages (e.g., '3' = drop first 3 pages).", ColorScheme.ACTION))
        print(Colors.colorize("Enter a negative number to drop that many trailing pages (e.g., '-2' = drop last 2 pages).", ColorScheme.ACTION))
        print(Colors.colorize("We'll show you a preview of the trimmed PDF before anything is changed.", ColorScheme.ACTION))
        print("=" * 70)
        
        # Small delay to ensure user sees the prompt and any previous input is cleared
        time.sleep(0.5)
        
        while True:
            try:
                # Clear buffered input to prevent leftover input from previous prompts
                response = self._input_with_timeout(
                    "Trim pages? [Enter=keep all / number=pages to drop from start / -number=pages to drop from end]: ",
                    default="",
                    clear_buffered=True
                )
                if response is None:
                    print("\n❌ Trim cancelled - keeping all pages")
                    return pdf_path, False
                response = response.strip().lower()
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Trim cancelled - keeping all pages")
                return pdf_path, False
            
            if response in ("", "0", "n", "no"):
                print("ℹ️  Keeping all pages.")
                return pdf_path, False
            
            # Check if it's a valid number (positive or negative)
            try:
                pages_to_drop = int(response)
            except ValueError:
                print("⚠️  Please enter a whole number (positive for leading pages, negative for trailing pages) or press Enter to keep everything.")
                continue
            
            if pages_to_drop == 0:
                print("ℹ️  Keeping all pages.")
                return pdf_path, False
            
            # Get total pages for validation
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(pdf_path)
                total_pages = len(doc)
                doc.close()
            except Exception:
                print("⚠️  Could not read PDF to get page count.")
                continue
            
            # Handle negative numbers (trim from end)
            if pages_to_drop < 0:
                pages_to_drop_abs = abs(pages_to_drop)
                if pages_to_drop_abs >= total_pages:
                    print(f"⚠️  This PDF has {total_pages} page(s); you cannot drop {pages_to_drop_abs} trailing pages.")
                    continue
                
                # Show preview of last page that will remain
                preview_text = self._extract_trailing_preview_text(pdf_path, pages_to_drop_abs)
                print(f"\nThe last page in your new PDF (page {total_pages - pages_to_drop_abs}) will end with:")
                if preview_text:
                    print(f'  "...{preview_text}"')
                else:
                    print("  [No text detected on that page]")
                print()
                
                try:
                    confirm = input(f"Type 'trim' to drop the last {pages_to_drop_abs} page(s), or press Enter to keep everything: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Trim cancelled - keeping all pages")
                    return pdf_path, False
                
                if confirm != "trim":
                    print("ℹ️  Keeping all pages.")
                    return pdf_path, False
                
                trimmed_pdf = self._create_pdf_without_trailing_pages(pdf_path, pages_to_drop_abs)
                if not trimmed_pdf:
                    print("⚠️  Failed to create trimmed PDF. Keeping original pages.")
                    return pdf_path, False
                
                print(f"✅ Trimmed last {pages_to_drop_abs} page(s) for Zotero attachment")
                self.logger.info(f"Trimmed last {pages_to_drop_abs} page(s) before attachment: {trimmed_pdf.name}")
                return trimmed_pdf, True
            
            # Handle positive numbers (trim from start)
            else:
                if pages_to_drop >= total_pages:
                    print(f"⚠️  This PDF has {total_pages} page(s); you cannot drop {pages_to_drop} leading pages.")
                    continue
                
                preview_text, _ = self._extract_page_preview_text(pdf_path, pages_to_drop)
                print("\nThe first page in your new PDF will start with:")
                if preview_text:
                    print(f'  "{preview_text}"')
                else:
                    print("  [No text detected on that page]")
                print()
                
                try:
                    confirm = input(f"Type 'trim' to drop the first {pages_to_drop} page(s), or press Enter to keep everything: ").strip().lower()
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Trim cancelled - keeping all pages")
                    return pdf_path, False
                
                if confirm != "trim":
                    print("ℹ️  Keeping all pages.")
                    return pdf_path, False
                
                trimmed_pdf = self._create_pdf_from_page_offset(pdf_path, pages_to_drop)
                if not trimmed_pdf:
                    print("⚠️  Failed to create trimmed PDF. Keeping original pages.")
                    return pdf_path, False
                
                print(f"✅ Trimmed first {pages_to_drop} page(s) for Zotero attachment")
                self.logger.info(f"Trimmed first {pages_to_drop} page(s) before attachment: {trimmed_pdf.name}")
                return trimmed_pdf, True
    
    def _delete_first_page_from_pdf(self, pdf_path: Path) -> Optional[Path]:
        """Delete the first page from a PDF and return path to the modified file.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Path to modified PDF without page 1, or None if failed
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.error("PyMuPDF (fitz) not available - cannot delete page 1")
            return None
        
        doc = None
        new_doc = None
        try:
            # Open the PDF
            doc = fitz.open(pdf_path)
            
            # Check if PDF has more than 1 page
            if len(doc) <= 1:
                self.logger.warning(f"PDF has only {len(doc)} page(s) - cannot delete page 1")
                doc.close()
                return None
            
            # Create new PDF without first page
            new_doc = fitz.open()
            
            # Copy all pages except the first one (page 0)
            for page_num in range(1, len(doc)):
                page = doc[page_num]
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.show_pdf_page(new_page.rect, doc, page_num)
            
            # Save to a new file in the same directory
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_no_page1.pdf"
            
            new_doc.save(str(out_path))
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Created PDF without page 1: {out_path.name}")
            return out_path
            
        except Exception as e:
            self.logger.error(f"Failed to delete page 1 from PDF: {e}")
            # Ensure both documents are closed to prevent resource leaks
            if new_doc is not None:
                try:
                    new_doc.close()
                except Exception:
                    pass  # Ignore errors during cleanup
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass  # Ignore errors during cleanup
            return None
    
    def _check_and_remove_dark_borders(self, pdf_path: Path) -> tuple[Optional[Path], Optional[dict]]:
        """Check for dark borders and optionally remove them.
        
        Checks first 4 pages for borders. If borders detected, prompts user
        to confirm removal. Returns path to cleaned PDF or None if no action taken.
        Also returns border detection statistics even if removal is rejected.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (output_pdf_path, border_detection_stats):
            - output_pdf_path: Path to cleaned PDF if borders removed, None if skipped
            - border_detection_stats: Dict with avg_left_border_px, avg_right_border_px, page_width_px
              or None if no borders detected
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.error("PyMuPDF (fitz) not available - cannot check borders")
            return None, None
        
        print("\n🔍 Checking for dark borders (optimized detection)...")
        
        # Use optimized border detection (checks first 3 pages, calculates variation)
        optimized_result = self.border_remover.detect_borders_optimized(pdf_path, sample_pages=3)
        borders = optimized_result.get('borders', {'top': 0, 'bottom': 0, 'left': 0, 'right': 0})
        method = optimized_result.get('method', 'consistent')
        variation = optimized_result.get('variation', {})
        pages_checked = optimized_result.get('pages_checked', 0)
        
        # Check if any borders were detected
        borders_detected = any(borders.values())
        
        # Get page width for stats
        page_width_px = None
        try:
            doc = fitz.open(str(pdf_path))
            if len(doc) > 0:
                page = doc[0]
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                page_width_px = pix.width
            doc.close()
        except Exception as e:
            self.logger.debug(f"Error getting page width: {e}")
        
        # Calculate border detection stats
        border_detection_stats = None
        if borders_detected and page_width_px:
            border_detection_stats = {
                'avg_left_border_px': borders.get('left', 0),
                'avg_right_border_px': borders.get('right', 0),
                'page_width_px': page_width_px
            }
            self.logger.debug(f"Border detection stats: {border_detection_stats}")
        
        # Report detection results
        if borders_detected:
            border_desc = []
            if borders['top'] > 0:
                border_desc.append(f"top: {borders['top']}px")
            if borders['bottom'] > 0:
                border_desc.append(f"bottom: {borders['bottom']}px")
            if borders['left'] > 0:
                border_desc.append(f"left: {borders['left']}px")
            if borders['right'] > 0:
                border_desc.append(f"right: {borders['right']}px")
            
            desc = ", ".join(border_desc) if border_desc else "detected"
            print(f"  ✓ Borders detected ({desc})")
            print(f"  ✓ Method: {method} (checked {pages_checked} pages)")
            if variation:
                max_cv = max(variation.values()) if variation else 0.0
                if max_cv > 0:
                    print(f"  ✓ Variation: {max_cv:.1%} (max across all sides)")
            self.logger.debug(f"Borders detected: {borders}, method: {method}")
        else:
            print("\nℹ️  No dark borders detected - skipping removal")
            return None, border_detection_stats
        
        # Report to user
        print(f"\n📊 Summary: Dark borders detected (method: {method}, checked {pages_checked} pages)")
        
        choice = input("Remove dark borders from the whole PDF? [Y/n]: ").strip().lower()
        if choice == 'n':
            print("Skipping border removal")
            return None, border_detection_stats
        
        # Process entire PDF with border removal
        print("\n🔄 Processing all pages...")
        
        # Create output path
        import tempfile
        temp_dir = Path(tempfile.gettempdir()) / 'pdf_borders_removed'
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / f"{pdf_path.stem}_no_borders.pdf"
        
        try:
            stats = self.border_remover.process_entire_pdf(pdf_path, out_path, zoom=2.0)
            
            if stats and stats.get('pages_processed', 0) > 0:
                pixel_count = stats.get('total_border_pixels', 0)
                if pixel_count > 0:
                    # Format pixel count nicely
                    if pixel_count > 1_000_000:
                        pixel_str = f"{pixel_count/1_000_000:.1f}M"
                    elif pixel_count > 1_000:
                        pixel_str = f"{pixel_count/1_000:.0f}K"
                    else:
                        pixel_str = str(pixel_count)
                    
                    print(f"✅ Borders removed from {stats['pages_processed']} pages ({pixel_str} pixels)")
                else:
                    print(f"✅ Borders removed from {stats['pages_processed']} pages")
                self.logger.debug(f"Created PDF without borders: {out_path.name}")
                return out_path, border_detection_stats
            else:
                print("⚠️  No pages were processed")
                return None, border_detection_stats
                
        except Exception as e:
            self.logger.error(f"Error during border removal: {e}")
            print(f"⚠️  Border removal failed: {e}")
            return None, border_detection_stats
    
    def start(self):
        """Start the daemon."""
        # Single-instance guard
        self._check_existing_instance()
        
        # Write PID file
        self.write_pid_file()
        
        # Setup file watcher
        event_handler = PaperFileHandler(self)
        self.observer = Observer()
        self.observer.schedule(event_handler, str(self.watch_dir), recursive=False)
        self.observer.start()
        
        self.logger.info("="*60)
        self.logger.info("Paper Processor Daemon Started")
        self.logger.info(f"Watching: {self.watch_dir}")
        self.logger.info(f"Publications: {self.publications_dir}")
        self.logger.info("="*60)
        
        # Position terminal window on right half of screen using Windows Snap
        # Wait for terminal window to be ready
        time.sleep(2.0)  # Give terminal window time to be fully ready
        self._position_terminal_window()
        
        # Note: Removed second positioning call to prevent window jumping
        # If positioning fails, it will be retried when PDF viewer opens
        
        # Process existing files in the directory
        self.process_existing_files()
        
        # Refresh publications cache on startup
        self._refresh_publications_cache()
        
        self.logger.info("Ready for scans!")
        self.logger.info("="*60)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown(None, None)
    
    def _open_pdf_in_viewer(self, pdf_path: Path) -> bool:
        """Open PDF in default system viewer (non-blocking) and position window.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            True if opened successfully, False otherwise
        """
        try:
            # Convert to Windows path if needed for WSL
            if sys.platform != 'win32':
                # Try to convert WSL path to Windows path
                windows_path = self._to_windows_path(pdf_path)
                # Validate that windows_path is actually a Windows path format (contains :\ or :/, or is UNC path starting with \\)
                # If conversion failed and returned a WSL path, we can't use it with Windows programs
                is_valid_windows_path = windows_path and ((":\\" in windows_path or ":/" in windows_path) or windows_path.startswith('\\\\'))
                if is_valid_windows_path:
                    self.logger.info(f"Opening PDF in viewer: {windows_path}")
                    
                    # Bring terminal to foreground first to ensure PDF opens on same desktop
                    # This switches to the terminal's virtual desktop before opening PDF
                    if hasattr(self, '_terminal_window_handle') and self._terminal_window_handle:
                        try:
                            ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
$terminalHwnd = [IntPtr]{self._terminal_window_handle}
if ([Win32]::IsWindowVisible($terminalHwnd)) {{
    # Restore window if minimized, then bring to foreground
    [Win32]::ShowWindow($terminalHwnd, 9)  # SW_RESTORE = 9
    Start-Sleep -Milliseconds 100
    [Win32]::SetForegroundWindow($terminalHwnd)
    # Wait longer to ensure virtual desktop switch completes
    Start-Sleep -Milliseconds 500
}}
'''
                            subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                        except Exception as e:
                            self.logger.debug(f"Could not bring terminal to foreground before opening PDF: {e}")
                    
                    # Try PowerShell to open file (works from WSL)
                    try:
                        ps_command = f'Start-Process "{windows_path}"'
                        proc = subprocess.Popen(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_command],
                                                stdout=subprocess.DEVNULL, 
                                                stderr=subprocess.DEVNULL)
                        # Store process for later closing
                        self._pdf_viewer_process = proc
                        self._pdf_viewer_path = pdf_path
                        
                        # Wait a moment for window to open, then position it
                        time.sleep(1.5)
                        self._position_pdf_window(pdf_path)
                        self.logger.info("PDF viewer opened successfully")
                        return True
                    except Exception as e:
                        self.logger.warning(f"Failed to open PDF with PowerShell: {e}")
                    
                    # Fallback: try wslview if available
                    try:
                        proc = subprocess.Popen(['wslview', str(windows_path)], 
                                                stdout=subprocess.DEVNULL, 
                                                stderr=subprocess.DEVNULL)
                        self._pdf_viewer_process = proc
                        self._pdf_viewer_path = pdf_path
                        time.sleep(1.5)
                        self._position_pdf_window(pdf_path)
                        return True
                    except FileNotFoundError:
                        self.logger.warning("wslview not found")
                    except Exception as e:
                        self.logger.warning(f"Failed to open PDF with wslview: {e}")
                else:
                    self.logger.warning(f"Could not convert path to Windows format: {pdf_path}")
                    return False
            else:
                # Windows: ensure we're on the correct desktop before opening
                # Bring terminal to foreground first to ensure PDF opens on same desktop
                # This switches to the terminal's virtual desktop before opening PDF
                if hasattr(self, '_terminal_window_handle') and self._terminal_window_handle:
                    try:
                        ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
}}
"@
$terminalHwnd = [IntPtr]{self._terminal_window_handle}
if ([Win32]::IsWindowVisible($terminalHwnd)) {{
    # Restore window if minimized, then bring to foreground
    [Win32]::ShowWindow($terminalHwnd, 9)  # SW_RESTORE = 9
    Start-Sleep -Milliseconds 100
    [Win32]::SetForegroundWindow($terminalHwnd)
    # Wait longer to ensure virtual desktop switch completes
    Start-Sleep -Milliseconds 500
}}
'''
                        subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=3)
                    except Exception as e:
                        self.logger.debug(f"Could not bring terminal to foreground before opening PDF: {e}")
                
                # Windows: use startfile (non-blocking)
                self.logger.info(f"Opening PDF in viewer: {pdf_path}")
                os.startfile(str(pdf_path))
                self._pdf_viewer_path = pdf_path
                
                # Wait a moment for window to open, then position it
                time.sleep(1.5)  # Slightly longer wait to ensure window is fully created
                self._position_pdf_window(pdf_path)
                self.logger.info("PDF viewer opened successfully")
                return True
                
        except Exception as e:
            self.logger.error(f"Could not open PDF in viewer: {e}")
            return False
        
        self.logger.warning("All methods to open PDF viewer failed")
        return False
    
    def _store_terminal_window_handle(self):
        """Store terminal window handle at startup for later use."""
        self.logger.info("Storing terminal window handle...")
        try:
            # Use PowerShell to find terminal window by process tree
            # Get current Python process, find parent (WSL/bash), then find its parent (cmd.exe)
            ps_script = '''
# Define all types in a single Add-Type block so they can reference each other
Add-Type @"
using System;
using System.Runtime.InteropServices;

public struct RECT {
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}

public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
}

public class Win32Find {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
}
"@

$found = $false

# Strategy 1: Find by process tree - get cmd.exe that launched WSL
$cmdProcesses = Get-Process -Name "cmd" -ErrorAction SilentlyContinue | Where-Object { 
    $_.MainWindowHandle -ne [IntPtr]::Zero 
} | Sort-Object StartTime -Descending

Write-Host "Checking $($cmdProcesses.Count) cmd.exe processes..."
foreach ($proc in $cmdProcesses) {
    try {
        $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
        Write-Host "Process $($proc.Id): $($proc.MainWindowTitle) - CmdLine: $cmdLine"
        if ($cmdLine) {
            $hasWsl = $cmdLine -like "*wsl*"
            $hasDaemon = $cmdLine -like "*paper_processor_daemon*"
            $notStatus = $cmdLine -notlike "*--status*"
            Write-Host "  Has WSL: $hasWsl, Has daemon: $hasDaemon, Not status: $notStatus"
            
            if ($hasWsl -and $hasDaemon -and $notStatus) {
                $hwnd = $proc.MainWindowHandle
                $rect = New-Object RECT
                if ([Win32]::GetWindowRect($hwnd, [ref]$rect)) {
                    $width = $rect.Right - $rect.Left
                    $height = $rect.Bottom - $rect.Top
                    Write-Host "  Window size: ${width}x${height}"
                    # Only use if reasonably sized
                    if ($width -gt 100 -and $height -gt 100) {
                        Write-Host "FOUND: $($hwnd.ToString())"
                        $found = $true
                        break
                    }
                }
            }
        }
    } catch {
        Write-Host "  Error: $_"
        continue
    }
}

# Strategy 2: Find console window by class name
if (!$found) {
    Write-Host "Trying console window class name..."
    try {
        # Win32Find class already defined in the top-level Add-Type block
        $hwnd = [Win32Find]::FindWindow("ConsoleWindowClass", $null)
        if ($hwnd -ne [IntPtr]::Zero) {
            $rect = New-Object RECT
            if ([Win32Find]::GetWindowRect($hwnd, [ref]$rect)) {
                $width = $rect.Right - $rect.Left
                $height = $rect.Bottom - $rect.Top
                Write-Host "Console window size: ${width}x${height}"
                if ($width -gt 100 -and $height -gt 100) {
                    Write-Host "FOUND: $($hwnd.ToString())"
                    $found = $true
                }
            }
        }
    } catch {
        Write-Host "Strategy 2 error: $_"
    }
}

# Strategy 3: Use foreground window if no console found (fallback)
if (!$found) {
    Write-Host "Trying foreground window as fallback..."
    try {
        $hwnd = [Win32]::GetForegroundWindow()
        if ($hwnd -ne [IntPtr]::Zero) {
            $rect = New-Object RECT
            if ([Win32]::GetWindowRect($hwnd, [ref]$rect)) {
                $width = $rect.Right - $rect.Left
                $height = $rect.Bottom - $rect.Top
                Write-Host "Foreground window size: ${width}x${height}"
                if ($width -gt 100 -and $height -gt 100) {
                    Write-Host "FOUND: $($hwnd.ToString())"
                    $found = $true
                }
            }
        }
    } catch {
        Write-Host "Strategy 3 error: $_"
    }
}

if (!$found) {
    Write-Host "NOTFOUND"
}
'''
            result = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10, text=True)
            
            if result.stdout:
                output = result.stdout.strip()
                # Always log the output for debugging
                self.logger.info(f"Terminal handle search output: {output}")
                # Look for "FOUND: <handle>" in output
                match = re.search(r'FOUND:\s*(\d+)', output)
                if match:
                    handle_str = match.group(1)
                    self._terminal_window_handle = handle_str
                    self.logger.info(f"Stored terminal window handle: {handle_str}")
                elif "NOTFOUND" in output:
                    self.logger.warning("Terminal window handle not found (NOTFOUND)")
                else:
                    # If we got output but no FOUND, log it for debugging
                    self.logger.warning(f"Terminal handle search completed but no handle found. Output: {output[:500]}")
            else:
                self.logger.warning("Could not find terminal window handle (no output from script)")
            if result.stderr:
                self.logger.warning(f"Terminal handle search errors: {result.stderr.strip()}")
            if result.returncode != 0:
                self.logger.warning(f"Terminal handle search script exited with code: {result.returncode}")
                
        except Exception as e:
            self.logger.warning(f"Could not store terminal window handle: {e}")
    
    def _position_terminal_window(self):
        """Position terminal window on the right half of the screen using Windows Snap.
        
        Uses Windows keyboard shortcut (Win+Right) to snap window to right half.
        This is more reliable than manual positioning and can create snap groups.
        """
        self.logger.info("Positioning terminal window to right half using Windows Snap...")
        try:
            # Use Windows keyboard shortcut to snap window to right half
            # This uses Windows' native snap functionality which is more reliable
            ps_script = '''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);
}
"@

# Find console window - try multiple strategies
$hwnd = [IntPtr]::Zero

# Strategy 1: Find console window by class name (most reliable)
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Find {
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}
"@
$hwnd = [Win32Find]::FindWindow("ConsoleWindowClass", $null)
if ($hwnd -ne [IntPtr]::Zero) {
    Write-Host "Found console window by class name"
}

# Strategy 2: Find most recent cmd.exe window
if ($hwnd -eq [IntPtr]::Zero) {
    $cmdProcesses = Get-Process -Name "cmd" -ErrorAction SilentlyContinue | Where-Object { 
        $_.MainWindowHandle -ne [IntPtr]::Zero 
    } | Sort-Object StartTime -Descending | Select-Object -First 1
    
    if ($cmdProcesses) {
        $hwnd = $cmdProcesses.MainWindowHandle
        Write-Host "Found most recent cmd.exe window (PID: $($cmdProcesses.Id))"
    }
}

# Strategy 3: Use foreground window if no console found (fallback)
if ($hwnd -eq [IntPtr]::Zero) {
    $hwnd = [Win32]::GetForegroundWindow()
    if ($hwnd -ne [IntPtr]::Zero) {
        Write-Host "Using foreground window as fallback"
    }
}

if ($hwnd -ne [IntPtr]::Zero) {
    # Add window positioning functions
    Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32Pos {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
    public const int SM_CXSCREEN = 0;
    public const int SM_CYSCREEN = 1;
    public const int SW_RESTORE = 9;
    public const uint SWP_SHOWWINDOW = 0x0040;
}
public struct RECT {
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}
"@
    
    # Restore window if minimized
    [Win32Pos]::ShowWindow($hwnd, [Win32Pos]::SW_RESTORE)
    Start-Sleep -Milliseconds 100
    
    # Bring window to foreground (if not already)
    [Win32]::SetForegroundWindow($hwnd)
    Start-Sleep -Milliseconds 200
    
    # Get screen dimensions
    $screenWidth = [Win32Pos]::GetSystemMetrics([Win32Pos]::SM_CXSCREEN)
    $screenHeight = [Win32Pos]::GetSystemMetrics([Win32Pos]::SM_CYSCREEN)
    
    # Calculate right half position and size
    $rightHalfWidth = [int]($screenWidth / 2)
    $rightHalfHeight = $screenHeight
    $rightHalfX = $screenWidth / 2
    $rightHalfY = 0
    
    # Use SetWindowPos to position AND size explicitly
    $result = [Win32Pos]::SetWindowPos($hwnd, [IntPtr]::Zero, $rightHalfX, $rightHalfY, $rightHalfWidth, $rightHalfHeight, [Win32Pos]::SWP_SHOWWINDOW)
    
    if ($result) {
        Write-Host "Positioned terminal window using SetWindowPos (right half, $rightHalfWidth x $rightHalfHeight)"
        Start-Sleep -Milliseconds 100
        # Also try Windows Snap as backup to ensure it's properly snapped
        [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x27, 0, 0, 0)  # Right arrow down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x27, 0, 0x0002, 0)  # Right arrow up
        [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
        Write-Host "SUCCESS"
    } else {
        Write-Host "SetWindowPos failed, trying Windows Snap only"
        # Fallback to Windows Snap
        [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x27, 0, 0, 0)  # Right arrow down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x27, 0, 0x0002, 0)  # Right arrow up
        [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
        Write-Host "SUCCESS"
    }
} else {
    Write-Host "Could not find terminal window"
}
'''
            
            result = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
            
            if result.stdout:
                output = result.stdout.strip()
                if "SUCCESS" in output:
                    self.logger.info("Terminal window snapped to right half successfully")
                else:
                    self.logger.info(f"Terminal snap output: {output}")
            if result.stderr:
                self.logger.warning(f"Terminal snap errors: {result.stderr.strip()}")
                
        except subprocess.TimeoutExpired:
            self.logger.warning("Terminal snap script timed out")
        except Exception as e:
            self.logger.warning(f"Could not snap terminal window: {e}")
    
    def _position_pdf_window(self, pdf_path: Path):
        """Position PDF viewer window on the left half of the screen and ensure it's on the same desktop as terminal.
        
        Args:
            pdf_path: Path to PDF file (used to find window by title)
        """
        # Retry logic: Sumatra may take a moment to open
        max_retries = 3
        retry_delay = 0.5
        
        for attempt in range(max_retries):
            try:
                if sys.platform != 'win32':
                    windows_path = self._to_windows_path(pdf_path)
                    if not windows_path:
                        return
                    filename = Path(windows_path).name
                else:
                    filename = pdf_path.name
                
                # Get terminal window handle if stored
                terminal_hwnd = None
                if hasattr(self, '_terminal_window_handle') and self._terminal_window_handle:
                    try:
                        terminal_hwnd = int(self._terminal_window_handle)
                    except (ValueError, TypeError):
                        terminal_hwnd = None
                
                # PowerShell script to find PDF viewer, move to same desktop as terminal, and position it
                ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")]
    public static extern void keybd_event(byte bVk, byte bScan, uint dwFlags, int dwExtraInfo);
    [DllImport("user32.dll")]
    public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);
}}
public struct RECT {{
    public int Left;
    public int Top;
    public int Right;
    public int Bottom;
}}
"@

$filename = "{filename}"
$terminalHwnd = {terminal_hwnd if terminal_hwnd else "[IntPtr]::Zero"}

# Find Sumatra PDF process specifically
$sumatraProcesses = Get-Process -Name "SumatraPDF" -ErrorAction SilentlyContinue | Where-Object {{
    $_.MainWindowHandle -ne [IntPtr]::Zero
}}

$pdfHwnd = [IntPtr]::Zero
foreach ($proc in $sumatraProcesses) {{
    $title = $proc.MainWindowTitle
    # Match by filename in title or just use first Sumatra window
    if ($title -like "*$filename*" -or $sumatraProcesses.Count -eq 1) {{
        $pdfHwnd = $proc.MainWindowHandle
        Write-Host "Found Sumatra PDF window: $title"
        break
    }}
}}

# Fallback: find any PDF viewer with filename in title
if ($pdfHwnd -eq [IntPtr]::Zero) {{
    $processes = Get-Process | Where-Object {{
        $_.MainWindowHandle -ne [IntPtr]::Zero -and
        ($_.MainWindowTitle -like "*$filename*" -or $_.MainWindowTitle -like "*PDF*")
    }} | Select-Object -First 1
    
    if ($processes) {{
        $pdfHwnd = $processes.MainWindowHandle
        Write-Host "Found PDF viewer window: $($processes.ProcessName) - $($processes.MainWindowTitle)"
    }}
}}

if ($pdfHwnd -ne [IntPtr]::Zero) {{
    # Step 1: Ensure PDF viewer is on the same desktop as terminal
    # Bring terminal to foreground first (if we have its handle) to switch to its desktop
    if ($terminalHwnd -ne [IntPtr]::Zero) {{
        try {{
            $terminalPtr = [IntPtr]$terminalHwnd
            if ([Win32]::IsWindowVisible($terminalPtr)) {{
                # Restore window if minimized, then bring to foreground
                [Win32]::ShowWindow($terminalPtr, 9)  # SW_RESTORE = 9
                Start-Sleep -Milliseconds 150
                [Win32]::SetForegroundWindow($terminalPtr)
                # Wait longer to ensure virtual desktop switch completes
                Start-Sleep -Milliseconds 800
                Write-Host "Brought terminal to foreground (switched to terminal desktop)"
            }}
        }} catch {{
            Write-Host "Could not bring terminal to foreground: $_"
        }}
    }}
    
    # Step 2: Bring PDF viewer to foreground (this moves it to current desktop)
    [Win32]::ShowWindow($pdfHwnd, 9)  # SW_RESTORE = 9
    Start-Sleep -Milliseconds 150
    [Win32]::SetForegroundWindow($pdfHwnd)
    Start-Sleep -Milliseconds 300
    Write-Host "Brought PDF viewer to foreground"
    
    # Step 3: Position PDF viewer relative to terminal or use Windows Snap
    if ($terminalHwnd -ne [IntPtr]::Zero) {{
        try {{
            $terminalPtr = [IntPtr]$terminalHwnd
            $terminalRect = New-Object RECT
            if ([Win32]::GetWindowRect($terminalPtr, [ref]$terminalRect)) {{
                $terminalLeft = $terminalRect.Left
                $terminalTop = $terminalRect.Top
                $terminalWidth = $terminalRect.Right - $terminalRect.Left
                $terminalHeight = $terminalRect.Bottom - $terminalRect.Top
                
                # Get screen dimensions using Add-Type
                Add-Type @"
using System;
using System.Runtime.InteropServices;
public class ScreenInfo {{
    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);
    public const int SM_CXSCREEN = 0;
    public const int SM_CYSCREEN = 1;
}}
"@
                $screenWidth = [ScreenInfo]::GetSystemMetrics([ScreenInfo]::SM_CXSCREEN)
                $screenHeight = [ScreenInfo]::GetSystemMetrics([ScreenInfo]::SM_CYSCREEN)
                
                # Position PDF viewer on left half, terminal on right half
                # Calculate left half position and size explicitly
                $pdfWidth = [int]($screenWidth / 2)
                $pdfHeight = $screenHeight
                $pdfX = 0
                $pdfY = 0
                
                # Use SetWindowPos to position AND size explicitly
                $result = [Win32]::SetWindowPos($pdfHwnd, [IntPtr]::Zero, $pdfX, $pdfY, $pdfWidth, $pdfHeight, 0x0040)
                if ($result) {{
                    Write-Host "Positioned PDF viewer using SetWindowPos (left half, $pdfWidth x $pdfHeight)"
                    Start-Sleep -Milliseconds 100
                    # Also try Windows Snap as backup to ensure it's properly snapped
                    [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
                    Start-Sleep -Milliseconds 50
                    [Win32]::keybd_event(0x25, 0, 0, 0)  # Left arrow down
                    Start-Sleep -Milliseconds 50
                    [Win32]::keybd_event(0x25, 0, 0x0002, 0)  # Left arrow up
                    [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
                }} else {{
                    Write-Host "SetWindowPos failed, trying Windows Snap only"
                    # Fallback to Windows Snap
                    [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
                    Start-Sleep -Milliseconds 50
                    [Win32]::keybd_event(0x25, 0, 0, 0)  # Left arrow down
                    Start-Sleep -Milliseconds 50
                    [Win32]::keybd_event(0x25, 0, 0x0002, 0)  # Left arrow up
                    [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
                }}
            }} else {{
                Write-Host "Could not get terminal window rect, using Windows Snap"
                # Fallback to Windows Snap
                [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
                Start-Sleep -Milliseconds 50
                [Win32]::keybd_event(0x25, 0, 0, 0)  # Left arrow down
                Start-Sleep -Milliseconds 50
                [Win32]::keybd_event(0x25, 0, 0x0002, 0)  # Left arrow up
                [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
            }}
        }} catch {{
            Write-Host "Error positioning relative to terminal: $_"
            # Fallback to Windows Snap
            [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
            Start-Sleep -Milliseconds 50
            [Win32]::keybd_event(0x25, 0, 0, 0)  # Left arrow down
            Start-Sleep -Milliseconds 50
            [Win32]::keybd_event(0x25, 0, 0x0002, 0)  # Left arrow up
            [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
        }}
    }} else {{
        # No terminal handle - use Windows Snap
        Write-Host "No terminal handle, using Windows Snap"
        [Win32]::keybd_event(0x5B, 0, 0, 0)  # Win key down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x25, 0, 0, 0)  # Left arrow down
        Start-Sleep -Milliseconds 50
        [Win32]::keybd_event(0x25, 0, 0x0002, 0)  # Left arrow up
        [Win32]::keybd_event(0x5B, 0, 0x0002, 0)  # Win key up
    }}
    
    Write-Host "SUCCESS"
}} else {{
    Write-Host "PDF viewer window not found"
}}
'''
                
                result = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                     stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
                
                if result.stdout and "SUCCESS" in result.stdout:
                    self.logger.info(f"PDF viewer positioned successfully (attempt {attempt + 1})")
                    if result.stdout.strip():
                        self.logger.debug(f"Positioning output: {result.stdout.strip()}")
                    return
                elif attempt < max_retries - 1:
                    self.logger.debug(f"PDF viewer not found yet, retrying in {retry_delay}s...")
                    time.sleep(retry_delay)
                else:
                    if result.stdout:
                        self.logger.warning(f"PDF viewer positioning failed: {result.stdout.strip()}")
                    if result.stderr:
                        self.logger.warning(f"PDF viewer positioning errors: {result.stderr.strip()}")
                        
            except subprocess.TimeoutExpired:
                self.logger.warning("PDF viewer positioning script timed out")
            except Exception as e:
                self.logger.debug(f"Could not position PDF window (attempt {attempt + 1}): {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
    
    def _close_previous_pdf_file(self):
        """Close previous PDF file in Sumatra PDF before opening new one.
        
        This closes just the file (not the entire viewer) so only one file is open at a time.
        """
        if not hasattr(self, '_pdf_viewer_path') or not self._pdf_viewer_path:
            return
        
        previous_path = self._pdf_viewer_path
        self.logger.info(f"Closing previous PDF file in viewer: {previous_path.name}")
        
        try:
            if sys.platform != 'win32':
                windows_path = self._to_windows_path(previous_path)
                if not windows_path:
                    return
                filename = Path(windows_path).name
            else:
                filename = previous_path.name
            
            # PowerShell script to close specific file in Sumatra PDF
            ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}}
"@

$filename = "{filename}"
$WM_CLOSE = 0x0010

# Find Sumatra PDF process with the specific file
$sumatraProcesses = Get-Process -Name "SumatraPDF" -ErrorAction SilentlyContinue | Where-Object {{
    $_.MainWindowHandle -ne [IntPtr]::Zero
}}

$closed = $false
foreach ($proc in $sumatraProcesses) {{
    $title = $proc.MainWindowTitle
    # Check if this window has the filename in title
    if ($title -like "*$filename*") {{
        $hwnd = $proc.MainWindowHandle
        Write-Host "Closing Sumatra PDF window: $title"
        # Send WM_CLOSE to close just this file/tab
        [Win32]::SendMessage($hwnd, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
        $closed = $true
        Start-Sleep -Milliseconds 300
        break
    }}
}}

# If not found by title, try closing the most recent Sumatra window
if (!$closed -and $sumatraProcesses.Count -gt 0) {{
    $proc = $sumatraProcesses | Sort-Object StartTime -Descending | Select-Object -First 1
    $hwnd = $proc.MainWindowHandle
    Write-Host "Closing most recent Sumatra PDF window: $($proc.MainWindowTitle)"
    [Win32]::SendMessage($hwnd, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
    $closed = $true
}}

if ($closed) {{
    Write-Host "SUCCESS"
}} else {{
    Write-Host "No Sumatra PDF window found to close"
}}
'''
            
            result = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
            
            if result.stdout and "SUCCESS" in result.stdout:
                self.logger.info("Previous PDF file closed successfully")
                # Wait a moment for file to close
                time.sleep(0.3)
            else:
                if result.stdout:
                    self.logger.debug(f"Close previous PDF output: {result.stdout.strip()}")
                    
        except Exception as e:
            self.logger.debug(f"Could not close previous PDF file: {e}")
    
    def _return_focus_to_terminal(self):
        """Return focus to terminal window after PDF viewer opens."""
        self.logger.info("Returning focus to terminal window...")
        try:
            handle_arg = self._terminal_window_handle if self._terminal_window_handle else ""
            ps_script = f'''
param([string]$StoredHandle = "{handle_arg}")

Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);
}}
"@

$hwnd = [IntPtr]::Zero

# Try stored handle first
if ($StoredHandle -and $StoredHandle -ne "") {{
    try {{
        $hwnd = [IntPtr]::new([int64]$StoredHandle)
        Write-Host "Using stored handle for focus: $StoredHandle"
    }} catch {{
        Write-Host "Invalid stored handle, finding window..."
    }}
}}

# If no stored handle, find window
if ($hwnd -eq [IntPtr]::Zero) {{
    # Strategy 1: Find console window by class name
    $hwnd = [Win32]::FindWindow("ConsoleWindowClass", $null)
    if ($hwnd -ne [IntPtr]::Zero) {{
        Write-Host "Found console window by class name"
    }}
}}

# Strategy 2: Find cmd.exe with WSL
if ($hwnd -eq [IntPtr]::Zero) {{
    $cmdProcesses = Get-Process -Name "cmd" -ErrorAction SilentlyContinue | Where-Object {{ 
        $_.MainWindowHandle -ne [IntPtr]::Zero 
    }} | Sort-Object StartTime -Descending
    
    foreach ($proc in $cmdProcesses) {{
        try {{
            $cmdLine = (Get-CimInstance Win32_Process -Filter "ProcessId = $($proc.Id)" -ErrorAction SilentlyContinue).CommandLine
            if ($cmdLine -and $cmdLine -like "*wsl*" -and $cmdLine -notlike "*--status*") {{
                $hwnd = $proc.MainWindowHandle
                Write-Host "Found cmd.exe window (PID: $($proc.Id))"
                break
            }}
        }} catch {{
            continue
        }}
    }}
}}

# Set focus
if ($hwnd -ne [IntPtr]::Zero) {{
    $result = [Win32]::SetForegroundWindow($hwnd)
    if ($result) {{
        Write-Host "SUCCESS"
    }} else {{
        Write-Host "SetForegroundWindow returned false"
    }}
}} else {{
    Write-Host "Could not find terminal window"
}}
'''
            
            result = subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True)
            
            if result.stdout and "SUCCESS" in result.stdout:
                self.logger.info("Focus returned to terminal successfully")
            else:
                if result.stdout:
                    self.logger.debug(f"Focus management output: {result.stdout.strip()}")
                    
        except Exception as e:
            self.logger.debug(f"Could not return focus to terminal: {e}")
    
    def _close_pdf_viewer(self):
        """Close PDF viewer window when processing completes."""
        try:
            if not hasattr(self, '_pdf_viewer_path') or not self._pdf_viewer_path:
                return
            
            pdf_path = self._pdf_viewer_path
            
            if sys.platform != 'win32':
                # For WSL, close Windows viewer using PowerShell
                windows_path = self._to_windows_path(pdf_path)
                if not windows_path:
                    return
                
                filename = Path(windows_path).name
                ps_script = f'''$filename = "{filename}"; $processes = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*$filename*" -or ($_.MainWindowTitle -like "*PDF*" -and ($_.Path -like "*Acrobat*" -or $_.Path -like "*Sumatra*" -or $_.Path -like "*Edge*")) }}; foreach ($proc in $processes) {{ if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {{ $proc.CloseMainWindow(); Start-Sleep -Milliseconds 500; if (!$proc.HasExited) {{ $proc.Kill() }} }} }}'''
                subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            else:
                # Windows: close using PowerShell
                filename = pdf_path.name
                ps_script = f'''$filename = "{filename}"; $processes = Get-Process | Where-Object {{ $_.MainWindowTitle -like "*$filename*" -or ($_.MainWindowTitle -like "*PDF*" -and ($_.Path -like "*Acrobat*" -or $_.Path -like "*Sumatra*" -or $_.Path -like "*Edge*")) }}; foreach ($proc in $processes) {{ if ($proc.MainWindowHandle -ne [IntPtr]::Zero) {{ $proc.CloseMainWindow(); Start-Sleep -Milliseconds 500; if (!$proc.HasExited) {{ $proc.Kill() }} }} }}'''
                subprocess.run(['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
            
            # Clear tracking
            if hasattr(self, '_pdf_viewer_process'):
                delattr(self, '_pdf_viewer_process')
            if hasattr(self, '_pdf_viewer_path'):
                delattr(self, '_pdf_viewer_path')
                
        except Exception as e:
            self.logger.debug(f"Could not close PDF viewer: {e}")
    
    def process_existing_files(self):
        """Process existing PDF files in the watch directory."""
        self.logger.info("Checking for existing PDF files to process...")
        
        existing_files = []
        for file_path in self.watch_dir.glob("*.pdf"):
            if self.should_process(file_path.name):
                existing_files.append(file_path)
        
        if not existing_files:
            self.logger.info("No existing PDF files found to process.")
            return
        
        # Sort by creation time (oldest first = scanning order)
        existing_files.sort(key=lambda p: p.stat().st_ctime)
        
        self.logger.info(f"Found {len(existing_files)} existing PDF file(s) to process (ordered by scan time):")
        for i, file_path in enumerate(existing_files, 1):
            print(f"  {i}. {file_path.name}")
        
        choice = input(f"\nProcess existing files? [Y/n]: ").strip().lower()
        if choice and choice != 'y':
            self.logger.info("Skipping existing files.")
            return
        
        # Process each file
        for file_path in existing_files:
            self.logger.info("")
            self.logger.info("-"*60)
            self.logger.info(f"Processing existing file: {file_path.name}")
            self.logger.info("-"*60)
            
            try:
                self.process_paper(file_path)
            except Exception as e:
                self.logger.error(f"Error processing {file_path.name}: {e}")
                print(f"Error processing {file_path.name}: {e}")
            
            self.logger.info("-"*60)
            self.logger.info("Ready for next scan")
    
    def shutdown(self, signum, frame):
        """Clean shutdown handler.
        
        Uses ServiceManager for centralized service shutdown.
        
        Args:
            signum: Signal number
            frame: Stack frame
        """
        self.logger.info("")
        self.logger.info("="*60)
        self.logger.info("Shutting down daemon...")
        
        if self.observer:
            self.observer.stop()
            self.observer.join()
        
        # Shutdown services using ServiceManager
        if hasattr(self, 'service_manager'):
            self.service_manager.shutdown()
        
        self.remove_pid_file()
        self.logger.info("Daemon stopped")
        self.logger.info("="*60)
        sys.exit(0)

    def compare_metadata_step(self, extracted_metadata: dict, zotero_metadata: dict) -> dict:
        """Step 1: Compare extracted metadata with Zotero item metadata.
        
        Args:
            extracted_metadata: Metadata from PDF extraction
            zotero_metadata: Metadata from existing Zotero item
            
        Returns:
            Final metadata dict to use for Zotero update
        """
        print("\n" + "="*60)
        print(Colors.colorize("📋 METADATA COMPARISON", ColorScheme.PAGE_TITLE))
        print("="*60)
        
        # Display comparison
        self._display_metadata_comparison(extracted_metadata, zotero_metadata)
        
        # Show user choices
        choice = self._get_metadata_comparison_choice()
        
        # Handle choice and return final metadata
        return self._handle_metadata_choice(choice, extracted_metadata, zotero_metadata)
    
    def _display_metadata_comparison(self, extracted: dict, zotero: dict):
        """Display side-by-side metadata comparison."""
        print(Colors.colorize("\nEXTRACTED METADATA:", ColorScheme.PAGE_TITLE))
        print("-" * 30)
        self._display_metadata_universal(extracted)
        
        print(Colors.colorize("\nZOTERO ITEM METADATA:", ColorScheme.PAGE_TITLE))
        print("-" * 30)
        self._display_metadata_universal(zotero)
        
        # Show key differences
        print(Colors.colorize("\n🔍 KEY DIFFERENCES:", ColorScheme.ACTION))
        print("-" * 30)
        
        fields_to_compare = ['title', 'authors', 'year', 'journal', 'doi']
        differences_found = False
        
        for field in fields_to_compare:
            extracted_val = extracted.get(field, '')
            zotero_val = zotero.get(field, '')
            
            if extracted_val != zotero_val:
                differences_found = True
                print(f"{field.title()}:")
                print(f"  Extracted: {extracted_val}")
                print(f"  Zotero:    {zotero_val}")
                print()
        
        if not differences_found:
            print("✅ Metadata appears to match!")
    
    def _get_metadata_comparison_choice(self) -> str:
        """Present metadata comparison menu and get user input."""
        print(Colors.colorize("\nWhat would you like to do?", ColorScheme.ACTION))
        print(Colors.colorize("[1] Use extracted metadata (Replace in Zotero, but keep Zotero tags)", ColorScheme.LIST))
        print(Colors.colorize("[2] Use Zotero metadata as it is (Keep existing Zotero item unchanged)", ColorScheme.LIST))
        print(Colors.colorize("[3] Merge both (show field-by-field comparison)", ColorScheme.LIST))
        print(Colors.colorize("[4] Edit manually", ColorScheme.LIST))
        print(Colors.colorize("[5] 🔍 Search for more metadata online (CrossRef, arXiv, PubMed)", ColorScheme.LIST))
        print(Colors.colorize("[6] 📝 Manual processing later (too similar to decide)", ColorScheme.LIST))
        print(Colors.colorize("[7] 📄 Create new Zotero item from extracted metadata", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Your choice: ").strip()
            if choice in ['1', '2', '3', '4', '5', '6', '7']:
                return choice
            else:
                print("Invalid choice. Please try again.")
    
    def _handle_metadata_choice(self, choice: str, extracted: dict, zotero: dict) -> dict:
        """Handle user's metadata comparison choice."""
        if choice == '1':
            print("✅ Using extracted metadata")
            return extracted
            
        elif choice == '2':
            print("✅ Using Zotero metadata as-is")
            return zotero
            
        elif choice == '3':
            print("🔀 Merging both metadata sources...")
            return self._merge_metadata_sources(extracted, zotero)
            
        elif choice == '4':
            print("✏️ Manual metadata editing...")
            return self.edit_metadata_interactively(extracted)
            
        elif choice == '5':
            # Search online libraries for enhanced metadata
            print("🔍 Searching online libraries for enhanced metadata...")
            return self._search_online_metadata(extracted, zotero)
            
        elif choice == '6':
            print("📝 Moving to manual processing...")
            return None  # Signal to stop processing
            
        elif choice == '7':
            print("📄 Creating new Zotero item...")
            return extracted  # Use extracted metadata for new item
    
    def _merge_metadata_sources(self, extracted: dict, zotero: dict) -> dict:
        """Merge metadata from both sources with field-by-field comparison."""
        print(Colors.colorize("\n🔀 FIELD-BY-FIELD MERGE", ColorScheme.PAGE_TITLE))
        print("=" * 40)
        
        merged = {}
        
        # Get all unique keys from both sources
        all_keys = set(extracted.keys()) | set(zotero.keys())
        
        for key in all_keys:
            extracted_val = extracted.get(key, '')
            zotero_val = zotero.get(key, '')
            
            if extracted_val == zotero_val:
                # Same value - use either
                merged[key] = extracted_val
            elif not extracted_val and zotero_val:
                # Only Zotero has value
                merged[key] = zotero_val
            elif extracted_val and not zotero_val:
                # Only extracted has value
                merged[key] = extracted_val
            else:
                # Different values - ask user
                print(f"\n{key.title()}:")
                print(f"  Extracted: {extracted_val}")
                print(f"  Zotero:    {zotero_val}")
                
                while True:
                    choice = input("Use (e)xtracted, (z)otero, or (c)ustom? ").strip().lower()
                    if choice == 'e':
                        merged[key] = extracted_val
                        break
                    elif choice == 'z':
                        merged[key] = zotero_val
                        break
                    elif choice == 'c':
                        custom = input("Enter custom value: ").strip()
                        merged[key] = custom
                        break
                    else:
                        print("Please enter 'e', 'z', or 'c'")
        
        print("\n✅ Metadata merge complete")
        return merged
    
    def _search_online_metadata(self, extracted: dict, zotero: dict) -> dict:
        """Search online libraries and let user choose how to merge results.
        
        Args:
            extracted: Extracted metadata from PDF
            zotero: Metadata from existing Zotero item
            
        Returns:
            Final metadata dict with online results merged
        """
        # Use Zotero metadata as base for online search (it's more canonical)
        base_metadata = zotero.copy() if zotero else extracted.copy()
        
        # Search online libraries
        print("\n🔍 Searching CrossRef, arXiv, OpenAlex...")
        online_metadata = self.search_online_libraries(base_metadata)
        
        if not online_metadata:
            print("⚠️  No online metadata found. Using Zotero/Extracted metadata.")
            return zotero if zotero else extracted
        
        # Show comparison between all three sources
        print("\n" + "="*60)
        print(Colors.colorize("🌐 ONLINE METADATA FOUND", ColorScheme.PAGE_TITLE))
        print("="*60)
        
        print(Colors.colorize("\nExtracted (from scan):", ColorScheme.ACTION))
        self._display_metadata_universal(extracted)
        
        print(Colors.colorize("\nZotero (existing item):", ColorScheme.ACTION))
        self._display_metadata_universal(zotero)
        
        print(Colors.colorize("\nOnline (CrossRef/arXiv/etc):", ColorScheme.ACTION))
        self._display_metadata_universal(online_metadata)
        
        print(Colors.colorize("\nWhich metadata to use?", ColorScheme.ACTION))
        print(Colors.colorize("[1] Use online metadata", ColorScheme.LIST))
        print(Colors.colorize("[2] Use online + merge with Zotero", ColorScheme.LIST))
        print(Colors.colorize("[3] Use online + merge with extracted", ColorScheme.LIST))
        print(Colors.colorize("[4] Edit manually with online as reference", ColorScheme.LIST))
        print(Colors.colorize("[5] Cancel (use Zotero metadata)", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Your choice [1-5]: ").strip()
            
            if choice == '1':
                print("✅ Using online metadata")
                return online_metadata
            elif choice == '2':
                print("🔀 Merging online + Zotero...")
                return self._merge_metadata_sources(online_metadata, zotero)
            elif choice == '3':
                print("🔀 Merging online + extracted...")
                return self._merge_metadata_sources(online_metadata, extracted)
            elif choice == '4':
                print("✏️ Editing with online as reference...")
                return self.edit_metadata_interactively(
                    online_metadata, 
                    local_metadata=zotero,
                    online_source='online_libraries'
                )
            elif choice == '5':
                print("✅ Using Zotero metadata (cancelled online)")
                return zotero if zotero else extracted
            else:
                print("⚠️  Invalid choice. Please enter 1-5.")
    
    def attach_to_existing_zotero_item(self, pdf_path: Path, zotero_item: dict, metadata: dict) -> bool:
        """Attach scanned PDF to existing Zotero item with 3-step UX.
        
        Args:
            pdf_path: Path to scanned PDF
            zotero_item: Selected Zotero item from local DB
            metadata: Extracted metadata
            
        Returns:
            True if successful
        """
        item_title = zotero_item.get('title', 'Unknown')
        item_key = zotero_item.get('key')
        
        print(Colors.colorize(f"\n📎 PROCESSING: {item_title}", ColorScheme.PAGE_TITLE))
        print("=" * 60)
        
        # STEP 1: Metadata Comparison
        print(Colors.colorize("\n🔄 Step 1: Metadata Comparison", ColorScheme.PAGE_TITLE))
        zotero_metadata = self.convert_zotero_item_to_metadata(zotero_item)
        final_metadata = self.compare_metadata_step(metadata, zotero_metadata)
        
        if final_metadata is None:
            # User chose manual processing
            self.move_to_manual_review(pdf_path)
            return False
        
        # Ensure language is detected from filename and update existing item if missing
        if not final_metadata.get('language'):
            detected_language = self._detect_language_from_filename(pdf_path)
            if detected_language:
                final_metadata['language'] = detected_language
                # Update existing Zotero item if language field is empty
                item_key = zotero_item.get('key')
                if item_key:
                    self.zotero_processor.update_item_field_if_missing(item_key, 'language', detected_language)
        
        # STEP 2: Tags Comparison
        print(Colors.colorize("\n🔄 Step 2: Tags Comparison", ColorScheme.PAGE_TITLE))
        # Get current tags from Zotero item (local search returns tags as strings)
        current_tags_raw = zotero_item.get('tags', [])
        # Convert to dict format for edit_tags_interactively
        current_tags = [{'tag': tag} if isinstance(tag, str) else tag for tag in current_tags_raw]
        
        final_tags = self.edit_tags_interactively(
            current_tags=current_tags,
            local_tags=current_tags  # Use current Zotero tags as local tags
        )
        
        # Save tags to Zotero if they changed
        if item_key:
            # Extract tag names from both lists for comparison
            current_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in current_tags]
            updated_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in final_tags]
            
            # Calculate what to add and remove
            add_tags = [tag for tag in updated_tag_names if tag not in current_tag_names]
            remove_tags = [tag for tag in current_tag_names if tag not in updated_tag_names]
            
            if add_tags or remove_tags:
                print(f"\n💾 Saving tag changes to Zotero...")
                success = self.zotero_processor.update_item_tags(
                    item_key,
                    add_tags=add_tags if add_tags else None,
                    remove_tags=remove_tags if remove_tags else None
                )
                if success:
                    print("✅ Tags updated successfully!")
                else:
                    print("⚠️  Failed to update tags in Zotero")
            else:
                print("ℹ️  No tag changes to save")
        
        # STEP 3: PDF Attachment (from Task 7 specification)
        print(Colors.colorize("\n🔄 Step 3: PDF Attachment", ColorScheme.PAGE_TITLE))
        return self._handle_pdf_attachment_step(pdf_path, zotero_item, final_metadata)
    

    def _handle_pdf_attachment_step(self, pdf_path: Path, zotero_item: dict, metadata: dict) -> bool:
        """Handle PDF attachment step (from Task 7 specification)."""
        item_title = zotero_item.get('title', 'Unknown')
        item_key = zotero_item.get('key')
        
        print(f"\n📎 Attaching to: {item_title}")

        # Offer to skip attaching entirely
        try:
            attach_now = input("Attach this PDF now? [Y/n]: ").strip().lower()
            if attach_now == 'n':
                self.move_to_done(pdf_path)
                print("✅ Skipped attachment and finished")
                return True
        except (KeyboardInterrupt, EOFError):
            self.move_to_done(pdf_path)
            print("✅ Skipped attachment and finished")
            return True
        
        # Check if item already has PDF
        has_pdf = zotero_item.get('hasAttachment', False)
        
        if has_pdf:
            # Enriched comparison before choice
            try:
                existing_info = self._locate_existing_attachment_for_item(item_key, zotero_item, metadata)
                scan_info = self._summarize_pdf_for_compare(pdf_path)
                self._display_enhanced_pdf_comparison(scan_info, existing_info)
            except Exception as e:
                self.logger.debug(f"Enhanced comparison failed: {e}")
            
            print(Colors.colorize("What would you like to do?", ColorScheme.ACTION))
            print(Colors.colorize("[1] Keep both (add scanned version)", ColorScheme.LIST))
            print(Colors.colorize("[2] Replace existing PDF with scan", ColorScheme.LIST))
            print(Colors.colorize("[3] Skip attaching and finish", ColorScheme.LIST))
            print(Colors.colorize("  (z) Cancel (keep original)", ColorScheme.LIST))
            print()
            
            pdf_choice = input("Enter your choice: ").strip().lower()
            
            if pdf_choice == 'z':
                self.move_to_done(pdf_path)
                print("✅ Cancelled - kept original PDF in Zotero")
                return True
            if pdf_choice == '3':
                self.move_to_done(pdf_path)
                print("✅ Skipped attachment and finished")
                return True
            
            # For options 1 and 2, we'll proceed with attachment
            attach_type = "additional" if pdf_choice == '1' else "replacement"
            print(f"📎 Adding as {attach_type} attachment...")
            
            # If replacing, try to delete old attachment in Zotero and move old file to Recycle Bin (Windows)
            if pdf_choice == '2':
                try:
                    if existing_info and existing_info.get('attachment_key'):
                        old_attach_key = existing_info['attachment_key']
                        self.zotero_processor.delete_item(old_attach_key)
                    if existing_info and existing_info.get('windows_path'):
                        self._move_to_recycle_bin_windows(existing_info['windows_path'])
                except Exception as e:
                    self.logger.warning(f"Failed to remove old attachment/file: {e}")
        
        # Before anything: try to reuse an identical file already in publications
        reuse_path = self._find_identical_in_publications(pdf_path)
        if reuse_path:
            print(f"✅ Existing identical file found: {reuse_path.name} — skipping copy/attachment of new scan")
            print("📎 Attaching existing file to Zotero item...")
            try:
                attach_target = self._to_windows_path(reuse_path)
                attach_result = self.zotero_processor.attach_pdf_to_existing(item_key, attach_target)
                if attach_result:
                    print("✅ PDF attached to Zotero item")
                else:
                    print("⚠️  Could not attach PDF to Zotero")
                self.move_to_done(pdf_path)
                print("✅ Processing complete!")
                return True
            except Exception as e:
                self.logger.error(f"Error attaching identical file: {e}")
                print(f"❌ Error attaching identical file: {e}")
                return False

        # Generate filename for publications directory using final metadata
        # (which includes user's choices from metadata comparison step)
        proposed_filename = self.generate_filename(metadata)
        
        print(f"\n📄 Proposed filename: {proposed_filename}")
        confirm = input("Use this filename? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':  # Enter or 'y' = use, anything else = custom
            new_name = input("Enter custom filename (without .pdf): ").strip()
            if new_name:
                proposed_filename = f"{new_name}.pdf"
            else:
                print("❌ Cancelled")
                return False
        
        # Step 1: Preprocess PDF with default options
        original_pdf = pdf_path
        print("\n" + "="*70)
        print("PDF PREPROCESSING")
        print("="*70)
        processed_pdf, preprocessing_state = self._preprocess_pdf_with_options(
            original_pdf,
            border_removal=True,
            split_method='auto',
            trim_leading=True
        )
        
        # Step 2: Preview and allow modification
        final_pdf, final_state = self._preview_and_modify_preprocessing(
            original_pdf,
            processed_pdf,
            preprocessing_state
        )
        
        # Handle user choices from preview menu
        if final_pdf is None:
            if final_state.get('back'):
                # User wants to go back - this should be handled by caller
                print("\n⬅️  Going back...")
                return False
            elif final_state.get('quit'):
                # User wants to quit to manual review
                self.move_to_manual_review(pdf_path)
                print("✅ Moved to manual review")
                return False
            else:
                # Cancelled or error
                print("❌ Processing cancelled")
                return False
        
        # Use final processed PDF for copy/attachment
        pdf_to_copy = final_pdf
        
        # Copy to publications directory with _scanned logic and conflict handling
        base_path = self.publications_dir / proposed_filename
        stem = base_path.stem
        suffix = base_path.suffix
        scanned_path = self.publications_dir / f"{stem}_scan{suffix}"
        final_path = base_path
        
        if base_path.exists():
            # If same size as incoming file, hash-compare and skip if identical
            try:
                if base_path.stat().st_size == pdf_path.stat().st_size and self._are_files_identical(base_path, pdf_path):
                    print(f"✅ Existing base file is identical: {base_path.name} — skipping copy/attachment")
                    self.move_to_done(pdf_path)
                    return True
            except Exception:
                pass
            if not scanned_path.exists():
                print(f"\n⚠️  File already exists: {base_path.name}")
                final_path = scanned_path
                print(f"Using scanned copy name: {final_path.name}")
            else:
                import os, time
                base_stat = os.stat(base_path)
                scanned_stat = os.stat(scanned_path)
                def fmt(stat):
                    return f"{stat.st_size} bytes, {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))}"
                print(f"\n⚠️  Both base and scanned files exist:")
                # If scanned also same size, check for identical content too
                try:
                    if scanned_path.stat().st_size == pdf_path.stat().st_size and self._are_files_identical(scanned_path, pdf_path):
                        print(f"✅ Existing scanned file is identical: {scanned_path.name} — skipping copy/attachment")
                        self.move_to_done(pdf_path)
                        return True
                except Exception:
                    pass
                print(f"  [1] Base   : {base_path.name} ({fmt(base_stat)})")
                print(f"  [2] Scanned: {scanned_path.name} ({fmt(scanned_stat)})")
                print("  [1] Keep both → save as scanned2")
                print("  [2] Replace base with new scanned")
                print("  [3] Replace existing scanned with new scanned")
                print("  (z) Cancel")
                while True:
                    opt = input("Enter your choice: ").strip().lower()
                    if opt == '1':
                        final_path = self.publications_dir / f"{stem}_scanned2{suffix}"
                        break
                    elif opt == '2':
                        final_path = base_path
                        break
                    elif opt == '3':
                        final_path = scanned_path
                        break
                    elif opt == 'z':
                        print("❌ Cancelled - kept originals")
                        return False
                    else:
                        print("⚠️  Invalid choice. Please enter 1-3 or 'z'.")
        
        success, error_msg = self._copy_file_universal(pdf_path, final_path, replace_existing=False)
        copied_ok = success
        if success:
            print(f"✅ Copied to: {final_path}")
        else:
            print(f"❌ File copy failed: {error_msg}")
            print("Proceeding to attach without copying...")
        
        # Attach to Zotero (linked file if possible)
        try:
            print("📖 Attaching to Zotero item...")
            attach_target = self._to_windows_path(final_path) if copied_ok else None
            attach_result = self.zotero_processor.attach_pdf_to_existing(item_key, attach_target)
            
            if attach_result:
                print("✅ PDF attached to Zotero item")
            else:
                if copied_ok:
                    print("⚠️  Could not attach PDF to Zotero (but file copied)")
                else:
                    print("⚠️  Attachment skipped (file copy failed). You can attach manually from:", str(final_path))
            
            # Move original to done/
            self.move_to_done(pdf_path)
            print("✅ Processing complete!")
            return True
        except Exception as e:
            self.logger.error(f"Error: {e}")
            print(f"❌ Error: {e}")
            return False
    
    def move_to_manual_review(self, pdf_path: Path):
        """Move PDF to manual review directory."""
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        
        # Check if source file exists before attempting to move
        if not Path(src).exists():
            self.logger.warning(f"Cannot move to manual review: file no longer exists: {src}")
            return
        
        manual_dir = self.watch_dir / "manual_review"
        manual_dir.mkdir(exist_ok=True)
        
        dest = manual_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to manual review: {dest}")
        print(f"📝 Moved to manual review: {dest}")
        
        # Log to CSV
        if hasattr(self, 'scanned_papers_logger'):
            original_filename = Path(src).name
            if not self.scanned_papers_logger.entry_exists(original_filename):
                self.scanned_papers_logger.log_processing(
                    original_filename=original_filename,
                    status='manual_review'
                )
    
    def select_authors_for_search(self, authors: list) -> list:
        """Let user select which authors to search by and in what order.
        
        Args:
            authors: List of author name strings
            
        Returns:
            List of selected author names in user-specified order
        """
        if not authors:
            return []
        
        # Get author info (paper counts) if validator available
        author_info = []
        for author in authors:
            info = {'name': author, 'paper_count': 0, 'recognized': False, 'recognized_as': None}
            if self.author_validator:
                # Try exact match first
                author_data = self.author_validator.get_author_info(author)
                if author_data:
                    info['paper_count'] = author_data.get('paper_count', 0)
                    info['recognized'] = True
                    info['recognized_as'] = author_data.get('name')
                else:
                    # Try lastname matching (for cases like "Sicakkan" matching "Hakan Gürcan Sicakkan")
                    # Use validate_authors which does lastname matching
                    validation_result = self.author_validator.validate_authors([author])
                    if validation_result['known_authors']:
                        # Found match via lastname
                        known_author = validation_result['known_authors'][0]
                        info['recognized'] = True
                        info['recognized_as'] = known_author['name']
                        # Get paper count for the matched full name
                        full_name_data = self.author_validator.get_author_info(known_author['name'])
                        if full_name_data:
                            info['paper_count'] = full_name_data.get('paper_count', 0)
                    else:
                        # Try OCR correction / alternatives match
                        try:
                            suggestion = self.author_validator.suggest_ocr_correction(author)
                            if suggestion:
                                info['recognized'] = True
                                info['recognized_as'] = suggestion.get('corrected_name')
                                info['paper_count'] = suggestion.get('paper_count', 0)
                        except Exception:
                            pass
            author_info.append(info)
        
        # Display authors with number labels (1, 2, 3, ...)
        author_map = {}
        
        while True:
            # Clear screen output area (reprint the header each time)
            print(Colors.colorize("\n🔍 Search for item in Zotero by selecting authors:", ColorScheme.ACTION))
            
            # Rebuild author_map each iteration (in case authors were edited)
            author_map = {}
            if author_info:
                for i, info in enumerate(author_info):
                    author_num = str(i + 1)  # 1-indexed for display
                    author_map[author_num] = info['name']
                    if info['paper_count'] > 0:
                        papers_str = f"(in Zotero: {info['paper_count']} publications)"
                    elif info['recognized']:
                        if info['recognized_as'] and info['recognized_as'] != info['name']:
                            papers_str = f"(in Zotero as '{info['recognized_as']}', 0 publications found)"
                        else:
                            papers_str = "(in Zotero, 0 publications found)"
                    else:
                        papers_str = "(not in Zotero)"
                    print(f"  [{author_num}] {info['name']} {papers_str}")
            else:
                print("  (No authors - use 'n' to add a new author)")
            
            print(Colors.colorize("\nSelection options:", ColorScheme.ACTION))
            print(Colors.colorize("  '1'   = Search by first author only", ColorScheme.LIST))
            print(Colors.colorize("  '12'  = Search where 1st=1, 2nd=2", ColorScheme.LIST))
            print(Colors.colorize("  '21'  = Search where 1st=2, 2nd=1", ColorScheme.LIST))
            print(Colors.colorize("  'all' = Search by any author (no order)", ColorScheme.LIST))
            print(Colors.colorize("  ''    = Use all authors as extracted", ColorScheme.LIST))
            print(Colors.colorize("  'e'   = Edit an author name", ColorScheme.LIST))
            print(Colors.colorize("  'n'   = Add new author manually", ColorScheme.LIST))
            print(Colors.colorize("  '-1'  = Delete author 1 from list", ColorScheme.LIST))
            print(Colors.colorize("  'z'   = Back to previous step", ColorScheme.LIST))
            print(Colors.colorize("  'r'   = Restart from beginning", ColorScheme.LIST))
            
            # Determine default behavior based on number of authors
            is_single_author = len(author_info) == 1
            if is_single_author:
                prompt_text = "\nYour selection (press Enter for '1', or commands e/n/-1/z/r): "
            else:
                prompt_text = "\nYour selection (numbers like '1', '12', 'all', or commands e/n/-1/z/r): "
            
            selection = input(prompt_text).strip()
            selection_lower = selection.lower()
            
            if selection_lower == 'z':
                return 'BACK'
            elif selection_lower == 'r':
                return 'RESTART'
            elif selection_lower.startswith('-'):
                # Delete an author by number
                num_to_delete = selection_lower[1:]  # Remove the '-' prefix
                if num_to_delete in author_map:
                    author_to_remove = author_map[num_to_delete]
                    # Remove from author_info
                    author_info = [info for info in author_info if info['name'] != author_to_remove]
                    # Remove from authors list
                    authors = [a for a in authors if a != author_to_remove]
                    print(f"✅ Removed: {author_to_remove}")
                    
                    # If no authors left, show message but continue to allow adding new author
                    if not author_info:
                        print("⚠️  No authors remaining - you can add a new author with 'n'")
                else:
                    print(f"⚠️  Invalid author number: '{num_to_delete}'")
                print()  # Blank line before showing list again
                continue
            elif selection_lower == 'e':
                # Edit an author
                if not author_info:
                    print("⚠️  No authors to edit")
                    continue
                print("\nWhich author to edit?")
                max_num = len(author_info)
                edit_choice = input(f"Enter number (1-{max_num}): ").strip()
                if edit_choice in author_map:
                    old_name = author_map[edit_choice]
                    new_name = input(f"Edit '{old_name}' to: ").strip()
                    if new_name:
                        # Update the author in author_info
                        for info in author_info:
                            if info['name'] == old_name:
                                info['name'] = new_name
                                # Re-validate author info
                                if self.author_validator:
                                    author_data = self.author_validator.get_author_info(new_name)
                                    if author_data:
                                        info['paper_count'] = author_data.get('paper_count', 0)
                                print(f"✅ Updated: {old_name} → {new_name}")
                        
                        # Also update the original authors list for consistency
                        for i, orig_author in enumerate(authors):
                            if orig_author == old_name:
                                authors[i] = new_name
                                break
                    else:
                        print("⚠️  No change made")
                else:
                    print(f"⚠️  Invalid selection")
                print()  # Blank line before showing list again
                continue
            elif selection_lower == 'n':
                # Add new author
                new_author = input("\nEnter new author name: ").strip()
                if new_author:
                    info = {'name': new_author, 'paper_count': 0, 'recognized': False, 'recognized_as': None}
                    if self.author_validator:
                        author_data = self.author_validator.get_author_info(new_author)
                        if author_data:
                            info['paper_count'] = author_data.get('paper_count', 0)
                            info['recognized'] = True
                            info['recognized_as'] = author_data.get('name')
                        else:
                            # Try OCR correction / alternatives match
                            try:
                                suggestion = self.author_validator.suggest_ocr_correction(new_author)
                                if suggestion:
                                    info['recognized'] = True
                                    info['recognized_as'] = suggestion.get('corrected_name')
                                    info['paper_count'] = suggestion.get('paper_count', 0)
                            except Exception:
                                pass
                    author_info.append(info)
                    authors.append(new_author)  # Also add to original list for consistency
                    print(f"✅ Added: {new_author}")
                else:
                    print("⚠️  No author name entered")
                print()  # Blank line before showing list again
                continue
            elif not selection or selection_lower == '':
                # If only one author, default to selecting that author (option '1')
                if is_single_author:
                    selected_authors = [author_info[0]['name']]
                    author_str = selected_authors[0]
                    self.logger.info(f"User selected author (default): {author_str}")
                    return selected_authors
                else:
                    # Use all authors - return the updated list from author_info
                    all_authors = [info['name'] for info in author_info]
                    return all_authors
            elif selection_lower == 'all':
                # Return all for unordered search - return updated list
                all_authors = [info['name'] for info in author_info]
                return all_authors
            else:
                # Parse selection (e.g., "12" or "21" for numbered authors)
                selected_authors = []
                
                # Support typing a last name directly (e.g., "Hochschild"): only for length >= 3
                # Check if it's not all digits (could be a name)
                if not selection_lower.isdigit() and len(selection_lower) >= 3:
                    # Try to resolve direct text to an author by last name match
                    direct = selection_lower.strip()
                    for info in author_info:
                        last = info['name'].split(',')[0].split()[-1].lower()
                        if last == direct or direct in last:
                            return [info['name']]
                
                # Parse number sequence (e.g., "12" means author 1 then author 2)
                # First check if the entire selection is a single valid author number
                if selection in author_map:
                    # Single author selection (e.g., "3" for author 3)
                    selected_authors = [author_map[selection]]
                    author_str = selected_authors[0]
                    self.logger.info(f"User selected author: {author_str}")
                    return selected_authors
                
                # Handle multi-digit numbers by parsing character by character (e.g., "12" means author 1 then author 2)
                for char in selection:
                    if char in author_map:
                        selected_authors.append(author_map[char])
                    elif char.isdigit():
                        # Valid digit but not in map (e.g., author number doesn't exist)
                        available = ', '.join(sorted(author_map.keys())) if author_map else 'none'
                        print(f"⚠️  Invalid author number: '{char}' (available: {available})")
                    else:
                        # Non-digit, non-command character
                        print(f"⚠️  Ignoring invalid character: '{char}'")
                
                if selected_authors:
                    author_str = ', '.join(selected_authors)
                    self.logger.info(f"User selected authors in order: {author_str}")
                    return selected_authors
                else:
                    # Show helpful error with available options
                    if author_map:
                        available = ', '.join(sorted(author_map.keys()))
                        print(f"⚠️  No valid selection. Available author numbers: {available}")
                    else:
                        print("⚠️  No authors available. Use 'n' to add a new author.")
                    print()  # Blank line before showing list again
                    continue
    
    def display_and_select_zotero_matches(self, matches: list, search_info: str = "") -> tuple:
        """Display Zotero matches and let user select one or take action.
        
        Args:
            matches: List of Zotero item dicts
            search_info: String describing the search (e.g., "by Kahan in 2012")
            
        Returns:
            Tuple of (action, selected_item):
            - action: 'select', 'search', 'edit', 'create', 'skip', or 'quit'
            - selected_item: The selected item dict (only if action='select')
        """
        if not matches:
            return ('none', None)
        
        print(f"\n✅ Found {len(matches)} potential match(es) {search_info}:")
        print()
        print("These items exist in your Zotero library.")
        print()
        
        # Display items with number labels
        item_map = {}
        max_items = min(len(matches), 99)  # Support up to 99 items
        
        for i, match in enumerate(matches[:max_items]):
            item_num = i + 1
            item_map[str(item_num)] = match
            
            title = match.get('title', 'Unknown title')
            # Truncate long titles
            if len(title) > 70:
                title = title[:67] + "..."
            
            print(f"  [{item_num}] {title}")
            
            # Show authors
            authors = match.get('authors', [])
            if authors:
                author_str = ', '.join(authors[:2])
                if len(authors) > 2:
                    author_str += " et al."
                print(f"      Authors: {author_str}")
            
            # Show year, item type, and PDF status
            year = match.get('year', '?')
            item_type = match.get('item_type') or match.get('itemType', 'unknown')
            has_pdf = match.get('has_attachment', match.get('hasAttachment', False))
            pdf_icon = '✅' if has_pdf else '❌'
            print(f"      Year: {year}  |  Type: {item_type}  |  PDF: {pdf_icon}")
            
            # Show container info (journal/book/conference) based on document type
            container_info = match.get('container_info')
            if container_info and container_info.get('value'):
                label = container_info.get('label', 'Publication')
                value = container_info['value']
                print(f"      {label}: {value}")
            else:
                # Fallback to journal field for backward compatibility
                journal = match.get('journal')
                if journal:
                    print(f"      Journal: {journal}")
            
            # Show DOI if available
            doi = match.get('doi')
            if doi:
                print(f"      DOI: {doi}")
            
            # Show abstract preview if available (first 150 chars)
            abstract = match.get('abstract')
            if abstract:
                abstract_preview = abstract[:150] if len(abstract) > 150 else abstract
                if len(abstract) > 150:
                    abstract_preview += "..."
                print(f"      Abstract: {abstract_preview}")
            
            # Show match quality if available
            if 'order_score' in match and match['order_score'] > 0:
                if match['order_score'] >= 100:
                    print(f"      Match: Perfect order")
                elif match['order_score'] >= 50:
                    print(f"      Match: Good order")
            
            print()
        
        # Show action menu
        print("ACTIONS:")
        print("  [1-N] Select item from list above")
        print("[a]   🔍 Change author/year search parameters")
        print("[b]   🔍 Change all search parameters")
        print("[c]   None of these items - create new")
        print("[d]   ❌ Skip document")
        print("  (z) ⬅️  Back to author selection")
        print("  (r) 🔄 Restart from beginning")
        print("  (q) Quit daemon")
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().lower()
            
            if choice in item_map:
                # User selected an item
                selected_item = item_map[choice]
                self.logger.info(f"User selected item: {selected_item.get('title', 'Unknown')}")
                return ('select', selected_item)
            elif choice == 'a':
                return ('search', None)
            elif choice == 'b':
                return ('edit', None)
            elif choice == 'c':
                return ('create', None)  # "None of these items"
            elif choice == 'd':
                return ('skip', None)
            elif choice == 'z':
                return ('back', None)
            elif choice == 'r':
                return ('restart', None)
            elif choice == 'q':
                return ('quit', None)
            else:
                max_num = len(matches) if len(matches) <= 99 else 99
                print(f"⚠️  Invalid choice. Please select a number 1-{max_num}, letter a-d, or 'z', 'r', 'q'.")
    
    def quick_manual_entry(self, extracted_metadata: dict) -> dict:
        """Allow user to quickly enter missing key fields manually.
        
        User has physical paper in front of them, so can quickly fill gaps.
        
        Args:
            extracted_metadata: Current extracted metadata
            
        Returns:
            Metadata dict with manual entries added/merged
        """
        print("\n" + "="*60)
        print("✏️  QUICK MANUAL ENTRY")
        print("="*60)
        print("Fill in missing fields from the physical paper:")
        print()
        
        # Show current extracted metadata
        print("Current extracted metadata:")
        print("-" * 40)
        print(f"Title: {extracted_metadata.get('title', '(not found)')}")
        authors = extracted_metadata.get('authors', [])
        if authors:
            # Use semicolons to separate author names (since names may contain commas)
            print(f"Authors: {'; '.join(authors)}")
        else:
            print("Authors: (not found)")
        print(f"Year: {extracted_metadata.get('year', '(not found)')}")
        print(f"Journal: {extracted_metadata.get('journal', '(not found)')}")
        print(f"DOI: {extracted_metadata.get('doi', '(not found)')}")
        print()
        
        # Create working copy
        enhanced_metadata = extracted_metadata.copy()
        
        # Prompt for fields (allow override if already present)
        print(Colors.colorize("Enter or correct information (press Enter to keep existing or skip):", ColorScheme.ACTION))
        print()
        
        # Title
        current_title = enhanced_metadata.get('title', '')
        try:
            if current_title:
                title = input(f"Title [{current_title}]: ").strip()
            else:
                title = input("Title: ").strip()
            if title:
                enhanced_metadata['title'] = title
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return None
        
        # Authors
        current_authors = enhanced_metadata.get('authors', [])
        try:
            if current_authors:
                # Use semicolons to separate author names (since names may contain commas)
                print(f"\nCurrent authors: {'; '.join(current_authors)}")
                print(Colors.colorize("Enter authors (one per line, empty line to keep current):", ColorScheme.ACTION))
            else:
                print(Colors.colorize("\nEnter authors (one per line, empty line to finish):", ColorScheme.ACTION))
            authors = []
            while True:
                try:
                    author = input("  Author: ").strip()
                    if not author:
                        break
                    authors.append(author)
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
            if authors:
                enhanced_metadata['authors'] = authors
            # If user skipped and no current authors, leave empty
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return None
        
        # Year
        current_year = enhanced_metadata.get('year', '')
        try:
            if current_year:
                year = input(f"\nYear [{current_year}]: ").strip()
            else:
                year = input("\nYear: ").strip()
            if year:
                enhanced_metadata['year'] = year
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return None
        
        # Journal/Conference/Book Title (context-dependent based on document type)
        doc_type = enhanced_metadata.get('document_type', '').lower()
        
        if doc_type == 'conference_paper':
            # For conference papers, ask for conference name
            current_conference = enhanced_metadata.get('conference', enhanced_metadata.get('journal', ''))
            try:
                if current_conference:
                    conference = input(f"\nConference/Proceedings name [{current_conference}]: ").strip()
                else:
                    conference = input("\nConference/Proceedings name: ").strip()
                if conference:
                    enhanced_metadata['conference'] = conference
                    # Also store in journal field for compatibility (some systems use journal for conference)
                    if not enhanced_metadata.get('journal'):
                        enhanced_metadata['journal'] = conference
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
        elif doc_type == 'book_chapter':
            # For book chapters, ask for book title (not journal)
            current_book_title = enhanced_metadata.get('book_title', '')
            try:
                if current_book_title:
                    book_title = input(f"\nBook title [{current_book_title}]: ").strip()
                else:
                    book_title = input("\nBook title: ").strip()
                if book_title:
                    enhanced_metadata['book_title'] = book_title
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
        elif doc_type == 'report':
            # For reports, ask for organization/publisher or report series
            current_org = enhanced_metadata.get('publisher', enhanced_metadata.get('organization', enhanced_metadata.get('journal', '')))
            try:
                if current_org:
                    organization = input(f"\nOrganization/Publisher/Report Series [{current_org}]: ").strip()
                else:
                    organization = input("\nOrganization/Publisher/Report Series: ").strip()
                if organization:
                    enhanced_metadata['publisher'] = organization
                    # Also store in journal field for compatibility
                    if not enhanced_metadata.get('journal'):
                        enhanced_metadata['journal'] = organization
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
        else:
            # For journal articles and other types, ask for journal
            current_journal = enhanced_metadata.get('journal', '')
            try:
                if current_journal:
                    journal = input(f"\nJournal [{current_journal}]: ").strip()
                else:
                    journal = input("\nJournal: ").strip()
                if journal:
                    enhanced_metadata['journal'] = journal
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
        
        print("\n✅ Manual entry complete")
        print()
        
        return enhanced_metadata
    
    def search_online_libraries(self, metadata: dict, pdf_path: Path = None) -> dict:
        """Search online libraries (CrossRef, arXiv, National Libraries) with metadata.
        
        Shows all results and lets user select one or choose "none".
        
        Args:
            metadata: Combined metadata (extracted + manual)
            pdf_path: Path to PDF file (for language detection)
            
        Returns:
            Online metadata dict if user selected one, None if no results or user chose "none"
        """
        title = metadata.get('title')
        authors = metadata.get('authors', [])
        year = metadata.get('year')
        journal = metadata.get('journal')
        
        if not title and not authors:
            print("⚠️  Need at least title or authors to search online")
            return None
        
        print("\n🌐 Searching online libraries...")
        print(f"   Title: {title or '(none)'}")
        print(f"   Authors: {'; '.join(authors) if authors else '(none)'}")
        print(f"   Year: {year or '(none)'}")
        print(f"   Journal: {journal or '(none)'}")
        print()
        
        all_results = []
        source_name = None
        checked_libraries = []  # Track which libraries were checked
        
        # Use document type to guide API selection
        doc_type = metadata.get('document_type', '').lower()
        
        # Try CrossRef for published academic papers (journal articles, conference papers, reports)
        # Skip for books/chapters, preprints, theses, news articles
        should_try_crossref = (
            title or authors
        ) and doc_type in ['journal_article', 'conference_paper', 'report', 'academic_paper', '']
        
        if should_try_crossref:
            print("🔍 Checking CrossRef...")
            checked_libraries.append("CrossRef")
            try:
                # Access crossref client from metadata processor
                crossref = self.metadata_processor.crossref
                results = crossref.search_by_metadata(
                    title=title,
                    authors=authors,
                    year=year,
                    journal=journal,
                    max_results=5
                )
                
                if results:
                    all_results = results
                    source_name = "CrossRef"
                    print("   ✅ CrossRef: Found results")
                else:
                    print("   ⚠️  CrossRef: No results found")
                    
            except Exception as e:
                self.logger.error(f"CrossRef search error: {e}")
                print(f"   ❌ CrossRef: Error - {e}")
        else:
            print("⏭️  Skipping CrossRef (document type: " + (doc_type if doc_type else "unknown") + ")")
        
        # Try arXiv for preprints and working papers (also try if no CrossRef result and no journal)
        should_try_arxiv = (
            doc_type in ['preprint', 'working_paper'] or
            (not all_results and (not journal or journal == 'arXiv'))
        )
        
        if should_try_arxiv:
            print("🔍 Checking arXiv...")
            checked_libraries.append("arXiv")
            try:
                arxiv = self.metadata_processor.arxiv
                results = arxiv.search_by_metadata(
                    title=title,
                    authors=authors,
                    max_results=5
                )
                
                if results:
                    all_results = results
                    source_name = "arXiv"
                    print("   ✅ arXiv: Found results")
                else:
                    print("   ⚠️  arXiv: No results found")
                    
            except Exception as e:
                self.logger.error(f"arXiv search error: {e}")
                print(f"   ❌ arXiv: Error - {e}")
        else:
            if not all_results:
                print("⏭️  Skipping arXiv (document type: " + (doc_type if doc_type else "unknown") + ")")
        
        # Try book lookup for book chapters (title + editor)
        should_try_book_lookup = doc_type == 'book_chapter'
        
        if should_try_book_lookup:
            # Get or prompt for book title and editor
            book_title = metadata.get('book_title', '')
            editor = metadata.get('editor', '')
            
            # Use chapter authors as editor candidates if editor not provided
            editor_candidates = metadata.get('authors', [])
            
            # Prompt for missing information
            if not book_title:
                try:
                    print("\n📚 Book Chapter Search - Need book information:")
                    book_title = input("Book title (required): ").strip()
                    if not book_title:
                        print("⚠️  Book title required for search, skipping...")
                        book_title = None
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
            
            if book_title and not editor:
                try:
                    print("\nEditor name (often one of the chapter authors):")
                    if editor_candidates:
                        print(f"Chapter authors found: {'; '.join(editor_candidates)}")
                        print(Colors.colorize("[Enter] = Use first chapter author as editor", ColorScheme.LIST))
                        print(Colors.colorize("[Enter name] = Enter editor name manually", ColorScheme.LIST))
                        editor_input = input("Editor: ").strip()
                        if not editor_input and editor_candidates:
                            editor = editor_candidates[0]
                            print(f"✅ Using first chapter author as editor: {editor}")
                        elif editor_input:
                            editor = editor_input
                    else:
                        editor = input("Editor (press Enter to skip): ").strip() or None
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
            
            # Perform book lookup if we have book title
            if book_title:
                print("🔍 Checking Google Books/OpenLibrary...")
                checked_libraries.append("Google Books/OpenLibrary")
                try:
                    print(f"   Searching for book: '{book_title}'" + (f" (editor: {editor})" if editor else " (no editor)"))
                    book_result = self.book_lookup_service.lookup_by_title_and_editor(book_title, editor)
                    
                    if book_result:
                        # Convert book metadata to our format (similar to CrossRef/arXiv results)
                        normalized_book = self._normalize_book_metadata_for_chapter(book_result, metadata)
                        
                        # Store as single result (books don't return multiple like CrossRef)
                        all_results = [normalized_book]
                        source_name = "Google Books/OpenLibrary"
                        print("   ✅ Google Books/OpenLibrary: Found results")
                    else:
                        print("   ⚠️  Google Books/OpenLibrary: No results found")
                        
                        # Try national library search as fallback
                        language = None
                        if pdf_path:
                            language = self._detect_language_from_filename(pdf_path)
                        elif hasattr(self, '_original_scan_path') and self._original_scan_path:
                            language = self._detect_language_from_filename(self._original_scan_path)
                        if language and book_title:
                            print(f"🔍 Checking National Libraries ({language})...")
                            checked_libraries.append(f"National Libraries ({language})")
                            try:
                                country_code = self._language_to_country_code(language)
                                nat_lib_results = self._search_national_library_for_book(
                                    book_title=book_title, 
                                    editor=editor,
                                    language=language,
                                    country_code=country_code
                                )
                                if nat_lib_results:
                                    all_results.extend(nat_lib_results)
                                    source_name = "Google Books/OpenLibrary + National Libraries"
                                    print(f"   ✅ National Libraries: Found {len(nat_lib_results)} result(s)")
                                else:
                                    print(f"   ⚠️  National Libraries: No results found")
                            except Exception as e:
                                self.logger.error(f"National library search error: {e}")
                                print(f"   ❌ National Libraries: Error - {e}")
                except Exception as e:
                    self.logger.error(f"Book lookup error: {e}")
                    print(f"   ❌ Google Books/OpenLibrary: Error - {e}")
        
        # Also try national library search for books and theses
        if doc_type in ['book', 'thesis'] and not all_results:
            title = metadata.get('title', '')
            authors = metadata.get('authors', [])
            language = None
            if pdf_path:
                language = self._detect_language_from_filename(pdf_path)
            elif hasattr(self, '_original_scan_path') and self._original_scan_path:
                language = self._detect_language_from_filename(self._original_scan_path)
            
            if title and language:
                print(f"🔍 Checking National Libraries ({language})...")
                checked_libraries.append(f"National Libraries ({language})")
                try:
                    country_code = self._language_to_country_code(language)
                    nat_lib_results = self._search_national_library_for_book(
                        book_title=title,
                        authors=authors,
                        language=language,
                        country_code=country_code,
                        item_type='books' if doc_type == 'book' else 'papers'
                    )
                    if nat_lib_results:
                        all_results.extend(nat_lib_results)
                        source_name = "National Libraries"
                        print(f"   ✅ National Libraries: Found {len(nat_lib_results)} result(s)")
                    else:
                        print(f"   ⚠️  National Libraries: No results found")
                except Exception as e:
                    self.logger.error(f"National library search error: {e}")
                    print(f"   ❌ National Libraries: Error - {e}")
        
        if not all_results:
            if checked_libraries:
                print(f"\n❌ No matches found in online libraries")
                print(f"   Checked: {', '.join(checked_libraries)}")
            else:
                print(f"\n❌ No matches found in online libraries")
                print(f"   No libraries were checked (document type: {doc_type if doc_type else 'unknown'})")
            print()
            return None
        
        # Display all results and let user choose
        print(f"✅ Found {len(all_results)} result(s) in {source_name}")
        print()
        
        # Show all results
        for idx, result in enumerate(all_results, start=1):
            print(f"[{idx}] {result.get('title', result.get('book_title', 'N/A'))}")
            
            # Show authors (book authors or chapter authors)
            if result.get('authors'):
                print(f"    Authors: {'; '.join(result['authors'][:3])}")
            elif result.get('chapter_authors'):
                print(f"    Chapter Authors: {'; '.join(result['chapter_authors'][:3])}")
            
            # Show editors for books
            if result.get('editors'):
                print(f"    Editors: {'; '.join(result['editors'][:3])}")
            
            if result.get('year'):
                print(f"    Year: {result.get('year')}")
            if result.get('journal'):
                print(f"    Journal: {result.get('journal')}")
            elif result.get('book_title') and result.get('title') != result.get('book_title'):
                # Show book title if different from result title
                print(f"    Book: {result.get('book_title')}")
            if result.get('publisher'):
                print(f"    Publisher: {result.get('publisher')}")
            if result.get('doi'):
                print(f"    DOI: {result.get('doi')}")
            elif result.get('arxiv_id'):
                print(f"    arXiv ID: {result.get('arxiv_id')}")
            elif result.get('isbn'):
                print(f"    ISBN: {result.get('isbn')}")
            print()
        
        # Let user select
        while True:
            try:
                print(f"Select a result (1-{len(all_results)}) or 'n' for none:")
                choice = input("Enter your choice: ").strip().lower()
                
                if choice == 'n' or choice == 'none':
                    print("⏭️  Skipping online library results, will use manual/extracted metadata")
                    return None
                
                try:
                    idx = int(choice)
                    if 1 <= idx <= len(all_results):
                        selected = all_results[idx - 1]
                        print(f"✅ Selected result {idx}")
                        return selected
                    else:
                        print(f"⚠️  Please enter a number between 1 and {len(all_results)}")
                except ValueError:
                    print("⚠️  Please enter a number or 'n' for none")
                    
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return None
    
    def _normalize_book_metadata_for_chapter(self, book_result: dict, chapter_metadata: dict) -> dict:
        """Convert book metadata from lookup service format to our standard format.
        
        Converts from Zotero format (creators list) to our format (authors list).
        Preserves chapter-specific metadata and adds book information.
        
        Args:
            book_result: Book metadata from DetailedISBNLookupService (Zotero format)
            chapter_metadata: Original chapter metadata to preserve
            
        Returns:
            Normalized metadata dict compatible with CrossRef/arXiv result format
        """
        normalized = {}
        
        # Convert creators to authors list (same format as CrossRef/arXiv)
        authors = []
        editors = []
        
        for creator in book_result.get('creators', []):
            first = creator.get('firstName', '')
            last = creator.get('lastName', '')
            creator_type = creator.get('creatorType', 'author')
            
            # Format as "LastName, FirstName" or just "LastName"
            if first and last:
                name = f"{last}, {first}"
            elif last:
                name = last
            else:
                continue  # Skip empty creators
            
            if creator_type == 'editor':
                editors.append(name)
            else:
                authors.append(name)
        
        # Build normalized metadata (similar to CrossRef/arXiv format)
        normalized['title'] = book_result.get('title', '')
        normalized['authors'] = authors
        normalized['editors'] = editors  # Keep editors separate
        
        # Extract year from date
        date = book_result.get('date', '')
        if date:
            year_match = re.search(r'\d{4}', str(date))
            if year_match:
                normalized['year'] = year_match.group()
        
        # Book-specific fields
        normalized['book_title'] = book_result.get('title', '')
        normalized['publisher'] = book_result.get('publisher', '')
        normalized['isbn'] = book_result.get('ISBN', '')
        normalized['document_type'] = 'book_chapter'
        
        # Preserve chapter title and authors from original metadata
        if chapter_metadata.get('title'):
            normalized['chapter_title'] = chapter_metadata['title']
        if chapter_metadata.get('authors'):
            normalized['chapter_authors'] = chapter_metadata['authors']
        
        # Add tags if available
        tags = book_result.get('tags', [])
        if tags:
            normalized['tags'] = [t.get('tag', '') if isinstance(t, dict) else str(t) for t in tags if t]
        
        # Metadata source
        normalized['source'] = 'book_lookup'
        normalized['data_source'] = book_result.get('extra', 'Google Books/OpenLibrary')
        
        return normalized
    
    def _map_zotero_item_type(self, item_type: Optional[str]) -> Optional[str]:
        """Map Zotero item types to internal document_type values."""
        if not item_type:
            return None
        mapping = {
            'book': 'book',
            'bookSection': 'book_chapter',
            'journalArticle': 'journal_article',
            'conferencePaper': 'conference_paper',
            'presentation': 'conference_paper',
            'report': 'report',
            'manuscript': 'report',
            'thesis': 'thesis',
            'dissertation': 'thesis',
            'preprint': 'preprint',
            'magazineArticle': 'news_article',
            'newspaperArticle': 'news_article'
        }
        return mapping.get(item_type)
    
    def _normalize_isbn_lookup_metadata(self, lookup_result: dict, isbn: str) -> dict:
        """Normalize metadata returned from DetailedISBNLookupService.lookup_isbn()."""
        normalized: Dict[str, str] = {}
        
        title = (lookup_result.get('title') or '').strip()
        if title:
            normalized['title'] = title
        
        creators = lookup_result.get('creators', []) or []
        authors: List[str] = []
        editors: List[str] = []
        for creator in creators:
            if not isinstance(creator, dict):
                continue
            first = (creator.get('firstName') or '').strip()
            last = (creator.get('lastName') or '').strip()
            if not first and not last:
                continue
            name = f"{last}, {first}" if first and last else (last or first)
            creator_type = (creator.get('creatorType') or 'author').lower()
            if creator_type == 'editor':
                editors.append(name)
            else:
                authors.append(name)
        if authors:
            normalized['authors'] = authors
        if editors:
            normalized['editors'] = editors
        
        date_value = (
            lookup_result.get('date')
            or lookup_result.get('issued')
            or lookup_result.get('year')
        )
        if date_value:
            year_match = re.search(r'\d{4}', str(date_value))
            if year_match:
                normalized['year'] = year_match.group(0)
        
        normalized['isbn'] = isbn
        
        publisher = (lookup_result.get('publisher') or '').strip()
        if publisher:
            normalized['publisher'] = publisher
        
        num_pages = lookup_result.get('numPages') or lookup_result.get('num_pages')
        if num_pages:
            normalized['num_pages'] = str(num_pages)
        
        language = lookup_result.get('language') or lookup_result.get('languageCode')
        if language:
            normalized['language'] = language
        
        tags = lookup_result.get('tags') or []
        tag_values: List[str] = []
        for tag in tags:
            if isinstance(tag, dict):
                tag_name = tag.get('tag') or tag.get('name') or ''
            else:
                tag_name = str(tag)
            if tag_name:
                tag_values.append(tag_name)
        if tag_values:
            normalized['tags'] = tag_values
        tag_flags = {tag.lower() for tag in tag_values}
        
        abstract = lookup_result.get('abstractNote') or lookup_result.get('abstract')
        if abstract:
            normalized['abstract'] = abstract
        
        place = lookup_result.get('place') or lookup_result.get('placeOfPublication')
        if place:
            normalized['place'] = place
        
        item_type = (lookup_result.get('itemType') or '').replace('_', '').lower()
        type_map = {
            'book': 'book',
            'booksection': 'book_chapter',
            'report': 'report',
            'governmentdocument': 'report',
            'manuscript': 'report'
        }
        document_type = type_map.get(item_type)
        if not document_type and {'report', 'rapport', 'notat'} & tag_flags:
            document_type = 'report'
        if not document_type:
            # Default to book for ISBN lookups unless caller overrides later
            document_type = 'book'
        normalized['document_type'] = document_type
        
        data_source = lookup_result.get('extra') or lookup_result.get('source') or 'ISBN lookup'
        normalized['source'] = data_source
        normalized['data_source'] = data_source
        normalized['extraction_method'] = 'isbn_lookup'
        
        return normalized
    
    def _handle_isbn_lookup_result(self, extraction_result: Dict) -> Dict:
        """Resolve ISBN hits via DetailedISBNLookupService before falling back."""
        if extraction_result.get('method') != 'isbn_found':
            return extraction_result
        
        identifiers = extraction_result.get('identifiers_found', {}) or {}
        raw_isbns = identifiers.get('isbns') or []
        
        validator = getattr(self.metadata_processor, 'validator', None)
        cleaned_isbns: List[str] = []
        for candidate in raw_isbns:
            normalized_candidate = None
            if validator:
                try:
                    is_valid, cleaned, _ = validator.validate_isbn(candidate)
                except Exception:
                    is_valid, cleaned = False, None
                if is_valid and cleaned:
                    normalized_candidate = cleaned
            if not normalized_candidate and candidate:
                normalized_candidate = re.sub(r'[^0-9Xx]', '', candidate)
            if normalized_candidate and len(normalized_candidate) in (10, 13):
                cleaned_isbns.append(normalized_candidate.upper())
        
        # Deduplicate while preserving order
        cleaned_isbns = list(dict.fromkeys(cleaned_isbns))
        if not cleaned_isbns:
            self.logger.info("ISBN detected but failed to normalize value; continuing with fallback workflow.")
            return extraction_result
        
        def isbn10_to_isbn13(isbn10: str) -> Optional[str]:
            if len(isbn10) != 10:
                return None
            core = isbn10[:-1]
            if not core.isdigit():
                return None
            prefix = '978' + core
            total = 0
            for i, digit in enumerate(prefix):
                weight = 1 if i % 2 == 0 else 3
                total += int(digit) * weight
            check = (10 - (total % 10)) % 10
            return prefix + str(check)
        
        def isbn13_to_isbn10(isbn13: str) -> Optional[str]:
            if len(isbn13) != 13 or not isbn13.isdigit():
                return None
            if not isbn13.startswith(('978', '979')):
                return None
            core = isbn13[3:-1]
            if len(core) != 9:
                return None
            total = 0
            for idx, digit in enumerate(core):
                weight = 10 - idx
                total += int(digit) * weight
            remainder = total % 11
            check_val = (11 - remainder) % 11
            if check_val == 10:
                check = 'X'
            else:
                check = str(check_val)
            return core + check
        
        possible_isbns: List[str] = []
        for isbn in cleaned_isbns:
            possible_isbns.append(isbn)
            if len(isbn) == 10:
                converted = isbn10_to_isbn13(isbn.replace('X', '0') if 'X' in isbn[:-1] else isbn)
                if converted:
                    possible_isbns.append(converted)
            elif len(isbn) == 13:
                converted = isbn13_to_isbn10(isbn)
                if converted:
                    possible_isbns.append(converted)
        
        # Deduplicate possible ISBNs while preserving order
        possible_isbns = list(dict.fromkeys([isbn for isbn in possible_isbns if isbn]))
        if not possible_isbns:
            possible_isbns = cleaned_isbns[:]
        
        base_time = extraction_result.get('processing_time_seconds', 0)
        lookup_start = time.time()
        
        for isbn in possible_isbns:
            try:
                step_title = Colors.colorize(f"\n📚 Step 3: Resolving ISBN {isbn} via configured lookup services...", ColorScheme.PAGE_TITLE)
                print(step_title)
                lookup_result = self.book_lookup_service.lookup_isbn(isbn)
                if lookup_result:
                    normalized_metadata = self._normalize_isbn_lookup_metadata(lookup_result, isbn)
                    elapsed = base_time + (time.time() - lookup_start)
                    print("✅ ISBN lookup succeeded")
                    return {
                        'success': True,
                        'metadata': normalized_metadata,
                        'method': 'isbn_lookup',
                        'processing_time_seconds': elapsed,
                        'identifiers_found': extraction_result.get('identifiers_found', {}),
                        'isbn_lookup_source': normalized_metadata.get('data_source')
                    }
            except Exception as exc:
                self.logger.warning(f"ISBN lookup failed for {isbn}: {exc}")
        
        # Try local Zotero database as a fallback
        if self.local_zotero:
            for isbn in possible_isbns:
                try:
                    local_matches = self.local_zotero.search_by_isbn(isbn, limit=1)
                except Exception as exc:
                    self.logger.warning(f"Local Zotero ISBN search failed for {isbn}: {exc}")
                    continue
                
                if local_matches:
                    item = local_matches[0]
                    normalized_item = self._normalize_search_result(item)
                    doc_type = self._map_zotero_item_type(normalized_item.get('item_type'))
                    metadata = {
                        'title': normalized_item.get('title', ''),
                        'authors': normalized_item.get('authors', []),
                        'year': str(normalized_item['year']) if normalized_item.get('year') else None,
                        'document_type': doc_type or 'report',
                        'isbn': isbn,
                        'source': 'zotero_local',
                        'data_source': 'Zotero local database',
                        'extraction_method': 'isbn_lookup_local',
                        'zotero_item_key': normalized_item.get('key')
                    }
                    if normalized_item.get('tags'):
                        metadata['tags'] = normalized_item['tags']
                    if normalized_item.get('journal'):
                        metadata['container'] = normalized_item['journal']
                    if normalized_item.get('abstract'):
                        metadata['abstract'] = normalized_item['abstract']
                    if normalized_item.get('year') is None:
                        metadata.pop('year', None)
                    elapsed = base_time + (time.time() - lookup_start)
                    print("✅ Found existing Zotero item by ISBN")
                    return {
                        'success': True,
                        'metadata': metadata,
                        'method': 'isbn_lookup_local',
                        'processing_time_seconds': elapsed,
                        'identifiers_found': extraction_result.get('identifiers_found', {}),
                        'isbn_lookup_source': 'zotero_local'
                    }
        
        # Try national library lookup using configuration manager
        for isbn in possible_isbns:
            clean_isbn = ISBNMatcher.extract_clean_isbn(isbn)
            if not clean_isbn:
                continue
            prefix2, prefix3 = ISBNMatcher.extract_isbn_prefix(clean_isbn)
            nat_client = None
            if prefix3:
                nat_client = self.national_library_manager.get_client_by_isbn_prefix(prefix3)
            if not nat_client and prefix2:
                nat_client = self.national_library_manager.get_client_by_isbn_prefix(prefix2)
            if not nat_client:
                continue
            
            query_candidates = [f"isbn:{clean_isbn}", clean_isbn]
            if len(clean_isbn) == 13 and clean_isbn.startswith(('978', '979')):
                query_candidates.append(clean_isbn[3:-1])
            
            for query_string in query_candidates:
                try:
                    search_result = nat_client.search(query_string, item_type='books')
                except Exception as exc:
                    self.logger.warning(f"National library ISBN search failed for {query_string}: {exc}")
                    continue
                
                books = search_result.get('books') or search_result.get('papers') or []
                for book in books:
                    normalized_book = self._normalize_national_library_result(book, item_type='books')
                    if not normalized_book:
                        continue
                    metadata = normalized_book
                    metadata['isbn'] = metadata.get('isbn') or clean_isbn
                    metadata['document_type'] = metadata.get('document_type') or 'report'
                    metadata['source'] = search_result.get('source', 'national_library')
                    metadata['data_source'] = metadata.get('source')
                    metadata['extraction_method'] = 'isbn_lookup_national'
                    elapsed = base_time + (time.time() - lookup_start)
                    print("✅ Found metadata via national library ISBN search")
                    return {
                        'success': True,
                        'metadata': metadata,
                        'method': 'isbn_lookup_national',
                        'processing_time_seconds': elapsed,
                        'identifiers_found': extraction_result.get('identifiers_found', {}),
                        'isbn_lookup_source': metadata.get('source')
                    }
        
        print("⚠️  ISBN lookup did not return metadata; continuing with fallback workflow.")
        return extraction_result
    
    def _detect_language_from_filename(self, pdf_path: Path) -> Optional[str]:
        """Detect language from filename prefix (NO_, EN_, DE_, etc.)
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            ISO 639-1 language code (no, en, de, fi, sv, da) for Zotero compatibility
        """
        filename = pdf_path.name.upper()
        # Map filename prefixes to ISO 639-1 language codes (for Zotero compatibility)
        language_map = {
            'NO_': 'no',  # Norwegian
            'EN_': 'en',  # English
            'DE_': 'de',  # German
            'FI_': 'fi',  # Finnish
            'SV_': 'sv',  # Swedish (ISO code is 'sv')
            'DA_': 'da'   # Danish
        }
        
        for prefix, lang_code in language_map.items():
            if filename.startswith(prefix):
                return lang_code
        
        return None
    
    def _language_to_country_code(self, language_code: str) -> Optional[str]:
        """Convert ISO 639-1 language code to country code for national library searches.
        
        Args:
            language_code: ISO 639-1 language code (e.g., 'no', 'sv', 'da')
            
        Returns:
            Country code (e.g., 'NO', 'SE', 'DK') or None
        """
        # Map ISO language codes to country codes for national library API
        lang_to_country = {
            'no': 'NO',  # Norwegian
            'en': 'EN',  # English (no specific country)
            'de': 'DE',  # German
            'fi': 'FI',  # Finnish
            'sv': 'SE',  # Swedish -> Sweden
            'da': 'DK'   # Danish -> Denmark
        }
        return lang_to_country.get(language_code.lower())
    
    def _search_national_library_for_book(self, book_title: str, editor: str = None, 
                                         authors: list = None, language: str = None,
                                         country_code: str = None, item_type: str = 'books') -> list:
        """Search national library for book, book chapter, or thesis metadata.
        
        Args:
            book_title: Title to search for
            editor: Optional editor name (for book chapters)
            authors: Optional list of author names
            language: ISO 639-1 language code (no, en, de, etc.) - used as fallback
            country_code: Country code (NO, SE, DK, etc.) for library selection (preferred)
            item_type: 'books' or 'papers' (theses are usually papers)
            
        Returns:
            List of normalized metadata dicts compatible with CrossRef/arXiv format
        """
        results = []
        
        if not book_title:
            return results
        
        # Build search query from title + editor/author
        query_parts = [book_title]
        if editor:
            query_parts.append(editor)
        elif authors:
            # Use first author if available
            first_author = authors[0] if isinstance(authors[0], str) else ' '.join(authors[0]) if isinstance(authors[0], list) else str(authors[0])
            query_parts.append(first_author)
        
        query = ' '.join(query_parts)
        
        # Get appropriate client
        client = None
        if country_code:
            client = self.national_library_manager.get_client_by_country_code(country_code)
        elif language:
            client = self.national_library_manager.get_client_by_language(language.lower())
        
        if not client:
            self.logger.warning(f"No national library client found for language={language}, country={country_code}")
            return results
        
        try:
            # Search national library
            search_result = client.search(query, item_type=item_type)
            
            # Extract results
            if item_type == 'books':
                items = search_result.get('books', [])
            else:
                items = search_result.get('papers', [])
            
            # Normalize each result
            for item in items[:5]:  # Limit to 5 results
                normalized = self._normalize_national_library_result(item, book_title, editor, item_type)
                if normalized:
                    results.append(normalized)
        
        except Exception as e:
            self.logger.error(f"Error searching national library: {e}")
        
        return results
    
    def _normalize_national_library_result(self, item: dict, expected_title: str = None,
                                          expected_editor: str = None, item_type: str = 'books') -> Optional[dict]:
        """Normalize national library result to standard format.
        
        Args:
            item: Raw result from national library API
            expected_title: Expected title for validation
            expected_editor: Expected editor (for book chapters)
            item_type: 'books' or 'papers'
            
        Returns:
            Normalized metadata dict or None if invalid
        """
        try:
            normalized = {}
            
            # Extract title
            title = item.get('title') or item.get('book_title', '')
            if not title:
                return None  # Skip items without title
            
            normalized['title'] = title
            
            # Extract authors
            authors = item.get('authors', [])
            if isinstance(authors, list) and authors:
                normalized['authors'] = [str(a) for a in authors if a]
            else:
                normalized['authors'] = []
            
            # Extract editors (for book chapters)
            editors = item.get('editors', [])
            if editors:
                normalized['editors'] = [str(e) for e in editors if e]
            
            # Extract publisher
            publisher = item.get('publisher', '')
            if publisher:
                normalized['publisher'] = publisher
            
            # Extract year
            year = item.get('year', '')
            if year:
                normalized['year'] = str(year)
            
            # Extract ISBN
            isbn = item.get('isbn', '')
            if isbn:
                normalized['isbn'] = isbn
            
            # Extract URL
            url = item.get('url', '')
            if url:
                normalized['url'] = url
            
            # For book chapters, preserve chapter title
            if expected_editor:
                normalized['book_title'] = title
                # Chapter title would be in original metadata
            
            if item_type == 'books':
                normalized['document_type'] = 'book'
            elif item_type == 'papers':
                normalized['document_type'] = 'report'
            
            return normalized
        
        except Exception as e:
            self.logger.error(f"Error normalizing national library result: {e}")
            return None
    
    def handle_create_new_item(self, pdf_path: Path, extracted_metadata: dict) -> bool:
        """Handle creating a new Zotero item with online library check.
        
        Workflow:
        1. Quick manual entry (fill gaps from physical paper)
        2. Search online libraries (CrossRef, arXiv)
        3. Metadata selection (use online, use manual, merge, or edit)
        4. Tag selection
        5. Create item and attach PDF
        
        Args:
            pdf_path: Path to scanned PDF
            extracted_metadata: Extracted metadata from PDF
            
        Returns:
            True if successful, False otherwise
        """
        
        print("\n" + "="*60)
        print(Colors.colorize("📄 CREATE NEW ZOTERO ITEM", ColorScheme.PAGE_TITLE))
        print("="*60)
        
        # Step 1: Quick manual entry
        print(Colors.colorize("\n📝 Step 1: Quick Manual Entry", ColorScheme.PAGE_TITLE))
        combined_metadata = self.quick_manual_entry(extracted_metadata)
        if combined_metadata is None:
            # User cancelled during manual entry
            print("❌ Manual entry cancelled")
            return False
        
        # Step 2: Search online libraries (optional)
        print(Colors.colorize("\n🌐 Step 2: Online Library Search (Optional)", ColorScheme.PAGE_TITLE))
        print(Colors.colorize("This step searches CrossRef and arXiv to enrich metadata from online sources.", ColorScheme.ACTION))
        print(Colors.colorize("You can skip this if your manual entry is complete.", ColorScheme.ACTION))
        print()
        
        while True:
            try:
                proceed = input("Search online libraries? [Y/n]: ").strip().lower()
                if not proceed:  # Enter = default yes
                    proceed = 'y'
                if proceed == 'y':
                    online_metadata = self.search_online_libraries(combined_metadata, pdf_path=pdf_path)
                    break
                elif proceed == 'n':
                    online_metadata = None
                    print("⏭️  Skipping online library search")
                    break
                else:
                    print("⚠️  Please enter 'y' or 'n'")
            except (KeyboardInterrupt, EOFError):
                print("\n❌ Cancelled")
                return False
        
        # Step 3: Metadata selection
        print(Colors.colorize("\n📋 Step 3: Metadata Selection", ColorScheme.PAGE_TITLE))
        final_metadata = combined_metadata
        
        if online_metadata:
            # Show comparison and let user choose
            print(Colors.colorize("\nComparing metadata:", ColorScheme.ACTION))
            print("-" * 40)
            print(Colors.colorize("Manual + Extracted:", ColorScheme.ACTION))
            self._display_metadata_universal(combined_metadata)
            print(Colors.colorize("\nOnline Library:", ColorScheme.ACTION))
            self._display_metadata_universal(online_metadata)
            print()
            
            print(Colors.colorize("Which metadata to use?", ColorScheme.ACTION))
            print(Colors.colorize("[1] Use manual/extracted metadata", ColorScheme.LIST))
            print(Colors.colorize("[2] Use online library metadata", ColorScheme.LIST))
            print(Colors.colorize("[3] Merge both (field-by-field)", ColorScheme.LIST))
            print(Colors.colorize("[4] Edit manually", ColorScheme.LIST))
            print()
            
            choice = input("Enter your choice: ").strip()
            
            if choice == '1':
                final_metadata = combined_metadata
            elif choice == '2':
                final_metadata = online_metadata
            elif choice == '3':
                final_metadata = self._merge_metadata_sources(combined_metadata, online_metadata)
            elif choice == '4':
                final_metadata = self.edit_metadata_interactively(combined_metadata, online_metadata, 
                                                                 online_source='online_library')
            else:
                print("Using manual/extracted metadata")
        else:
            # No online results - either none found or user skipped all
            print("\nUsing manual/extracted metadata (no online library metadata selected)")
            confirm = self._input_with_timeout(
                "Proceed with creation? [Y/n]: ",
                default="y"
            )
            if confirm is None:
                print("❌ Cancelled")
                return False
            confirm = confirm.strip().lower()
            if confirm and confirm != 'y':  # Enter or 'y' = proceed, anything else = cancel
                print("❌ Cancelled")
                return False
        
        # Step 4: Tag selection
        print(Colors.colorize("\n🏷️  Step 4: Tag Selection", ColorScheme.PAGE_TITLE))
        
        # Get tags from online metadata if available
        online_tags = []
        if online_metadata and online_metadata.get('tags'):
            online_tags = online_metadata['tags'] if isinstance(online_metadata['tags'], list) else []
        
        final_tags = self.edit_tags_interactively(
            current_tags=final_metadata.get('tags', []),
            online_tags=online_tags
        )
        
        # Add selected tags to metadata
        final_metadata['tags'] = final_tags
        
        # Ensure language is detected from filename and added to metadata if not already present
        if not final_metadata.get('language'):
            detected_language = self._detect_language_from_filename(pdf_path)
            if detected_language:
                final_metadata['language'] = detected_language
        
        # Step 5: Create item and attach PDF
        print(Colors.colorize("\n📖 Step 5: Creating Zotero Item", ColorScheme.PAGE_TITLE))

        # Allow skipping attachment entirely
        try:
            attach_now = input("Attach this PDF now? [Y/n]: ").strip().lower()
        except (KeyboardInterrupt, EOFError):
            attach_now = 'n'

        if attach_now == 'n':
            try:
                print("📖 Creating Zotero item without attachment...")
                zotero_result = self.zotero_processor.add_paper(final_metadata, None)
                if zotero_result['success']:
                    print(f"✅ Created Zotero item (key: {zotero_result.get('item_key', 'N/A')})")
                    print("⚠️  Item created without attachment (skipped by user)")
                    
                    # Offer to add a handwritten note
                    item_key = zotero_result.get('item_key')
                    if item_key:
                        self._prompt_for_note(item_key)
                    
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
                else:
                    error = zotero_result.get('error', 'Unknown error')
                    print(f"❌ Failed to create Zotero item: {error}")
                    return False
            except Exception as e:
                self.logger.error(f"Error creating item: {e}")
                print(f"❌ Error: {e}")
                return False

        # First: try to reuse an identical file already in publications
        reuse_path = self._find_identical_in_publications(pdf_path)
        if reuse_path:
            print(f"✅ Existing identical file found: {reuse_path.name} — skipping copy")
            try:
                windows_path = self._to_windows_path(reuse_path)
                print("📖 Creating Zotero item...")
                zotero_result = self.zotero_processor.add_paper(final_metadata, windows_path)
                if zotero_result['success']:
                    print(f"✅ Created Zotero item (key: {zotero_result.get('item_key', 'N/A')})")
                    action = zotero_result.get('action', 'unknown')
                    if action == 'duplicate_skipped':
                        print("⚠️  Item already exists in Zotero - skipped duplicate")
                    elif action == 'added_with_pdf':
                        print("✅ PDF attached to new Zotero item")
                    elif action == 'added_without_pdf':
                        print("⚠️  Item created without attachment")
                    
                    # Offer to add a handwritten note
                    item_key = zotero_result.get('item_key')
                    if item_key:
                        self._prompt_for_note(item_key)
                    
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
                else:
                    error = zotero_result.get('error', 'Unknown error')
                    print(f"❌ Failed to create Zotero item: {error}")
                    return False
            except Exception as e:
                self.logger.error(f"Error creating item with existing file: {e}")
                print(f"❌ Error: {e}")
                return False

        # Generate filename
        proposed_filename = self.generate_filename(final_metadata)
        if not proposed_filename.endswith('.pdf'):
            proposed_filename += '.pdf'
        
        print(f"\n📄 Proposed filename: {proposed_filename}")
        confirm = input("Use this filename? [Y/n]: ").strip().lower()
        if confirm and confirm != 'y':  # Enter or 'y' = use, anything else = custom
            new_name = input("Enter custom filename (without .pdf): ").strip()
            if new_name:
                proposed_filename = f"{new_name}.pdf"
            else:
                print("❌ Cancelled")
                return False
        
        # Copy to publications directory with _scanned logic and proceed even if copy fails
        base_path = self.publications_dir / proposed_filename
        stem = base_path.stem
        suffix = base_path.suffix
        scanned_path = self.publications_dir / f"{stem}_scanned{suffix}"
        final_path = base_path
        
        if base_path.exists():
            # If same size as incoming file, hash-compare and skip if identical
            try:
                if base_path.stat().st_size == pdf_path.stat().st_size and self._are_files_identical(base_path, pdf_path):
                    print(f"✅ Existing base file is identical: {base_path.name} — skipping copy/creation")
                    self.move_to_done(pdf_path)
                    return True
            except Exception:
                pass
            if not scanned_path.exists():
                print(f"\n⚠️  File already exists: {base_path.name}")
                final_path = scanned_path
                print(f"Using scanned copy name: {final_path.name}")
            else:
                import os, time
                base_stat = os.stat(base_path)
                scanned_stat = os.stat(scanned_path)
                def fmt(stat):
                    return f"{stat.st_size} bytes, {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))}"
                print(f"\n⚠️  Both base and scanned files exist:")
                # If scanned also same size, check for identical content too
                try:
                    if scanned_path.stat().st_size == pdf_path.stat().st_size and self._are_files_identical(scanned_path, pdf_path):
                        print(f"✅ Existing scanned file is identical: {scanned_path.name} — skipping copy/creation")
                        self.move_to_done(pdf_path)
                        return True
                except Exception:
                    pass
                print(f"  [1] Base   : {base_path.name} ({fmt(base_stat)})")
                print(f"  [2] Scanned: {scanned_path.name} ({fmt(scanned_stat)})")
                print("  [1] Keep both → save as scanned2")
                print("  [2] Replace base with new scanned")
                print("  [3] Replace existing scanned with new scanned")
                print("  (z) Cancel")
                while True:
                    opt = input("Enter your choice: ").strip().lower()
                    if opt == '1':
                        final_path = self.publications_dir / f"{stem}_scanned2{suffix}"
                        break
                    elif opt == '2':
                        final_path = base_path
                        break
                    elif opt == '3':
                        final_path = scanned_path
                        break
                    elif opt == 'z':
                        print("❌ Cancelled - kept originals")
                        return False
                    else:
                        print("⚠️  Invalid choice. Please enter 1-3 or 'z'.")
        
        success, error_msg = self._copy_file_universal(pdf_path, final_path, replace_existing=False)
        copied_ok = success
        if success:
            print(f"✅ Copied to: {final_path}")
        else:
            print(f"❌ File copy failed: {error_msg}")
            print("Proceeding to create item without attachment...")
        
        # Ensure language is detected from filename and added to metadata if not already present
        if not final_metadata.get('language'):
            detected_language = self._detect_language_from_filename(pdf_path)
            if detected_language:
                final_metadata['language'] = detected_language
        
        # Create Zotero item (linked file if copy succeeded)
        try:
            print("📖 Creating Zotero item...")
            attach_target = self._to_windows_path(final_path) if copied_ok else None
            zotero_result = self.zotero_processor.add_paper(final_metadata, attach_target)
            
            if zotero_result['success']:
                print(f"✅ Created Zotero item (key: {zotero_result.get('item_key', 'N/A')})")
                action = zotero_result.get('action', 'unknown')
                if action == 'duplicate_skipped':
                    print("⚠️  Item already exists in Zotero - skipped duplicate")
                elif action == 'added_with_pdf':
                    print("✅ PDF attached to new Zotero item")
                elif action == 'added_without_pdf':
                    if copied_ok:
                        print("⚠️  Item created but PDF attachment failed")
                    else:
                        print("⚠️  Item created without attachment (file copy failed)")
                
                    # Offer to add a handwritten note
                    item_key = zotero_result.get('item_key')
                    if item_key:
                        self._prompt_for_note(item_key)
                    
                    # Log to CSV (no preprocessing in handle_create_new_item)
                    if hasattr(self, 'scanned_papers_logger'):
                        original_filename = pdf_path.name
                        if hasattr(self, '_original_scan_path') and self._original_scan_path:
                            original_filename = Path(self._original_scan_path).name
                        self.scanned_papers_logger.log_processing(
                            original_filename=original_filename,
                            status='success',
                            final_filename=final_path.name if 'final_path' in locals() else reuse_path.name,
                            split='no',
                            borders='no',
                            trim='no',
                            zotero_item_code=item_key
                        )
                    
                    # Move original to done/
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
            else:
                error = zotero_result.get('error', 'Unknown error')
                print(f"❌ Failed to create Zotero item: {error}")
                return False
            
        except Exception as e:
            self.logger.error(f"Error creating item: {e}")
            print(f"❌ Error: {e}")
            return False
    
    def _prompt_for_note(self, item_key: str) -> bool:
        """Prompt user to add a handwritten note to a Zotero item.
        
        Args:
            item_key: Zotero item key
            
        Returns:
            True if note was added successfully or skipped, False if cancelled
        """
        print("\n" + "="*70)
        print("WRITE A NOTE")
        print("="*70)
        print("You can add a sentence or two from your notes on the paper folder.")
        print("  (Enter) Skip - don't add a note")
        print("  (a) Add a note")
        print("  (z) Cancel and go back")
        print("="*70)
        note_choice = self._input_with_timeout(
            "\nAdd a note? [Enter/a/z]: ",
            default=""
        )
        if note_choice is None:
            print("⬅️  Cancelling note addition")
            return False
        note_choice = note_choice.strip().lower()
        
        if note_choice == 'z':
            print("⬅️  Cancelling note addition")
            return False
        elif note_choice == 'a':
            print("\n📝 Enter your note (press Enter on a blank line when finished):")
            note_lines = []
            while True:
                try:
                    line = input()
                    if not line.strip():
                        break
                    note_lines.append(line)
                except (KeyboardInterrupt, EOFError):
                    break
            
            if note_lines:
                note_text = '\n'.join(note_lines)
                print(f"\n💾 Adding note to Zotero item...")
                if self.zotero_processor.add_note_to_item(item_key, note_text):
                    print("✅ Note added successfully!")
                    return True
                else:
                    print("⚠️  Failed to add note, continuing...")
                    return True
            else:
                print("ℹ️  No note text entered, skipping note...")
                return True
        else:
            print("ℹ️  Skipping note...")
            return True
    
    def handle_item_selected(self, pdf_path: Path, metadata: dict, selected_item: dict):
        """Handle user selecting a Zotero item.
        
        Shows metadata review, then PDF comparison (if existing), proposed actions, and asks for confirmation.
        Uses page-based navigation system for clean flow management.
        
        Args:
            pdf_path: Path to scanned PDF
            metadata: Extracted metadata
            selected_item: The Zotero item dict that was selected
        """
        from shared_tools.ui.navigation import NavigationEngine, ItemSelectedContext
        from handle_item_selected_pages import create_all_pages
        
        title = selected_item.get('title', 'Unknown')
        has_pdf = selected_item.get('has_attachment', selected_item.get('hasAttachment', False))
        
        print(f"\n✅ Selected: {title}\n")
        
        # Show detailed metadata and give option to review/edit before proceeding
        self._display_zotero_item_details(selected_item)
        
        # Create context
        context = ItemSelectedContext(
            pdf_path=pdf_path,
            metadata=metadata,
            selected_item=selected_item,
            item_key=selected_item.get('key') or selected_item.get('item_key'),
            has_pdf=has_pdf
        )
        
        # Add daemon instance to context dict for page handlers
        ctx_dict = context.to_dict()
        ctx_dict['daemon'] = self
        
        # Create pages and navigation engine
        pages = create_all_pages(self)
        engine = NavigationEngine(pages, timeout_seconds=self.prompt_timeout)
        
        # Run page flow starting from REVIEW & PROCEED
        result = engine.run_page_flow('review_and_proceed', ctx_dict)
        
        # Handle navigation results
        if result.type == result.Type.RETURN_TO_CALLER:
            return
        elif result.type == result.Type.QUIT_SCAN:
            if result.move_to_manual:
                self.move_to_manual_review(pdf_path)
            return
        elif result.type == result.Type.PROCESS_PDF:
            # Process the PDF
            target_filename = ctx_dict.get('target_filename')
            if not target_filename:
                # Fallback: generate filename if not set
                from shared_tools.utils.filename_generator import FilenameGenerator
                zotero_authors = selected_item.get('authors', [])
                zotero_title = selected_item.get('title', '')
                zotero_year = selected_item.get('year', selected_item.get('date', ''))
                zotero_item_type = selected_item.get('itemType', 'journalArticle')
                merged_metadata = {
                    'title': zotero_title,
                    'authors': zotero_authors,
                    'year': zotero_year if zotero_year else 'Unknown',
                    'document_type': zotero_item_type
                }
                filename_gen = FilenameGenerator()
                target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
            
            # Validate state before processing
            if not metadata.get('_year_confirmed'):
                self.logger.warning("Processing item without confirmed year - metadata may be incomplete")
            if not metadata.get('authors'):
                self.logger.warning("Processing item without selected authors - metadata may be incomplete")
            
            # Check if we have a preprocessed PDF from PDF preview
            final_processed_pdf = ctx_dict.get('final_processed_pdf')
            preprocessing_state_from_context = ctx_dict.get('preprocessing_state', {})
            # Use merged_metadata if available (from proceed_after_edit), otherwise use metadata from context or original
            metadata_to_use = ctx_dict.get('merged_metadata') or ctx_dict.get('metadata', metadata)
            # Use the preprocessed PDF if available, otherwise will do preprocessing
            self._process_selected_item(pdf_path, selected_item, target_filename, metadata_to_use, 
                                      preprocessed_pdf=final_processed_pdf, 
                                      preprocessing_state=preprocessing_state_from_context)
            return
        
        # Should not reach here
        print("⚠️  Unexpected navigation result")
        return
    
    def _process_selected_item(self, pdf_path: Path, zotero_item: dict, target_filename: str, metadata: dict = None, preprocessed_pdf: Path = None, preprocessing_state: dict = None):
        """Process selected Zotero item: copy PDF and attach.
        
        Steps:
        1. Check if PDF should be split for Zotero attachment (or use preprocessed PDF)
        2. Copy PDF to publications directory (via PowerShell)
        3. Attach as linked file in Zotero
        4. Update URL field if missing and available
        5. Move scan to done/
        
        Args:
            pdf_path: Path to scanned PDF
            zotero_item: Selected Zotero item dict
            target_filename: Generated filename for publications dir
            metadata: Extracted metadata (optional, may contain URL to add)
            preprocessed_pdf: Optional preprocessed PDF (if provided, skips preprocessing step)
            preprocessing_state: Optional preprocessing state dict (required if preprocessed_pdf is provided)
        """
        item_key = zotero_item.get('key') or zotero_item.get('item_key')
        if not item_key:
            print("❌ No item key found")
            self.move_to_failed(pdf_path)
            return
        
        print("\n📋 Executing actions...")
        
        # Initialize final_state early (will be populated from context or preprocessing)
        final_state = {}
        
        # Step 1: Determine which PDF to use (original or page-offset temp or preprocessed)
        if preprocessed_pdf and preprocessed_pdf.exists():
            # Use preprocessed PDF from navigation flow (skip preprocessing)
            pdf_to_copy = preprocessed_pdf
            self.logger.info(f"Using preprocessed PDF from navigation: {pdf_to_copy.name}")
            
            # Create final_state from preprocessing_state passed from context
            if preprocessing_state:
                final_state = {
                    'split_method': preprocessing_state.get('split_method', 'none'),
                    'border_removal': preprocessing_state.get('border_removal', False),
                    'trim_leading': preprocessing_state.get('trim_leading', False),
                    'split_attempted': preprocessing_state.get('split_attempted', False)
                }
            else:
                # Fallback: initialize with defaults if preprocessing_state not provided
                final_state = {
                    'split_method': 'none',
                    'border_removal': False,
                    'trim_leading': False,
                    'split_attempted': False
                }
        else:
            # Determine which PDF to use (original or page-offset temp)
            # Check if there's a temporary PDF created from page offset
            pdf_to_copy = getattr(self, '_temp_pdf_path', None)
            # Determine original PDF (before any preprocessing)
            original_pdf = pdf_path
            if pdf_to_copy is None or not pdf_to_copy.exists():
                # No temp PDF, use original
                pdf_to_copy = pdf_path
            else:
                self.logger.info(f"Using temporary PDF from page offset: {pdf_to_copy.name}")
                # Keep original for preprocessing, but use pdf_to_copy as starting point if from offset
                # For preprocessing preview workflow, we want to work from original after page offset
                original_pdf = pdf_to_copy
            
            # Step 1: Preprocess PDF with default options
            print("\n" + "="*70)
            print("PDF PREPROCESSING")
            print("="*70)
            processed_pdf, preprocessing_state = self._preprocess_pdf_with_options(
                original_pdf,
                border_removal=True,
                split_method='auto',
                trim_leading=True
            )
            
            # Step 2: Preview and allow modification
            final_pdf, final_state = self._preview_and_modify_preprocessing(
                original_pdf,
                processed_pdf,
                preprocessing_state
            )
            
            # Handle user choices
            if final_pdf is None:
                if final_state.get('back'):
                    # User wants to go back to metadata
                    print("\n⬅️  Going back to metadata...")
                    return
                elif final_state.get('quit'):
                    # User wants to quit to manual review
                    self.move_to_manual_review(pdf_path)
                    print("✅ Moved to manual review")
                    return
                else:
                    # Cancelled or error
                    print("❌ Processing cancelled")
                    return
            
            # Use final processed PDF
            pdf_to_copy = final_pdf
        name_lower = pdf_to_copy.name.lower()
        
        # Step 2: Check if target file exists and show comparison/choice if needed
        target_path_full = self.publications_dir / target_filename
        replace_existing = False
        
        # Try to check if file exists, but handle case where cloud drive isn't accessible from WSL
        target_exists = False
        try:
            target_exists = target_path_full.exists()
        except OSError as e:
            # Cloud drives (like Google Drive) may not be accessible from WSL
            # PowerShell will handle the existence check during copy
            self.logger.debug(f"Could not check if target exists from WSL (cloud drive?): {e}")
            target_exists = False
        
        if target_exists:
            # File exists - show that Zotero item already has PDF and prompt for filename edit
            print("\n" + "="*70)
            print("⚠️  FILE CONFLICT")
            print("="*70)
            print("⚠️  This Zotero item already has a PDF attached")
            print()
            
            # Show PDF comparison
            try:
                existing_info = self._summarize_pdf_for_compare(target_path_full)
                scan_info = self._summarize_pdf_for_compare(pdf_to_copy)
                self._display_enhanced_pdf_comparison(scan_info, existing_info)
            except Exception as e:
                self.logger.debug(f"Enhanced comparison failed: {e}")
                # Fallback to basic info
                existing_info = {'filename': target_filename, 'path': target_path_full}
                scan_info = {'filename': pdf_to_copy.name}
            
            # Prepare metadata for filename editing
            zotero_authors = zotero_item.get('authors', [])
            zotero_title = zotero_item.get('title', '')
            zotero_year = zotero_item.get('year', zotero_item.get('date', ''))
            zotero_item_type = zotero_item.get('itemType', 'journalArticle')
            
            zotero_metadata = {
                'title': zotero_title,
                'authors': zotero_authors,
                'year': zotero_year if zotero_year else 'Unknown',
                'document_type': zotero_item_type
            }
            
            # Extract metadata from context if available
            extracted_metadata = metadata if metadata else {}
            
            # Loop until unique filename is found
            while True:
                # Prompt for filename editing
                new_filename = self._prompt_filename_edit(
                    target_filename=target_filename,
                    zotero_metadata=zotero_metadata,
                    extracted_metadata=extracted_metadata
                )
                
                # Check if new filename exists
                new_path = self.publications_dir / new_filename
                try:
                    if not new_path.exists():
                        # Unique filename found
                        target_filename = new_filename
                        target_path_full = new_path
                        break
                    else:
                        # Still exists, ask user what to do
                        print()
                        print(f"⚠️  File '{new_filename}' already exists")
                        print("What would you like to do?")
                        print("[1] Replace existing PDF with scan")
                        print("[2] Edit filename again")
                        print("[3] Skip attaching and finish")
                        print("  (z) Cancel (keep original)")
                        print()
                        
                        conflict_choice = input("Enter your choice: ").strip().lower()
                        
                        if conflict_choice == 'z':
                            self.move_to_done(pdf_path)
                            print("✅ Cancelled - kept original PDF")
                            return
                        elif conflict_choice == '3':
                            self.move_to_done(pdf_path)
                            print("✅ Skipped attachment and finished")
                            return
                        elif conflict_choice == '1':
                            # Replace existing
                            target_filename = new_filename
                            target_path_full = new_path
                            replace_existing = True
                            break
                        elif conflict_choice == '2':
                            # Edit again - continue loop
                            target_filename = new_filename
                            continue
                        else:
                            # Invalid choice, default to replace
                            target_filename = new_filename
                            target_path_full = new_path
                            replace_existing = True
                            break
                except OSError as e:
                    # Cloud drive may not be accessible from WSL
                    self.logger.debug(f"Could not check if new filename exists (cloud drive?): {e}")
                    # Assume it's unique and proceed
                    target_filename = new_filename
                    target_path_full = new_path
                    break
        
        # Step 2: Verify and log target filename before copy
        # Defensive check: ensure target_filename doesn't contain temp file patterns
        temp_file_patterns = ['_no_borders', '_split', '_from_page', '_no_page1']
        if target_filename and any(pattern in target_filename for pattern in temp_file_patterns):
            self.logger.warning(f"Target filename contains temp file pattern: {target_filename}")
            # ALWAYS regenerate filename from Zotero item (not from old metadata)
            from shared_tools.utils.filename_generator import FilenameGenerator
            filename_gen = FilenameGenerator()
            zotero_authors = zotero_item.get('authors', [])
            zotero_title = zotero_item.get('title', '')
            zotero_year = zotero_item.get('year', zotero_item.get('date', ''))
            zotero_item_type = zotero_item.get('itemType', 'journalArticle')
            self.logger.info(f"Regenerating filename from Zotero item - Title: '{zotero_title}', Authors: {zotero_authors}, Year: {zotero_year}")
            merged_metadata = {
                'title': zotero_title,
                'authors': zotero_authors,
                'year': zotero_year if zotero_year else 'Unknown',
                'document_type': zotero_item_type
            }
            target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
            self.logger.info(f"Regenerated target filename: {target_filename}")
        
        # Log the filename being used for copy
        # Verify we're using Zotero item data, not old metadata
        zotero_title = zotero_item.get('title', '')
        zotero_authors = zotero_item.get('authors', [])
        self.logger.info(f"Copying PDF to publications with filename: {target_filename}")
        self.logger.debug(f"Source PDF: {pdf_to_copy.name}, Target filename: {target_filename}")
        self.logger.debug(f"Zotero item title: '{zotero_title}', authors: {zotero_authors}")
        
        # Step 2: Copy to publications directory via PowerShell
        print(f"2/4 Copying to publications directory...")
        success, target_path, error = self._copy_to_publications_via_windows(pdf_to_copy, target_filename, replace_existing=replace_existing)
        
        if not success:
            print(f"❌ Copy failed: {error}")
            print("📝 Moving to manual review")
            self.move_to_manual_review(pdf_path)
            return
        
        print(f"✅ Copied")
        
        # Step 3: Attach to Zotero as linked file
        print(f"3/4 Attaching to Zotero item...")
        self.logger.debug(f"Attaching {target_path.name} to Zotero item {item_key}")
        
        try:
            result = self.zotero_processor.attach_pdf_to_existing(item_key, target_path)
            
            if not result:
                print("❌ Zotero attachment failed")
                print(f"⚠️  PDF copied but not attached: {target_path}")
                print("📝 Moving scan to manual review")
                self.move_to_manual_review(pdf_path)
                return
            
            print("✅ Attached to Zotero")
            
            # Update URL field if metadata has URL and item doesn't have it yet
            if metadata and metadata.get('url'):
                url = metadata['url']
                print(f"3b/4 Updating URL field if missing...")
                url_updated = self.zotero_processor.update_item_field_if_missing(item_key, 'url', url)
                if url_updated:
                    print(f"✅ URL updated: {url}")
                else:
                    print("ℹ️  URL already exists or update failed")
            
            # Update tags/keywords from metadata if available
            if metadata:
                tags_to_add = []
                
                # Extract tags from metadata (can be list of strings or list of dicts)
                if metadata.get('tags'):
                    for tag in metadata['tags']:
                        if isinstance(tag, dict):
                            tag_name = tag.get('tag', '')
                        else:
                            tag_name = str(tag)
                        if tag_name and tag_name.strip():
                            tags_to_add.append(tag_name.strip())
                
                # Extract keywords from metadata (GROBID or API)
                if metadata.get('keywords'):
                    for keyword in metadata['keywords']:
                        keyword_str = str(keyword) if not isinstance(keyword, dict) else keyword.get('tag', '')
                        if keyword_str and keyword_str.strip():
                            keyword_clean = keyword_str.strip()
                            # Avoid duplicates
                            if keyword_clean not in tags_to_add:
                                tags_to_add.append(keyword_clean)
                
                # Add tags to Zotero item if we have any
                if tags_to_add:
                    print(f"3c/4 Adding {len(tags_to_add)} tag(s) from metadata...")
                    tags_updated = self.zotero_processor.update_item_tags(item_key, add_tags=tags_to_add)
                    if tags_updated:
                        print(f"✅ Tags added: {', '.join(tags_to_add[:5])}{'...' if len(tags_to_add) > 5 else ''}")
                    else:
                        print("ℹ️  Tags update failed or tags already exist")
            
        except Exception as e:
            print(f"❌ Zotero attachment error: {e}")
            print(f"⚠️  PDF copied but not attached: {target_path}")
            print("📝 Moving scan to manual review")
            self.logger.error(f"Zotero attachment error: {e}")
            self.move_to_manual_review(pdf_path)
            return
        
        # Step 4: Move scan to done/ and log processing
        print(f"4/4 Moving scan to done/...")
        
        # Get original filename for logging
        original_filename = pdf_path.name
        if hasattr(self, '_original_scan_path') and self._original_scan_path:
            original_filename = Path(self._original_scan_path).name
        
        # Extract preprocessing state information
        split_status = 'no'
        if final_state.get('split_method', 'none') != 'none':
            split_status = 'yes'
        elif final_state.get('split_method') == 'failed':
            split_status = 'failed'
        
        borders_status = 'yes' if final_state.get('border_removal', False) else 'no'
        trim_status = 'yes' if final_state.get('trim_leading', False) else 'no'
        
        # Log to CSV
        self.scanned_papers_logger.log_processing(
            original_filename=original_filename,
            status='success',
            final_filename=target_filename,
            split=split_status,
            borders=borders_status,
            trim=trim_status,
            zotero_item_code=item_key
        )
        
        self.move_to_done(pdf_path)
        print(f"✅ Moved to done/")
        
        print("\n🎉 Processing complete!")
        print(f"   📁 Publications: {target_path.name}")
        print(f"   📚 Zotero: Linked file attached")
        print(f"   ✅ Scan: Moved to done/")
        
    def _display_zotero_item_details(self, zotero_item: dict):
        """Display detailed information about a Zotero item for review.
        
        Also ensures 'authors' field is populated for later use.
        
        Args:
            zotero_item: Zotero item dict
        """
        # Extract authors if not already in 'authors' field
        authors = zotero_item.get('authors', [])
        if not authors and 'creators' in zotero_item:
            authors = []
            for creator in zotero_item['creators']:
                # Include both 'author' and 'presenter' for presentations
                creator_type = creator.get('creatorType', '').lower()
                if creator_type in ('author', 'presenter'):
                    first = creator.get('firstName', '')
                    last = creator.get('lastName', '')
                    if first and last:
                        authors.append(f"{first} {last}")
                    elif last:
                        authors.append(last)
            # Store in zotero_item for later use
            zotero_item['authors'] = authors
        
        print("\n" + "="*70)
        print("📚 ZOTERO ITEM DETAILS:")
        print("="*70)
        
        # Title
        title = zotero_item.get('title', 'Unknown')
        print(f"Title: {title}")
        
        # Journal/Publication
        container_info = zotero_item.get('container_info')
        if container_info and container_info.get('value'):
            print(f"Journal: {container_info['value']}")
        elif zotero_item.get('journal'):
            print(f"Journal: {zotero_item['journal']}")
        
        # Authors
        if authors:
            author_str = '; '.join(authors)
            print(f"Authors: {author_str}")
        
        # Year
        year = zotero_item.get('year', zotero_item.get('date', 'Unknown'))
        print(f"Year: {year}")
        
        # DOI
        doi = zotero_item.get('doi')
        if doi:
            print(f"DOI: {doi}")
        
        # Abstract
        abstract = zotero_item.get('abstract')
        if abstract:
            abstract_preview = abstract[:150] if len(abstract) > 150 else abstract
            if len(abstract) > 150:
                abstract_preview += "..."
            print(f"Abstract: {abstract_preview}")
        
        # Tags (detailed display)
        tags = zotero_item.get('tags', [])
        if tags:
            print(f"\nTags ({len(tags)}):")
            # Show tags in multiple columns if many
            tag_lines = []
            for i in range(0, len(tags), 3):
                chunk = tags[i:i+3]
                tag_lines.append("  " + " | ".join(chunk))
            print("\n".join(tag_lines))
        else:
            print("\nTags: (none)")
        
        print("="*70)
    
    def _get_existing_pdf_info(self, zotero_item: dict) -> dict:
        """Get information about existing PDF attachment in Zotero item.
        
        Args:
            zotero_item: Zotero item dict
            
        Returns:
            Dict with existing PDF info (path, size, date) or empty dict if not accessible
        """
        # Try to find existing PDF in publications directory
        # We can infer the filename from metadata
        try:
            # Generate what the non-scan filename would be
            filename_gen = FilenameGenerator()
            # Build metadata from Zotero item
            item_metadata = {
                'title': zotero_item.get('title', ''),
                'authors': zotero_item.get('authors', []),
                'year': zotero_item.get('year', '')
            }
            
            # Generate filename without _scan suffix
            expected_filename = filename_gen.generate(item_metadata, is_scan=False) + '.pdf'
            expected_path = self.publications_dir / expected_filename
            
            if expected_path.exists():
                stat = expected_path.stat()
                return {
                    'path': expected_path,
                    'size_mb': stat.st_size / 1024 / 1024,
                    'modified': stat.st_mtime,
                    'filename': expected_filename
                }
            
            # Fuzzy match: Look for similar filenames
            # Extract author and year as search keys
            author = item_metadata.get('authors', [''])
            author_lastname = author[0].split(',')[0] if author else ''
            year = item_metadata.get('year', '')
            
            if author_lastname and year:
                # Look for files starting with Author_Year using cached list
                search_pattern = f"{author_lastname}_{year}"
                cached_files = self._get_publications_cache()
                
                # Filter cached filenames that match the pattern
                matching_filenames = [f for f in cached_files if f.startswith(search_pattern)]
                
                if matching_filenames:
                    # Return the first match (most likely the same file)
                    found_filename = matching_filenames[0]
                    found_path = self.publications_dir / found_filename
                    
                    # Verify file still exists (cache might be slightly stale)
                    if found_path.exists():
                        stat = found_path.stat()
                        return {
                            'path': found_path,
                            'size_mb': stat.st_size / 1024 / 1024,
                            'modified': stat.st_mtime,
                            'filename': found_filename,
                            'fuzzy_match': True  # Flag this as fuzzy match
                        }
        except Exception as e:
            self.logger.debug(f"Could not locate existing PDF: {e}")
        
        return {}
    
    def _refresh_publications_cache(self):
        """Refresh the publications directory cache by listing all PDF files.
        
        This is called on startup and periodically while daemon is idle to keep
        the cache fresh for fast fuzzy matching.
        """
        try:
            # List all PDF files in publications directory
            pdf_files = []
            if self.publications_dir.exists():
                # Use glob to get all PDFs
                pdf_paths = list(self.publications_dir.glob("*.pdf"))
                pdf_files = [p.name for p in pdf_paths]
            
            # Save to cache file
            cache_data = {
                'pdf_files': pdf_files,
                'timestamp': time.time(),
                'count': len(pdf_files)
            }
            
            with open(self.publications_cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2)
            
            self.logger.debug(f"Refreshed publications cache: {len(pdf_files)} PDFs")
        except Exception as e:
            self.logger.warning(f"Failed to refresh publications cache: {e}")
    
    def _get_publications_cache(self) -> list:
        """Get cached list of PDF filenames from publications directory.
        
        Returns:
            List of PDF filenames, or empty list if cache unavailable
        """
        try:
            if not self.publications_cache_file.exists():
                return []
            
            with open(self.publications_cache_file, 'r', encoding='utf-8') as f:
                cache_data = json.load(f)
                return cache_data.get('pdf_files', [])
        except Exception as e:
            self.logger.debug(f"Could not load publications cache: {e}")
            return []
    
    def _display_pdf_comparison(self, scan_path: Path, scan_size_mb: float, existing_pdf_info: dict):
        """Display comparison between scan and existing PDF.
        
        Args:
            scan_path: Path to scanned PDF
            scan_size_mb: Size of scan in MB
            existing_pdf_info: Dict with existing PDF info (from _get_existing_pdf_info)
        """
        print()
        print("="*70)
        print("📊 PDF COMPARISON:")
        print("="*70)
        
        if existing_pdf_info:
            existing_size_mb = existing_pdf_info['size_mb']
            existing_filename = existing_pdf_info['filename']
            is_fuzzy_match = existing_pdf_info.get('fuzzy_match', False)
            
            match_type = "🔍 Found (similar name)" if is_fuzzy_match else "✅ Found (exact match)"
            print(f"{match_type}: {existing_filename}")
            print(f"  Size: {existing_size_mb:.1f} MB")
            if is_fuzzy_match:
                print(f"  Note: Using closest match by author/year")
            print()
            print(f"Your Scan: {scan_path.name}")
            print(f"  Size: {scan_size_mb:.1f} MB")
            print()
            
            # Analyze and recommend
            size_diff = scan_size_mb - existing_size_mb
            size_diff_pct = (size_diff / existing_size_mb * 100) if existing_size_mb > 0 else 0
            
            if scan_size_mb > existing_size_mb * 1.5:
                print("💡 RECOMMENDATION: Keep BOTH files")
                print(f"   Scan is {size_diff:.1f} MB larger (+{size_diff_pct:.0f}%)")
                print("   → Likely contains your handwritten notes!")
                print("   → Original may be cleaner OCR text")
            elif scan_size_mb > existing_size_mb:
                print("💡 RECOMMENDATION: Keep BOTH files")
                print(f"   Scan is {size_diff:.1f} MB larger (+{size_diff_pct:.0f}%)")
                print("   → May contain your notes")
            elif scan_size_mb < existing_size_mb:
                print("ℹ️  Note: Existing PDF is larger")
                print(f"   Original is {-size_diff:.1f} MB larger")
                print("   → You may already have the better version")
            else:
                print("ℹ️  Files are similar size")
                print("   → May be duplicates")
        else:
            print("⚠️  Zotero item has PDF but file not found in publications directory")
            print(f"   No PDF found matching author/year pattern")
            print(f"Your Scan: {scan_path.name} ({scan_size_mb:.1f} MB)")
        
        print("="*70)
        print()

    def _locate_existing_attachment_for_item(self, item_key: str, zotero_item: dict, metadata: dict) -> dict:
        """Find existing attachment path via Zotero DB; fallback to publications fuzzy match.
        Returns dict with: path (Path), filename, size_mb, modified, windows_path, attachment_key
        """
        try:
            # Use local Zotero DB if available
            if getattr(self, 'local_zotero', None) and self.local_zotero.db_connection:
                cur = self.local_zotero.db_connection.cursor()
                cur.execute("SELECT itemID FROM items WHERE key = ?", (item_key,))
                row = cur.fetchone()
                if row:
                    parent_id = row[0]
                    q = (
                        "SELECT items.key, itemAttachments.path "
                        "FROM itemAttachments "
                        "JOIN items ON itemAttachments.itemID = items.itemID "
                        "WHERE itemAttachments.parentItemID = ? "
                        "AND itemAttachments.contentType = 'application/pdf' "
                        "AND items.itemID NOT IN (SELECT itemID FROM deletedItems)"
                    )
                    cur.execute(q, (parent_id,))
                    for akey, apath in cur.fetchall() or []:
                        if not apath:
                            continue
                        wsl_path = Path(self._normalize_path(apath))
                        if wsl_path.exists():
                            st = wsl_path.stat()
                            return {
                                'path': wsl_path,
                                'filename': wsl_path.name,
                                'size_mb': st.st_size / 1024 / 1024,
                                'modified': st.st_mtime,
                                'windows_path': apath,
                                'attachment_key': akey
                            }
        except Exception as e:
            self.logger.debug(f"Attachment lookup failed: {e}")
        
        # Fallback to fuzzy publications match
        info = self._get_existing_pdf_info(zotero_item)
        return info or {}

    def _summarize_pdf_for_compare(self, path: Path) -> dict:
        """Gather page count, times, OCR snippet, and border detection summary for a PDF."""
        out = {
            'path': path,
            'filename': path.name,
            'size_mb': 0.0,
            'modified': None,
            'created': None,
            'pages': None,
            'snippet': None,
            'borders_summary': None
        }
        try:
            st = path.stat()
            out['size_mb'] = st.st_size / 1024 / 1024
            out['modified'] = st.st_mtime
            out['created'] = st.st_ctime
        except Exception:
            pass
        # Page count and OCR snippet
        try:
            import fitz
            with fitz.open(str(path)) as doc:
                out['pages'] = len(doc)
                if len(doc) > 0:
                    txt = (doc[0].get_text("text") or "").strip()
                    oneline = " ".join(txt.split())
                    out['snippet'] = oneline[:80]
        except Exception as e:
            self.logger.debug(f"PDF open/text failed for {path.name}: {e}")
        # Border detection on first up to 4 pages
        try:
            import fitz, numpy as np, cv2  # noqa: F401
            from shared_tools.pdf.border_remover import BorderRemover
            detected = 0
            total = 0
            with fitz.open(str(path)) as doc:
                check_n = min(len(doc), 4)
                remover = BorderRemover({'max_border_width': self.border_max_width})
                for i in range(check_n):
                    page = doc[i]
                    pix = page.get_pixmap(alpha=False)
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                    edges = remover.detect_page_edges_center_out(img)
                    if any(v > 0 for v in edges.values()):
                        detected += 1
                    total += 1
            if total:
                out['borders_summary'] = f"Dark borders on {detected} of {total} pages checked"
        except Exception as e:
            self.logger.debug(f"Border detection failed for {path.name}: {e}")
        return out

    def _display_enhanced_pdf_comparison(self, scan_info: dict, existing_info: dict):
        """Print enhanced comparison panel with details for both PDFs."""
        import time
        print("\n" + "="*70)
        print("📊 PDF COMPARISON:")
        print("="*70)
        if existing_info:
            print(f"Existing: {existing_info.get('filename','(unknown)')}")
            if existing_info.get('size_mb') is not None:
                print(f"  Size: {existing_info['size_mb']:.1f} MB")
            if existing_info.get('modified'):
                print(f"  Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(existing_info['modified']))}")
        else:
            print("⚠️  Zotero item has PDF but file not found in publications directory")
        print()
        print(f"Your Scan: {scan_info.get('filename')}")
        if scan_info.get('size_mb') is not None:
            print(f"  Size: {scan_info['size_mb']:.1f} MB")
        if scan_info.get('modified'):
            print(f"  Modified: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(scan_info['modified']))}")
        # Page counts
        ex_pages = existing_info.get('pages') if existing_info else None
        if ex_pages is None and existing_info and existing_info.get('path'):
            # lazy summarize to fill pages/snippet/borders if needed
            try:
                enriched = self._summarize_pdf_for_compare(existing_info['path'])
                existing_info.update({k: enriched.get(k) for k in ('pages','snippet','borders_summary')})
                ex_pages = existing_info.get('pages')
            except Exception:
                pass
        if ex_pages is not None:
            print(f"  Pages: {ex_pages}")
        if existing_info and existing_info.get('borders_summary'):
            print(f"  Borders: {existing_info['borders_summary']}")
        if existing_info and existing_info.get('snippet'):
            print(f"  OCR1: {existing_info['snippet']}")
        print()
        if scan_info.get('pages') is not None:
            print(f"Scan Pages: {scan_info['pages']}")
        if scan_info.get('borders_summary'):
            print(f"Scan Borders: {scan_info['borders_summary']}")
        if scan_info.get('snippet'):
            print(f"Scan OCR1: {scan_info['snippet']}")
        print("="*70)
        print()

    def _move_to_recycle_bin_windows(self, windows_path: str) -> bool:
        """Send a Windows file to Recycle Bin using PowerShell script."""
        try:
            ps_script_win = self._get_script_path_win('move_to_recycle_bin.ps1')
            result = subprocess.run(
                ['powershell.exe', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win, windows_path],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                return True
            self.logger.warning(f"Recycle Bin script failed ({result.returncode}): {result.stdout or result.stderr}")
            return False
        except Exception as e:
            self.logger.warning(f"Recycle Bin move failed: {e}")
            return False

class PaperFileHandler(FileSystemEventHandler):
    """File system event handler for watchdog."""
    
    def __init__(self, daemon: PaperProcessorDaemon):
        """Initialize handler.
        
        Args:
            daemon: Reference to daemon instance
        """
        self.daemon = daemon
        super().__init__()
    
    def on_created(self, event):
        """Handle file creation events.
        
        Args:
            event: File system event
        """
        if event.is_directory:
            return
        
        file_path = Path(event.src_path)
        
        # Only process PDF files
        if not file_path.suffix.lower() == '.pdf':
            return
        
        # Only process academic papers
        if not self.daemon.should_process(file_path.name):
            self.daemon.logger.debug(f"Ignored: {file_path.name} (not academic paper)")
            return
        
        # Small delay to ensure file is fully written
        time.sleep(2)
        
        # Check if file still exists (may have been moved/deleted by another process)
        if not file_path.exists():
            self.daemon.logger.warning(f"File no longer exists, skipping: {file_path.name}")
            return
        
        # Process the paper
        self.daemon.logger.info("")
        self.daemon.logger.info("-"*60)
        self.daemon.process_paper(file_path)
        self.daemon.logger.info("-"*60)
        self.daemon.logger.info("Ready for next scan")


def normalize_path_for_wsl(path_str: str) -> str:
    """Normalize a path string to WSL format (standalone function for main).
    
    This is a wrapper around the static method for backward compatibility.
    
    Args:
        path_str: Path string that may be in WSL or Windows format
        
    Returns:
        Normalized WSL path string
    """
    return PaperProcessorDaemon._normalize_path(path_str)


def main():
    """Main entry point."""
    import argparse
    import signal
    import time
    import subprocess
    
    parser = argparse.ArgumentParser(description="Paper processor daemon")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    parser.add_argument("--status", action="store_true", help="Show daemon status and exit")
    parser.add_argument("--stop", action="store_true", help="Stop daemon and exit")
    parser.add_argument("--force-stop", action="store_true", help="Force stop daemon and exit")
    parser.add_argument("--restart", action="store_true", help="Restart daemon")
    args = parser.parse_args()
    
    # Get watch directory from config
    config = configparser.ConfigParser()
    root_dir = Path(__file__).parent.parent
    config.read([
        root_dir / 'config.conf',
        root_dir / 'config.personal.conf'
    ])
    
    # Normalize scanner_papers_dir path (handle both WSL and Windows formats)
    scanner_path = config.get('PATHS', 'scanner_papers_dir', 
                              fallback='/mnt/i/FraScanner/papers')
    watch_dir = Path(normalize_path_for_wsl(scanner_path))
    
    if not watch_dir.exists():
        print(f"Error: Watch directory not found: {watch_dir}")
        sys.exit(1)

    pid_file = watch_dir / ".daemon.pid"

    def _read_pid() -> Optional[int]:
        try:
            if pid_file.exists():
                return int(pid_file.read_text().strip())
        except Exception:
            return None
        return None

    def _is_alive(pid: Optional[int]) -> bool:
        if not pid:
            return False
        try:
            os.kill(pid, 0)
            return True
        except Exception:
            return False

    def _stop_graceful(timeout_seconds: int = 8) -> bool:
        pid = _read_pid()
        if not _is_alive(pid):
            # Try pkill fallback if no pid file but process may exist
            try:
                # Find matching PIDs and avoid killing ourselves
                out = subprocess.check_output(["pgrep", "-f", "scripts/paper_processor_daemon.py"], text=True)
                current_pid = os.getpid()
                for line in out.strip().splitlines():
                    try:
                        target = int(line.strip())
                        if target != current_pid:
                            try:
                                os.kill(target, signal.SIGTERM)
                            except Exception:
                                pass
                    except Exception:
                        continue
            except Exception:
                pass
            if pid_file.exists():
                pid_file.unlink(missing_ok=True)
            return True
        try:
            os.kill(pid, signal.SIGTERM)
        except Exception:
            pass
        # wait
        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            if not _is_alive(pid):
                if pid_file.exists():
                    pid_file.unlink(missing_ok=True)
                return True
            time.sleep(0.3)
        # force
        try:
            os.kill(pid, signal.SIGKILL)
        except Exception:
            pass
        time.sleep(0.2)
        if not _is_alive(pid):
            if pid_file.exists():
                pid_file.unlink(missing_ok=True)
            return True
        return False

    if args.status:
        pid = _read_pid()
        if _is_alive(pid):
            print(f"running (PID {pid})")
            sys.exit(0)
        else:
            # Clean stale pid file
            if pid_file.exists():
                pid_file.unlink(missing_ok=True)
            print("not running")
            sys.exit(1)

    if args.stop:
        ok = _stop_graceful()
        print("stopped" if ok else "stop failed")
        sys.exit(0 if ok else 1)

    if args.force_stop:
        # Kill any matching processes and clear pid file
        try:
            subprocess.run(["pkill", "-9", "-f", "scripts/paper_processor_daemon.py"], check=False)
        except Exception:
            pass
        if pid_file.exists():
            pid_file.unlink(missing_ok=True)
        print("force-stopped")
        sys.exit(0)
    
    if args.restart:
        print("Stopping existing daemon (if any)...")
        _stop_graceful()
        print("Starting daemon...")
    
    daemon = PaperProcessorDaemon(watch_dir, debug=args.debug)
    daemon.start()


if __name__ == "__main__":
    main()

