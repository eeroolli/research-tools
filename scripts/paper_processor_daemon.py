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
from typing import Optional
import subprocess
import socket
import threading
import re
from pathlib import Path
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

# Import border remover for scanned documents
from shared_tools.pdf.border_remover import BorderRemover


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
        self.debug = debug
        
        # Load configuration for publications directory
        self.load_config()
        
        # Setup logging
        self.setup_logging()
        
        # Initialize processors
        self.metadata_processor = PaperMetadataProcessor()
        self.zotero_processor = ZoteroPaperProcessor()
        
        # Initialize book lookup service (for book chapters)
        self.book_lookup_service = DetailedISBNLookupService()
        
        # Initialize national library manager (for thesis, book chapters, books)
        self.national_library_manager = ConfigDrivenNationalLibraryManager()
        
        # Initialize border remover (for dark border removal from scanned PDFs)
        self.border_remover = BorderRemover()
        
        # Initialize services
        self.ollama_process = None
        self.ollama_ready = False
        self.grobid_ready = False
        
        print("🚀 Initializing services...")
        self._initialize_services()
        
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
            self.author_validator.refresh_if_needed(max_age_hours=24, silent=True)
            self.logger.info("✅ Author validator ready")
        except Exception as e:
            self.logger.error(f"❌ Failed to initialize author validator: {e}")
            self.author_validator = None
        
        # Initialize journal validator for recognizing Zotero journals
        try:
            from shared_tools.utils.journal_validator import JournalValidator
            self.journal_validator = JournalValidator()
            self.journal_validator.refresh_if_needed(max_age_hours=24, silent=True)
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
        
        # Observer will be set in start()
        self.observer = None
    
    def load_config(self):
        """Load configuration."""
        self.config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent
        
        self.config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
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
        
        # Get GROBID configuration
        self.grobid_auto_start = self.config.getboolean('GROBID', 'auto_start', fallback=True)
        self.grobid_auto_stop = self.config.getboolean('GROBID', 'auto_stop', fallback=True)
        self.grobid_container_name = self.config.get('GROBID', 'container_name', fallback='grobid')
        self.grobid_port = self.config.getint('GROBID', 'port', fallback=8070)
        self.grobid_max_pages = self.config.getint('GROBID', 'max_pages', fallback=2)
        
        # Check if publications directory is accessible
        self._validate_publications_directory()
    
    def _normalize_path(self, path_str: str) -> str:
        """Normalize a path string to WSL format.
        
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
        """Validate that publications directory is accessible and handle setup."""
        try:
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
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(logging.Formatter('%(message)s'))
        logger.addHandler(console_handler)
        
        # File handler - detailed format with timestamp (if file logging is needed later)
        # For now, we only use console output
        
        self.logger = logging.getLogger(__name__)
    
    def _initialize_services(self):
        """Initialize services with GROBID as primary, Ollama as lazy fallback."""
        print("  🔍 Checking GROBID...")
        
        # Check GROBID availability
        from shared_tools.api.grobid_client import GrobidClient
        
        # Create GROBID config with rotation settings
        grobid_config = {
            'handle_rotation': self.config.getboolean('GROBID', 'handle_rotation', fallback=True),
            'rotation_check_pages': self.config.getint('GROBID', 'rotation_check_pages', fallback=2),
            'tesseract_path': self.config.get('PROCESSING', 'tesseract_path', fallback=None)
        }
        
        self.grobid_client = GrobidClient(f"http://localhost:{self.grobid_port}", config=grobid_config)
        
        if self.grobid_client.is_available(verbose=False):
            self.grobid_ready = True
            print("    ✅ GROBID: Available")
        else:
            # Try to start GROBID container
            if self.grobid_auto_start:
                print("    🐳 GROBID: Starting Docker container...")
                if self._start_grobid_container():
                    self.grobid_ready = True
                    print("    ✅ GROBID: Started successfully")
                else:
                    self.grobid_ready = False
                    print("    ❌ GROBID: Failed to start (will use fallback methods)")
                    print("      💡 Tip: Check if Docker is running and port 8070 is free")
            else:
                self.grobid_ready = False
                print("    ❌ GROBID: Not available (will use fallback methods)")
        
        # Don't start Ollama yet - only when needed
        print("    ⏭️  Ollama: Will start when needed")
        
        print("  ✅ Services initialized")
        print()
    
    def _ensure_ollama_ready(self) -> bool:
        """Ensure Ollama is ready, starting it if necessary.
        
        Returns:
            True if Ollama is ready, False if failed to start
        """
        if self.ollama_ready:
            return True
        
        if not self.ollama_auto_start:
            self.logger.warning("Ollama auto-start disabled")
            return False
        
        print("  🤖 Starting Ollama (needed for fallback extraction)...")
        self._start_ollama_background()
        
        # Wait for Ollama to be ready
        for attempt in range(self.ollama_startup_timeout):
            time.sleep(1)
            if self.is_ollama_running():
                self.ollama_ready = True
                print("    ✅ Ollama: Started successfully")
                return True
        
        print("    ❌ Ollama: Failed to start")
        return False
    
    def _start_grobid_container(self) -> bool:
        """Start GROBID Docker container.
        
        Returns:
            True if started successfully
        """
        try:
            # Check if container already exists
            result = subprocess.run(['docker', 'ps', '-a', '--filter', f'name={self.grobid_container_name}', '--format', '{{.Names}}'], 
                                  capture_output=True, text=True)
            
            if self.grobid_container_name in result.stdout:
                # Container exists - start it
                print(f"    🔄 Starting existing GROBID container...")
                result = subprocess.run(['docker', 'start', self.grobid_container_name], 
                                      capture_output=True, text=True)
                if result.returncode == 0:
                    self.logger.info("Started existing GROBID container")
                else:
                    self.logger.error(f"Failed to start existing container: {result.stderr}")
                    return False
            else:
                # Create new container (standard model - lightweight, CPU-only)
                # Full model is 8GB+ and requires significant resources
                print(f"    🐳 Creating new GROBID container...")
                result = subprocess.run([
                    'docker', 'run', '-d', 
                    '--name', self.grobid_container_name,
                    '-p', f'{self.grobid_port}:8070',
                    'lfoppiano/grobid:0.8.2'  # Standard model - lightweight
                ], capture_output=True, text=True)
                
                if result.returncode == 0:
                    self.logger.info("Created new GROBID container")
                else:
                    self.logger.error(f"Failed to create container: {result.stderr}")
                    return False
            
            # Wait for GROBID to be ready with better feedback
            print(f"    ⏳ Waiting for GROBID to initialize...")
            for attempt in range(60):  # 60 second timeout (GROBID can be slow)
                time.sleep(1)
                
                # Show progress every 5 seconds
                if attempt % 5 == 0 and attempt > 0:
                    print(f"      Still waiting... ({attempt}s)")
                
                if self.grobid_client.is_available(verbose=False):
                    print(f"    ✅ GROBID ready after {attempt + 1} seconds")
                    return True
            
            print(f"    ❌ GROBID failed to respond within 60 seconds")
            self.logger.error("GROBID container started but not responding")
            return False
            
        except FileNotFoundError:
            self.logger.error("Docker not found. Please install Docker first.")
            return False
        except Exception as e:
            self.logger.error(f"Failed to start GROBID container: {e}")
            # Add diagnostic info
            print(f"      🔍 Diagnostic: Try 'docker ps' to check container status")
            print(f"      🔍 Diagnostic: Try 'docker logs {self.grobid_container_name}' for container logs")
            return False
    
    def _stop_grobid_container(self):
        """Stop GROBID Docker container if we started it."""
        if not self.grobid_auto_stop:
            self.logger.info("⏭️  GROBID auto-stop disabled - leaving container running")
            return
        
        try:
            result = subprocess.run(['docker', 'stop', self.grobid_container_name], 
                                  capture_output=True, text=True)
            if result.returncode == 0:
                self.logger.info("✅ GROBID container stopped")
            else:
                self.logger.warning(f"Failed to stop GROBID container: {result.stderr}")
        except Exception as e:
            self.logger.error(f"Error stopping GROBID container: {e}")
    
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
    
    def is_ollama_running(self) -> bool:
        """Check if Ollama server is running on the configured port.
        
        Returns:
            True if Ollama is responding, False otherwise
        """
        try:
            # Try to connect to Ollama's configured port with fast timeout
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)  # Fast 2 second timeout for detection
            result = sock.connect_ex(('localhost', self.ollama_port))
            sock.close()
            return result == 0
        except Exception:
            return False
    
    def _start_ollama_background(self):
        """Start Ollama server in background without blocking initialization."""
        try:
            self.logger.info("🤖 Starting Ollama server in background...")
            
            # Start Ollama server in background
            self.ollama_process = subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Start a background thread to wait for Ollama to be ready
            def wait_for_ollama():
                for attempt in range(self.ollama_startup_timeout):
                    time.sleep(1)
                    if self.is_ollama_running():
                        self.ollama_ready = True
                        self.logger.info("✅ Ollama server started successfully")
                        return
                
                # If we get here, Ollama didn't start in time
                self.logger.warning(f"⚠️  Ollama failed to start within {self.ollama_startup_timeout} seconds")
                self.ollama_ready = False
            
            # Start the waiting thread
            threading.Thread(target=wait_for_ollama, daemon=True).start()
            
        except FileNotFoundError:
            self.logger.error("❌ Ollama not found. Please install Ollama first.")
            self.ollama_ready = False
        except Exception as e:
            self.logger.error(f"❌ Failed to start Ollama: {e}")
            self.ollama_ready = False
    
    def start_ollama_if_needed(self):
        """Start Ollama server if it's not already running.
        
        This ensures the daemon can use Ollama for metadata extraction
        without requiring manual startup.
        """
        if self.is_ollama_running():
            self.logger.info("✅ Ollama server is already running")
            return
        
        self.logger.info("🤖 Starting Ollama server...")
        print("🤖 Starting Ollama server...")
        
        try:
            # Start Ollama server in background
            self.ollama_process = subprocess.Popen(
                ['ollama', 'serve'],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True
            )
            
            # Wait for Ollama to be ready (up to configured timeout)
            self.logger.info("⏳ Waiting for Ollama to start...")
            print("⏳ Waiting for Ollama to start...")
            
            for attempt in range(self.ollama_startup_timeout):  # Configurable timeout
                time.sleep(1)
                if self.is_ollama_running():
                    self.logger.info("✅ Ollama server started successfully")
                    print("✅ Ollama server started successfully")
                    return
                if attempt % 5 == 0 and attempt > 0:
                    self.logger.info(f"⏳ Still waiting for Ollama... ({attempt}s)")
                    print(f"⏳ Still waiting for Ollama... ({attempt}s)")
            
            # If we get here, Ollama didn't start in time
            self.logger.warning(f"⚠️  Ollama failed to start within {self.ollama_startup_timeout} seconds")
            print(f"⚠️  Ollama failed to start within {self.ollama_startup_timeout} seconds")
            print("   You may need to start it manually: ollama serve")
            
        except FileNotFoundError:
            self.logger.error("❌ Ollama not found. Please install Ollama first.")
            print("❌ Ollama not found. Please install Ollama first.")
            print("   Install from: https://ollama.ai/")
        except Exception as e:
            self.logger.error(f"❌ Failed to start Ollama: {e}")
            print(f"❌ Failed to start Ollama: {e}")
    
    def stop_ollama_if_started(self):
        """Stop Ollama server if we started it.
        
        This is called during daemon shutdown to clean up.
        """
        if not self.ollama_auto_stop:
            self.logger.info("⏭️  Ollama auto-stop disabled - leaving server running")
            return
            
        if self.ollama_process:
            self.logger.info("🛑 Stopping Ollama server...")
            print("🛑 Stopping Ollama server...")
            try:
                self.ollama_process.terminate()
                # Wait up to configured timeout for graceful shutdown
                self.ollama_process.wait(timeout=self.ollama_shutdown_timeout)
                self.logger.info("✅ Ollama server stopped")
                print("✅ Ollama server stopped")
            except subprocess.TimeoutExpired:
                # Force kill if it doesn't stop gracefully
                self.ollama_process.kill()
                self.logger.warning("⚠️  Ollama server force-stopped")
                print("⚠️  Ollama server force-stopped")
            except Exception as e:
                self.logger.error(f"❌ Error stopping Ollama: {e}")
                print(f"❌ Error stopping Ollama: {e}")
    
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
        print(f"SCANNED DOCUMENT: {pdf_path.name}")
        print("="*60)
        print(f"\nMetadata extracted in {extraction_time:.1f}s")
        
        # Show data source
        source = metadata.get('source', 'OCR extraction')
        method = metadata.get('method', 'unknown')
        print(f"Data source: {source} ({method})")
        
        # Show filtering notice if authors were cleaned
        if metadata.get('_filtered'):
            print(f"📝 Note: {metadata.get('_filtering_reason', 'Authors filtered')}")
        
        print("\nEXTRACTED METADATA:")
        print("-" * 40)
        
        # Universal field display using smart grouping
        self._display_metadata_universal(metadata)
        
        print("-" * 40)
    
    def prompt_for_year(self, metadata: dict, allow_back: bool = False) -> dict:
        """Prompt user for publication year if missing.
        
        Args:
            metadata: Metadata dict
            allow_back: If True, allows 'z' to go back
            
        Returns:
            Updated metadata with year, or special string 'BACK'/'RESTART'
        """
        # Skip if already confirmed earlier in this session
        if metadata.get('_year_confirmed'):
            return metadata
        if metadata.get('year'):
            metadata['_year_confirmed'] = True
            return metadata
        
        print("\n📅 Publication year not found in scan")
        hint = "(or press Enter to skip"
        if allow_back:
            hint += ", 'z' to back, 'r' to restart"
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
        elif year_input and year_input != '':
            # Validate year format
            if year_input.isdigit() and len(year_input) == 4:
                metadata['year'] = year_input
                metadata['_year_confirmed'] = True
                print(f"User provided year: {year_input}")
                self.logger.info(f"User provided year: {year_input}")
            else:
                print("⚠️  Invalid year format (expected 4 digits)")
        
        return metadata
    
    def filter_garbage_authors(self, metadata: dict) -> dict:
        """Filter out garbage authors, keeping only those found in Zotero.
        
        When extraction quality is poor (e.g., regex fallback finds junk like
        "Working Paper", "Series Working", etc.), this filters to keep only
        real authors that exist in your Zotero collection.
        
        Args:
            metadata: Metadata dict with 'authors' field
            
        Returns:
            Updated metadata dict with filtered authors
        """
        if not metadata.get('authors') or not self.author_validator:
            return metadata
        
        original_authors = metadata['authors']
        
        # Skip filtering if extraction method is reliable (GROBID, CrossRef, arXiv)
        extraction_method = metadata.get('extraction_method', metadata.get('method', ''))
        reliable_methods = ['grobid', 'crossref', 'arxiv', 'doi']
        if extraction_method in reliable_methods:
            return metadata
        
        # Validate authors
        validation = self.author_validator.validate_authors(original_authors)
        known_authors = validation['known_authors']
        unknown_authors = validation['unknown_authors']
        
        # Decision logic: Filter if we have many unknowns and some known authors
        total = len(original_authors)
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
            '9': ('unknown', 'Other')
        }
        
        # Reverse mapping: document_type -> number choice
        reverse_map = {v[0]: k for k, v in doc_type_map.items()}
        
        current_type = metadata.get('document_type', '').lower()
        
        print("\n" + "="*60)
        print("📚 DOCUMENT TYPE")
        print("="*60)
        print("Getting the document type right helps guide search strategies.")
        print("This ensures we search the right APIs and ask for relevant fields.")
        print()
        
        if current_type and current_type in reverse_map:
            # Show detected type and ask for confirmation
            current_name = next(name for num, (typ, name) in doc_type_map.items() 
                              if typ == current_type)
            print(f"📄 Detected type: {current_name}")
            print()
            print("[Enter] = Keep this type")
            print("[1-9] = Change to a different type")
            print("[q] = Cancel and skip this document")
            print()
            
            print("Document types:")
            for num, (typ, name) in doc_type_map.items():
                marker = " ← detected" if typ == current_type else ""
                print(f"  [{num}] {name}{marker}")
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
            print("No document type detected. Please select:")
            print()
            print("[1] Journal Article")
            print("[2] Book Chapter")
            print("[3] Conference Paper")
            print("[4] Book")
            print("[5] Thesis/Dissertation")
            print("[6] Report")
            print("[7] News Article")
            print("[8] Working Paper/preprint")
            print("[9] Other")
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
        
        # Display each group if it has non-empty fields
        for group_name, field_mapping in field_groups:
            group_fields = self._extract_group_fields(metadata, field_mapping)
            if group_fields:
                print(f"\n{group_name}:")
                for field_name, field_value in group_fields.items():
                    self._display_field(field_name, field_value)
    
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
    
    def _display_field(self, field_name: str, field_value):
        """Display a single field with appropriate formatting.
        
        Args:
            field_name: Display name for the field
            field_value: Value to display
        """
        if field_name == 'Authors':
            if isinstance(field_value, list):
                # Validate authors against Zotero if validator available
                if self.author_validator:
                    validation = self.author_validator.validate_authors(field_value)
                    print(f"  {field_name}:")
                    for author_info in validation['known_authors']:
                        author_name = author_info['name']
                        print(f"    ✅ {author_name} (in Zotero)")
                        if author_info.get('alternatives'):
                            alts = ', '.join(author_info['alternatives'][:2])
                            print(f"       Other options: {alts}")
                    for author_info in validation['unknown_authors']:
                        print(f"    🆕 {author_info['name']} (new author)")
                else:
                    # Fallback if validator not available
                    if len(field_value) > 3:
                        author_str = ', '.join(field_value[:3]) + f" (+{len(field_value)-3} more)"
                    else:
                        author_str = ', '.join(field_value)
                    print(f"  {field_name}: {author_str}")
            else:
                print(f"  {field_name}: {field_value}")
        
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
        print("\n🎯 ZOTERO MATCH FOUND!")
        print("What would you like to do with the scanned PDF?")
        print()
        print("[1] 📎 Attach PDF to existing Zotero item")
        print("[2] ✏️  Edit metadata before attaching")
        print("[3] 🔍 Search Zotero again with different info")
        print("[4] 📄 Create new Zotero item (ignore match)")
        print("[5] ❌ Skip document")
        print("  (q) Quit daemon")
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
        print("\nWHAT WOULD YOU LIKE TO DO?")
        print()
        print("[1] 📄 Create new Zotero item with extracted metadata")
        print("[2] ✏️  Edit metadata before creating item")
        print("[3] 🔍 Search Zotero with additional info")
        print("[4] ❌ Skip document (not academic)")
        print("[5] 📝 Manual processing later")
        print("  (q) Quit daemon")
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
        4. Display matches with letter labels (A-Z)
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
                return ('quit', None, metadata)
            else:
                metadata = year_result  # Year was added/updated in metadata
            year = metadata.get('year', None)
            
            # Step 2: Try quick title/DOI search first
            if metadata.get('title') or metadata.get('doi'):
                print("\n🔍 Quick Zotero search using found info...")
                matches = self.local_zotero.search_by_metadata(metadata, max_matches=10)
                
                if matches:
                    search_info = "by title/DOI"
                    if year:
                        search_info += f" in {year}"
                    
                    action, item = self.display_and_select_zotero_matches(matches, search_info)
                    return (action, item, metadata)
            
            # Preserve full author list for future re-search cycles
            if metadata.get('authors') and not metadata.get('_all_authors'):
                metadata['_all_authors'] = metadata['authors'].copy()

            # Step 3: Author-based search
            if not metadata.get('authors'):
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
                return ('quit', None, metadata)  # Will cause restart from outer loop
            
            if not selected_authors:
                print("❌ No authors selected")
                return ('none', None, metadata)
            
            # Update metadata with edited/selected authors
            # This preserves any author edits made in select_authors_for_search()
            metadata['authors'] = selected_authors
            
            # Step 4: Search by selected authors with year filter
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
                author_lastnames.append(lastname)
            
            # Show search query before executing
            # Arrow indicates author order: first → second → third, etc.
            author_display = ' & '.join(author_lastnames)
            year_str = f" (year: {year})" if year else " (any year)"
            doc_type_str = f" [type: {metadata.get('document_type', 'any')}]" if metadata.get('document_type') else ""
            print(f"\n🔍 Searching Zotero database for authors (in order): {author_display}{year_str}{doc_type_str}")
            
            matches = self.local_zotero.search_by_authors_ordered(
                author_lastnames, 
                year=year,
                limit=10,
                document_type=metadata.get('document_type')
            )
            
            # Normalize results
            normalized_matches = []
            for item in matches:
                normalized = self._normalize_search_result(item)
                normalized_matches.append(normalized)
            
            if not normalized_matches:
                # Show what was searched (reuse author_display computed above)
                year_str = f" in {year}" if year else ""
                print(f"\n❌ No matches found in Zotero for: {author_display}{year_str}")
                print()
                
                # Offer options to user
                print("Options (enter a number):")
                print("[1] Search again without year filter")
                if year:
                    print("[2] Search again with different year")
                    print("[3] Proceed to create new Zotero item")
                    print("[4] Move to manual review")
                    print("  (z) Back to previous step")
                else:
                    print("[2] Proceed to create new Zotero item")
                    print("[3] Move to manual review")
                    print("  (z) Back to previous step")
                print()
                
                while True:
                    choice = input("Enter your choice (1-4 or 'z' to go back): ").strip().lower()
                    
                    if choice == '1':
                        # Retry without year filter
                        print("\n🔄 Searching without year filter...")
                        matches_no_year = self.local_zotero.search_by_authors_ordered(
                            author_lastnames,
                            year=None,
                            limit=10,
                            document_type=metadata.get('document_type')
                        )
                        normalized_matches = [self._normalize_search_result(item) for item in matches_no_year]
                        
                        if normalized_matches:
                            search_info = f"by {author_display} (any year)"
                            action, item = self.display_and_select_zotero_matches(normalized_matches, search_info)
                            return (action, item, metadata)
                        else:
                            print(f"❌ Still no matches found for {author_display}")
                            # Fall through to other options
                            break
                    
                    elif choice == '2' and year:
                        # Retry with different year
                        new_year = input(f"Enter different year (currently {year}): ").strip()
                        if new_year and new_year.isdigit():
                            metadata['year'] = new_year  # Update metadata with new year
                            print(f"\n🔄 Searching with year {new_year}...")
                            matches_new_year = self.local_zotero.search_by_authors_ordered(
                                author_lastnames,
                                year=new_year,
                                limit=10,
                                document_type=metadata.get('document_type')
                            )
                            normalized_matches = [self._normalize_search_result(item) for item in matches_new_year]
                            
                            if normalized_matches:
                                search_info = f"by {author_display} in {new_year}"
                                action, item = self.display_and_select_zotero_matches(normalized_matches, search_info)
                                return (action, item, metadata)
                            else:
                                print(f"❌ No matches found for {author_display} in {new_year}")
                                break
                        else:
                            print("⚠️  Invalid year, keeping original search")
                            break
                    
                    elif (choice == '2' and not year) or (choice == '3' and year):
                        # Create new item
                        return ('create', None, metadata)
                    
                    elif (choice == '3' and not year) or (choice == '4' and year):
                        # Move to manual review
                        return ('none', None, metadata)
                    
                    elif choice == 'z':
                        # Back/go back
                        return ('back', None, metadata)
                    
                    else:
                        if year:
                            print("⚠️  Invalid choice. Please enter 1-4 or 'z' to go back.")
                        else:
                            print("⚠️  Invalid choice. Please enter 1-3 or 'z' to go back.")
                        continue
                
                # If we get here, no matches after retry - offer final options
                print("\nOptions:")
                print("[1] Proceed to create new Zotero item")
                print("[2] Move to manual review")
                print("  (z) Back to previous step")
                print()
                
                final_choice = input("Enter your choice: ").strip().lower()
                if final_choice == '1':
                    return ('create', None, metadata)
                elif final_choice == 'z':
                    return ('back', None, metadata)
                else:
                    # Default to manual review
                    return ('none', None, metadata)
            
            # Step 5: Display and let user select
            author_str = ' → '.join([a.split()[-1] for a in selected_authors])
            search_info = f"by {author_str}"
            if year:
                search_info += f" in {year}"
            
            action, item = self.display_and_select_zotero_matches(normalized_matches, search_info)
            return (action, item, metadata)
            
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
    
    def _copy_to_publications_via_windows(self, pdf_path: Path, target_filename: str) -> tuple:
        """Copy PDF to publications directory using Windows PowerShell.
        
        This avoids WSL→Google Drive sync issues by using native Windows file operations.
        
        Args:
            pdf_path: Path to source PDF (WSL or Windows path)
            target_filename: Target filename (just the name, not full path)
            
        Returns:
            Tuple of (success: bool, target_path: Path or None, error_msg: str)
        """
        try:
            # Normalize source path to WSL format first, then convert to Windows for PowerShell
            source_str = str(pdf_path)
            if ':' in source_str and not source_str.startswith('/'):
                # Convert Windows path to WSL format first
                source_str = self._normalize_path(source_str)
            
            # Convert source WSL path to Windows path for PowerShell
            source_win = subprocess.check_output(
                ['wslpath', '-w', source_str],
                text=True
            ).strip()
            
            # Get target directory - already normalized in load_config
            target_dir_str = str(self.publications_dir)
            
            # Convert target WSL path to Windows path
            target_dir_win = subprocess.check_output(
                ['wslpath', '-w', target_dir_str],
                text=True
            ).strip()
            
            target_win = f"{target_dir_win}\\{target_filename}"
            
            # Get path to PowerShell script
            script_dir = Path(__file__).parent
            ps_script = script_dir / 'copy_to_publications.ps1'
            ps_script_win = subprocess.check_output(
                ['wslpath', '-w', str(ps_script)],
                text=True
            ).strip()
            
            # Call PowerShell script
            self.logger.debug(f"Copying via PowerShell: {source_win} → {target_win}")
            
            result = subprocess.run(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win, source_win, target_win],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout for large files
            )
            
            if result.returncode == 0:
                # Success - target is in publications directory
                target_path = self.publications_dir / target_filename
                self.logger.debug(f"Copy successful: {target_path}")
                return (True, target_path, None)
            else:
                # Failed
                error_msg = result.stdout + result.stderr
                self.logger.error(f"PowerShell copy failed (code {result.returncode}): {error_msg}")
                return (False, None, error_msg)
                
        except subprocess.TimeoutExpired:
            error_msg = "Copy timeout (file too large or network issue)"
            self.logger.error(error_msg)
            return (False, None, error_msg)
        except Exception as e:
            error_msg = f"Copy error: {e}"
            self.logger.error(error_msg)
            return (False, None, error_msg)
    
    def handle_failed_extraction(self, pdf_path: Path) -> dict:
        """Handle failed metadata extraction with guided workflow.
        
        Args:
            pdf_path: Path to PDF
            
        Returns:
            Manually entered metadata dict
        """
        print("\n⚠️  METADATA EXTRACTION FAILED")
        print("Let's gather information manually to help identify this document.")
        print()
        
        # Step 1: Document type selection
        # TODO: later to maximize portability this could be moved to a config file       
        print("📚 What type of document is this?")
        print()
        print("[1] Journal Article")
        print("[2] Book Chapter")
        print("[3] Conference Paper")
        print("[4] Book")
        print("[5] Thesis/Dissertation")
        print("[6] Report")
        print("[7] News Article")
        print("[8] Working Paper/preprint")
        print("[9] Other")
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
            '9': ('unknown', 'Other')
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
        print("\n📝 MANUAL METADATA ENTRY")
        print("We'll search local Zotero as you type to help find matches.")
        print()
        
        metadata = partial_metadata.copy()
        
        # Get author
        author = input("First author's last name: ").strip()
        if author:
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
        title = input("\nPaper title: ").strip()
        if title:
            metadata['title'] = title
        
        year = input("Publication year: ").strip()
        if year:
            metadata['year'] = year
        
        # Type-specific fields
        if doc_type in ['journal_article', 'conference_paper']:
            journal = input("Journal/Conference name: ").strip()
            if journal:
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
            print(f"\n⚠️  FILE ALREADY EXISTS: {proposed_filename}")
            print(f"   Existing: {self.get_file_info(final_path)}")
            print(f"   Scanned:  {self.get_file_info(pdf_path)}")
            print()
            print("What would you like to do?")
            print("[1] Keep both (rename scan with _scanned suffix)")
            print("[2] Replace original with scan")
            print("[3] Keep original, discard scan")
            print("[4] Manual review later")
            
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
            shutil.copy2(str(pdf_path), str(final_path))
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
    
    def edit_metadata_interactively(self, metadata: dict, online_metadata: dict = None, local_metadata: dict = None, online_source: str = None) -> dict:
        """Allow user to edit metadata fields with intelligent merging from multiple sources.
        
        Args:
            metadata: Current metadata (from extraction or user input)
            online_metadata: Optional metadata from online libraries (CrossRef, arXiv, etc.)
            local_metadata: Optional metadata from local Zotero database
            online_source: Source of online metadata (e.g., 'crossref_api', 'arxiv_api')
            
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
        new_value = input("New year (or Enter to keep current): ").strip()
        if new_value:
            edited['year'] = new_value
        elif online_metadata and online_metadata.get('year') and not edited.get('year'):
            edited['year'] = online_metadata['year']
            print(f"✅ Auto-filled from online: {online_metadata['year']}")
        elif local_metadata and local_metadata.get('year') and not edited.get('year'):
            edited['year'] = local_metadata['year']
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
        
        print("Options:")
        print("[Enter] Keep current")
        print("[o] Use online abstract")
        print("[l] Use local abstract")
        print("[e] Edit manually")
        
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
            
            print("\nTag editing options:")
            print("  [Enter] = Keep current tags (or none)")
            print("  [t]     = Edit tags interactively")
            
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
            
            print("\nNote editing options:")
            print("  [Enter] = Keep current note (or none)")
            print("  [o]     = Use online note")
            print("  [l]     = Use local note")
            print("  [e]     = Edit note manually")
            
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
        print("\n📋 FIELD COMPARISON:")
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
        print("\n📋 CURRENT TAG SOURCES:")
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
            print("  (w) Write (apply) and return")
            print("  (s) Skip (return without changes)")
            print("=" * 60)
            print(f"📋 FINAL TAGS: {', '.join(working_tags) if working_tags else '(none)'}")
            
            choice = input("\nEnter your choice: ").strip().lower()
            
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
        - If PID file exists and PID is alive, print message and exit(0)
        - If PID file exists but PID is stale, remove PID file and continue
        - If no PID file, continue
        """
        try:
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
        except Exception:
            # On any unexpected error, continue without blocking startup
            return False
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
        prefixes = ['NO_', 'EN_', 'DE_', 'SE_', 'FI_']
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
        self.logger.info(f"New scan: {pdf_path.name}")
        # Remember the original scan path for final move operations
        self._original_scan_path = Path(pdf_path)
        
        try:
            # Step 1: Extract metadata
            self.logger.info("Extracting metadata...")
            
            # Step 1a: Try GREP first (fast identifier extraction + API lookup)
            # This is much faster (2-4 seconds) when identifiers are found
            self.logger.info("Step 1: Trying fast GREP identifier extraction + API lookup...")
            result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=False)
            
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
            elif not has_authors and self.grobid_ready:
                self.logger.info("Step 2: No identifiers found or API lookup failed - trying GROBID...")
                metadata = self.grobid_client.extract_metadata(pdf_path)
                
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
                else:
                    self.logger.info("GROBID did not find authors")
            
            # Step 3: Last resort - try Ollama if still no authors
            if not result.get('success') or not result.get('metadata', {}).get('authors'):
                self.logger.info("Step 3: No authors found from GREP/API/GROBID - trying Ollama as last resort...")
                if self._ensure_ollama_ready():
                    # Try with Ollama fallback
                    ollama_result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=True, 
                                                                       progress_callback=self._show_ollama_progress)
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
                metadata = self.filter_garbage_authors(metadata)

                # Always prompt user to confirm or enter year manually
                # First, check what year sources we have
                identifiers = result.get('identifiers_found', {})
                grep_year = identifiers.get('best_year')
                grobid_year = metadata.get('year')
                
                # Build year sources list for display
                year_sources = []
                if grep_year:
                    year_sources.append(('GREP (scan)', grep_year))
                if grobid_year:
                    year_sources.append(('GROBID/API', grobid_year))
                
                # Always prompt user to confirm or enter year
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
                    while True:
                        try:
                            year_input = input(f"Press Enter to confirm ({suggested_year}) or type a different year: ").strip()
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
                        elif year_input.isdigit() and len(year_input) == 4:
                            # User entered a different year
                            metadata['year'] = year_input
                            metadata['_year_source'] = 'manual'
                            print(f"✅ Using manual year: {year_input}")
                            self.logger.info(f"User entered manual year: {year_input}")
                            metadata['_year_confirmed'] = True
                            break
                        else:
                            print("⚠️  Invalid year format (expected 4 digits or press Enter)")
                
                # Prompt for year BEFORE document type, so numeric input isn't misrouted
                # (This will only prompt if no year was found by any source)
                metadata = self.prompt_for_year(metadata)
                
                # Check if JSTOR ID was found - automatically set as journal article
                if identifiers.get('jstor_ids') and not metadata.get('document_type'):
                    metadata['document_type'] = 'journal_article'
                    self.logger.info("JSTOR ID detected - automatically set as journal article")
                    print("ℹ️  JSTOR ID detected - treating as journal article")
                
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
                    if action == 'back' or action == 'restart':
                        if action == 'restart':
                            print("🔄 Restarting from beginning...")
                            updated_metadata = metadata.copy()  # Reset to original
                        else:
                            print("⬅️  Going back to author selection...")
                        # Loop will restart and prompt again
                        continue
                    
                    break
            
            # Step 4: Handle action from Zotero search
            if action == 'select' and selected_item:
                # User selected an item - offer to attach PDF
                self.handle_item_selected(pdf_path, updated_metadata, selected_item)
            elif action == 'search':
                # User wants to search again - reset authors to full set if available, then recursive call
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

    def _to_windows_path(self, path: Path) -> str:
        """Convert WSL /mnt/<drive>/... path to Windows-style X:\\... for linked files.
        If path is already a Windows path, return as-is.
        """
        path_str = str(path)
        # Already Windows style
        if ":\\" in path_str or ":/" in path_str:
            return path_str
        # WSL mount conversion
        if path_str.startswith('/mnt/') and len(path_str) > 6:
            drive_letter = path_str[5].upper()
            rest = path_str[7:]  # skip '/mnt/<d>/'
            return f"{drive_letter}:\\" + rest.replace('/', '\\')
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
        
        try:
            shutil.copy2(source, final_path)
            self.logger.debug(f"Copied to: {final_path}")
            return final_path
        except Exception as e:
            self.logger.error(f"Copy failed: {e}")
            return None
    
    def move_to_done(self, pdf_path: Path):
        """Move processed PDF to done/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        done_dir = self.watch_dir / "done"
        done_dir.mkdir(exist_ok=True)
        
        dest = done_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.debug(f"Moved to done/")
    
    def move_to_failed(self, pdf_path: Path):
        """Move failed PDF to failed/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        failed_dir = self.watch_dir / "failed"
        failed_dir.mkdir(exist_ok=True)
        
        dest = failed_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to failed/")
    
    def move_to_skipped(self, pdf_path: Path):
        """Move non-academic PDF to skipped/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        skipped_dir = self.watch_dir / "skipped"
        skipped_dir.mkdir(exist_ok=True)
        
        dest = skipped_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to skipped/")
    
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
    
    def _split_with_mutool(self, pdf_path: Path, width: Optional[float] = None, height: Optional[float] = None) -> Optional[Path]:
        """Split a two-up PDF using mutool poster and return path to the split file.
        Creates split in temp directory to avoid cluttering watch directory.
        """
        try:
            if width is None or height is None:
                try:
                    import pdfplumber
                    with pdfplumber.open(str(pdf_path)) as pdf:
                        if len(pdf.pages) > 0:
                            width, height = pdf.pages[0].width, pdf.pages[0].height
                except Exception:
                    width = height = 0
            x, y = (2, 1) if (width and height and width > height) else (1, 2)
            # Create split in temp directory to avoid cluttering watch directory
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_split.pdf"
            cmd = [
                'mutool', 'poster', '-x', str(x), '-y', str(y),
                str(pdf_path), str(out_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"mutool poster failed: {result.stderr.strip()}")
                return None
            # Use split file for downstream processing
            self.logger.info(f"Split PDF created: {out_path.name}")
            return out_path
        except FileNotFoundError:
            self.logger.warning("mutool not found; skipping two-up split")
            return None
        except Exception as e:
            self.logger.error(f"Split failed: {e}")
            return None
    
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
    
    def _check_and_remove_dark_borders(self, pdf_path: Path) -> Optional[Path]:
        """Check for dark borders and optionally remove them.
        
        Checks first 4 pages for borders. If borders detected, prompts user
        to confirm removal. Returns path to cleaned PDF or None if no action taken.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Path to cleaned PDF if borders removed, None if skipped
        """
        try:
            import fitz  # PyMuPDF
        except ImportError:
            self.logger.error("PyMuPDF (fitz) not available - cannot check borders")
            return None
        
        print("\n🔍 Checking for dark borders (pages 1-4)...")
        
        # Check first 4 pages for borders
        borders_detected = False
        pages_with_borders = []
        all_borders_info = []
        
        try:
            doc = fitz.open(str(pdf_path))
            pages_to_check = min(4, len(doc))
            
            for page_num in range(pages_to_check):
                try:
                    processed_image, borders = self.border_remover.process_pdf_page(
                        pdf_path, page_num, zoom=2.0
                    )
                    
                    # Check if any borders were detected
                    if any(borders.values()):
                        borders_detected = True
                        pages_with_borders.append(page_num + 1)
                        all_borders_info.append((page_num + 1, borders))
                        
                        # Format border description
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
                        print(f"  ✓ Page {page_num + 1}: borders detected ({desc})")
                        self.logger.debug(f"Page {page_num + 1}: borders detected {borders}")
                    else:
                        print(f"  ✓ Page {page_num + 1}: no borders")
                except Exception as e:
                    self.logger.debug(f"Error checking page {page_num + 1}: {e}")
                    print(f"  ⚠️  Page {page_num + 1}: error checking borders")
                    continue
            
            doc.close()
            
            if not borders_detected:
                print("\nℹ️  No dark borders detected - skipping removal")
                return None
            
            # Report to user
            pages_str = ", ".join(str(p) for p in pages_with_borders)
            print(f"\n📊 Summary: Dark borders found on {len(pages_with_borders)} of {pages_to_check} pages checked")
            
            choice = input("Remove dark borders from the whole PDF? [Y/n]: ").strip().lower()
            if choice == 'n':
                print("Skipping border removal")
                return None
            
            # Process entire PDF with border removal
            print("\n🔄 Processing all pages...")
            
            # Create output path
            import tempfile
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_borders_removed'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_no_borders.pdf"
            
            stats = self.border_remover.process_entire_pdf(pdf_path, out_path, zoom=2.0)
            
            if stats['pages_processed'] > 0:
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
                return out_path
            else:
                print("⚠️  No pages were processed")
                return None
                
        except Exception as e:
            self.logger.error(f"Error during border removal: {e}")
            print(f"⚠️  Border removal failed: {e}")
            return None
    
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
        
        # Process existing files in the directory
        self.process_existing_files()
        
        self.logger.info("Ready for scans!")
        self.logger.info("="*60)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown(None, None)
    
    def process_existing_files(self):
        """Process existing PDF files in the watch directory."""
        self.logger.info("🔍 Checking for existing PDF files to process...")
        
        existing_files = []
        for file_path in self.watch_dir.glob("*.pdf"):
            if self.should_process(file_path.name):
                existing_files.append(file_path)
        
        if not existing_files:
            self.logger.info("No existing PDF files found to process.")
            return
        
        self.logger.info(f"Found {len(existing_files)} existing PDF file(s) to process:")
        for i, file_path in enumerate(existing_files, 1):
            self.logger.info(f"  {i}. {file_path.name}")
        
        print(f"\n📄 Found {len(existing_files)} existing PDF file(s) to process:")
        for i, file_path in enumerate(existing_files, 1):
            print(f"  {i}. {file_path.name}")
        
        choice = input(f"\nProcess existing files? [y/n]: ").strip().lower()
        if choice != 'y':
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
                print(f"❌ Error processing {file_path.name}: {e}")
            
            self.logger.info("-"*60)
            self.logger.info("Ready for next scan")
    
    def shutdown(self, signum, frame):
        """Clean shutdown handler.
        
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
        
        # Stop Ollama if we started it and auto-stop is enabled
        self.stop_ollama_if_started()
        
        # Stop GROBID container if we started it and auto-stop is enabled
        self._stop_grobid_container()
        
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
        print("📋 METADATA COMPARISON")
        print("="*60)
        
        # Display comparison
        self._display_metadata_comparison(extracted_metadata, zotero_metadata)
        
        # Show user choices
        choice = self._get_metadata_comparison_choice()
        
        # Handle choice and return final metadata
        return self._handle_metadata_choice(choice, extracted_metadata, zotero_metadata)
    
    def _display_metadata_comparison(self, extracted: dict, zotero: dict):
        """Display side-by-side metadata comparison."""
        print("\nEXTRACTED METADATA:")
        print("-" * 30)
        self._display_metadata_universal(extracted)
        
        print("\nZOTERO ITEM METADATA:")
        print("-" * 30)
        self._display_metadata_universal(zotero)
        
        # Show key differences
        print("\n🔍 KEY DIFFERENCES:")
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
        print("\nWhat would you like to do?")
        print("[1] Use extracted metadata (Replace in Zotero, but keep Zotero tags)")
        print("[2] Use Zotero metadata as it is (Keep existing Zotero item unchanged)")
        print("[3] Merge both (show field-by-field comparison)")
        print("[4] Edit manually")
        print("[5] 🔍 Search for more metadata online (CrossRef, arXiv, PubMed)")
        print("[6] 📝 Manual processing later (too similar to decide)")
        print("[7] 📄 Create new Zotero item from extracted metadata")
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
        print("\n🔀 FIELD-BY-FIELD MERGE")
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
        print("🌐 ONLINE METADATA FOUND")
        print("="*60)
        
        print("\nExtracted (from scan):")
        self._display_metadata_universal(extracted)
        
        print("\nZotero (existing item):")
        self._display_metadata_universal(zotero)
        
        print("\nOnline (CrossRef/arXiv/etc):")
        self._display_metadata_universal(online_metadata)
        
        print("\nWhich metadata to use?")
        print("[1] Use online metadata")
        print("[2] Use online + merge with Zotero")
        print("[3] Use online + merge with extracted")
        print("[4] Edit manually with online as reference")
        print("[5] Cancel (use Zotero metadata)")
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
        
        print(f"\n📎 PROCESSING: {item_title}")
        print("=" * 60)
        
        # STEP 1: Metadata Comparison
        print("\n🔄 Step 1: Metadata Comparison")
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
        print("\n🔄 Step 2: Tags Comparison")
        final_tags = self.edit_tags_interactively(
            current_tags=metadata.get('tags', []),
            local_tags=self._extract_zotero_tags(zotero_item)
        )
        
        # STEP 3: PDF Attachment (from Task 7 specification)
        print("\n🔄 Step 3: PDF Attachment")
        return self._handle_pdf_attachment_step(pdf_path, zotero_item, final_metadata)
    
    def _extract_zotero_tags(self, zotero_item: dict) -> list:
        """Extract tags from Zotero item for comparison."""
        # This would need to be implemented to get tags from Zotero item
        # For now, return empty list
        return []
    
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
            print("⚠️  This Zotero item already has a PDF attachment")
            print("\nWhat would you like to do?")
            print("[1] Keep both (add scanned version)")
            print("[2] Replace existing PDF with scan")
            print("[3] Skip attaching and finish")
            print("  (z) Cancel (keep original)")
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
        
        # Copy to publications directory with _scanned logic and conflict handling
        base_path = self.publications_dir / proposed_filename
        stem = base_path.stem
        suffix = base_path.suffix
        scanned_path = self.publications_dir / f"{stem}_scanned{suffix}"
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
        
        copied_ok = False
        try:
            shutil.copy2(str(pdf_path), str(final_path))
            print(f"✅ Copied to: {final_path}")
            copied_ok = True
        except Exception as e:
            print(f"❌ File copy failed: {e}")
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
        manual_dir = self.watch_dir / "manual_review"
        manual_dir.mkdir(exist_ok=True)
        
        dest = manual_dir / Path(src).name
        shutil.move(str(src), str(dest))
        self.logger.info(f"Moved to manual review: {dest}")
        print(f"📝 Moved to manual review: {dest}")
    
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
                author_data = self.author_validator.get_author_info(author)
                if author_data:
                    info['paper_count'] = author_data.get('paper_count', 0)
                    info['recognized'] = True
                    info['recognized_as'] = author_data.get('name')
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
        
        # Display authors with letter labels
        letters = 'abcdefghijklmnopqrstuvwxyz'
        author_map = {}
        
        while True:
            # Clear screen output area (reprint the header each time)
            print("\n🔍 Search for item in Zotero by selecting authors:")
            
            # Rebuild author_map each iteration (in case authors were edited)
            author_map = {}
            if author_info:
                for i, info in enumerate(author_info[:26]):  # Limit to 26 authors
                    letter = letters[i]
                    author_map[letter] = info['name']
                    if info['paper_count'] > 0:
                        papers_str = f"(in Zotero: {info['paper_count']} publications)"
                    elif info['recognized']:
                        if info['recognized_as'] and info['recognized_as'] != info['name']:
                            papers_str = f"(in Zotero as '{info['recognized_as']}', 0 publications found)"
                        else:
                            papers_str = "(in Zotero, 0 publications found)"
                    else:
                        papers_str = "(not in Zotero)"
                    print(f"  [{letter}] {info['name']} {papers_str}")
            else:
                print("  (No authors - use 'n' to add a new author)")
            
            print("\nSelection options:")
            print("  'a'   = Search by first author only")
            print("  'ab'  = Search where 1st=a, 2nd=b")
            print("  'ba'  = Search where 1st=b, 2nd=a")
            print("  'all' = Search by any author (no order)")
            print("  ''    = Use all authors as extracted")
            print("  'e'   = Edit an author name")
            print("  'n'   = Add new author manually")
            print("  '-a'  = Delete author 'a' from list")
            print("  'z'   = Back to previous step")
            print("  'r'   = Restart from beginning")
            
            selection = input("\nYour selection (letters like 'a', 'ab', 'all', or commands e/n/-a/z/r): ").strip()
            selection_lower = selection.lower()
            
            if selection_lower == 'z':
                return 'BACK'
            elif selection_lower == 'r':
                return 'RESTART'
            elif selection_lower.startswith('-'):
                # Delete an author by letter
                letter_to_delete = selection_lower[1:]  # Remove the '-' prefix
                if letter_to_delete in author_map:
                    author_to_remove = author_map[letter_to_delete]
                    # Remove from author_info
                    author_info = [info for info in author_info if info['name'] != author_to_remove]
                    # Remove from authors list
                    authors = [a for a in authors if a != author_to_remove]
                    print(f"✅ Removed: {author_to_remove}")
                    
                    # If no authors left, show message but continue to allow adding new author
                    if not author_info:
                        print("⚠️  No authors remaining - you can add a new author with 'n'")
                else:
                    print(f"⚠️  Invalid author letter: '{letter_to_delete}'")
                print()  # Blank line before showing list again
                continue
            elif selection_lower == 'e':
                # Edit an author
                if not author_info:
                    print("⚠️  No authors to edit")
                    continue
                print("\nWhich author to edit?")
                edit_choice = input(f"Enter letter (a-{letters[len(author_info)-1]}): ").strip().lower()
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
                # Use all authors - return the updated list from author_info
                all_authors = [info['name'] for info in author_info]
                return all_authors
            elif selection_lower == 'all':
                # Return all for unordered search - return updated list
                all_authors = [info['name'] for info in author_info]
                return all_authors
            else:
                # Parse selection (e.g., "ab" or "bac")
                selected_authors = []
                # If user typed option digits here by mistake, guide them
                if selection_lower.isdigit():
                    print("⚠️  This menu uses letters (e.g., 'a' or 'ab'). For numeric options (1-4), respond in the previous options prompt.")
                # Support typing a last name directly (e.g., "Hochschild"): only for length >= 3
                else:
                    # Try to resolve direct text to an author by last name match
                    direct = selection_lower.strip()
                    if direct and len(direct) >= 3:
                        for info in author_info:
                            last = info['name'].split(',')[0].split()[-1].lower()
                            if last == direct or direct in last:
                                return [info['name']]
                for char in selection:
                    if char.lower() in author_map:
                        selected_authors.append(author_map[char.lower()])
                    else:
                        print(f"⚠️  Ignoring invalid selection: '{char}'")
                
                if selected_authors:
                    author_str = ', '.join(selected_authors)
                    self.logger.info(f"User selected authors in order: {author_str}")
                    return selected_authors
                else:
                    print("⚠️  No valid selection, please try again")
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
        
        # Display items with letter labels
        letters = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ'
        item_map = {}
        
        for i, match in enumerate(matches[:26]):  # Limit to 26 items
            letter = letters[i]
            item_map[letter] = match
            
            title = match.get('title', 'Unknown title')
            # Truncate long titles
            if len(title) > 70:
                title = title[:67] + "..."
            
            print(f"  [{letter}] {title}")
            
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
        print("  [A-Z] Select item from list above")
        print("[1]   🔍 Search again (different authors/year)")
        print("[2]   ✏️  Edit metadata")
        print("[3]   None of these items - create new")
        print("[4]   ❌ Skip document")
        print("  (z) ⬅️  Back to author selection")
        print("  (r) 🔄 Restart from beginning")
        print("  (q) Quit daemon")
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().upper()
            
            if choice in item_map:
                # User selected an item
                selected_item = item_map[choice]
                self.logger.info(f"User selected item: {selected_item.get('title', 'Unknown')}")
                return ('select', selected_item)
            elif choice == '1':
                return ('search', None)
            elif choice == '2':
                return ('edit', None)
            elif choice == '3':
                return ('create', None)  # "None of these items"
            elif choice == '4':
                return ('skip', None)
            elif choice == 'Z':
                return ('back', None)
            elif choice == 'R':
                return ('restart', None)
            elif choice == 'Q':
                return ('quit', None)
            else:
                print("⚠️  Invalid choice. Please select a letter A-Z, number 1-4, or 'z', 'r', 'q'.")
    
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
        print("Enter or correct information (press Enter to keep existing or skip):")
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
                print("Enter authors (one per line, empty line to keep current):")
            else:
                print("\nEnter authors (one per line, empty line to finish):")
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
        
        # Use document type to guide API selection
        doc_type = metadata.get('document_type', '').lower()
        
        # Try CrossRef for published academic papers (journal articles, conference papers, reports)
        # Skip for books/chapters, preprints, theses, news articles
        should_try_crossref = (
            title or authors
        ) and doc_type in ['journal_article', 'conference_paper', 'report', 'academic_paper', '']
        
        if should_try_crossref:
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
                    
            except Exception as e:
                self.logger.error(f"CrossRef search error: {e}")
                print(f"⚠️  CrossRef search failed: {e}")
        
        # Try arXiv for preprints and working papers (also try if no CrossRef result and no journal)
        should_try_arxiv = (
            doc_type in ['preprint', 'working_paper'] or
            (not all_results and (not journal or journal == 'arXiv'))
        )
        
        if should_try_arxiv:
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
                    
            except Exception as e:
                self.logger.error(f"arXiv search error: {e}")
                print(f"⚠️  arXiv search failed: {e}")
        
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
                        print("[Enter] = Use first chapter author as editor")
                        print("[Enter name] = Enter editor name manually")
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
                try:
                    print(f"\n🔍 Searching for book: '{book_title}'" + (f" (editor: {editor})" if editor else " (no editor)"))
                    book_result = self.book_lookup_service.lookup_by_title_and_editor(book_title, editor)
                    
                    if book_result:
                        # Convert book metadata to our format (similar to CrossRef/arXiv results)
                        normalized_book = self._normalize_book_metadata_for_chapter(book_result, metadata)
                        
                        # Store as single result (books don't return multiple like CrossRef)
                        all_results = [normalized_book]
                        source_name = "Google Books/OpenLibrary"
                        print("✅ Found book metadata")
                    else:
                        print("❌ No book metadata found")
                        
                        # Try national library search as fallback
                        language = None
                        if pdf_path:
                            language = self._detect_language_from_filename(pdf_path)
                        elif hasattr(self, '_original_scan_path') and self._original_scan_path:
                            language = self._detect_language_from_filename(self._original_scan_path)
                        if language and book_title:
                            try:
                                print(f"\n🔍 Trying national library search for {language}...")
                                nat_lib_results = self._search_national_library_for_book(
                                    book_title=book_title, 
                                    editor=editor,
                                    language=language,
                                    country_code=language
                                )
                                if nat_lib_results:
                                    all_results.extend(nat_lib_results)
                                    source_name = "Google Books/OpenLibrary + National Libraries"
                                    print(f"✅ Found {len(nat_lib_results)} additional result(s) in national libraries")
                            except Exception as e:
                                self.logger.error(f"National library search error: {e}")
                                print(f"⚠️  National library search failed: {e}")
                except Exception as e:
                    self.logger.error(f"Book lookup error: {e}")
                    print(f"⚠️  Book search failed: {e}")
        
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
                try:
                    print(f"\n🔍 Trying national library search for {doc_type} ({language})...")
                    nat_lib_results = self._search_national_library_for_book(
                        book_title=title,
                        authors=authors,
                        language=language,
                        country_code=language,
                        item_type='books' if doc_type == 'book' else 'papers'
                    )
                    if nat_lib_results:
                        all_results.extend(nat_lib_results)
                        source_name = "National Libraries"
                        print(f"✅ Found {len(nat_lib_results)} result(s) in national libraries")
                except Exception as e:
                    self.logger.error(f"National library search error: {e}")
                    print(f"⚠️  National library search failed: {e}")
        
        if not all_results:
            print("❌ No matches found in online libraries")
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
    
    def _detect_language_from_filename(self, pdf_path: Path) -> Optional[str]:
        """Detect language from filename prefix (NO_, EN_, DE_, etc.)
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Language code (NO, EN, DE, FI, SE) or None if not detected
        """
        filename = pdf_path.name.upper()
        language_map = {
            'NO_': 'NO',
            'EN_': 'EN',
            'DE_': 'DE',
            'FI_': 'FI',
            'SE_': 'SE'
        }
        
        for prefix, lang_code in language_map.items():
            if filename.startswith(prefix):
                return lang_code
        
        return None
    
    def _search_national_library_for_book(self, book_title: str, editor: str = None, 
                                         authors: list = None, language: str = None,
                                         country_code: str = None, item_type: str = 'books') -> list:
        """Search national library for book, book chapter, or thesis metadata.
        
        Args:
            book_title: Title to search for
            editor: Optional editor name (for book chapters)
            authors: Optional list of author names
            language: Language code (NO, EN, DE, etc.)
            country_code: Country code for library selection (defaults to language)
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
        print("📄 CREATE NEW ZOTERO ITEM")
        print("="*60)
        
        # Step 1: Quick manual entry
        print("\n📝 Step 1: Quick Manual Entry")
        combined_metadata = self.quick_manual_entry(extracted_metadata)
        if combined_metadata is None:
            # User cancelled during manual entry
            print("❌ Manual entry cancelled")
            return False
        
        # Step 2: Search online libraries (optional)
        print("\n🌐 Step 2: Online Library Search (Optional)")
        print("This step searches CrossRef and arXiv to enrich metadata from online sources.")
        print("You can skip this if your manual entry is complete.")
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
        print("\n📋 Step 3: Metadata Selection")
        final_metadata = combined_metadata
        
        if online_metadata:
            # Show comparison and let user choose
            print("\nComparing metadata:")
            print("-" * 40)
            print("Manual + Extracted:")
            self._display_metadata_universal(combined_metadata)
            print("\nOnline Library:")
            self._display_metadata_universal(online_metadata)
            print()
            
            print("Which metadata to use?")
            print("[1] Use manual/extracted metadata")
            print("[2] Use online library metadata")
            print("[3] Merge both (field-by-field)")
            print("[4] Edit manually")
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
            confirm = input("Proceed with creation? [Y/n]: ").strip().lower()
            if confirm and confirm != 'y':  # Enter or 'y' = proceed, anything else = cancel
                print("❌ Cancelled")
                return False
        
        # Step 4: Tag selection
        print("\n🏷️  Step 4: Tag Selection")
        
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
        print("\n📖 Step 5: Creating Zotero Item")

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
        
        copied_ok = False
        try:
            shutil.copy2(str(pdf_path), str(final_path))
            print(f"✅ Copied to: {final_path}")
            copied_ok = True
        except Exception as e:
            print(f"❌ File copy failed: {e}")
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
    
    def handle_item_selected(self, pdf_path: Path, metadata: dict, selected_item: dict):
        """Handle user selecting a Zotero item.
        
        Shows metadata review, then PDF comparison (if existing), proposed actions, and asks for confirmation.
        
        Args:
            pdf_path: Path to scanned PDF
            metadata: Extracted metadata
            selected_item: The Zotero item dict that was selected
        """
        title = selected_item.get('title', 'Unknown')
        has_pdf = selected_item.get('has_attachment', selected_item.get('hasAttachment', False))
        
        print(f"\n✅ Selected: {title}\n")
        
        # Show detailed metadata and give option to review/edit before proceeding
        self._display_zotero_item_details(selected_item)
        
        # Ask if user wants to review/approve or go back
        print("\n" + "="*70)
        print("REVIEW & PROCEED")
        print("="*70)
        print("  (y/Enter) Proceed with attaching PDF to this item")
        print("  (e) Edit metadata in Zotero first")
        print("  (z) Go back to item selection")
        print("="*70)
        
        while True:
            choice = input("\nProceed or edit? [y/e/z]: ").strip().lower()
            
            # Enter (empty string) always proceeds (acts as 'y')
            if not choice:
                choice = 'y'
            
            if choice == 'z':
                print("⬅️  Going back to item selection")
                return
            elif choice == 'e':
                # User wants to edit tags - offer interactive tag editing
                item_key = selected_item.get('key') or selected_item.get('item_key')
                if not item_key:
                    print("❌ No item key found - cannot edit tags")
                    print("ℹ️  Please edit this item in Zotero, then process the scan again")
                    self.move_to_manual_review(pdf_path)
                    return
                
                # Get current tags from the item (local search returns tags as strings)
                current_tags_raw = selected_item.get('tags', [])
                # Convert to dict format for edit_tags_interactively if needed
                # edit_tags_interactively expects dict format, but returns dict format
                current_tags = [{'tag': tag} if isinstance(tag, str) else tag for tag in current_tags_raw]
                
                # Offer tag editing
                print("\n🏷️  EDIT TAGS")
                print("="*70)
                print("You can edit tags for this Zotero item.")
                print("  (t) Edit tags interactively")
                print("  (z) Go back (don't edit)")
                print("  (m) Move to manual review (edit in Zotero directly)")
                print("="*70)
                
                edit_choice = input("\nChoose edit option [t/z/m]: ").strip().lower()
                
                if edit_choice == 'z':
                    # Go back to proceed/edit menu
                    continue
                elif edit_choice == 'm':
                    # User wants to edit in Zotero directly
                    print("ℹ️  Please edit this item in Zotero, then process the scan again")
                    self.move_to_manual_review(pdf_path)
                    return
                elif edit_choice == 't':
                    # Edit tags interactively
                    print("\n✏️  Editing tags...")
                    updated_tags = self.edit_tags_interactively(current_tags=current_tags)
                    
                    # Extract tag names from both lists for comparison
                    # Both should be in dict format now
                    current_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in current_tags]
                    updated_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in updated_tags]
                    
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
                            # Update selected_item with new tags for display
                            selected_item['tags'] = updated_tags
                        else:
                            print("⚠️  Failed to update tags in Zotero")
                            retry = input("Continue anyway? [y/N]: ").strip().lower()
                            if retry != 'y':
                                return
                    else:
                        print("ℹ️  No tag changes to save")
                    
                    # After editing tags, ask if they want to proceed
                    print("\n" + "="*70)
                    proceed = input("Proceed with PDF attachment? [Y/n]: ").strip().lower()
                    if proceed == 'n':
                        print("⬅️  Going back...")
                        continue
                    # Otherwise break and continue with attachment
                    break
                else:
                    print("⚠️  Invalid choice, going back...")
                    continue
            elif choice == 'y':
                # Continue with attachment
                break
            else:
                print("⚠️  Invalid choice. Please enter 'y' to proceed, 'e' to edit, or 'z' to go back.")
        
        print()
        
        # Get scan file info
        scan_size_mb = pdf_path.stat().st_size / 1024 / 1024
        
        # CRITICAL: Use ONLY Zotero metadata for filename generation
        # When attaching to existing Zotero item, Zotero metadata is canonical
        # Fallback to scan metadata only causes incorrect filenames like "P_et_al_Unknown_..."
        
        # Extract metadata from Zotero item (authors already extracted in _display_zotero_item_details)
        zotero_authors = selected_item.get('authors', [])
        zotero_title = selected_item.get('title', '')
        zotero_year = selected_item.get('year', selected_item.get('date', ''))
        zotero_item_type = selected_item.get('itemType', 'journalArticle')
        
        # Validate critical fields
        missing_fields = []
        if not zotero_title:
            missing_fields.append('title')
        if not zotero_authors:
            missing_fields.append('authors')
        
        # Show warning if critical fields missing
        if missing_fields:
            print(f"⚠️  WARNING: Zotero item missing: {', '.join(missing_fields)}")
            print("   Cannot generate proper filename without this information.")
            print("   Please edit Zotero item metadata or choose manual processing.")
            confirm_anyway = input("Proceed anyway with placeholder values? [y/n]: ").strip().lower()
            if confirm_anyway != 'y':
                self.move_to_manual_review(pdf_path)
                return
            # Set placeholders
            if 'title' in missing_fields:
                zotero_title = 'Unknown_Title'
            if 'authors' in missing_fields:
                zotero_authors = ['Unknown_Author']
        
        # Build metadata using ONLY Zotero data
        merged_metadata = {
            'title': zotero_title,
            'authors': zotero_authors,
            'year': zotero_year if zotero_year else 'Unknown',
            'document_type': zotero_item_type
        }
        
        # Generate target filename with _scan suffix
        filename_gen = FilenameGenerator()
        target_filename = filename_gen.generate(merged_metadata, is_scan=True) + '.pdf'
        
        # Show what authors will be used in filename
        if zotero_authors:
            author_display = '_'.join([a.split()[-1] if ' ' in a else a for a in zotero_authors[:2]])
            print(f"📝 Filename will use authors: {author_display}")
            print()
        
        # Show filename preview before confirmation
        print(f"📄 Generated filename: {target_filename}")
        print()
        
        # Show PDF comparison if item already has PDF
        if has_pdf:
            existing_pdf_info = self._get_existing_pdf_info(selected_item)
            self._display_pdf_comparison(pdf_path, scan_size_mb, existing_pdf_info)
        
        # Show proposed actions
        print("="*70)
        print("PROPOSED ACTIONS:")
        print("="*70)
        print(f"Scan: {pdf_path.name} ({scan_size_mb:.1f} MB)")
        print()
        print("Will perform:")
        print(f"  1. Generate filename: {target_filename}")
        print(f"  2. Copy to publications: {self.publications_dir.name}/")
        print(f"  3. Attach as linked file in Zotero")
        print(f"  4. Move scan to: done/")
        print("="*70)
        print()
        print("  (y/Enter) Proceed with all actions")
        print("  (n) Cancel - move to manual review")
        print("  (skip) Move to manual review")
        print("  (z) Go back to item selection")
        print()
        
        # Ask for confirmation
        confirm = input("Proceed with these actions? [y/n/skip/z]: ").strip().lower()
        
        # Enter (empty string) always proceeds (acts as 'y')
        if not confirm:
            confirm = 'y'
        
        if confirm == 'y' or confirm == 'yes':
            # Execute the actions
            self._process_selected_item(pdf_path, selected_item, target_filename, metadata)
        elif confirm == 'skip' or confirm == 's':
            print("📝 Moving to manual review")
            self.move_to_manual_review(pdf_path)
        elif confirm == 'z':
            print("⬅️  Going back to item selection")
            self.move_to_manual_review(pdf_path)
        else:
            print("❌ Cancelled - moving to manual review")
            self.move_to_manual_review(pdf_path)
    
    def _process_selected_item(self, pdf_path: Path, zotero_item: dict, target_filename: str, metadata: dict = None):
        """Process selected Zotero item: copy PDF and attach.
        
        Steps:
        1. Check if PDF should be split for Zotero attachment
        2. Copy PDF to publications directory (via PowerShell)
        3. Attach as linked file in Zotero
        4. Update URL field if missing and available
        5. Move scan to done/
        
        Args:
            pdf_path: Path to scanned PDF
            zotero_item: Selected Zotero item dict
            target_filename: Generated filename for publications dir
            metadata: Extracted metadata (optional, may contain URL to add)
        """
        item_key = zotero_item.get('key') or zotero_item.get('item_key')
        if not item_key:
            print("❌ No item key found")
            self.move_to_failed(pdf_path)
            return
        
        print("\n📋 Executing actions...")
        
        # Step 1: Determine which PDF to use (original or split)
        pdf_to_copy = pdf_path
        name_lower = pdf_path.name.lower()
        split_result = None
        
        if name_lower.endswith('_double.pdf'):
            # Always split on _double.pdf
            print(f"1/4 Preparing split for two-up file...")
            split_result = self._split_with_mutool(pdf_path)
            if split_result:
                pdf_to_copy = split_result
                self.logger.info(f"Using split version for Zotero: {split_result.name}")
            else:
                print("⚠️  Splitting the PDF did fail. Using the original in landscape format.")
        else:
            # Check if we should prompt for split on wide pages
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pdf:
                    if len(pdf.pages) > 0:
                        first = pdf.pages[0]
                        width, height = first.width, first.height
                        if width and height and width / max(1.0, height) > 1.3:
                            is_two_up, score, mode = self._detect_two_up_page(pdf_path)
                            if is_two_up:
                                print("\nTwo-up candidate detected:")
                                print(f"  Aspect ratio: {width/height:.2f}")
                                print(f"  Center structure: {mode} score={score:.2f}")
                                choice = input("Split this file into single pages before attaching to Zotero? [y/N]: ").strip().lower()
                                if choice == 'y':
                                    split_result = self._split_with_mutool(pdf_path, width=width, height=height)
                                    if split_result:
                                        pdf_to_copy = split_result
                                        self.logger.info(f"Using split version for Zotero: {split_result.name}")
                                    else:
                                        print("⚠️  Splitting the PDF did fail. Using the original in landscape format.")
            except Exception as e:
                self.logger.debug(f"Two-up detection skipped: {e}")
                pass
        
        # Step 1b: For book chapters, offer to delete page 1 after splitting
        if split_result and metadata and metadata.get('document_type', '').lower() == 'book_chapter':
            print("\nThis is a book chapter. After splitting, page 1 is typically blank.")
            print("For book chapters, the first content page is usually page 2.")
            choice = input("Delete page 1 from the split PDF? [y/N]: ").strip().lower()
            if choice == 'y':
                modified_pdf = self._delete_first_page_from_pdf(pdf_to_copy)
                if modified_pdf:
                    pdf_to_copy = modified_pdf
                    self.logger.info(f"Using PDF without page 1: {modified_pdf.name}")
                    print("✅ Page 1 deleted from split PDF")
                else:
                    print("⚠️  Failed to delete page 1 - using original split PDF")
        
        # Step 1c: Check and optionally remove dark borders
        border_removed_pdf = self._check_and_remove_dark_borders(pdf_to_copy)
        if border_removed_pdf:
            pdf_to_copy = border_removed_pdf
            self.logger.debug(f"Using PDF without borders: {border_removed_pdf.name}")
        
        # Step 2: Copy to publications directory via PowerShell
        print(f"2/4 Copying to publications directory...")
        success, target_path, error = self._copy_to_publications_via_windows(pdf_to_copy, target_filename)
        
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
            
        except Exception as e:
            print(f"❌ Zotero attachment error: {e}")
            print(f"⚠️  PDF copied but not attached: {target_path}")
            print("📝 Moving scan to manual review")
            self.logger.error(f"Zotero attachment error: {e}")
            self.move_to_manual_review(pdf_path)
            return
        
        # Step 4: Move scan to done/
        print(f"4/4 Moving scan to done/...")
        try:
            done_dir = pdf_path.parent / 'done'
            done_dir.mkdir(exist_ok=True)
            dest = done_dir / pdf_path.name
            
            pdf_path.rename(dest)
            self.logger.debug(f"Moved to done: {dest}")
            print(f"✅ Moved to done/")
            
        except Exception as e:
            print(f"⚠️  Failed to move to done/: {e}")
            self.logger.error(f"Failed to move to done: {e}")
        
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
                # Look for files starting with Author_Year
                search_pattern = f"{author_lastname}_{year}"
                matching_files = list(self.publications_dir.glob(f"{search_pattern}*.pdf"))
                
                if matching_files:
                    # Return the first match (most likely the same file)
                    found_path = matching_files[0]
                    stat = found_path.stat()
                    return {
                        'path': found_path,
                        'size_mb': stat.st_size / 1024 / 1024,
                        'modified': stat.st_mtime,
                        'filename': found_path.name,
                        'fuzzy_match': True  # Flag this as fuzzy match
                    }
        except Exception as e:
            self.logger.debug(f"Could not locate existing PDF: {e}")
        
        return {}
    
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
        
        # Process the paper
        self.daemon.logger.info("")
        self.daemon.logger.info("-"*60)
        self.daemon.process_paper(file_path)
        self.daemon.logger.info("-"*60)
        self.daemon.logger.info("Ready for next scan")


def normalize_path_for_wsl(path_str: str) -> str:
    """Normalize a path string to WSL format (standalone function for main).
    
    Handles both WSL paths (/mnt/c/...) and Windows paths (C:\...)
    - Windows paths like "G:\My Drive\publications" -> "/mnt/g/My Drive/publications"
    - WSL paths already in correct format are returned as-is
    
    Args:
        path_str: Path string that may be in WSL or Windows format
        
    Returns:
        Normalized WSL path string
    """
    # If already a WSL path (starts with /), return as-is
    if path_str.startswith('/'):
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
            return wsl_path
    
    # If no clear format, return as-is
    return path_str


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

