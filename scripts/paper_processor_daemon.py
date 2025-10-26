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
import subprocess
import socket
import threading
from pathlib import Path
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
from shared_tools.zotero.local_search import ZoteroLocalSearch


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
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent
        
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        # Get publications directory
        self.publications_dir = Path(config.get('PATHS', 'publications_dir', 
                                                 fallback='/mnt/g/My Drive/publications'))
        
        # Get Ollama configuration
        self.ollama_auto_start = config.getboolean('OLLAMA', 'auto_start', fallback=True)
        self.ollama_auto_stop = config.getboolean('OLLAMA', 'auto_stop', fallback=True)
        self.ollama_startup_timeout = config.getint('OLLAMA', 'startup_timeout', fallback=30)
        self.ollama_shutdown_timeout = config.getint('OLLAMA', 'shutdown_timeout', fallback=10)
        self.ollama_port = config.getint('OLLAMA', 'port', fallback=11434)
        
        # Get GROBID configuration
        self.grobid_auto_start = config.getboolean('GROBID', 'auto_start', fallback=True)
        self.grobid_auto_stop = config.getboolean('GROBID', 'auto_stop', fallback=True)
        self.grobid_container_name = config.get('GROBID', 'container_name', fallback='grobid')
        self.grobid_port = config.getint('GROBID', 'port', fallback=8070)
        self.grobid_max_pages = config.getint('GROBID', 'max_pages', fallback=2)
        
        # Check if publications directory is accessible
        self._validate_publications_directory()
    
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
        
        logging.basicConfig(
            level=log_level,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
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
                # Create new container
                print(f"    🐳 Creating new GROBID container...")
                result = subprocess.run([
                    'docker', 'run', '-d', 
                    '--name', self.grobid_container_name,
                    '-p', f'{self.grobid_port}:8070',
                    'lfoppiano/grobid:0.8.2'
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
        
        print("\nEXTRACTED METADATA:")
        print("-" * 40)
        
        # Universal field display using smart grouping
        self._display_metadata_universal(metadata)
        
        print("-" * 40)
    
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
        print("[q] Quit daemon")
        print()
        
        while True:
            choice = input("Your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', 'q']:
                return choice
            else:
                print("Invalid choice. Please try again.")
    
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
        print("[q] Quit daemon")
        print()
        
        while True:
            choice = input("Your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', 'q']:
                return choice
            else:
                print("Invalid choice. Please try again.")
    
    def search_and_display_local_zotero(self, metadata: dict) -> list:
        """Search local Zotero database and display matches.
        
        SAFETY: This method only performs READ operations on the database.
        No write operations are possible.
        
        Args:
            metadata: Metadata to search with
            
        Returns:
            List of matching Zotero items
        """
        if not self.local_zotero:
            print("❌ Zotero database not available")
            return []
        
        print("\n🔍 Searching live Zotero database (read-only)...")
        
        try:
            matches = self.local_zotero.search_by_metadata(metadata, max_matches=5)
            
            if not matches:
                print("❌ No matches found in local Zotero database")
                return []
            
            print(f"\n✅ Found {len(matches)} potential match(es):")
            print()
            
            for i, match in enumerate(matches, 1):
                print(f"[{i}] {match.get('title', 'Unknown title')}")
                
                authors = match.get('authors', [])
                if authors:
                    author_str = ', '.join(authors[:2])
                    if len(authors) > 2:
                        author_str += f" et al."
                    print(f"    Authors: {author_str}")
                
                print(f"    Year: {match.get('year', 'Unknown')}")
                print(f"    Similarity: {match.get('similarity', 0):.1f}%")
                print(f"    Method: {match.get('method', 'Unknown')}")
                
                # Check for existing PDF
                has_pdf = match.get('has_attachment', False)
                print(f"    PDF: {'✅ Yes' if has_pdf else '❌ No'}")
                
                if match.get('DOI'):
                    print(f"    DOI: {match['DOI']}")
                
                print()
            
            return matches
            
        except Exception as e:
            self.logger.error(f"Error searching Zotero database: {e}")
            print("❌ Error searching Zotero database")
            return []
    
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
        
        confirm = input("Use this filename? (y/n): ").strip().lower()
        if confirm != 'y':
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
            # No online metadata AND no local metadata
            print("\n❌ NO METADATA SOURCES AVAILABLE")
            print("There is no matching zotero item, nor can any metadata match be found online.")
            print("Please process this file manually. It can be a case of seldom document type or bad scan.")
            print()
            # Return unchanged metadata - caller should move to manual processing
            return metadata
        
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
        new_value = input("New authors (comma-separated, or Enter to keep current): ").strip()
        if new_value:
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
        new_value = input("New journal/source (or Enter to keep current): ").strip()
        if new_value:
            edited['journal'] = new_value
        elif online_metadata and online_metadata.get('journal') and not edited.get('journal'):
            edited['journal'] = online_metadata['journal']
            print(f"✅ Auto-filled from online: {online_metadata['journal']}")
        elif local_metadata and local_metadata.get('journal') and not edited.get('journal'):
            edited['journal'] = local_metadata['journal']
            print(f"✅ Auto-filled from local: {local_metadata['journal']}")
        
        # DOI
        display_field_with_sources(
            "DOI",
            edited.get('doi', ''),
            online_metadata.get('doi') if online_metadata else None,
            local_metadata.get('doi') if local_metadata else None
        )
        new_value = input("New DOI (or Enter to keep current): ").strip()
        if new_value:
            edited['doi'] = new_value
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
        
        print("\n✅ Metadata editing complete")
        print()
        
        # Show summary
        print("Updated metadata:")
        print(f"  Title: {edited.get('title', 'Unknown')}")
        print(f"  Authors: {', '.join(edited.get('authors', ['Unknown']))}")
        print(f"  Year: {edited.get('year', 'Unknown')}")
        print(f"  Journal: {edited.get('journal', 'Unknown')}")
        print(f"  DOI: {edited.get('doi', 'Unknown')}")
        print(f"  Type: {edited.get('document_type', 'unknown')}")
        if edited.get('abstract'):
            abstract_preview = edited['abstract'][:100] + "..." if len(edited['abstract']) > 100 else edited['abstract']
            print(f"  Abstract: {abstract_preview}")
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
                    # Parse comma-separated tags
                    tags = [tag.strip() for tag in value.split(',') if tag.strip()]
                    tag_groups[key] = tags
        except Exception as e:
            self.logger.warning(f"Could not load tag groups: {e}")
        
        return tag_groups
    
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
            group1_tags = ', '.join(self.tag_groups.get('group1', [])) or '(empty)'
            group2_tags = ', '.join(self.tag_groups.get('group2', [])) or '(empty)'
            group3_tags = ', '.join(self.tag_groups.get('group3', [])) or '(empty)'
            
            print("  (s) Skip tag editing")
            print(f"  1. Add tag group 1: {group1_tags}")
            print(f"  2. Add tag group 2: {group2_tags}")
            print(f"  3. Add tag group 3: {group3_tags}")
            print("  4. Add online metadata tags")
            print("  5. Add local Zotero tags")
            print("  6. Add custom tag")
            print("  7. Remove specific tag")
            print("  8. Clear all tags")
            print("  9. Show tag group details")
            print("  (d) Save and add to Zotero")
            print("=" * 60)
            print(f"📋 FINAL TAGS: {', '.join(working_tags) if working_tags else '(none)'}")
            
            choice = input("\nEnter your choice: ").strip().lower()
            
            if choice == 'd':
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
    
    def _add_tag_group(self, working_tags: list, group_name: str) -> list:
        """Add tags from a configured tag group."""
        group_tags = self.tag_groups.get(group_name, [])
        if not group_tags:
            print(f"❌ No tags configured for {group_name}")
            return working_tags
        
        print(f"\n📋 {group_name.upper()} TAGS: {', '.join(group_tags)}")
        confirm = input("Add these tags? (y/n): ").strip().lower()
        
        if confirm == 'y':
            # Add tags without duplicates
            for tag in group_tags:
                if tag not in working_tags:
                    working_tags.append(tag)
            print(f"✅ Added {group_name} tags")
        else:
            print("❌ Tag group not added")
        
        return working_tags
    
    def _add_online_tags(self, working_tags: list, online_tag_names: list) -> list:
        """Add tags from online metadata."""
        if not online_tag_names:
            print("❌ No online tags available")
            return working_tags
        
        print(f"\n📋 ONLINE TAGS: {', '.join(online_tag_names)}")
        confirm = input("Add these tags? (y/n): ").strip().lower()
        
        if confirm == 'y':
            for tag in online_tag_names:
                if tag not in working_tags:
                    working_tags.append(tag)
            print("✅ Added online tags")
        else:
            print("❌ Online tags not added")
        
        return working_tags
    
    def _add_local_tags(self, working_tags: list, local_tag_names: list) -> list:
        """Add tags from local Zotero metadata."""
        if not local_tag_names:
            print("❌ No local tags available")
            return working_tags
        
        print(f"\n📋 LOCAL TAGS: {', '.join(local_tag_names)}")
        confirm = input("Add these tags? (y/n): ").strip().lower()
        
        if confirm == 'y':
            for tag in local_tag_names:
                if tag not in working_tags:
                    working_tags.append(tag)
            print("✅ Added local tags")
        else:
            print("❌ Local tags not added")
        
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
        prefixes = ['NO_', 'EN_', 'DE_']
        return any(filename.startswith(p) for p in prefixes)
    
    def process_paper(self, pdf_path: Path):
        """Process a single paper with full user interaction.
        
        Args:
            pdf_path: Path to PDF file
        """
        self.logger.info(f"New scan: {pdf_path.name}")
        
        try:
            # Step 1: Extract metadata
            self.logger.info("Extracting metadata...")
            
            # Try GROBID first (fast and accurate)
            if self.grobid_ready:
                self.logger.info("Using GROBID for metadata extraction...")
                metadata = self.grobid_client.extract_metadata(pdf_path)
                
                if metadata and metadata.get('authors'):
                    # GROBID succeeded
                    result = {
                        'success': True,
                        'metadata': metadata,
                        'method': 'grobid',
                        'processing_time_seconds': 0  # GROBID is fast
                    }
                    self.logger.info(f"✅ GROBID extracted: {len(metadata.get('authors', []))} authors")
                else:
                    # GROBID failed - try other methods
                    self.logger.info("GROBID failed - trying other extraction methods...")
                    result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=False)
            else:
                # GROBID not available - use other methods
                self.logger.info("GROBID not available - using other extraction methods...")
                result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=False)
            
            # If still no authors found, try Ollama as last resort
            if not result['success'] or not result.get('metadata', {}).get('authors'):
                self.logger.info("No authors found - trying Ollama as last resort...")
                if self._ensure_ollama_ready():
                    # Try with Ollama fallback
                    ollama_result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=True, 
                                                                       progress_callback=self._show_ollama_progress)
                    if ollama_result['success'] and ollama_result.get('metadata', {}).get('authors'):
                        result = ollama_result
                        self.logger.info("✅ Ollama found authors")
                    else:
                        self.logger.warning("Ollama also failed to find authors")
                else:
                    self.logger.warning("Ollama not available - limited extraction methods only")
            
            extraction_time = result.get('processing_time_seconds', 0)
            
            # Step 2: Check if extraction succeeded
            if result['success'] and result['metadata']:
                metadata = result['metadata']
                self.display_metadata(metadata, pdf_path, extraction_time)
            else:
                # Extraction failed - use guided workflow
                self.logger.warning("Metadata extraction failed - starting guided workflow")
                metadata = self.handle_failed_extraction(pdf_path)
                
                if metadata:
                    # Display what we gathered
                    self.display_metadata(metadata, pdf_path, extraction_time)
                else:
                    # User gave up
                    self.move_to_failed(pdf_path)
                    self.logger.info("User cancelled - moved to failed/")
                    return
            
            # Step 3: Search local Zotero for matches
            local_matches = []
            if self.local_zotero:
                local_matches = self.search_and_display_local_zotero(metadata)
            
            # Step 4: Show context-aware menu based on what we found
            if local_matches:
                # Found Zotero matches - show attachment-focused menu
                choice = self.display_zotero_match_menu()
            else:
                # No matches - show standard menu
                choice = self.display_interactive_menu()
            
            # Step 5: Handle user choice based on context
            self.handle_user_choice(choice, pdf_path, metadata, local_matches, result)
            
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
        done_dir = self.watch_dir / "done"
        done_dir.mkdir(exist_ok=True)
        
        dest = done_dir / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        self.logger.debug(f"Moved to done/")
    
    def move_to_failed(self, pdf_path: Path):
        """Move failed PDF to failed/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        failed_dir = self.watch_dir / "failed"
        failed_dir.mkdir(exist_ok=True)
        
        dest = failed_dir / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        self.logger.info(f"Moved to failed/")
    
    def move_to_skipped(self, pdf_path: Path):
        """Move non-academic PDF to skipped/ directory.
        
        Args:
            pdf_path: PDF to move
        """
        skipped_dir = self.watch_dir / "skipped"
        skipped_dir.mkdir(exist_ok=True)
        
        dest = skipped_dir / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        self.logger.info(f"Moved to skipped/")
    
    def start(self):
        """Start the daemon."""
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
        print("[5] 📝 Manual processing later (too similar to decide)")
        print("[6] 📄 Create new Zotero item from extracted metadata")
        print()
        
        while True:
            choice = input("Your choice: ").strip()
            if choice in ['1', '2', '3', '4', '5', '6']:
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
            print("📝 Moving to manual processing...")
            return None  # Signal to stop processing
            
        elif choice == '6':
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
        
        # Check if item already has PDF
        has_pdf = zotero_item.get('hasAttachment', False)
        
        if has_pdf:
            print("⚠️  This Zotero item already has a PDF attachment")
            print("\nWhat would you like to do?")
            print("[1] Keep both (add scanned version)")
            print("[2] Replace existing PDF with scan")
            print("[3] Cancel (keep original)")
            
            pdf_choice = input("\nChoice: ").strip()
            
            if pdf_choice == '3':
                self.move_to_done(pdf_path)
                print("✅ Cancelled - kept original PDF in Zotero")
                return True
            
            # For options 1 and 2, we'll proceed with attachment
            attach_type = "additional" if pdf_choice == '1' else "replacement"
            print(f"📎 Adding as {attach_type} attachment...")
        
        # Generate filename for publications directory using final metadata
        # (which includes user's choices from metadata comparison step)
        proposed_filename = self.generate_filename(metadata)
        
        print(f"\n📄 Proposed filename: {proposed_filename}")
        confirm = input("Use this filename? (y/n): ").strip().lower()
        if confirm != 'y':
            new_name = input("Enter custom filename (without .pdf): ").strip()
            if new_name:
                proposed_filename = f"{new_name}.pdf"
            else:
                print("❌ Cancelled")
                return False
        
        # Copy to publications directory
        final_path = self.publications_dir / proposed_filename
        
        # Handle duplicates
        if final_path.exists():
            print(f"\n⚠️  File already exists: {proposed_filename}")
            stem = final_path.stem
            final_path = self.publications_dir / f"{stem}_scanned{final_path.suffix}"
            print(f"Using: {final_path.name}")
        
        try:
            shutil.copy2(str(pdf_path), str(final_path))
            print(f"✅ Copied to: {final_path}")
            
            # Attach to Zotero
            print("📖 Attaching to Zotero item...")
            attach_result = self.zotero_processor.attach_pdf_to_existing(item_key, final_path)
            
            if attach_result:
                print("✅ PDF attached to Zotero item")
            else:
                print("⚠️  Could not attach PDF to Zotero (but file copied)")
            
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
        manual_dir = self.watch_dir / "manual_review"
        manual_dir.mkdir(exist_ok=True)
        
        dest = manual_dir / pdf_path.name
        shutil.move(str(pdf_path), str(dest))
        self.logger.info(f"Moved to manual review: {dest}")
        print(f"📝 Moved to manual review: {dest}")


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


def main():
    """Main entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Paper processor daemon")
    parser.add_argument("--debug", action="store_true", help="Enable debug logging")
    args = parser.parse_args()
    
    # Get watch directory from config
    config = configparser.ConfigParser()
    root_dir = Path(__file__).parent.parent
    config.read([
        root_dir / 'config.conf',
        root_dir / 'config.personal.conf'
    ])
    
    watch_dir = Path(config.get('PATHS', 'scanner_papers_dir', 
                                 fallback='/mnt/i/FraScanner/papers'))
    
    if not watch_dir.exists():
        print(f"Error: Watch directory not found: {watch_dir}")
        sys.exit(1)
    
    daemon = PaperProcessorDaemon(watch_dir, debug=args.debug)
    daemon.start()


if __name__ == "__main__":
    main()

