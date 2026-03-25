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
import queue
import re
from pathlib import Path
try:
    import select
    # On Windows, select() only works with sockets; using it on sys.stdin causes
    # OSError [WinError 10038]. Treat select-as-available only on non-Windows.
    HAS_SELECT = sys.platform != "win32"
except ImportError:
    HAS_SELECT = False
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
from shared_tools.zotero.local_search import ZoteroLocalSearch
from shared_tools.utils.filename_generator import FilenameGenerator
from shared_tools.utils.author_extractor import AuthorExtractor
from shared_tools.utils.grobid_validator import GrobidValidator
from shared_tools.utils.author_filter import AuthorFilter
from shared_tools.utils.author_filter import AuthorFilter
from shared_tools.metadata.enrichment_policy import MatchPolicy, MatchPolicyConfig
from shared_tools.metadata.enrichment_planner import EnrichmentPlanner
from shared_tools.daemon.enrichment_workflow import EnrichmentWorkflow
from shared_tools.daemon.enrichment_display import display_enrichment_summary

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
        # Platform flag: primary runtime is native Windows
        self.is_windows = (sys.platform == 'win32')
        
        # Setup logging first (needed for config loading)
        self.setup_logging()
        
        # Load configuration for publications directory
        self.load_config()
        
        # Initialize processors
        self.metadata_processor = PaperMetadataProcessor()
        self.zotero_processor = ZoteroPaperProcessor()
        self.enrichment_workflow = EnrichmentWorkflow(
            metadata_processor=self.metadata_processor,
            match_policy=MatchPolicy(self.enrichment_policy_config),
            planner=EnrichmentPlanner(self.enrichment_field_policy),
            logger=self.logger,
        )
        
        # Initialize book lookup service (for book chapters)
        self.book_lookup_service = DetailedISBNLookupService()
        
        # Initialize national library manager (for thesis, book chapters, books)
        self.national_library_manager = ConfigDrivenNationalLibraryManager()
        
        # Initialize border remover (for dark border removal from scanned PDFs)
        # Note: border_max_width is set in load_config() which is called before this
        self.border_remover = BorderRemover({'max_border_width': self.border_max_width})
        
        # Initialize content detector (for content-aware border removal and gutter detection)
        from shared_tools.pdf.content_detector import ContentDetector
        content_detector_config = {
            'gutter_min_percent': self.gutter_min_percent,
            'gutter_max_percent': self.gutter_max_percent
        }
        self.content_detector = ContentDetector(config=content_detector_config)
        
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
        self._pdf_viewer_path = None
        self._opened_pdf_paths: List[Path] = []
        
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
        
        # Store terminal window handle for PDF viewer positioning (Windows only)
        if self.is_windows:
            self._store_terminal_window_handle()
        else:
            self.logger.debug("Skipping terminal window handle storage on non-Windows platform")
        
        # Observer will be set in start()
        self.observer = None
        # Thread-safe queue for paper paths; only main thread calls process_paper()
        self._paper_queue = queue.Queue()
        # Guard async queue notices so watcher output never interrupts active prompts.
        self._queue_notice_lock = threading.Lock()
        self._processing_active = False
        self._deferred_scan_notices = 0
    
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
        self.ollama_container_name = self.config.get('OLLAMA', 'container_name', fallback='ollama-gpu')
        self.ollama_auto_start = self.config.getboolean('OLLAMA', 'auto_start', fallback=True)
        self.ollama_auto_stop = self.config.getboolean('OLLAMA', 'auto_stop', fallback=True)
        self.ollama_startup_timeout = self.config.getint('OLLAMA', 'startup_timeout', fallback=30)
        self.ollama_shutdown_timeout = self.config.getint('OLLAMA', 'shutdown_timeout', fallback=10)
        self.ollama_port = self.config.getint('OLLAMA', 'port', fallback=11434)
        self.ollama_base_url = self.config.get('OLLAMA', 'base_url', fallback='http://localhost:11434')
        
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
        
        # Get gutter detection configuration
        self.gutter_min_percent = self.config.getint('GUTTER', 'gutter_min_percent', fallback=40)
        self.gutter_max_percent = self.config.getint('GUTTER', 'gutter_max_percent', fallback=60)
        self.min_consistent_pages = self.config.getint('GUTTER', 'min_consistent_pages', fallback=2)
        
        # Get UX configuration
        self.page_offset_timeout = self.config.getint('UX', 'page_offset_timeout', fallback=10)
        self.prompt_timeout = self.config.getint('UX', 'prompt_timeout', fallback=10)

        # Enrichment policy configuration
        self.enrichment_policy_config, self.enrichment_field_policy = self._load_enrichment_settings()
        
        # Check if publications directory is accessible
        self._validate_publications_directory()
        
        # Get log folder path from config
        log_folder = self.config.get('PATHS', 'log_folder', fallback='./data/logs')
        log_folder_path = Path(self._normalize_path(log_folder))
        # Initialize scanned papers CSV logger
        log_file = log_folder_path / 'scanned_papers_log.csv'
        self.scanned_papers_logger = ScannedPapersLogger(log_file)
    
    def _load_enrichment_settings(self) -> Tuple[MatchPolicyConfig, Dict]:
        """Load enrichment policy and field policy from config files."""
        try:
            section = 'ENRICHMENT'
            auto_accept = self.config.getfloat(section, 'auto_accept_threshold', fallback=0.85)
            manual_review = self.config.getfloat(section, 'manual_review_threshold', fallback=0.75)
            lang_conf = self.config.getfloat(section, 'language_confidence_min', fallback=0.90)
            weight_title = self.config.getfloat(section, 'weight_title', fallback=0.45)
            weight_authors = self.config.getfloat(section, 'weight_authors', fallback=0.30)
            weight_year = self.config.getfloat(section, 'weight_year', fallback=0.15)
            weight_type = self.config.getfloat(section, 'weight_type', fallback=0.10)
            weight_language = self.config.getfloat(section, 'weight_language', fallback=0.05)

            policy_cfg = MatchPolicyConfig(
                auto_accept_threshold=auto_accept,
                manual_review_threshold=manual_review,
                language_confidence_min=lang_conf,
                weight_title=weight_title,
                weight_authors=weight_authors,
                weight_year=weight_year,
                weight_type=weight_type,
                weight_language=weight_language,
            )
        except Exception:
            policy_cfg = MatchPolicyConfig()

        field_policy_raw = self.config.get(
            'ENRICHMENT',
            'field_policy',
            fallback="",
        )
        field_policy: Dict[str, str] = {}
        if field_policy_raw:
            for pair in field_policy_raw.split(','):
                if ':' in pair:
                    key, val = pair.split(':', 1)
                    field_policy[key.strip()] = val.strip()

        return policy_cfg, field_policy

    @staticmethod
    def _normalize_path(path_str: str) -> str:
        """Normalize a path string according to the current platform.
        
        On WSL/Linux:
        - Windows paths like "G:\\My Drive\\publications" -> "/mnt/g/My Drive/publications"
        - WSL paths already in correct format are returned as-is
        
        On native Windows:
        - WSL-style paths like "/mnt/g/My Drive/publications" -> "G:\\My Drive\\publications"
        - Windows paths are returned as-is
        
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
        
        # Native Windows runtime: keep Windows paths, optionally convert WSL-style /mnt paths
        if sys.platform == 'win32':
            # Convert WSL-style paths (/mnt/g/...) back to Windows drive paths
            if path_str.startswith('/mnt/') and len(path_str) > 6:
                # /mnt/g/My Drive/publications -> G:\My Drive\publications
                drive_letter = path_str[5].upper()
                remainder = path_str[7:]  # strip "/mnt/x/"
                windows_path = f"{drive_letter}:\\" + remainder.replace('/', '\\')
                return windows_path
            # For other cases, return cleaned path as-is
            return path_str
        
        # WSL/Linux runtime: normalize everything to WSL-style paths
        # If already a WSL path (starts with /), normalize duplicate slashes and return
        if path_str.startswith('/'):
            while '//' in path_str:
                path_str = path_str.replace('//', '/')
            return path_str
        
        # If Windows path (contains : or starts with letter), convert to WSL
        if ':' in path_str or (len(path_str) > 1 and path_str[1].isalpha() and path_str[1] != ':'):
            # Handle Windows paths like "G:\\My Drive\\publications" or "G:/My Drive/publications"
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
            self.publications_access_mode = 'wsl'
            # Check if this is a cloud drive path (G: drive or other cloud drives)
            # Cloud drives are accessed via PowerShell, not directly from WSL
            path_str = str(self.publications_dir)
            is_cloud_drive = path_str.startswith('/mnt/g/') or 'My Drive' in path_str
            
            if is_cloud_drive:
                self.publications_access_mode = 'powershell'
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
                self.publications_access_mode = 'powershell'
                print(f"✅ Publications directory configured (cloud drive, will use PowerShell): {self.publications_dir}")
                return
            self._handle_missing_publications_directory()
    
    def _publications_use_powershell(self) -> bool:
        """Return True when publications dir is only accessible via PowerShell."""
        return getattr(self, 'publications_access_mode', 'wsl') == 'powershell'
    
    def _get_file_info_via_powershell(self, path: Path, with_hash: bool = False) -> Optional[Dict]:
        """Get file info for a path using PowerShell (cloud-drive safe)."""
        if sys.platform != 'win32':
            # PowerShell-based file info is only available on native Windows
            self.logger.debug("Skipping PowerShell file info lookup on non-Windows platform")
            return None
        try:
            ps_script_win = self._get_path_utils_script_win()
        except Exception as e:
            self.logger.debug(f"Failed to get path utils script path: {e}")
            return None
        
        path_str = str(path)
        if path_str.startswith('/'):
            try:
                path_str = self._convert_wsl_to_windows_path(path_str)
            except Exception as e:
                self.logger.debug(f"Failed to convert path for file info: {e}")
                return None
        
        cmd = [
            'powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win,
            'get-file-info', path_str
        ]
        if with_hash:
            cmd.append('-Hash')
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        except Exception as e:
            self.logger.debug(f"PowerShell get-file-info failed: {e}")
            return None
        
        if result.returncode != 0:
            self.logger.debug(f"PowerShell get-file-info error: {result.stderr}")
            return None
        
        try:
            info = json.loads(result.stdout.strip())
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'H6',
                        'location': 'paper_processor_daemon.py:_get_file_info_via_powershell',
                        'message': 'PowerShell file info result',
                        'data': {
                            'path': str(path),
                            'with_hash': bool(with_hash),
                            'exists': bool(info.get('exists')),
                            'is_file': bool(info.get('isFile')),
                            'size': info.get('size')
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            return info
        except Exception as e:
            self.logger.debug(f"Failed to parse get-file-info output: {e}")
            return None
    
    def _pub_exists(self, path: Path) -> bool:
        """Check if a publications file exists using the correct backend."""
        if self._publications_use_powershell():
            info = self._get_file_info_via_powershell(path, with_hash=False)
            return bool(info and info.get('exists') and info.get('isFile'))
        return path.exists()
    
    def _pub_stat_display(self, path: Path) -> Optional[str]:
        """Format stat info for conflict UI display."""
        if self._publications_use_powershell():
            info = self._get_file_info_via_powershell(path, with_hash=False)
            if not info or not info.get('exists'):
                return None
            size = info.get('size')
            ctime = info.get('ctime')
            if ctime:
                try:
                    from datetime import datetime
                    ctime_fmt = datetime.fromisoformat(ctime).strftime('%Y-%m-%d %H:%M:%S')
                except Exception:
                    ctime_fmt = ctime
            else:
                ctime_fmt = 'unknown'
            return f"{size} bytes, {ctime_fmt}"
        
        stat = os.stat(path)
        return f"{stat.st_size} bytes, {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(stat.st_ctime))}"
    
    def _pub_identical(self, source_path: Path, target_path: Path) -> bool:
        """Compare source and target using correct backend."""
        try:
            if not source_path.exists():
                return False
        except Exception:
            return False
        
        if self._publications_use_powershell():
            info = self._get_file_info_via_powershell(target_path, with_hash=True)
            if not info or not info.get('exists'):
                return False
            try:
                source_size = source_path.stat().st_size
            except Exception:
                return False
            if info.get('size') != source_size:
                return False
            target_hash = info.get('hash')
            if not target_hash:
                return False
            source_hash = self._sha256_file(source_path)
            return bool(source_hash) and source_hash == target_hash
        
        return self._are_files_identical(target_path, source_path)

    def _list_pdfs_in_publications(self) -> List[str]:
        """List all PDF files in publications directory using correct backend.
        
        Uses PowerShell for cloud drives, direct WSL access for local paths.
        
        Returns:
            List of PDF filenames (just names, not full paths)
        """
        pdf_files = []
        
        if self._publications_use_powershell():
            # Use PowerShell to list PDFs (for cloud drives)
            try:
                ps_script_win = self._get_path_utils_script_win()
                path_str = str(self.publications_dir)
                if path_str.startswith('/'):
                    path_str = self._convert_wsl_to_windows_path(path_str)
                
                cmd = ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', ps_script_win,
                       'list-pdfs', path_str]
                
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                
                if result.returncode == 0:
                    try:
                        result_data = json.loads(result.stdout.strip())
                        if result_data.get('success'):
                            pdf_files = result_data.get('pdf_files', [])
                        else:
                            error_msg = result_data.get('error', 'Unknown error')
                            self.logger.debug(f"PowerShell list-pdfs failed: {error_msg}")
                    except json.JSONDecodeError as e:
                        self.logger.debug(f"Failed to parse list-pdfs output: {e}")
                else:
                    self.logger.debug(f"PowerShell list-pdfs returned code {result.returncode}: {result.stderr}")
            except subprocess.TimeoutExpired:
                self.logger.warning("PowerShell list-pdfs timed out")
            except Exception as e:
                self.logger.debug(f"PowerShell list-pdfs exception: {e}")
        else:
            # Use WSL direct access (for local paths)
            try:
                if self.publications_dir.exists():
                    pdf_paths = list(self.publications_dir.glob("*.pdf"))
                    pdf_files = [p.name for p in pdf_paths]
            except Exception as e:
                self.logger.debug(f"WSL glob failed: {e}")
        
        return pdf_files

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
                self.publications_access_mode = 'wsl'
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
                self.publications_access_mode = 'wsl'
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
        """Start Ollama Docker container if it's not already running.
        
        Uses ServiceManager for centralized service management.
        
        This ensures the daemon can use Ollama for metadata extraction
        without requiring manual startup.
        """
        # Check if already ready
        if self.service_manager.ollama_ready:
            self.logger.info("✅ Ollama server is already running")
            return
        
        self.logger.info("🤖 Starting Ollama Docker container...")
        print("🤖 Starting Ollama Docker container...")
        
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
        """Stop Ollama Docker container if we started it.
        
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
        print(Colors.colorize(
            "Note: At this stage, no Zotero item has been created. "
            "The metadata above is used to search your existing Zotero library. "
            "A new Zotero item is only created later if you explicitly choose a 'create new Zotero item' option.",
            ColorScheme.ACTION
        ))
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
    
    def filter_garbage_authors(self, metadata: dict, pdf_path: Path = None, regex_authors: Optional[List[str]] = None) -> dict:
        """Filter out garbage authors, keeping only those found in Zotero and/or document text.
        
        When extraction quality is poor (e.g., regex fallback finds junk like
        "Working Paper", "Series Working", etc.), this filters to keep only
        real authors that exist in your Zotero collection.
        
        For GROBID authors, also validates against document text to filter hallucinations.
        
        This method delegates to the AuthorFilter module for reusable filtering logic.
        
        Args:
            metadata: Metadata dict with 'authors' field
            pdf_path: Optional path to PDF for document text validation (for GROBID hallucinations)
            
        Returns:
            Updated metadata dict with filtered authors
        """
        return AuthorFilter.filter_authors(
            metadata=metadata,
            pdf_path=pdf_path,
            author_validator=self.author_validator,
            logger=self.logger,
            regex_authors=regex_authors,
        )
    
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
                    for author_info in validation.get('weak_author_matches', []):
                        author_name = author_info.get('name', '')
                        author_display = Colors.colorize(author_name, color) if color else author_name
                        print(f"    ⚠️  {author_display} (possible Zotero match, unconfirmed)")
                        if author_info.get('alternatives'):
                            alts = ', '.join(author_info['alternatives'][:2])
                            print(f"       Possible matches: {alts}")
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
        print(Colors.colorize("[6] 🔍 Re-search CrossRef/OpenAlex with current metadata", ColorScheme.LIST))
        print(Colors.colorize("  (q) Quit daemon", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', '6', 'q']:
                return choice
            else:
                print("⚠️  Invalid choice. Please enter 1-6 or 'q' to quit.")
    
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
        print(Colors.colorize("[6] 🔍 Re-search CrossRef/OpenAlex with current metadata", ColorScheme.LIST))
        print(Colors.colorize("  (q) Quit daemon", ColorScheme.LIST))
        print()
        
        while True:
            choice = input("Enter your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', '6', 'q']:
                return choice
            else:
                print("⚠️  Invalid choice. Please enter 1-6 or 'q' to quit.")
    
    def search_and_display_local_zotero(self, metadata: dict, force_prompt_year: bool = False) -> tuple:
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
            force_prompt_year: If True, prompts for year even if one exists (allows changing)
            
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
            year_result = self.prompt_for_year(metadata, force_prompt=force_prompt_year)
            # Handle special return values
            if year_result == 'BACK':
                return ('back', None, metadata)
            elif year_result == 'RESTART':
                return ('restart', None, metadata)
            else:
                metadata = year_result  # Year was added/updated in metadata
            year = metadata.get('year', None)
            
            # Step 2: Determine available components for component-based search strategy
            has_author = bool(metadata.get('authors'))
            has_year = bool(year)
            has_title = bool(metadata.get('title'))
            has_doi = bool(metadata.get('doi'))
            
            # Preserve full author list for future re-search cycles
            if metadata.get('authors') and not metadata.get('_all_authors'):
                metadata['_all_authors'] = metadata['authors'].copy()
            
            # Step 3: Apply component-based search strategy
            search_matches = []
            search_info = ""
            used_components = []
            
            # Priority 1: Author + Year (highest priority - most reliable)
            if has_author and has_year:
                # Use current author-based search flow (most reliable)
                used_components = ["author", "year"]
                # Will continue to author selection and search below
                pass
            
            # Priority 2: Any two of three components
            elif has_author and has_title:
                # Author + Title
                print("\n🔍 Searching Zotero by author and title...")
                search_matches = self.local_zotero.search_by_metadata(metadata, max_matches=10)
                # #region agent log
                try:
                    import json as _json, time as _time, os as _os
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H2",
                            "location": "paper_processor_daemon.py:search_by_author_title",
                            "message": "search_return",
                            "data": {"count": len(search_matches) if search_matches is not None else None},
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                used_components = ["author", "title"]
                search_info = "by author and title"
                if year:
                    search_info += f" in {year}"
            
            elif has_title and has_year:
                # Title + Year
                print("\n🔍 Searching Zotero by title and year...")
                search_matches = self.local_zotero.search_by_metadata(metadata, max_matches=10)
                # #region agent log
                try:
                    import json as _json, time as _time, os as _os
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H2",
                            "location": "paper_processor_daemon.py:search_by_title_year",
                            "message": "search_return",
                            "data": {"count": len(search_matches) if search_matches is not None else None},
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                used_components = ["title", "year"]
                search_info = f"by title and year ({year})"
            
            # Priority 3: Title only
            elif has_title and not has_author and not has_year:
                # Title only
                print("\n🔍 Searching Zotero by title...")
                search_matches = self.local_zotero.search_by_metadata(metadata, max_matches=10)
                used_components = ["title"]
                search_info = "by title only"
            
            # Priority 4: Year only - cannot search effectively, prompt for author
            elif has_year and not has_author and not has_title:
                # Year only - prompt for author
                print("\n📝 No authors or title found - please provide author name")
                print("   (Cannot search effectively with year alone)")
                author_input = input("First author's last name (or 'z' to skip, 'r' to restart): ").strip()
                
                if author_input.lower() == 'r':
                    return ('restart', None, metadata)
                elif author_input.lower() == 'z':
                    print("❌ No authors provided - cannot search")
                    return ('none', None, metadata)
                elif author_input:
                    # Add author to metadata and continue with author+year search
                    metadata['authors'] = [author_input]
                    self.logger.info(f"User provided author: {author_input}")
                    has_author = True
                    used_components = ["author", "year"]
                    # Will continue to author selection and search below
                else:
                    print("❌ No authors provided - cannot search")
                    return ('none', None, metadata)
            
            # Priority 5: Author only
            elif has_author and not has_year and not has_title:
                # Author only - use current author-based search flow
                used_components = ["author"]
                # Will continue to author selection and search below
                pass
            
            # No usable components
            else:
                print("❌ No usable search components found (need at least title, or author+year)")
                return ('none', None, metadata)
            
            # Step 4: Display search results if we have matches from title-based searches
            if search_matches:
                if search_info:
                    print(f"   Found {len(search_matches)} potential match(es) {search_info}")
                
                # #region agent log
                try:
                    import json as _json, time as _time, os as _os
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H3",
                            "location": "paper_processor_daemon.py:before_display_matches",
                            "message": "display_call",
                            "data": {"count": len(search_matches)},
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion

                action, item = self.display_and_select_zotero_matches(search_matches, search_info)
                # #region agent log
                try:
                    import json as _json, time as _time, os as _os
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "H3",
                            "location": "paper_processor_daemon.py:after_display_matches",
                            "message": "display_return",
                            "data": {"action": action},
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                if action == 'select':
                    return (action, item, metadata)
                # If user doesn't select from matches, allow them to provide author for more refined search
                if not has_author:
                    print("\n💡 No match selected. You can provide author name for more refined search.")
                    author_input = input("First author's last name (or Enter to skip, 'r' to restart): ").strip()
                    
                    if author_input.lower() == 'r':
                        return ('restart', None, metadata)
                    elif author_input:
                        metadata['authors'] = [author_input]
                        self.logger.info(f"User provided author for refined search: {author_input}")
                        has_author = True
                        # Continue to author-based search below
                    else:
                        # User skipped - return with no selection
                        return ('none', None, metadata)
            else:
                # No matches from title/year search
                if not has_author:
                    print("\n💡 No matches found. You can provide author name for refined search.")
                    author_input = input("First author's last name (or Enter to skip, 'r' to restart): ").strip()
                    if author_input.lower() == 'r':
                        return ('restart', None, metadata)
                    elif author_input:
                        metadata['authors'] = [author_input]
                        self.logger.info(f"User provided author for refined search (no initial matches): {author_input}")
                        has_author = True
                    else:
                        return ('none', None, metadata)
            
            # Step 5: Author-based search (for Priority 1, Priority 4 with author provided, or Priority 5)
            if has_author:
                # If we already have authors from metadata, let user select which to use
                if metadata.get('authors'):
                    selected_authors = self.select_authors_for_search(metadata['authors'].copy())
                else:
                    # Authors were just provided above, use them directly
                    selected_authors = metadata.get('authors', [])
                
                # Check for back/restart commands
                if selected_authors == 'BACK':
                    # Restore full filtered author list if available
                    if metadata.get('_all_authors'):
                        metadata['authors'] = metadata['_all_authors'].copy()
                    return ('back', None, metadata)
                elif selected_authors == 'RESTART':
                    return ('restart', None, metadata)
                
                if not selected_authors:
                    print("❌ No authors selected")
                    return ('none', None, metadata)
                
                # Update metadata with edited/selected authors
                metadata['authors'] = selected_authors
                
                # Update _all_authors to include manually added authors
                if metadata.get('_all_authors'):
                    all_authors_set = set(metadata['_all_authors'])
                    selected_authors_set = set(selected_authors)
                    new_authors = selected_authors_set - all_authors_set
                    if new_authors:
                        metadata['_all_authors'].extend(list(new_authors))
                else:
                    metadata['_all_authors'] = selected_authors.copy()
                
                # Search by selected authors with year filter
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

                # If user selected an author we can already resolve exactly from Zotero,
                # avoid noisy broad surname-only fallback later.
                has_confirmed_selected_author = False
                if self.author_validator:
                    for selected_author in selected_authors:
                        try:
                            if self.author_validator.get_author_info(selected_author):
                                has_confirmed_selected_author = True
                                break
                        except Exception:
                            continue
                
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
                
                db_unavailable = False
                for spec in attempts:
                    target_year = spec['year']
                    target_type = spec['document_type']
                    if spec['notice']:
                        print(f"\n{spec['notice']}")
                    matches = self.local_zotero.search_by_authors_ordered(
                        author_lastnames,
                        year=target_year,
                        limit=10,
                        document_type=target_type,
                        target_doi=metadata.get('doi'),
                        target_url=metadata.get('url'),
                        target_title=metadata.get('title'),
                        target_year=year
                    )
                    if matches is None:
                        # DB locked/unavailable – stop ordered attempts
                        db_unavailable = True
                        print("\n⚠️  Zotero database is currently locked or unavailable – cannot search for existing items by ordered authors.")
                        break
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
                
                # Fallback: search broadly by first author's last name (only if DB available
                # and we do not already have a confirmed Zotero author identity).
                if author_lastnames and not db_unavailable and not has_confirmed_selected_author:
                    broad_name = author_lastnames[0]
                    print(f"\nℹ️  No ordered matches; searching broadly for last name '{broad_name}'...")
                    broad_matches = self.local_zotero.search_by_author(broad_name, limit=10)
                    if broad_matches is None:
                        db_unavailable = True
                        print("\n⚠️  Zotero database is currently locked or unavailable – cannot search for existing items by author.")
                    else:
                        normalized_broad = [self._normalize_search_result(item) for item in broad_matches]
                        if normalized_broad:
                            search_info = f"by last name {broad_name}"
                            action, item = self.display_and_select_zotero_matches(normalized_broad, search_info)
                            return (action, item, metadata)
                elif has_confirmed_selected_author:
                    print("\nℹ️  Skipping broad last-name fallback because selected author is already confirmed in Zotero.")
                
                if db_unavailable:
                    # Special flow: DB could not be queried at all
                    print("\n❌ Could not search Zotero items because the local Zotero database is locked or unavailable.")
                    print()
                    print(Colors.colorize("Options:", ColorScheme.ACTION))
                    print(Colors.colorize("[1] Try again later (restart search)", ColorScheme.LIST))
                    print(Colors.colorize("[2] Proceed to create new Zotero item using the current metadata (title, authors, year, DOI, etc.)", ColorScheme.LIST))
                    print(Colors.colorize("[3] Move to manual review", ColorScheme.LIST))
                    print(Colors.colorize("  (z) Back to previous step", ColorScheme.LIST))
                    print()
                    
                    while True:
                        final_choice = input("Enter your choice: ").strip().lower()
                        if final_choice == '1':
                            return ('search', None, metadata)
                        elif final_choice == '2':
                            return ('create', None, metadata)
                        elif final_choice == '3':
                            return ('manual', None, metadata)
                        elif final_choice == 'z':
                            return ('back', None, metadata)
                        else:
                            print("Invalid choice. Please enter 1, 2, 3, or 'z'.")
                    # Unreachable
                
                # Final metadata fallback before declaring no matches.
                # Keep this deterministic and compact: reuse existing metadata
                # search path (DOI/URL/title/year aware), then normalize display.
                metadata_fallback = {
                    'title': metadata.get('title'),
                    'authors': metadata.get('authors', []),
                    'year': metadata.get('year'),
                    'doi': metadata.get('doi'),
                    'url': metadata.get('url'),
                    'document_type': metadata.get('document_type'),
                }
                if any([metadata_fallback.get('doi'), metadata_fallback.get('url'), metadata_fallback.get('title')]):
                    print("\nℹ️  No author matches; trying metadata fallback (DOI/URL/title/year)...")
                    metadata_matches = self.local_zotero.search_by_metadata(metadata_fallback, max_matches=10)
                    if metadata_matches:
                        normalized_metadata_matches = [self._normalize_search_result(item) for item in metadata_matches]
                        if normalized_metadata_matches:
                            action, item = self.display_and_select_zotero_matches(
                                normalized_metadata_matches,
                                "by metadata fallback (DOI/URL/title/year)"
                            )
                            return (action, item, metadata)

                # No matches after all fallbacks
                print(f"\n❌ No matches found in Zotero after trying relaxed filters for: {author_display}")
                print()
                print(Colors.colorize("Options:", ColorScheme.ACTION))
                print(Colors.colorize("[1] Enter a different year and search again", ColorScheme.LIST))
                print(Colors.colorize("[2] Proceed to create new Zotero item using the current metadata (title, authors, year, DOI, etc.)", ColorScheme.LIST))
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
                        return ('manual', None, metadata)
                    elif final_choice == 'z':
                        return ('back', None, metadata)
                    else:
                        print("Invalid choice. Please enter 1, 2, 3, or 'z'.")
        # ... rest of function unchanged ...
                    normalized_broad = [self._normalize_search_result(item) for item in broad_matches]
                    if normalized_broad:
                        search_info = f"by last name {broad_name}"
                        action, item = self.display_and_select_zotero_matches(normalized_broad, search_info)
                        return (action, item, metadata)
                
                # Final metadata fallback before declaring no matches.
                metadata_fallback = {
                    'title': metadata.get('title'),
                    'authors': metadata.get('authors', []),
                    'year': metadata.get('year'),
                    'doi': metadata.get('doi'),
                    'url': metadata.get('url'),
                    'document_type': metadata.get('document_type'),
                }
                if any([metadata_fallback.get('doi'), metadata_fallback.get('url'), metadata_fallback.get('title')]):
                    print("\nℹ️  No author matches; trying metadata fallback (DOI/URL/title/year)...")
                    metadata_matches = self.local_zotero.search_by_metadata(metadata_fallback, max_matches=10)
                    if metadata_matches:
                        normalized_metadata_matches = [self._normalize_search_result(item) for item in metadata_matches]
                        if normalized_metadata_matches:
                            action, item = self.display_and_select_zotero_matches(
                                normalized_metadata_matches,
                                "by metadata fallback (DOI/URL/title/year)"
                            )
                            return (action, item, metadata)

                # No matches after all fallbacks
                print(f"\n❌ No matches found in Zotero after trying relaxed filters for: {author_display}")
                print()
                print(Colors.colorize("Options:", ColorScheme.ACTION))
                print(Colors.colorize("[1] Enter a different year and search again", ColorScheme.LIST))
                print(Colors.colorize("[2] Proceed to create new Zotero item using the current metadata (title, authors, year, DOI, etc.)", ColorScheme.LIST))
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
        # Conversion helper is only meaningful on native Windows
        if sys.platform != 'win32':
            self.logger.debug("Skipping WSL-to-Windows path conversion via PowerShell on non-Windows platform")
            return wsl_path
        
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
        
        # Only supported on native Windows
        if sys.platform != 'win32':
            return (False, "PowerShell path validation is only available on Windows")
        
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
        source_exists = source_path.exists()
        # #region agent log
        try:
            import time as _time, json as _json
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'H1',
                    'location': 'paper_processor_daemon.py:_copy_file_universal:entry',
                    'message': 'Copy request received',
                    'data': {
                        'source_path': str(source_path),
                        'target_path': str(target_path),
                        'replace_existing': bool(replace_existing),
                        'source_exists': bool(source_exists)
                    },
                    'timestamp': int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        if not source_exists:
            return (False, f"Source file not found: {source_path}")
        
        # First, try native Python copy (fastest, works for most paths)
        try:
            # Ensure target directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Check if target exists and handle replacement
            if target_path.exists():
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'H2',
                            'location': 'paper_processor_daemon.py:_copy_file_universal:target-exists',
                            'message': 'Target exists before copy',
                            'data': {
                                'target_path': str(target_path),
                                'replace_existing': bool(replace_existing)
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
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
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'H3',
                        'location': 'paper_processor_daemon.py:_copy_file_universal:native-failed',
                        'message': 'Native copy failed, falling back to PowerShell',
                        'data': {
                            'error_type': type(e).__name__,
                            'error': str(e),
                            'source_path': str(source_path),
                            'target_path': str(target_path)
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            return self._copy_file_via_powershell(source_path, target_path, replace_existing)
        except Exception as e:
            # Other errors - try PowerShell as fallback
            self.logger.debug(f"Unexpected error in native copy ({e}), trying PowerShell fallback...")
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'H3',
                        'location': 'paper_processor_daemon.py:_copy_file_universal:native-error',
                        'message': 'Unexpected native copy error, falling back to PowerShell',
                        'data': {
                            'error_type': type(e).__name__,
                            'error': str(e),
                            'source_path': str(source_path),
                            'target_path': str(target_path)
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
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
        if sys.platform != 'win32':
            # Copying via PowerShell is only supported on Windows
            self.logger.debug("Skipping PowerShell-based copy on non-Windows platform")
            return (False, "PowerShell copy is only available on Windows")
        
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
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'H4',
                        'location': 'paper_processor_daemon.py:_copy_file_via_powershell:validated',
                        'message': 'PowerShell copy validation result',
                        'data': {
                            'source_path': str(source_path),
                            'target_path': str(target_path),
                            'source_valid': bool(is_valid),
                            'validation_error': error,
                            'replace_existing': bool(replace_existing)
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
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
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'H4',
                        'location': 'paper_processor_daemon.py:_copy_file_via_powershell:completed',
                        'message': 'PowerShell copy completed',
                        'data': {
                            'returncode': result.returncode,
                            'stdout_len': len(result.stdout or ''),
                            'stderr_len': len(result.stderr or '')
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
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
                        # #region agent log
                        try:
                            import time as _time, json as _json
                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                            with open(log_path, 'a', encoding='utf-8') as f:
                                f.write(_json.dumps({
                                    'sessionId': 'debug-session',
                                    'runId': 'run1',
                                    'hypothesisId': 'H4',
                                    'location': 'paper_processor_daemon.py:_copy_file_via_powershell:json-failure',
                                    'message': 'PowerShell copy reported failure',
                                    'data': {
                                        'error': result_data.get('error'),
                                        'error_code': result_data.get('errorCode'),
                                        'target_path': str(target_path)
                                    },
                                    'timestamp': int(_time.time() * 1000)
                                }) + '\n')
                        except Exception:
                            pass
                        # #endregion
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
                    error_code = result_data.get('errorCode', result.returncode)
                    error_msg = result_data.get('error', f'PowerShell copy failed with code {result.returncode}')
                    # #region agent log
                    try:
                        import time as _time, json as _json
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(_json.dumps({
                                'sessionId': 'debug-session',
                                'runId': 'run1',
                                'hypothesisId': 'H4',
                                'location': 'paper_processor_daemon.py:_copy_file_via_powershell:nonzero',
                                'message': 'PowerShell copy returned nonzero',
                                'data': {
                                    'returncode': result.returncode,
                                    'error': error_msg,
                                    'error_code': error_code,
                                    'target_path': str(target_path)
                                },
                                'timestamp': int(_time.time() * 1000)
                            }) + '\n')
                    except Exception:
                        pass
                    # #endregion
                    
                    # Special handling for error code 5 (target exists but differs)
                    if error_code == 5 or (result.returncode == 5 and 'Target exists but differs' in error_msg):
                        # Return a special error that caller can detect for conflict UI
                        return (False, f"CONFLICT:{error_msg}")
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
        manual_metadata = self.manual_metadata_entry(metadata, doc_type)
        # #region agent log
        try:
            import time as _time, json as _json
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'M1',
                    'location': 'paper_processor_daemon.py:handle_failed_extraction',
                    'message': 'Manual metadata entry result',
                    'data': {
                        'has_metadata': bool(manual_metadata),
                        'from_zotero': bool(manual_metadata.get('from_zotero')) if isinstance(manual_metadata, dict) else False,
                        'method': manual_metadata.get('method') if isinstance(manual_metadata, dict) else None,
                        'document_type': manual_metadata.get('document_type') if isinstance(manual_metadata, dict) else None
                    },
                    'timestamp': int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        if manual_metadata and not manual_metadata.get('_restart'):
            if manual_metadata.get('from_zotero'):
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'M6',
                            'location': 'paper_processor_daemon.py:handle_failed_extraction',
                            'message': 'Skipping _search_online_after_manual due to from_zotero',
                            'data': {
                                'from_zotero': True,
                                'method': manual_metadata.get('method'),
                                'document_type': manual_metadata.get('document_type')
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
                return manual_metadata
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'M2',
                        'location': 'paper_processor_daemon.py:handle_failed_extraction',
                        'message': 'Calling _search_online_after_manual',
                        'data': {
                            'from_zotero': bool(manual_metadata.get('from_zotero')),
                            'method': manual_metadata.get('method'),
                            'document_type': manual_metadata.get('document_type')
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            manual_metadata = self._search_online_after_manual(manual_metadata)
        return manual_metadata
    
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
            
            if author_matches is None:
                print("\n⚠️  Zotero database is currently locked or unavailable – cannot search for existing items by this author.")
            elif author_matches:
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
                        print(f"\\n✅ Using: {selected.get('title')}")
                        # #region agent log
                        try:
                            import time as _time, json as _json
                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                            with open(log_path, 'a', encoding='utf-8') as f:
                                f.write(_json.dumps({
                                    'sessionId': 'debug-session',
                                    'runId': 'run1',
                                    'hypothesisId': 'M3',
                                    'location': 'paper_processor_daemon.py:manual_metadata_entry',
                                    'message': 'Zotero match selected',
                                    'data': {
                                        'title': selected.get('title'),
                                        'item_type': selected.get('itemType'),
                                        'year': selected.get('year')
                                    },
                                    'timestamp': int(_time.time() * 1000)
                                }) + '\n')
                        except Exception:
                            pass
                        # #endregion
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
    
    def review_search_params(
        self,
        title: Optional[str],
        authors: Optional[List[str]],
        year_str: Optional[str],
        journal: Optional[str],
    ) -> Tuple[Optional[str], Optional[List[str]], Optional[str], Optional[str], bool, bool]:
        """Show search parameters and let user confirm, edit, or skip online search.

        Returns:
            (title, authors, year_str, journal, skip_search, go_back)
            skip_search is True if user chose to skip online search.
            go_back is True if user chose to return to previous step.
        """
        def fmt(s: Optional[str]) -> str:
            return s if (s and str(s).strip()) else "(none)"

        def fmt_authors(a: Optional[List[str]]) -> str:
            if not a or not isinstance(a, list):
                return "(none)"
            return ", ".join(str(x).strip() for x in a if x and str(x).strip()) or "(none)"

        while True:
            print("\n" + "=" * 60)
            print("Search parameters (extracted):")
            print(f"  Author(s): {fmt_authors(authors)}")
            print(f"  Year:      {fmt(year_str)}")
            print(f"  Title:     {fmt(title)}")
            print(f"  Journal:   {fmt(journal)}")
            print()
            print("[Enter] = Search with these  |  [e] = Edit  |  [s] = Skip online search  |  [z] = Back")
            choice = self._input_with_timeout("Your choice: ", default="", clear_buffered=True)
            if choice is None:
                choice = ""
            choice = (choice or "").strip().lower()

            if choice == "z":
                return (title, authors, year_str, journal, False, True)
            if choice == "s":
                return (title, authors, year_str, journal, True, False)
            if choice != "e":
                return (title, authors, year_str, journal, False, False)

            # Edit sub-menu
            while True:
                print("\nEdit field: [1] Author(s)  [2] Year  [3] Title  [4] Journal  [Enter] Done  [z] Back")
                field_choice = self._input_with_timeout("Your choice: ", default="", clear_buffered=True)
                if field_choice is None:
                    field_choice = ""
                field_choice = (field_choice or "").strip()
                if not field_choice:
                    break
                if field_choice.lower() == "z":
                    break

                if field_choice == "1":
                    current = fmt_authors(authors)
                    new_val = self._input_with_timeout(
                        f"Author(s) (comma-separated) [{current}]: ",
                        default=current,
                        clear_buffered=True,
                    )
                    if new_val is not None and new_val.strip():
                        new_list = [a.strip() for a in new_val.split(",") if a.strip()]
                        if new_list and self.author_validator:
                            resolved = []
                            for name in new_list:
                                result = self.author_validator.validate_authors([name])
                                known = result.get("known_authors", [])
                                if len(known) == 1 and known[0].get("alternatives"):
                                    alts = known[0]["alternatives"]
                                    if alts:
                                        print(f"\n  Zotero matches for \"{name}\":")
                                        for i, alt in enumerate(alts[:10], 1):
                                            print(f"    [{i}] {alt}")
                                        print("  [0] Keep as entered")
                                        pick = self._input_with_timeout("Your choice: ", default="0", clear_buffered=True)
                                        if pick and pick.strip().isdigit():
                                            idx = int(pick.strip())
                                            if 1 <= idx <= len(alts):
                                                resolved.append(alts[idx - 1])
                                                continue
                                if len(known) == 1:
                                    resolved.append(known[0]["name"])
                                else:
                                    resolved.append(name)
                            authors = resolved if resolved else new_list
                        else:
                            authors = new_list

                elif field_choice == "2":
                    new_val = self._input_with_timeout(
                        f"Year [{fmt(year_str)}]: ",
                        default=year_str or "",
                        clear_buffered=True,
                    )
                    if new_val is not None:
                        year_str = new_val.strip() if new_val.strip() else year_str

                elif field_choice == "3":
                    new_val = self._input_with_timeout(
                        f"Title [{fmt(title)}]: ",
                        default=title or "",
                        clear_buffered=True,
                    )
                    if new_val is not None:
                        title = new_val.strip() if new_val.strip() else title

                elif field_choice == "4":
                    new_val = self._input_with_timeout(
                        f"Journal [{fmt(journal)}]: ",
                        default=journal or "",
                        clear_buffered=True,
                    )
                    if new_val is not None:
                        journal = new_val.strip() if new_val.strip() else journal
    
    def _search_online_after_manual(self, metadata: dict) -> dict:
        """Run online lookups using manually entered metadata (papers and books)."""
        doc_type = metadata.get('document_type', '').lower()
        # #region agent log
        try:
            import time as _time, json as _json
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'M4',
                    'location': 'paper_processor_daemon.py:_search_online_after_manual',
                    'message': 'Entry',
                    'data': {
                        'from_zotero': bool(metadata.get('from_zotero')),
                        'method': metadata.get('method'),
                        'document_type': doc_type,
                        'has_title': bool(metadata.get('title')),
                        'has_authors': bool(metadata.get('authors')),
                        'has_year': bool(metadata.get('year')),
                        'has_journal': bool(metadata.get('journal')),
                        'has_isbn': bool(metadata.get('isbn'))
                    },
                    'timestamp': int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        
        if doc_type in ['book', 'book_chapter']:
            title = metadata.get('title')
            authors = metadata.get('authors', [])
            year = metadata.get('year')
            isbn = metadata.get('isbn')
            
            if title or (authors and year) or isbn:
                print("\n🔍 Searching national libraries with provided metadata...")
                try:
                    nat_results = self._search_national_library_for_book(
                        book_title=title,
                        authors=authors,
                        language=None,
                        country_code=None,
                        item_type='books'
                    )
                except Exception as e:
                    self.logger.warning(f"National library search failed: {e}")
                    nat_results = []
                
                if nat_results:
                    print(f"Found {len(nat_results)} result(s).")
                    for idx, item in enumerate(nat_results[:5], 1):
                        print(f"[{idx}] {item.get('title', 'Unknown')} ({item.get('year', '?')})")
                    print("[0] None of these")
                    choice = input("Select best match (0 to skip): ").strip()
                    if choice.isdigit():
                        idx = int(choice)
                        if 1 <= idx <= min(5, len(nat_results)):
                            selected = nat_results[idx - 1]
                            merged = selected.copy()
                            for key, value in metadata.items():
                                if key not in merged or not merged.get(key):
                                    merged[key] = value
                            return merged
        else:
            available_params = sum([
                bool(metadata.get('title')),
                bool(metadata.get('authors')),
                bool(metadata.get('year')),
                bool(metadata.get('journal'))
            ])
            
            if available_params >= 2:
                print("\n🔍 Searching CrossRef/OpenAlex with manual metadata...")
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'M5',
                            'location': 'paper_processor_daemon.py:_search_online_after_manual',
                            'message': 'CrossRef search triggered',
                            'data': {
                                'available_params': available_params,
                                'title_len': len(metadata.get('title') or ''),
                                'authors_count': len(metadata.get('authors') or []),
                                'year': metadata.get('year'),
                                'journal_present': bool(metadata.get('journal'))
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
                try:
                    crossref_results = self.metadata_processor.crossref.search_by_metadata(
                        title=metadata.get('title'),
                        authors=metadata.get('authors'),
                        year=str(metadata.get('year')).strip() if metadata.get('year') else None,
                        journal=metadata.get('journal'),
                        max_results=3
                    )
                except Exception as e:
                    self.logger.warning(f"CrossRef manual search failed: {e}")
                    crossref_results = []
                
                if crossref_results:
                    merged = crossref_results[0]
                    for key, value in metadata.items():
                        if key not in merged or not merged.get(key):
                            merged[key] = value
                    merged['method'] = 'manual+crossref'
                    return merged
                
                try:
                    openalex_results = self.metadata_processor.openalex.search_by_metadata(
                        title=metadata.get('title'),
                        authors=metadata.get('authors'),
                        year=int(metadata.get('year')) if str(metadata.get('year')).isdigit() else None,
                        journal=metadata.get('journal'),
                        max_results=3
                    )
                except Exception as e:
                    self.logger.warning(f"OpenAlex manual search failed: {e}")
                    openalex_results = []
                
                if openalex_results:
                    merged = openalex_results[0]
                    for key, value in metadata.items():
                        if key not in merged or not merged.get(key):
                            merged[key] = value
                    merged['method'] = 'manual+openalex'
                    return merged
        
        return metadata
    
    def convert_zotero_item_to_metadata(self, zotero_item: dict) -> dict:
        """Convert Zotero item to our metadata format.
        
        Args:
            zotero_item: Item from local Zotero DB
            
        Returns:
            Metadata dict in our format
        """
        # #region agent log
        try:
            import os as _os, json as _json, time as _time
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ZMAP1",
                    "location": "paper_processor_daemon.py:convert_zotero_item_to_metadata",
                    "message": "Convert Zotero item to metadata (raw keys/preview)",
                    "data": {
                        "zotero_item_keys_preview": list(zotero_item.keys())[:30] if isinstance(zotero_item, dict) else None,
                        "has_creators": bool(zotero_item.get("creators")) if isinstance(zotero_item, dict) else False,
                        "has_authors_list": bool(zotero_item.get("authors")) if isinstance(zotero_item, dict) else False,
                        "raw_title": (zotero_item.get("title") if isinstance(zotero_item, dict) else None),
                        "raw_year": (zotero_item.get("year") if isinstance(zotero_item, dict) else None),
                        "raw_itemType": (zotero_item.get("itemType") if isinstance(zotero_item, dict) else None),
                        "raw_DOI": (zotero_item.get("DOI") if isinstance(zotero_item, dict) else None),
                        "raw_doi": (zotero_item.get("doi") if isinstance(zotero_item, dict) else None),
                        "raw_publicationTitle": (zotero_item.get("publicationTitle") if isinstance(zotero_item, dict) else None),
                        "raw_journal": (zotero_item.get("journal") if isinstance(zotero_item, dict) else None),
                        "raw_ISSN": (zotero_item.get("ISSN") if isinstance(zotero_item, dict) else None),
                        "raw_issn": (zotero_item.get("issn") if isinstance(zotero_item, dict) else None),
                        "raw_url": (zotero_item.get("url") if isinstance(zotero_item, dict) else None),
                        "raw_pages": (zotero_item.get("pages") if isinstance(zotero_item, dict) else None),
                        "raw_volume": (zotero_item.get("volume") if isinstance(zotero_item, dict) else None),
                        "raw_issue": (zotero_item.get("issue") if isinstance(zotero_item, dict) else None),
                        "raw_publisher": (zotero_item.get("publisher") if isinstance(zotero_item, dict) else None),
                    },
                    "timestamp": int(_time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion

        metadata = {
            'title': zotero_item.get('title', ''),
            'year': zotero_item.get('year', ''),
            'document_type': zotero_item.get('itemType', 'unknown'),
            'zotero_key': zotero_item.get('key'),
            'from_zotero': True,
            'source': 'Zotero',
            'method': 'zotero_manual'
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
        # Journal: prefer publicationTitle, fallback to journal (from local DB)
        if zotero_item.get('publicationTitle'):
            metadata['journal'] = zotero_item['publicationTitle']
        elif zotero_item.get('journal'):
            metadata['journal'] = zotero_item['journal']
        if zotero_item.get('abstractNote'):
            metadata['abstract'] = zotero_item['abstractNote']
        # ISSN: check both uppercase and lowercase variants
        if zotero_item.get('ISSN'):
            metadata['issn'] = zotero_item['ISSN']
        elif zotero_item.get('issn'):
            metadata['issn'] = zotero_item['issn']
        # URL
        if zotero_item.get('url'):
            metadata['url'] = zotero_item['url']
        # Pages
        if zotero_item.get('pages'):
            metadata['pages'] = zotero_item['pages']
        # Volume
        if zotero_item.get('volume'):
            metadata['volume'] = zotero_item['volume']
        # Issue
        if zotero_item.get('issue'):
            metadata['issue'] = zotero_item['issue']
        # Publisher
        if zotero_item.get('publisher'):
            metadata['publisher'] = zotero_item['publisher']
        
        # #region agent log
        try:
            import os as _os, json as _json, time as _time
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ZMAP2",
                    "location": "paper_processor_daemon.py:convert_zotero_item_to_metadata",
                    "message": "Converted Zotero metadata (mapped preview)",
                    "data": {
                        "title": metadata.get("title", "")[:80],
                        "year": metadata.get("year", ""),
                        "document_type": metadata.get("document_type", ""),
                        "authors_count": len(metadata.get("authors") or []),
                        "doi": metadata.get("doi", ""),
                        "journal": metadata.get("journal", ""),
                        "has_url": bool(metadata.get("url")),
                        "has_issn": bool(metadata.get("issn")),
                        "has_volume": bool(metadata.get("volume")),
                        "has_issue": bool(metadata.get("issue")),
                        "has_pages": bool(metadata.get("pages")),
                        "has_publisher": bool(metadata.get("publisher")),
                    },
                    "timestamp": int(_time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion

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
            print(f"📋 Current Tags: {', '.join(working_tags) if working_tags else '(none)'}")
            
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
        """Add a custom tag entered by user. Supports comma-separated tags."""
        tag_input = input("\nEnter custom tag(s) (comma-separated for multiple): ").strip()
        if tag_input:
            # Split on commas, trim whitespace, filter empty strings
            new_tags = [t.strip() for t in tag_input.split(',') if t.strip()]
            added_count = 0
            for tag in new_tags:
                if tag not in working_tags:
                    working_tags.append(tag)
                    added_count += 1
            if added_count > 0:
                print(f"✅ Added {added_count} custom tag(s): {', '.join(new_tags)}")
            else:
                print(f"❌ All tag(s) already exist: {', '.join(new_tags)}")
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
            
        Returns:
            None when finished (success, failed, or cancelled).
            'RESTART' when the user requested restart from beginning; the caller
            should re-queue the same path and run the next item.
        """
        # Track documents opened for this paper so we can close them precisely in finally.
        self._opened_pdf_paths = []

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

        # UI simplification: we treat scan page 1 as document start.
        # This removes the extra prompt and avoids unnecessary re-creating PDFs.
        pdf_to_use = pdf_path
        temp_pdf_path = None
        effective_page_offset = 0
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
                    
                    # Filter authors early to avoid propagating hallucinations into searches
                    if metadata.get('authors'):
                        regex_authors_for_merge = identifiers_found.get('regex_authors', []) if isinstance(identifiers_found, dict) else []
                        metadata = self.filter_garbage_authors(metadata, pdf_path=pdf_to_use, regex_authors=regex_authors_for_merge)
                        result['metadata'] = metadata
                    
                    # If we have a JSTOR ID, try to fetch full metadata from JSTOR (authoritative) before other searches
                    jstor_ids = identifiers_found.get('jstor_ids', [])
                    skip_metadata_search = False
                    
                    if jstor_ids:
                        jstor_id = jstor_ids[0]
                        metadata['document_type'] = 'journal_article'
                        jstor_url = f"https://www.jstor.org/stable/{jstor_id}"
                        print(f"\n🔍 JSTOR ID found ({jstor_id}) - fetching metadata from JSTOR page...")
                        try:
                            jstor_metadata = self.metadata_processor.jstor.fetch_metadata_from_url(jstor_url)
                        except Exception as e:
                            self.logger.warning(f"JSTOR metadata fetch failed for {jstor_id}: {e}")
                            jstor_metadata = None
                        
                        if jstor_metadata:
                            print(f"  ✅ Found metadata from JSTOR")
                            # Merge: prefer JSTOR fields, supplement with GROBID
                            for key, value in metadata.items():
                                if key not in jstor_metadata or not jstor_metadata.get(key):
                                    jstor_metadata[key] = value
                            
                            jstor_metadata['jstor_id'] = jstor_id
                            result['metadata'] = jstor_metadata
                            result['method'] = 'grobid+jstor'
                            metadata = jstor_metadata  # Use merged metadata for subsequent steps
                            skip_metadata_search = True
                        else:
                            print(f"  ⚠️  Could not fetch metadata from JSTOR page - falling back to metadata search if possible")
                    
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
                    
                    # Count available parameters for metadata search
                    available_params = sum([
                        bool(title),
                        bool(authors),
                        bool(year_str),
                        bool(journal)
                    ])
                    
                    doc_type = metadata.get('document_type', '').lower()
                    if doc_type not in ['book', 'book_chapter']:
                        has_search_params = available_params >= 2
                    else:
                        # Books handled via national libraries later
                        has_search_params = False
                    
                    # Pre-search review: let user confirm, edit, or skip online search (journal articles etc.)
                    if doc_type not in ['book', 'book_chapter'] and not skip_metadata_search:
                        title, authors, year_str, journal, skip_search, go_back = self.review_search_params(
                            title, authors, year_str, journal
                        )
                        if go_back:
                            print("⬅️  Going back to previous step...")
                            return 'RESTART'
                        if skip_search:
                            has_search_params = False
                        else:
                            metadata['title'] = title
                            metadata['authors'] = authors
                            metadata['year'] = year_str
                            metadata['journal'] = journal
                            result['metadata'] = metadata
                            year_int = None
                            if year_str and year_str.isdigit():
                                yi = int(year_str)
                                if 1900 <= yi <= 2100:
                                    year_int = yi
                            available_params = sum([bool(title), bool(authors), bool(year_str), bool(journal)])
                            has_search_params = available_params >= 2
                    
                    # Books: try national library search before metadata APIs
                    if doc_type in ['book', 'book_chapter'] and not skip_metadata_search:
                        try:
                            nat_results = self._search_national_library_for_book(
                                book_title=metadata.get('title'),
                                authors=metadata.get('authors', []),
                                language=None,
                                country_code=None,
                                item_type='books'
                            )
                        except Exception as e:
                            self.logger.warning(f"National library search failed: {e}")
                            nat_results = []
                        
                        if nat_results:
                            print(f"\n🔍 Found {len(nat_results)} book result(s) from national libraries.")
                            for idx, item in enumerate(nat_results[:5], 1):
                                print(f"[{idx}] {item.get('title', 'Unknown')} ({item.get('year', '?')})")
                            print("[0] None of these")
                            choice = input("Select best match (0 to skip): ").strip()
                            if choice.isdigit():
                                idx = int(choice)
                                if 1 <= idx <= min(5, len(nat_results)):
                                    selected = nat_results[idx - 1]
                                    merged = selected.copy()
                                    for key, value in metadata.items():
                                        if key not in merged or not merged.get(key):
                                            merged[key] = value
                                    result['metadata'] = merged
                                    result['method'] = 'grobid+national_library'
                                    metadata = merged
                                    has_search_params = False  # skip CrossRef/OpenAlex once book metadata found
                    
                    if has_search_params and not skip_metadata_search:
                        jstor_id = jstor_ids[0] if jstor_ids else None
                        self.logger.info(f"Searching CrossRef/OpenAlex with {available_params} metadata parameters")
                        print(f"\n🔍 Searching CrossRef/OpenAlex for metadata...")
                        
                        try:
                            crossref_results = self.metadata_processor.crossref.search_by_metadata(
                                title=title,
                                authors=authors,
                                year=year_str,  # Pass as string for CrossRef
                                journal=journal,
                                max_results=3
                            )
                            if crossref_results:
                                api_metadata = crossref_results[0]
                                is_match = self.metadata_processor._validate_doi_metadata_against_pdf(
                                    api_metadata, pdf_to_use, page_offset=effective_page_offset
                                )
                                if not is_match:
                                    print("  ⚠️  CrossRef result doesn't match PDF content - skipping")
                                    crossref_results = []
                                else:
                                    grobid_keywords = metadata.get('keywords', [])
                                    api_tags = api_metadata.get('tags', [])
                                    api_keywords = api_metadata.get('keywords', [])
                                    combined_tags = []
                                    if grobid_keywords:
                                        combined_tags.extend([str(k) for k in grobid_keywords if k])
                                    if api_tags:
                                        combined_tags.extend([str(t) if not isinstance(t, dict) else t.get('tag', '') for t in api_tags if t])
                                    if api_keywords:
                                        combined_tags.extend([str(k) for k in api_keywords if k and str(k) not in combined_tags])
                                    metadata.update(api_metadata)
                                    if combined_tags:
                                        metadata['tags'] = list(set(combined_tags))  # Remove duplicates
                                    if jstor_id:
                                        metadata['jstor_id'] = jstor_id
                                    result['metadata'] = metadata
                                    result['method'] = 'grobid+crossref'
                                    print(f"  ✅ Found metadata in CrossRef - merged with GROBID extraction")
                                    self.logger.info("Metadata search: Found metadata in CrossRef")
                            if not crossref_results:
                                try:
                                    openalex_results = self.metadata_processor.openalex.search_by_metadata(
                                        title=title,
                                        authors=authors,
                                        year=year_int,  # Pass as integer for OpenAlex
                                        journal=journal,
                                        max_results=3
                                    )
                                    openalex_merged = False
                                    if openalex_results:
                                        api_metadata = openalex_results[0]
                                        is_match = self.metadata_processor._validate_doi_metadata_against_pdf(
                                            api_metadata, pdf_to_use, page_offset=effective_page_offset
                                        )
                                        if not is_match:
                                            print("  ⚠️  OpenAlex result doesn't match PDF content - skipping")
                                        else:
                                            grobid_keywords = metadata.get('keywords', [])
                                            api_tags = api_metadata.get('tags', [])
                                            api_keywords = api_metadata.get('keywords', [])
                                            combined_tags = []
                                            if grobid_keywords:
                                                combined_tags.extend([str(k) for k in grobid_keywords if k])
                                            if api_tags:
                                                combined_tags.extend([str(t) if not isinstance(t, dict) else t.get('tag', '') for t in api_tags if t])
                                            if api_keywords:
                                                combined_tags.extend([str(k) for k in api_keywords if k and str(k) not in combined_tags])
                                            metadata.update(api_metadata)
                                            if combined_tags:
                                                metadata['tags'] = list(set(combined_tags))  # Remove duplicates
                                            if jstor_id:
                                                metadata['jstor_id'] = jstor_id
                                            result['metadata'] = metadata
                                            result['method'] = 'grobid+openalex'
                                            print(f"  ✅ Found metadata in OpenAlex - merged with GROBID extraction")
                                            self.logger.info("Metadata search: Found metadata in OpenAlex")
                                            openalex_merged = True
                                    if not openalex_merged:
                                        print(f"  ⚠️  No metadata found in CrossRef/OpenAlex - using GROBID extraction only")
                                        if jstor_id:
                                            metadata['jstor_id'] = jstor_id
                                        result['metadata'] = metadata
                                except Exception as e:
                                    self.logger.warning(f"OpenAlex search failed: {e}")
                                    if jstor_id:
                                        metadata['jstor_id'] = jstor_id
                                    result['metadata'] = metadata
                        except Exception as e:
                            self.logger.warning(f"CrossRef search failed: {e}")
                            if jstor_id:
                                metadata['jstor_id'] = jstor_id
                            result['metadata'] = metadata
                else:
                    self.logger.info("GROBID did not find authors")
                    # Ensure result is properly initialized if GROBID failed
                    if result is None or not isinstance(result, dict):
                        self.logger.warning("Result was None or invalid after GROBID failure - initializing")
                        result = {
                            'success': False,
                            'metadata': {},
                            'method': 'grobid',
                            'processing_time_seconds': 0,
                            'identifiers_found': identifiers_found if 'identifiers_found' in locals() else {}
                        }
                    
                    # Try regex extraction from first page text before falling back to Ollama
                    self.logger.info("Step 2.5: GROBID failed - trying regex extraction from first page...")
                    try:
                        import pdfplumber
                        with pdfplumber.open(pdf_to_use) as pdf:
                            if len(pdf.pages) > effective_page_offset:
                                first_page_text = pdf.pages[effective_page_offset].extract_text() or ""
                                if first_page_text:
                                    regex_authors = AuthorExtractor.extract_authors_simple(first_page_text)
                                    if regex_authors:
                                        self.logger.info(f"✅ Regex found {len(regex_authors)} author(s): {', '.join(regex_authors)}")
                                        # Create result with regex authors
                                        result = {
                                            'success': True,
                                            'metadata': {
                                                'authors': regex_authors,
                                                # Prefer identifiers extracted from the PDF first page (JSTOR-like front pages)
                                                'title': (identifiers_found.get('title') or (metadata.get('title', '') if metadata else '')),
                                                'journal': identifiers_found.get('journal', ''),
                                                'year': identifiers_found.get('best_year', ''),
                                                'document_type': 'journal_article' if identifiers_found.get('jstor_ids') else 'unknown'
                                            },
                                            'method': 'regex_fallback',
                                            'processing_time_seconds': 0,
                                            'identifiers_found': identifiers_found
                                        }
                                        # #region agent log
                                        try:
                                            import os as _os, json as _json, time as _time
                                            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                                            with open(log_path, "a", encoding="utf-8") as _f:
                                                _f.write(_json.dumps({
                                                    "sessionId": "debug-session",
                                                    "runId": "run1",
                                                    "hypothesisId": "RX_META1",
                                                    "location": "paper_processor_daemon.py:regex_fallback_metadata",
                                                    "message": "Built regex_fallback metadata (title/journal propagation)",
                                                    "data": {
                                                        "title": (identifiers_found.get("title") or ""),
                                                        "journal": (identifiers_found.get("journal") or ""),
                                                        "year": identifiers_found.get("best_year", ""),
                                                        "authors_count": len(regex_authors),
                                                    },
                                                    "timestamp": int(_time.time() * 1000),
                                                }) + "\n")
                                        except Exception:
                                            pass
                                        # #endregion
                    except Exception as e:
                        self.logger.warning(f"Regex extraction failed: {e}")
                    
            
            # Step 3: Last resort - try Ollama if still no authors
            # Safety check: ensure result exists
            if result is None or not isinstance(result, dict):
                self.logger.error("Result is None or invalid before Ollama check - initializing")
                result = {
                    'success': False,
                    'metadata': {},
                    'method': 'unknown',
                    'processing_time_seconds': 0,
                    'identifiers_found': identifiers_found if 'identifiers_found' in locals() else {}
                }
            
            if not result.get('success') or not result.get('metadata', {}).get('authors'):
                use_ollama = False
                try:
                    use_ollama = self.config.getboolean('METADATA', 'use_ollama_fallback', fallback=False)
                except Exception:
                    use_ollama = False
                
                if use_ollama:
                    self.logger.info("Step 3: No authors found from GREP/API/GROBID - trying Ollama as last resort...")
                else:
                    self.logger.info("Step 3: Ollama fallback disabled in config - skipping")
                
                if use_ollama and self._ensure_ollama_ready():
                    # Try with Ollama fallback
                    ollama_result = self.metadata_processor.process_pdf(pdf_to_use, use_ollama_fallback=True, 
                                                                       progress_callback=self._show_ollama_progress,
                                                                       page_offset=effective_page_offset)
                    if ollama_result['success'] and ollama_result.get('metadata', {}).get('authors'):
                        # Preserve identifiers_found from GREP
                        ollama_result['identifiers_found'] = identifiers_found
                        # Filter authors immediately to limit hallucinations before further handling
                        filtered_meta = self.filter_garbage_authors(
                            ollama_result['metadata'],
                            pdf_path=pdf_to_use,
                            regex_authors=identifiers_found.get('regex_authors', []) if isinstance(identifiers_found, dict) else [],
                        )
                        ollama_result['metadata'] = filtered_meta
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
                    if use_ollama:
                        self.logger.warning("Ollama not available - limited extraction methods only")
            
            # Safety check: ensure result exists and has required keys
            if result is None:
                self.logger.error("Metadata extraction returned None - this should not happen")
                result = {
                    'success': False,
                    'metadata': {},
                    'method': 'unknown',
                    'processing_time_seconds': 0,
                    'identifiers_found': identifiers_found if 'identifiers_found' in locals() else {}
                }
            elif not isinstance(result, dict):
                self.logger.error(f"Metadata extraction returned unexpected type: {type(result)}")
                result = {
                    'success': False,
                    'metadata': {},
                    'method': 'unknown',
                    'processing_time_seconds': 0,
                    'identifiers_found': identifiers_found if 'identifiers_found' in locals() else {}
                }
            
            extraction_time = result.get('processing_time_seconds', 0)
            
            # Step 2: Check if extraction succeeded
            if result.get('success') and result.get('metadata'):
                metadata = result['metadata']
                # Preserve extraction method for downstream filtering
                if result.get('method') and not metadata.get('extraction_method'):
                    metadata['extraction_method'] = result.get('method')
                
                # Filter garbage authors (keeps only known authors when extraction is poor)
                # For GROBID, also validates against document text to filter hallucinations
                identifiers = result.get('identifiers_found', {})
                regex_authors_for_merge = identifiers.get('regex_authors', []) if isinstance(identifiers, dict) else []
                metadata = self.filter_garbage_authors(metadata, pdf_path=pdf_to_use, regex_authors=regex_authors_for_merge)

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
                                prompt_text = Colors.colorize(
                                    f"Year [{suggested_year}] (Enter=confirm, type new year, 'm'=manual entry, 'z'=back, or 'r'=restart): ",
                                    ColorScheme.ACTION
                                )
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
                            elif year_input.lower() == 'z':
                                print("⬅️  Going back to previous step...")
                                return
                            elif year_input.lower() == 'r':
                                # User wants to restart - go back to beginning of process_paper
                                print("🔄 Restarting from beginning...")
                                print("   (This will re-extract metadata and prompt for year again)")
                                return 'RESTART'
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
                        return 'RESTART'
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
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    regex_count = len(identifiers_found.get('regex_authors', [])) if identifiers_found else 0
                    has_single = regex_count == 1
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'R1',
                            'location': 'paper_processor_daemon.py:process_paper',
                            'message': 'Regex authors before manual flow',
                            'data': {
                                'regex_authors_count': regex_count,
                                'has_single_regex_author': has_single
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
                metadata = self.handle_failed_extraction(pdf_path)
                
                # Check for restart request
                if metadata and metadata.get('_restart'):
                    print("🔄 Restarting from beginning...")
                    return 'RESTART'
                
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
                        return 'RESTART'
                    
                    break
            
            def _handle_zotero_action(action_value, selected_item_value, metadata_value):
                """Handle a resolved Zotero action.

                Returns:
                    - 'handled': action completed for this paper
                    - 'continue_selection': return to Zotero selection flow
                    - 'exit': stop current paper processing
                    - 'restart': restart current paper from beginning
                """
                action_value = (str(action_value).strip().lower() if action_value is not None else 'none')
                self.logger.info(f"Zotero search action resolved to: {action_value}")

                if action_value == 'select' and selected_item_value:
                    # User selected an item - offer to attach PDF
                    selection_outcome = self.handle_item_selected(pdf_path, metadata_value, selected_item_value)
                    if selection_outcome == 'back_to_item_selection':
                        return 'continue_selection'
                    if selection_outcome == 'restart':
                        return 'restart'
                    if selection_outcome in ('quit_scan', 'quit_scan_manual_review'):
                        return 'exit'
                    return 'handled'
                elif action_value == 'search':
                    # User wants to search again - allow year editing by clearing confirmation flag
                    if metadata_value.get('_year_confirmed'):
                        metadata_value.pop('_year_confirmed', None)
                    # Reset authors to full set if available, then recursive call
                    if metadata_value.get('_all_authors'):
                        metadata_value['authors'] = metadata_value['_all_authors'].copy()
                    action2, selected_item2, metadata_value = self.search_and_display_local_zotero(
                        metadata_value,
                        force_prompt_year=True
                    )
                    action2_outcome = _handle_zotero_action(action2, selected_item2, metadata_value)
                    if action2_outcome in ('continue_selection', 'handled'):
                        return action2_outcome
                    if action2_outcome == 'restart':
                        return 'restart'
                    return 'exit'
                elif action_value == 'edit':
                    # Edit metadata then search again
                    print("\n✏️  Editing metadata...")
                    edited_metadata = self.edit_metadata_interactively(metadata_value)

                    if edited_metadata:
                        # Re-run Zotero search with edited metadata
                        print("\n🔍 Searching Zotero with edited metadata...")
                        action2, selected_item2, final_metadata = self.search_and_display_local_zotero(edited_metadata)
                        action2_outcome = _handle_zotero_action(action2, selected_item2, final_metadata)
                        if action2_outcome in ('continue_selection', 'handled'):
                            return action2_outcome
                        if action2_outcome == 'restart':
                            return 'restart'
                        return 'exit'

                    # User cancelled editing
                    print("❌ Metadata editing cancelled")
                    self.move_to_manual_review(pdf_path)
                    return 'handled'
                elif action_value == 'create':
                    # Create new Zotero item with online library check
                    # Use metadata_value which includes any edited authors
                    self.logger.info(
                        f"Dispatching create flow for {pdf_path.name} "
                        f"(title='{(metadata_value or {}).get('title', '')[:80]}')"
                    )
                    success = self.handle_create_new_item(pdf_path, metadata_value)
                    if not success:
                        # User cancelled or error occurred; avoid silent "jump" to next scan.
                        print("❌ Item creation cancelled or failed; moved to manual review.")
                        self.move_to_manual_review(pdf_path)
                    return 'handled'
                elif action_value == 'skip':
                    # User wants to skip this document
                    self.move_to_skipped(pdf_path)
                    return 'handled'
                elif action_value == 'quit':
                    # User wants to quit current processing
                    print("🔚 Exiting current processing per user request")
                    return 'exit'
                elif action_value == 'restart':
                    # User requested full restart from within nested flow.
                    print("🔄 Restarting from beginning...")
                    return 'restart'

                # action == 'none' or unknown
                print("📝 Moving to manual review...")
                self.move_to_manual_review(pdf_path)
                return 'handled'

            # Step 4: Handle action from Zotero search
            while True:
                action_outcome = _handle_zotero_action(action, selected_item, updated_metadata)
                if action_outcome == 'continue_selection':
                    action, selected_item, updated_metadata = self.search_and_display_local_zotero(updated_metadata)
                    continue
                if action_outcome == 'restart':
                    return 'RESTART'
                if action_outcome == 'exit':
                    return
                break
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

        elif choice == '6':  # Re-search CrossRef/OpenAlex with current metadata
            updated = self._search_online_after_manual(metadata)
            if updated and updated != metadata:
                metadata = updated
                result['metadata'] = metadata
                print("  ✅ Metadata updated from CrossRef/OpenAlex. Showing menu again.")
            else:
                print("  ⚠️  No additional metadata found or search skipped.")
            new_choice = self.display_zotero_match_menu()
            self.handle_zotero_match_choice(new_choice, pdf_path, metadata, local_matches, result)
    
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

        elif choice == '6':  # Re-search CrossRef/OpenAlex with current metadata
            updated = self._search_online_after_manual(metadata)
            if updated and updated != metadata:
                metadata = updated
                result['metadata'] = metadata
                print("  ✅ Metadata updated from CrossRef/OpenAlex. Showing menu again.")
            else:
                print("  ⚠️  No additional metadata found or search skipped.")
            new_choice = self.display_interactive_menu()
            self.handle_standard_choice(new_choice, pdf_path, metadata, result)
            
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
            preprocessing_state is a dict with keys:
              - border_removal: bool
              - split_method: 'none' | 'auto' | '50-50' | 'manual'
              - split_attempted: bool
              - split_succeeded: bool (optional, present if attempted)
              - split_reason: str (optional, e.g. 'filename_double', 'landscape_two_up')
              - trim_leading: bool
        """
        current_pdf = pdf_path
        # Store original filename for _double detection (before any renaming)
        original_filename_lower = pdf_path.name.lower()
        
        preprocessing_state = {
            'border_removal': False,
            'split_method': 'none',
            'split_attempted': False,
            'trim_leading': False,
        }
        
        # Step 1: Remove borders if requested
        if border_removal:
            border_removed_pdf, border_detection_stats = self._check_and_remove_dark_borders(current_pdf)
            if border_removed_pdf:
                current_pdf = border_removed_pdf
                preprocessing_state['border_removal'] = True
                self.logger.debug(f"Borders removed: {border_removed_pdf.name}")
            
            # Store border detection stats even if removal was rejected
            if border_detection_stats:
                preprocessing_state['border_detection_stats'] = border_detection_stats
                self.logger.debug(f"Border detection stats stored: {border_detection_stats}")
        
        # Step 2: Check if splitting is needed and perform split
        if split_method != 'none':
            # Check if PDF is landscape/two-up
            # Use original filename for _double detection (before border removal renamed it)
            name_lower = original_filename_lower
            needs_split = False
            landscape_width = None
            landscape_height = None
            
            # 1) Filename-based rule: any occurrence of '_double' forces a split
            if '_double' in name_lower:
                needs_split = True
                preprocessing_state['split_reason'] = 'filename_double'
                self.logger.info(f"_double detected in original filename '{pdf_path.name}' - will split via filename rule")
                print("Auto-splitting due to '_double' in filename...")
            else:
                # 2) Aspect ratio + gutter-based rule (may depend on pdfplumber)
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
                                    if is_two_up:
                                        needs_split = True
                                        landscape_width = width
                                        landscape_height = height
                                        preprocessing_state['split_reason'] = 'landscape_two_up'
                                        self.logger.info(
                                            f"Landscape two-up detected: {width:.1f}x{height:.1f} (ratio: {aspect_ratio:.2f}), "
                                            f"mode={mode} score={score:.2f}"
                                        )
                except Exception as e:
                    self.logger.debug(f"Landscape detection skipped: {e}")
            
            if needs_split:
                # Track that split is being attempted - update state BEFORE calling _split_with_mutool
                preprocessing_state['split_method'] = split_method
                preprocessing_state['split_attempted'] = True
                
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
                    self.logger.info(f"Split completed: {split_path.name} (reason={preprocessing_state.get('split_reason', 'unknown')}, method={split_method})")
                    preprocessing_state['split_succeeded'] = True
                else:
                    # Split was attempted but failed or was cancelled
                    # Keep split_method in state to show what was attempted
                    self.logger.info(
                        f"Split attempted with method '{split_method}' (reason={preprocessing_state.get('split_reason', 'unknown')}) "
                        f"but did not complete (user cancelled or failed)"
                    )
                    preprocessing_state['split_succeeded'] = False
        
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
        - Improve split (gutter detection + border removal) when currently using fast 50/50
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
            # Check if split actually succeeded by comparing processed_pdf with original
            split_succeeded = preprocessing_state.get('split_succeeded', False)
            # If split_method is 'none' but split_attempted is True, user cancelled
            if split_method == 'manual' and split_attempted and split_succeeded:
                manual_ratio = preprocessing_state.get('manual_split_ratio')
                if manual_ratio:
                    split_status = f"✓ Applied (manual {manual_ratio:.0f}/{100-manual_ratio:.0f})"
                else:
                    split_status = "✓ Applied (manual)"
            elif split_method == 'auto' and split_attempted and split_succeeded:
                split_status = "✓ Applied (gutter detection)"
            elif split_method == '50-50' and split_attempted and split_succeeded:
                split_status = "✓ Applied (50/50 geometric)"
            elif split_method != 'none' and split_attempted:
                # Split was attempted with a method but failed or was cancelled
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
            
            if preprocessing_state.get('split_method', 'none') == '50-50':
                option_num += 1
                option_map[option_num] = 'improve_split'
                print(Colors.colorize(f"  [{option_num}] Improve split (gutter detection + border removal)", ColorScheme.LIST))
            
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
                    
                    elif action == 'improve_split':
                        # Rerun with gutter detection and border removal (slower, higher accuracy).
                        new_state = preprocessing_state.copy()
                        print("\n🔄 Improving split (gutter detection + border removal)...")
                        processed_pdf, new_state = self._preprocess_pdf_with_options(
                            original_pdf,
                            border_removal=True,
                            split_method='auto',
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
                                
                                # Get all page widths from ORIGINAL PDF for per-page split (handles mixed page sizes)
                                try:
                                    import fitz  # PyMuPDF
                                    doc = fitz.open(str(original_pdf))
                                    if len(doc) == 0:
                                        print("❌ Error: PDF has no pages")
                                        doc.close()
                                        break
                                    page_widths = [doc[i].rect.width for i in range(len(doc))]
                                    doc.close()
                                except ImportError:
                                    print("❌ Error: PyMuPDF not available")
                                    break
                                except Exception as e:
                                    print(f"❌ Error reading PDF: {e}")
                                    break
                                
                                # Per-page gutter at requested ratio so mixed page sizes work
                                gutter_x_per_page = [w * (ratio / 100) for w in page_widths]
                                first_width = page_widths[0]
                                first_gutter = gutter_x_per_page[0]
                                print(f"📊 Split point: {first_gutter:.1f} (page width: {first_width:.1f}, ratio: {ratio}%)")
                                if len(page_widths) > 1:
                                    print(f"   (per-page split applied to {len(page_widths)} pages)")
                                
                                # Perform split on ORIGINAL PDF (not processed_pdf which may be already split)
                                print("\n🔄 Performing manual split...")
                                split_path, error_msg = self._split_with_custom_gutter(original_pdf, gutter_x_per_page[0], gutter_x_per_page)
                                
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
        """Find the actual gutter position using dual-method approach.
        
        Uses both edge detection and density minimum methods in parallel.
        Both methods must pass validation AND agree (no overlap with detected columns).
        If any check fails, rejects split entirely for reliability.
        
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
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G1',
                        'location': 'paper_processor_daemon.py:_find_gutter_position',
                        'message': 'Entry',
                        'data': {
                            'pdf_path': str(pdf_path),
                            'min_consistent_pages': getattr(self, 'min_consistent_pages', None)
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            # Run both methods in parallel
            edge_results = self.content_detector.detect_two_column_regions_binary_search(
                pdf_path,
                density_threshold=None,  # Will auto-detect
                pages=None  # Process all pages
            )
            
            density_results = self.content_detector.detect_gutter_by_density_minimum(
                pdf_path,
                pages=None,  # Process all pages
                density_threshold=None  # Will auto-detect
            )
            
            if not edge_results or not density_results:
                self.logger.debug("One or both methods found no results")
                return None
            
            if len(edge_results) != len(density_results):
                self.logger.warning(
                    f"Mismatch in page counts: edge method found {len(edge_results)} pages, "
                    f"density method found {len(density_results)} pages"
                )
                return None
            
            # Get page width from first page
            doc = fitz.open(str(pdf_path))
            if len(doc) == 0:
                doc.close()
                return None
            page_width = doc[0].rect.width
            
            # Process each page: check individual validations, check agreement, final safety check
            valid_gutter_positions = []
            valid_left_boxes = []
            valid_right_boxes = []
            
            for page_num in range(len(edge_results)):
                if page_num >= len(doc):
                    continue
                
                # Unpack edge detection results: (left_box, right_box, gutter_x_pts, is_valid, validation_errors, left_col_right_px, right_col_left_px, edge_mode)
                edge_left_box, edge_right_box, edge_gutter_x_pts, edge_is_valid, edge_errors, left_col_right_px, right_col_left_px, edge_mode = edge_results[page_num]
                
                # Unpack density method results: (gutter_x_pts, shape_metrics, is_valid)
                density_gutter_x_pts, density_shape_metrics, density_is_valid = density_results[page_num]
                
                # Check individual validations
                if not edge_is_valid:
                    self.logger.warning(
                        f"Page {page_num + 1} edge detection validation failed: {'; '.join(edge_errors)}"
                    )
                    continue
                
                if not density_is_valid:
                    validation_errors_str = '; '.join(density_shape_metrics.get('validation_errors', ['Unknown error']))
                    self.logger.warning(
                        f"Page {page_num + 1} density method validation failed: {validation_errors_str}"
                    )
                    continue
                
                # Both methods passed validation - check agreement (no overlap)
                # Edge method provides: left_col_right_px and right_col_left_px (column boundaries in pixels)
                # Density method provides: gutter_position (in PDF points) - need to convert to pixels
                page = doc[page_num]
                page_width_pts = page.rect.width
                
                # Render page to get pixel dimensions
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                img_width_px = pix.width
                
                # Convert density method gutter position from PDF points to pixels
                density_gutter_px = int((density_gutter_x_pts / page_width_pts) * img_width_px) if page_width_pts > 0 else 0
                
                # Overlap check: density method's gutter position must be between detected column edges
                if edge_mode == "outer":
                    overlaps = density_gutter_px < right_col_left_px or density_gutter_px > left_col_right_px
                else:
                    overlaps = density_gutter_px < left_col_right_px or density_gutter_px > right_col_left_px
                
                if overlaps:
                    # Overlap detected - reject this page
                    density_gutter_pct = (density_gutter_px / img_width_px) * 100 if img_width_px > 0 else 0
                    left_col_right_pct = (left_col_right_px / img_width_px) * 100 if img_width_px > 0 else 0
                    right_col_left_pct = (right_col_left_px / img_width_px) * 100 if img_width_px > 0 else 0
                    self.logger.warning(
                        f"Page {page_num + 1} methods disagree: "
                        f"Density method gutter at {density_gutter_pct:.1f}% overlaps with edge-detected columns "
                        f"(left ends at {left_col_right_pct:.1f}%, right starts at {right_col_left_pct:.1f}%)"
                    )
                    continue
                
                # Both methods agree - perform final safety check
                # Use density method's gutter position (since it passed overlap check)
                import cv2
                if len(pix.samples) > 0:
                    img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                    if len(img.shape) == 3:
                        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                    else:
                        gray = img
                    
                    # Sample 20px wide strip at gutter position (from middle 35-65% of height)
                    h, w = gray.shape
                    middle_top = int(h * 0.35)
                    middle_bottom = int(h * 0.65)
                    strip_width_px = 20
                    x1 = max(0, density_gutter_px - strip_width_px // 2)
                    x2 = min(w, density_gutter_px + strip_width_px // 2)
                    
                    strip = gray[middle_top:middle_bottom, x1:x2]
                    if strip.size > 0:
                        # Calculate content density (non-white pixels < 240)
                        non_white = np.sum(strip < 240)
                        total = strip.size
                        content_density = float(non_white / total) if total > 0 else 0.0
                        
                        if content_density > 0.20:  # 20% threshold
                            self.logger.warning(
                                f"Page {page_num + 1} final safety check failed: "
                                f"Gutter position has {content_density:.1%} content density (would cut through text)"
                            )
                            continue
                
                # All checks passed - add to valid results
                valid_gutter_positions.append(density_gutter_x_pts)
                valid_left_boxes.append(edge_left_box)
                valid_right_boxes.append(edge_right_box)
                
                self.logger.info(
                    f"Page {page_num + 1} dual-method detection succeeded: "
                    f"gutter={density_gutter_x_pts:.1f}pts ({density_gutter_x_pts/page_width_pts*100:.1f}%)"
                )
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'G2',
                            'location': 'paper_processor_daemon.py:_find_gutter_position',
                            'message': 'Valid gutter added',
                            'data': {
                                'page_num': page_num + 1,
                                'valid_count': len(valid_gutter_positions),
                                'min_consistent_pages': getattr(self, 'min_consistent_pages', None)
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
                
                # Early exit once enough consistent pages are found
                min_pages = getattr(self, 'min_consistent_pages', 2) or 2
                if len(valid_gutter_positions) >= min_pages:
                    median_gutter = float(np.median(valid_gutter_positions))
                    consistent_idxs = []
                    for i, gutter_pos in enumerate(valid_gutter_positions):
                        diff_pct = abs(gutter_pos - median_gutter) / page_width * 100 if page_width > 0 else 0
                        if diff_pct <= 5.0:
                            consistent_idxs.append(i)
                    if len(consistent_idxs) >= min_pages:
                        consistent_gutters = [valid_gutter_positions[i] for i in consistent_idxs]
                        consistent_left_boxes = [valid_left_boxes[i] for i in consistent_idxs]
                        consistent_right_boxes = [valid_right_boxes[i] for i in consistent_idxs]
                        final_median_gutter = float(np.median(consistent_gutters))
                        doc.close()
                        # #region agent log
                        try:
                            import time as _time, json as _json
                            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                            with open(log_path, 'a', encoding='utf-8') as f:
                                f.write(_json.dumps({
                                    'sessionId': 'debug-session',
                                    'runId': 'run1',
                                    'hypothesisId': 'G5',
                                    'location': 'paper_processor_daemon.py:_find_gutter_position',
                                    'message': 'Early exit with consistent gutters',
                                    'data': {
                                        'valid_pages': len(valid_gutter_positions),
                                        'consistent_pages': len(consistent_gutters),
                                        'median_gutter': final_median_gutter
                                    },
                                    'timestamp': int(_time.time() * 1000)
                                }) + '\n')
                        except Exception:
                            pass
                        # #endregion
                        return {
                            'gutter_x_per_page': [float(x) for x in consistent_gutters],
                            'left_column_boxes': consistent_left_boxes,
                            'right_column_boxes': consistent_right_boxes,
                            'method': 'dual_method_edge_density',
                            'variation': 0.0,
                            'confidence': [1.0] * len(consistent_gutters),
                            'gutter_x': final_median_gutter,
                            'gutter_positions': [float(x) for x in consistent_gutters],
                            'page_width': float(page_width)
                        }
            
            doc.close()
            
            # Per-page consistency check: require at least 2 pages
            if len(valid_gutter_positions) < 2:
                self.logger.warning(
                    f"Not enough valid pages: {len(valid_gutter_positions)} pages passed all checks "
                    f"(require at least 2 for consistency)"
                )
                return None
            
            # Use median across pages for final gutter position
            median_gutter = float(np.median(valid_gutter_positions))
            
            # Reject pages where position differs > 5% from median (outlier detection)
            consistent_gutters = []
            consistent_left_boxes = []
            consistent_right_boxes = []
            
            for i, gutter_pos in enumerate(valid_gutter_positions):
                diff_pct = abs(gutter_pos - median_gutter) / page_width * 100 if page_width > 0 else 0
                if diff_pct <= 5.0:
                    consistent_gutters.append(gutter_pos)
                    consistent_left_boxes.append(valid_left_boxes[i])
                    consistent_right_boxes.append(valid_right_boxes[i])
                else:
                    self.logger.warning(
                        f"Page {i+1} gutter position ({gutter_pos:.1f}pts, {gutter_pos/page_width*100:.1f}%) "
                        f"differs {diff_pct:.1f}% from median ({median_gutter:.1f}pts) - rejected as outlier"
                    )
            
            if len(consistent_gutters) < 2:
                self.logger.warning(
                    f"Not enough consistent pages after outlier removal: {len(consistent_gutters)} pages "
                    f"(require at least 2)"
                )
                return None
            
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G3',
                        'location': 'paper_processor_daemon.py:_find_gutter_position',
                        'message': 'Exit with consistent gutters',
                        'data': {
                            'valid_pages': len(valid_gutter_positions),
                            'consistent_pages': len(consistent_gutters),
                            'median_gutter': final_median_gutter
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
            # Calculate final median from consistent pages
            final_median_gutter = float(np.median(consistent_gutters))
            
            # Calculate variation across consistent pages
            if len(consistent_gutters) > 1:
                std_dev = np.std(consistent_gutters)
                mean_gutter = np.mean(consistent_gutters)
                cv = std_dev / (mean_gutter + 1e-6)  # Coefficient of variation
            else:
                cv = 0.0
            
            if cv > 0.10:
                self.logger.warning(f"Gutter position varies significantly across pages (CV: {cv:.1%})")
            
            # Return per-page results
            return {
                'gutter_x_per_page': [float(x) for x in consistent_gutters],
                'left_column_boxes': consistent_left_boxes,
                'right_column_boxes': consistent_right_boxes,
                'method': 'dual_method_edge_density',
                'variation': float(cv),
                'confidence': [1.0] * len(consistent_gutters),  # High confidence when both methods agree
                'gutter_x': final_median_gutter,  # Backward compatibility: median
                'gutter_positions': [float(x) for x in consistent_gutters],  # Backward compatibility
                'page_width': float(page_width)
            }
            
        except Exception as e:
            self.logger.error(f"Dual-method gutter detection failed: {e}", exc_info=True)
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
            if len(doc) == 0:
                doc.close()
                return None, "PDF has no pages"
            
            
            # Create new document for split pages
            new_doc = fitz.open()
            
            pages_created = 0
            stage = "start"
            current_page_num = None
            doc_len = len(doc)
            for page_num in range(doc_len):
                current_page_num = page_num
                stage = "get_page"
                try:
                    page = doc[page_num]
                except (IndexError, AttributeError) as e:
                    error_msg = f"Failed to access page {page_num}: {e}"
                    self.logger.error(error_msg)
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                except Exception as e:
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
                
                
                if gutter_ratio < 0.3 or gutter_ratio > 0.7:
                    error_msg = f"Gutter position {gutter_ratio:.1%} outside reasonable range (30-70%). Calculated split at {page_gutter_x:.1f} points on page {page_num + 1} (page width: {page_width:.1f} points)."
                    self.logger.warning(error_msg)
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                min_page_width = min(page_gutter_x, page_width - page_gutter_x)
                if min_page_width < 0.3 * page_width:
                    error_msg = f"Split would create a page < 30% width on page {page_num + 1}. Left page: {page_gutter_x:.1f} points ({page_gutter_x/page_width:.1%}), right page: {page_width - page_gutter_x:.1f} points ({(page_width - page_gutter_x)/page_width:.1%})."
                    self.logger.warning(error_msg)
                    doc.close()
                    new_doc.close()
                    return None, error_msg
                
                
                # Log before split
                gutter_ratio_pct = (page_gutter_x / page_width) * 100 if page_width > 0 else 0
                self.logger.debug(
                    f"Page {page_num + 1} split: gutter={page_gutter_x:.1f}pts ({gutter_ratio_pct:.1f}%), "
                    f"page_width={page_width:.1f}pts, left_width={page_gutter_x:.1f}pts, right_width={page_width - page_gutter_x:.1f}pts"
                )
                
                # Create left page (from 0 to page_gutter_x)
                stage = "new_left_page"
                left_page = new_doc.new_page(width=page_gutter_x, height=page_height)
                source_page_rect = page.rect
                left_clip_rect = fitz.Rect(
                    max(0, 0),
                    max(0, 0),
                    min(page_gutter_x, source_page_rect.width),
                    min(page_height, source_page_rect.height)
                )
                
                try:
                    if page is None:
                        raise ValueError(f"Source page {page_num} is None")
                    if page_num < 0 or page_num >= len(doc):
                        raise ValueError(f"Page number {page_num} is out of bounds (document has {len(doc)} pages)")
                    
                    source_page = doc.load_page(page_num)
                    if source_page is None:
                        raise ValueError(f"Source page {page_num} is None")
                    
                    source_rect = source_page.rect
                    if (left_clip_rect.x0 < 0 or left_clip_rect.y0 < 0 or 
                        left_clip_rect.x1 > source_rect.width or left_clip_rect.y1 > source_rect.height):
                        raise ValueError(f"Clip rectangle {left_clip_rect} is outside source page bounds {source_rect}")
                    
                    stage = "left_show_pdf_page"
                    left_page.show_pdf_page(left_page.rect, doc, page_num, clip=left_clip_rect)
                except Exception as e:
                    self.logger.warning(
                        f"Left show_pdf_page failed on page {page_num + 1} (stage={locals().get('stage','unknown')}): {e} - trying pixmap fallback"
                    )
                    try:
                        stage = "left_pixmap_fallback"
                        pix = source_page.get_pixmap(clip=left_clip_rect)
                        left_page.insert_image(left_page.rect, pixmap=pix)
                    except Exception as e2:
                        error_msg = f"Failed to create left page {page_num + 1} (stage={locals().get('stage','unknown')}): {e2}"
                        self.logger.error(error_msg)
                        doc.close()
                        new_doc.close()
                        return None, error_msg
                
                # Create right page (from page_gutter_x to page_width)
                stage = "new_right_page"
                right_page = new_doc.new_page(width=page_width - page_gutter_x, height=page_height)
                source_page_rect = page.rect
                right_clip_rect = fitz.Rect(
                    max(0, page_gutter_x),
                    max(0, 0),
                    min(page_width, source_page_rect.width),
                    min(page_height, source_page_rect.height)
                )
                
                try:
                    if page is None:
                        raise ValueError(f"Source page {page_num} is None")
                    if page_num < 0 or page_num >= len(doc):
                        raise ValueError(f"Page number {page_num} is out of bounds (document has {len(doc)} pages)")
                    
                    source_page = doc.load_page(page_num)
                    if source_page is None:
                        raise ValueError(f"Source page {page_num} is None")
                    
                    source_rect = source_page.rect
                    if (right_clip_rect.x0 < 0 or right_clip_rect.y0 < 0 or 
                        right_clip_rect.x1 > source_rect.width or right_clip_rect.y1 > source_rect.height):
                        raise ValueError(f"Clip rectangle {right_clip_rect} is outside source page bounds {source_rect}")
                    
                    stage = "right_show_pdf_page"
                    right_page.show_pdf_page(right_page.rect, doc, page_num, clip=right_clip_rect)
                except Exception as e:
                    self.logger.warning(
                        f"Right show_pdf_page failed on page {page_num + 1} (stage={locals().get('stage','unknown')}): {e} - trying pixmap fallback"
                    )
                    try:
                        stage = "right_pixmap_fallback"
                        pix = source_page.get_pixmap(clip=right_clip_rect)
                        right_page.insert_image(right_page.rect, pixmap=pix)
                    except Exception as e2:
                        error_msg = f"Failed to create right page {page_num + 1} (stage={locals().get('stage','unknown')}): {e2}"
                        self.logger.error(error_msg)
                        doc.close()
                        new_doc.close()
                        return None, error_msg
                pages_created += 2
                
                # Diagnostic logging: Check content immediately after creation
                stage = "post_split_diagnostics"
                try:
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
                except Exception:
                    pass
                
            
            # Check if we have the expected number of pages (2 per original)
            expected_pages = len(doc) * 2
            actual_pages = len(new_doc)
            
            
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
            out_path = temp_dir / f"PREPROCESSED_{pdf_path.stem}_split.pdf"
            
            
            new_doc.save(str(out_path))
            
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Split PDF created with custom gutter: {out_path.name}")
            return out_path, None
            
        except Exception as e:
            error_msg = f"Custom split failed: {e}"
            self.logger.error(error_msg)
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
                gutter_result = self._find_gutter_position(pdf_path)
            
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'G4',
                        'location': 'paper_processor_daemon.py:_split_with_mutool',
                        'message': 'Split method decision',
                        'data': {
                            'split_method': split_method,
                            'gutter_result_type': 'none' if gutter_result is None else type(gutter_result).__name__
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
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
            
            # Calculate split point: content center if borders detected, page center otherwise.
            # For no-borders (50/50), use per-page split so mixed page sizes work.
            gutter_x_per_page = None
            split_x = None
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
                # No borders detected: use page center per-page so mixed page sizes work
                try:
                    import fitz
                    doc = fitz.open(str(pdf_path))
                    page_widths = [doc[i].rect.width for i in range(len(doc))]
                    doc.close()
                    gutter_x_per_page = [w / 2 for w in page_widths]
                    self.logger.info(f"Using page center for split (per-page): {len(gutter_x_per_page)} pages")
                except Exception as e:
                    self.logger.warning(f"Could not get per-page widths: {e}, using first page only")
                    split_x = width / 2
                    self.logger.info(f"Using page center for split: {split_x:.1f}")
            
            # Always use _split_with_custom_gutter() for splitting
            if gutter_x_per_page is not None:
                result, error_msg = self._split_with_custom_gutter(pdf_path, gutter_x_per_page[0], gutter_x_per_page)
            else:
                result, error_msg = self._split_with_custom_gutter(pdf_path, split_x)
            if result:
                self.logger.info(f"Split PDF created (geometric): {result.name}")
            elif error_msg:
                self.logger.warning(f"Geometric split failed: {error_msg}")
            return result
        except FileNotFoundError:
            self.logger.warning("mutool not found; skipping two-up split")
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
        
        from shared_tools.ui.input_timeout import read_line_with_timeout

        # Use shared helper for cross-platform behavior
        try:
            user_input = read_line_with_timeout(
                prompt,
                timeout=timeout_seconds,
                default=default,
                clear_buffered=clear_buffered,
            )
        except (KeyboardInterrupt, EOFError):
            print("\n❌ Cancelled")
            return None

        # Determine return value:
        # - None  -> timeout with no default or user cancelled at lower level
        # - ''    -> treat as default if provided
        # - other -> user input
        if user_input is None:
            if default is not None:
                timeout_msg = Colors.colorize("⏱️  Timeout reached - proceeding with default", ColorScheme.TIMEOUT)
                print(f"\n{timeout_msg}")
                return default
            else:
                timeout_msg = Colors.colorize("⏱️  Timeout reached", ColorScheme.TIMEOUT)
                print(f"\n{timeout_msg}")
                return None

        user_input = user_input.strip()
        return user_input if user_input else default
    
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
            out_path = temp_dir / f"PREPROCESSED_{pdf_path.stem}_from_page{page_offset + 1}.pdf"
            
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
            out_path = temp_dir / f"PREPROCESSED_{pdf_path.stem}_trimmed_end_{pages_to_drop}.pdf"
            
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
            out_path = temp_dir / f"PREPROCESSED_{pdf_path.stem}_no_page1.pdf"
            
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
        out_path = temp_dir / f"PREPROCESSED_{pdf_path.stem}_no_borders.pdf"
        
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
            self._run_processing_loop()
        except KeyboardInterrupt:
            self.shutdown(None, None)
    
    def _run_processing_loop(self):
        """Run the main processing loop: take one path from the queue, process it, repeat.
        Only the main thread runs this; the watcher thread only enqueues paths.
        """
        while True:
            path = self._paper_queue.get()
            self._set_processing_active(True)
            try:
                while True:
                    self.logger.info("")
                    self.logger.info("=" * 60)
                    self.logger.info(f"Processing: {path.name}")
                    self.logger.info("=" * 60)
                    try:
                        result = self.process_paper(path)
                        if result == 'RESTART':
                            # Restart should continue immediately with the same file,
                            # not enqueue behind newly arrived scans.
                            self.logger.info("Restart requested for current scan - reprocessing immediately")
                            continue
                    except Exception as e:
                        self.logger.error(f"Error processing {path.name}: {e}")
                        print(f"Error processing {path.name}: {e}")
                    self.logger.info("-" * 60)
                    self.logger.info("Ready for next scan")
                    break
            finally:
                self._set_processing_active(False)
                deferred_notice = self._consume_deferred_scan_notice()
                if deferred_notice:
                    self.logger.info(deferred_notice)

    def _set_processing_active(self, active: bool) -> None:
        """Track whether we're inside an active scan interaction."""
        with self._queue_notice_lock:
            self._processing_active = active

    def _register_new_scan_notice(self, file_name: str) -> Optional[str]:
        """Return immediate queue message, or defer while active interaction is running."""
        with self._queue_notice_lock:
            if self._processing_active:
                self._deferred_scan_notices += 1
                return None
        return f"New scan queued: {file_name}"

    def _consume_deferred_scan_notice(self) -> Optional[str]:
        """Consume and reset deferred queue notices."""
        with self._queue_notice_lock:
            count = self._deferred_scan_notices
            self._deferred_scan_notices = 0
        if count <= 0:
            return None
        noun = "scan" if count == 1 else "scans"
        return f"{count} new {noun} queued while finishing the current interaction"
    
    def _open_pdf_in_viewer(self, pdf_path: Path) -> bool:
        """Open PDF in default system viewer (non-blocking) and position window.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            True if opened successfully, False otherwise
        """
        try:
            # Non-Windows (e.g., WSL/Linux): avoid calling Windows executables directly
            if sys.platform != 'win32':
                # Try to convert WSL path to Windows path for wslview integration
                windows_path = self._to_windows_path(pdf_path)
                is_valid_windows_path = windows_path and ((":\\" in windows_path or ":/" in windows_path) or windows_path.startswith('\\\\'))
                if is_valid_windows_path:
                    # Preferred path: use wslview if available to open in Windows from WSL
                    try:
                        self.logger.info(f"Opening PDF in viewer via wslview: {windows_path}")
                        proc = subprocess.Popen(
                            ['wslview', str(windows_path)],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self._pdf_viewer_process = proc
                        self._pdf_viewer_path = pdf_path
                        self._track_opened_pdf_path(pdf_path)
                        time.sleep(1.5)
                        return True
                    except FileNotFoundError:
                        self.logger.warning("wslview not found")
                    except Exception as e:
                        self.logger.warning(f"Failed to open PDF with wslview: {e}")

                # Fallback: xdg-open with WSL path (Linux viewer if path is accessible)
                try:
                    wsl_path_str = str(pdf_path)
                    if not (wsl_path_str.startswith('\\\\') or (':\\' in wsl_path_str or ':/' in wsl_path_str)):
                        proc = subprocess.Popen(
                            ['xdg-open', wsl_path_str],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        self._pdf_viewer_process = proc
                        self._pdf_viewer_path = pdf_path
                        self._track_opened_pdf_path(pdf_path)
                        time.sleep(1.5)
                        self.logger.info("PDF viewer opened via xdg-open")
                        return True
                except FileNotFoundError:
                    self.logger.warning("xdg-open not found")
                except Exception as e:
                    self.logger.warning(f"Failed to open PDF with xdg-open: {e}")

                self.logger.warning(f"Could not open PDF in viewer on non-Windows platform: {pdf_path}")
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
                self._track_opened_pdf_path(pdf_path)
                
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

    def _track_opened_pdf_path(self, pdf_path: Path) -> None:
        """Track a PDF path opened in viewer for end-of-paper cleanup."""
        try:
            normalized = Path(pdf_path)
            if normalized not in self._opened_pdf_paths:
                self._opened_pdf_paths.append(normalized)
        except Exception:
            # Keep tracking best-effort; viewer opening should not fail because of bookkeeping.
            pass

    def _send_sumatra_command(self, command_id: str, file_path: Optional[Path] = None) -> bool:
        """Send a command to SumatraPDF and return True on success.

        For per-document close we optionally activate/open a target file first and then
        issue close for the current document.
        """
        cmd = (command_id or "").strip()
        if not cmd:
            return False

        try:
            ps_lines = [
                "$ErrorActionPreference = 'Stop'",
                "$sumatra = Get-Command SumatraPDF.exe -ErrorAction SilentlyContinue",
                "if (-not $sumatra) { Write-Host 'NO_SUMATRA'; exit 2 }",
                "$exe = $sumatra.Source",
            ]

            if file_path is not None:
                open_target = str(file_path)
                if sys.platform != 'win32':
                    windows_path = self._to_windows_path(Path(file_path))
                    if windows_path:
                        open_target = windows_path
                escaped_path = open_target.replace("'", "''")
                ps_lines.extend([
                    f"$targetFile = '{escaped_path}'",
                    "& $exe -reuse-instance $targetFile | Out-Null",
                    "Start-Sleep -Milliseconds 250",
                ])

            escaped_cmd = cmd.replace("'", "''")
            ps_lines.extend([
                f"$ddeCmd = '[{escaped_cmd}]'",
                "& $exe -dde $ddeCmd | Out-Null",
                "Write-Host 'SUCCESS'",
            ])

            ps_script = "; ".join(ps_lines)
            result = subprocess.run(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=6,
                text=True,
            )
            if result.returncode == 0 and result.stdout and "SUCCESS" in result.stdout:
                return True

            if result.stdout:
                self.logger.debug(f"Sumatra command stdout: {result.stdout.strip()}")
            if result.stderr:
                self.logger.debug(f"Sumatra command stderr: {result.stderr.strip()}")
            return False
        except Exception as e:
            self.logger.debug(f"Failed to send Sumatra command '{cmd}': {e}")
            return False

    def _close_pdf_document(self, pdf_path: Path) -> bool:
        """Close a specific PDF document in Sumatra by command, fallback to window close."""
        target = Path(pdf_path)
        self.logger.info(f"Closing PDF document in Sumatra: {target.name}")

        if self._send_sumatra_command("CmdCloseCurrentDocument", target):
            self.logger.info(f"Closed PDF document via Sumatra command: {target.name}")
            return True

        self.logger.debug(f"Sumatra command close failed for {target.name}; falling back to WM_CLOSE")
        return self._close_pdf_document_via_window(target)

    def _close_pdf_document_via_window(self, pdf_path: Path) -> bool:
        """Fallback: close a PDF document window/tab by title match and WM_CLOSE."""
        try:
            if sys.platform != 'win32':
                windows_path = self._to_windows_path(pdf_path)
                if not windows_path:
                    return False
                filename = Path(windows_path).name
            else:
                filename = Path(pdf_path).name

            ps_script = f'''
Add-Type @"
using System;
using System.Runtime.InteropServices;
public class Win32 {{
    [DllImport("user32.dll")]
    public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
}}
"@
$filename = "{filename}"
$WM_CLOSE = 0x0010
$sumatraProcesses = Get-Process -Name "SumatraPDF" -ErrorAction SilentlyContinue | Where-Object {{
    $_.MainWindowHandle -ne [IntPtr]::Zero
}}
$closed = $false
foreach ($proc in $sumatraProcesses) {{
    $title = $proc.MainWindowTitle
    if ($title -like "*$filename*") {{
        [Win32]::SendMessage($proc.MainWindowHandle, $WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero)
        $closed = $true
        Start-Sleep -Milliseconds 250
        break
    }}
}}
if ($closed) {{ Write-Host "SUCCESS" }} else {{ Write-Host "NOT_FOUND" }}
'''

            result = subprocess.run(
                ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-Command', ps_script],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=5,
                text=True,
            )
            return bool(result.stdout and "SUCCESS" in result.stdout)
        except Exception as e:
            self.logger.debug(f"Fallback window close failed for {pdf_path}: {e}")
            return False
    
    def _store_terminal_window_handle(self):
        """Store terminal window handle at startup for later use."""
        if sys.platform != 'win32':
            # Only supported on native Windows where user32 APIs are available
            self.logger.debug("Skipping terminal window handle storage on non-Windows platform")
            return
        
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
        if sys.platform != 'win32':
            # Window snapping is only supported on native Windows
            self.logger.debug("Skipping terminal window positioning on non-Windows platform")
            return
        
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
        # Only supported on native Windows where user32 APIs are available
        if sys.platform != 'win32':
            self.logger.debug("Skipping PDF window positioning on non-Windows platform")
            return
        
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
        
        previous_path = Path(self._pdf_viewer_path)
        if self._close_pdf_document(previous_path):
            self.logger.info("Previous PDF file closed successfully")
            time.sleep(0.3)
    
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
            targets: List[Path] = []
            if self._opened_pdf_paths:
                targets.extend([Path(p) for p in self._opened_pdf_paths])
            elif hasattr(self, '_pdf_viewer_path') and self._pdf_viewer_path:
                targets.append(Path(self._pdf_viewer_path))

            for target in targets:
                closed = self._close_pdf_document(target)
                if not closed:
                    self.logger.warning(f"Could not close PDF document: {target.name}")

            # Clear tracking
            if hasattr(self, '_pdf_viewer_process'):
                delattr(self, '_pdf_viewer_process')
            self._pdf_viewer_path = None
            self._opened_pdf_paths = []
                
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
        
        # Enqueue for the main processing loop (single-threaded)
        for file_path in existing_files:
            self._paper_queue.put(file_path)
            self.logger.info(f"Queued: {file_path.name}")
    
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

    def compare_metadata_step(self, extracted_metadata: dict, zotero_metadata: dict, zotero_item: dict = None) -> dict:
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
        return self._handle_metadata_choice(choice, extracted_metadata, zotero_metadata, zotero_item=zotero_item)
    
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
    
    def _handle_metadata_choice(self, choice: str, extracted: dict, zotero: dict, zotero_item: dict = None) -> dict:
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
            return self._search_online_metadata(extracted, zotero, zotero_item=zotero_item)
            
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
        
        # Special handling for tags: always merge instead of prompting
        if 'tags' in all_keys:
            current_tags = zotero.get('tags', [])
            extracted_tags = extracted.get('tags', [])
            
            if current_tags or extracted_tags:
                merged_tags = self._merge_tags(current_tags, extracted_tags)
                merged['tags'] = merged_tags
                added_count = len(merged_tags) - len(current_tags)
                if added_count > 0:
                    print(f"  ✅ tags: merged {added_count} new tag(s) from online/extracted")
                else:
                    print(f"  ⏭️  tags: no new tags to add")
            
            # Remove tags from all_keys so it's not processed again
            all_keys.discard('tags')
        
        # Special handling for abstract: use extracted if Zotero doesn't have one
        if 'abstract' in all_keys:
            zotero_abstract = zotero.get('abstract', '')
            extracted_abstract = extracted.get('abstract', '')
            
            if not zotero_abstract or (isinstance(zotero_abstract, str) and not zotero_abstract.strip()):
                # Zotero doesn't have abstract, use extracted if available
                if extracted_abstract:
                    merged['abstract'] = extracted_abstract
                    print(f"  ✅ abstract: filled from online/extracted source")
                else:
                    merged['abstract'] = zotero_abstract  # Keep empty
                    print(f"  ⏭️  abstract: no abstract available from either source")
            elif extracted_abstract and extracted_abstract != zotero_abstract:
                # Both have abstracts but they differ - ask user
                print(f"\nabstract:")
                print(f"  Extracted: {extracted_abstract[:200]}{'...' if len(extracted_abstract) > 200 else ''}")
                print(f"  Zotero:    {zotero_abstract[:200]}{'...' if len(zotero_abstract) > 200 else ''}")
                
                while True:
                    choice = input("Use (e)xtracted, (z)otero, or (c)ustom? ").strip().lower()
                    if choice == 'e':
                        merged['abstract'] = extracted_abstract
                        break
                    elif choice == 'z':
                        merged['abstract'] = zotero_abstract
                        break
                    elif choice == 'c':
                        custom = input("Enter custom abstract: ").strip()
                        merged['abstract'] = custom
                        break
                    else:
                        print("Please enter 'e', 'z', or 'c'")
            else:
                # Same abstract or Zotero has one and extracted doesn't - use Zotero
                merged['abstract'] = zotero_abstract
            
            # Remove abstract from all_keys so it's not processed again
            all_keys.discard('abstract')
        
        # Process remaining fields with standard field-by-field logic
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
    
    def _search_online_metadata(self, extracted: dict, zotero: dict, zotero_item: dict = None) -> dict:
        """Search online libraries and let user choose how to merge results.
        
        Args:
            extracted: Extracted metadata from PDF
            zotero: Metadata from existing Zotero item
            
        Returns:
            Final metadata dict with online results merged
        """
        # Use Zotero metadata as base for online search (it's more canonical)
        base_metadata = zotero.copy() if zotero else extracted.copy()
        # Preserve source information from extracted metadata if available
        if extracted:
            for key in ['data_source', 'source', 'extraction_method']:
                if key in extracted and key not in base_metadata:
                    base_metadata[key] = extracted[key]
        
        # Search online libraries
        print("\n🔍 Searching CrossRef, arXiv, OpenAlex...")
        online_metadata = self.search_online_libraries(base_metadata, zotero_item=zotero_item)
        
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

        # If we have a Zotero item, offer to apply fill-only updates from online metadata
        if zotero_item and zotero_item.get('key') and online_metadata:
            decision = self.enrichment_workflow.match_policy.evaluate(zotero or {}, online_metadata)
            plan = self.enrichment_workflow.plan_updates(zotero or {}, online_metadata, decision)
            display_enrichment_summary(zotero or {}, online_metadata, plan, heading="ENRICHMENT REVIEW")
            apply_choice = input("Apply these enrichment fields to Zotero? [Y/n]: ").strip().lower()
            if not apply_choice or apply_choice == 'y':
                apply_result = self.enrichment_workflow.apply_plan(
                    self.zotero_processor, zotero_item['key'], plan
                )
                applied = apply_result.get("applied", [])
                failed = apply_result.get("failed", [])
                if applied:
                    print(Colors.colorize(f"Applied fields to Zotero ({zotero_item['key']}): {', '.join(applied)}", ColorScheme.SUCCESS))
                if failed:
                    print(Colors.colorize(f"Failed to apply fields: {', '.join(failed)}", ColorScheme.ERROR))
            else:
                print("Skipped applying enrichment to Zotero.")
    
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
        final_metadata = self.compare_metadata_step(metadata, zotero_metadata, zotero_item=zotero_item)
        
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
            # Fast path: geometric 50/50 split first, postpone gutter detection + border removal.
            border_removal=False,
            split_method='50-50',
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
                # #region agent log
                try:
                    import time as _time, json as _json
                    log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run1",
                            "hypothesisId": "MR_CALL1",
                            "location": "paper_processor_daemon.py:_handle_pdf_attachment_step",
                            "message": "Manual review requested (preprocess preview)",
                            "data": {"pdf_path": str(pdf_path)},
                            "timestamp": int(_time.time() * 1000),
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                moved = self.move_to_manual_review(pdf_path)
                if moved:
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
        
        if self._pub_exists(base_path):
            # If same size as incoming file, hash-compare and skip if identical
            try:
                if self._pub_identical(pdf_to_copy, base_path):
                    print(f"✅ Existing base file is identical: {base_path.name} — skipping copy/attachment")
                    self.move_to_done(pdf_path)
                    return True
            except Exception:
                pass
            if not self._pub_exists(scanned_path):
                print(f"\n⚠️  File already exists: {base_path.name}")
                final_path = scanned_path
                print(f"Using scanned copy name: {final_path.name}")
            else:
                base_stat = self._pub_stat_display(base_path) or "unknown"
                scanned_stat = self._pub_stat_display(scanned_path) or "unknown"
                print(f"\n⚠️  Both base and scanned files exist:")
                # If scanned also same size, check for identical content too
                try:
                    if self._pub_identical(pdf_to_copy, scanned_path):
                        print(f"✅ Existing scanned file is identical: {scanned_path.name} — skipping copy/attachment")
                        self.move_to_done(pdf_path)
                        return True
                except Exception:
                    pass
                print(f"  [1] Base   : {base_path.name} ({base_stat})")
                print(f"  [2] Scanned: {scanned_path.name} ({scanned_stat})")
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
        
        success, error_msg = self._copy_file_universal(pdf_to_copy, final_path, replace_existing=False)
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
    
    def move_to_manual_review(self, pdf_path: Path) -> bool:
        """Move PDF to manual review directory.
        
        Returns:
            True if the file was moved, False otherwise.
        """
        # Prefer moving the original scan if available
        src = getattr(self, '_original_scan_path', None)
        if src is None or not Path(src).exists():
            src = pdf_path
        
        # Check if source file exists before attempting to move
        if not Path(src).exists():
            self.logger.warning(f"Cannot move to manual review: file no longer exists: {src}")
            # #region agent log
            try:
                import time as _time, json as _json
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as f:
                    f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "MR1",
                        "location": "paper_processor_daemon.py:move_to_manual_review",
                        "message": "Source missing; move skipped",
                        "data": {"src": str(src), "pdf_path": str(pdf_path)},
                        "timestamp": int(_time.time() * 1000),
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            return False
        
        manual_dir = self.watch_dir / "manual_review"
        manual_dir.mkdir(exist_ok=True)
        
        dest = manual_dir / Path(src).name
        # #region agent log
        try:
            import time as _time, json as _json
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "MR2",
                    "location": "paper_processor_daemon.py:move_to_manual_review",
                    "message": "Moving to manual_review",
                    "data": {"src": str(src), "dest": str(dest)},
                    "timestamp": int(_time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion

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
        return True
    
    def select_authors_for_search(self, authors: list) -> list:
        """Let user select which authors to search by and in what order.
        
        Args:
            authors: List of author name strings
            
        Returns:
            List of selected author names in user-specified order
        """
        if not authors:
            return []
        
        # Keep author cache consistent with the live Zotero DB.
        # Prevents confusing cases where an author is "recognized" from cache
        # but local Zotero searches still return zero matches.
        if self.author_validator:
            self.author_validator.refresh_if_needed(max_age_hours=6, silent=True)
        
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

        # #region agent log
        try:
            import json as _json, time as _time, os as _os
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "H3",
                    "location": "paper_processor_daemon.py:display_and_select_zotero_matches",
                    "message": "entry",
                    "data": {"count": len(matches), "search_info": search_info},
                    "timestamp": int(_time.time() * 1000)
                }) + "\n")
        except Exception:
            pass
        # #endregion
        
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
            if match.get('match_label'):
                print(f"      Match: {match.get('match_label')}")
            elif 'order_score' in match and match['order_score'] > 0:
                if match['order_score'] >= 100:
                    print("      Match: Perfect order (fallback)")
                elif match['order_score'] >= 50:
                    print("      Match: Good order (fallback)")
            
            print()
        
        # Show action menu
        print("ACTIONS:")
        print("  [1-N] Select item from list above")
        print("[a]   🔍 Change author/year search parameters")
        print("[b]   🔍 Change all search parameters")
        print("[c]   Create new Zotero item using the metadata above (title, authors, year, DOI, etc.)")
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
                # #region agent log
                try:
                    import time as _time, json as _json, os as _os
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if _os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    tags = selected_item.get('tags', []) if isinstance(selected_item, dict) else []
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(_json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'T10',
                            'location': 'paper_processor_daemon.py:display_and_select_zotero_matches',
                            'message': 'Zotero item selected (local DB snapshot)',
                            'data': {
                                'item_key': selected_item.get('item_key') or selected_item.get('key'),
                                'tag_count': len(tags),
                                'tag_preview': tags[:5]
                            },
                            'timestamp': int(_time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
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
            
            # For journal articles, also ask for issue, volume, and pages
            if doc_type == 'journal_article':
                # Volume
                current_volume = enhanced_metadata.get('volume', '')
                try:
                    if current_volume:
                        volume = input(f"\nVolume [{current_volume}]: ").strip()
                    else:
                        volume = input("\nVolume: ").strip()
                    if volume:
                        enhanced_metadata['volume'] = volume
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
                
                # Issue
                current_issue = enhanced_metadata.get('issue', '')
                try:
                    if current_issue:
                        issue = input(f"\nIssue [{current_issue}]: ").strip()
                    else:
                        issue = input("\nIssue: ").strip()
                    if issue:
                        enhanced_metadata['issue'] = issue
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
                
                # Pages
                current_pages = enhanced_metadata.get('pages', '')
                try:
                    if current_pages:
                        pages = input(f"\nPages [{current_pages}]: ").strip()
                    else:
                        pages = input("\nPages: ").strip()
                    if pages:
                        enhanced_metadata['pages'] = pages
                except (KeyboardInterrupt, EOFError):
                    print("\n❌ Cancelled")
                    return None
        
        print("\n✅ Manual entry complete")
        print()
        
        return enhanced_metadata
    
    def search_online_libraries(self, metadata: dict, pdf_path: Path = None, zotero_item: dict = None) -> dict:
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
        
        # Check if incoming metadata is from a high-quality source (national-library, ISBN lookup, etc.)
        # If so, include it as a candidate for enrichment evaluation
        metadata_source = metadata.get('data_source') or metadata.get('source') or metadata.get('extraction_method', '')
        if any(keyword in str(metadata_source).lower() for keyword in ['national', 'library', 'isbn_lookup', 'isbn']):
            # Normalize metadata to candidate format
            candidate_metadata = metadata.copy()
            candidate_metadata['source'] = metadata_source
            all_results.append(candidate_metadata)
            checked_libraries.append(f"Extracted ({metadata_source})")
        
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

        # Evaluate best candidate with match policy
        best_candidate, decision = self.enrichment_workflow.choose_best(metadata, all_results)
        plan = None
        if decision and best_candidate:
            status = decision.get("status")
            reason = decision.get("reason")
            plan = self.enrichment_workflow.plan_updates(metadata, best_candidate, decision)
            if status == "auto_accept":
                print("\n✅ Match policy auto-accepted the best online result.")
                display_enrichment_summary(metadata, best_candidate, plan, heading="AUTO ENRICHMENT (ONLINE)")
                if zotero_item and zotero_item.get('key'):
                    apply_result = self.enrichment_workflow.apply_plan(
                        self.zotero_processor, zotero_item['key'], plan
                    )
                    applied = apply_result.get("applied", [])
                    failed = apply_result.get("failed", [])
                    if applied:
                        print(Colors.colorize(f"Applied fields to Zotero ({zotero_item['key']}): {', '.join(applied)}", ColorScheme.SUCCESS))
                    if failed:
                        print(Colors.colorize(f"Failed to apply fields: {', '.join(failed)}", ColorScheme.ERROR))
                    self.logger.info(
                        "Auto-applied enrichment",
                        extra={"item_key": zotero_item['key'], "applied": applied, "failed": failed},
                    )
                return best_candidate
            if status == "reject":
                print("\n⚠️  Match policy rejected available online results.")
                return None
            if status == "manual_review":
                print("\nℹ️  Match policy requires manual review (reason: " + str(reason) + ").")
        
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
                print(f"Select a result (1-{len(all_results)})")
                print("  'n' = Use manual/extracted metadata (skip online metadata)")
                print("  'w' = The online search results are all wrong")
                choice = input("Enter your choice: ").strip().lower()
                
                if choice == 'n' or choice == 'none':
                    print("⏭️  Skipping online library results, will use manual/extracted metadata")
                    return None

                if choice in {'w', 'wrong'}:
                    # Explicitly discard any online payload for this attempt so later steps
                    # cannot accidentally merge online fields or tags.
                    all_results.clear()
                    best_candidate = None
                    plan = None
                    print("⏭️  Marked online results as wrong; continuing with manual/extracted metadata")
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
                    print("⚠️  Please enter a number, 'n' to skip, or 'w' for all wrong")
                    
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
        
        self.logger.info(
            f"Entered handle_create_new_item for {pdf_path.name} "
            f"(has_title={bool((extracted_metadata or {}).get('title'))}, "
            f"has_authors={bool((extracted_metadata or {}).get('authors'))}, "
            f"has_year={bool((extracted_metadata or {}).get('year'))})"
        )
        print("\n" + "="*60)
        print(Colors.colorize("📄 CREATE NEW ZOTERO ITEM", ColorScheme.PAGE_TITLE))
        print("="*60)

        def _safe_add_paper(metadata_payload: dict, attach_target: str = None):
            """Call zotero add_paper defensively and normalize result shape."""
            processor = getattr(self, 'zotero_processor', None)
            if not processor:
                return {
                    'success': False,
                    'error': 'Zotero processor is not initialized'
                }
            add_fn = getattr(processor, 'add_paper', None)
            if not callable(add_fn):
                return {
                    'success': False,
                    'error': 'Zotero processor add_paper is not available'
                }
            result = add_fn(metadata_payload, attach_target)
            if not isinstance(result, dict):
                return {
                    'success': False,
                    'error': f"Unexpected add_paper response type: {type(result).__name__}"
                }
            return result
        
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
                zotero_result = _safe_add_paper(final_metadata, None)
                if zotero_result.get('success'):
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

        # ------------------------
        # PDF preprocess + preview
        # ------------------------
        print("\n" + "="*70)
        print("PDF PREPROCESSING")
        print("="*70)

        processed_pdf, preprocessing_state = self._preprocess_pdf_with_options(
            pdf_path,
            # Fast path first: geometric 50/50 split preview.
            border_removal=False,
            split_method='50-50',
            trim_leading=True
        )

        final_pdf, final_state = self._preview_and_modify_preprocessing(
            pdf_path,
            processed_pdf,
            preprocessing_state
        )
        final_state = final_state if isinstance(final_state, dict) else {}

        if final_pdf is None:
            # User cancelled the preview flow.
            if final_state.get('quit'):
                moved = self.move_to_manual_review(pdf_path)
                if moved:
                    print("✅ Moved to manual review")
            return False

        # Derive log values once for both the "reuse" and "copy" paths.
        split_status = 'no'
        if final_state.get('split_succeeded'):
            split_status = 'yes'
        elif final_state.get('split_attempted'):
            split_status = 'failed'

        borders_status = 'yes' if final_state.get('border_removal', False) else 'no'
        trim_status = 'yes' if final_state.get('trim_leading', False) else 'no'

        # First: try to reuse an identical file already in publications (based on the
        # preprocessed/accepted PDF, not the original scan).
        reuse_path = self._find_identical_in_publications(final_pdf)
        if reuse_path:
            print(f"✅ Existing identical file found: {reuse_path.name} — skipping copy")
            try:
                windows_path = self._to_windows_path(reuse_path)
                print("📖 Creating Zotero item...")
                zotero_result = _safe_add_paper(final_metadata, windows_path)
                if zotero_result.get('success'):
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

                    # Log to CSV using real preprocessing decisions
                    if hasattr(self, 'scanned_papers_logger'):
                        original_filename = pdf_path.name
                        if hasattr(self, '_original_scan_path') and self._original_scan_path:
                            original_filename = Path(self._original_scan_path).name
                        self.scanned_papers_logger.log_processing(
                            original_filename=original_filename,
                            status='success',
                            final_filename=reuse_path.name,
                            split=split_status,
                            borders=borders_status,
                            trim=trim_status,
                            zotero_item_code=item_key
                        )

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

        # Copy to publications directory with _scanned logic and proceed even if copy fails
        base_path = self.publications_dir / proposed_filename
        stem = base_path.stem
        suffix = base_path.suffix
        scanned_path = self.publications_dir / f"{stem}_scanned{suffix}"
        final_path = base_path
        
        if base_path.exists():
            # If same size as incoming file, hash-compare and skip if identical
            try:
                if base_path.stat().st_size == final_pdf.stat().st_size and self._are_files_identical(base_path, final_pdf):
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
                    if scanned_path.stat().st_size == final_pdf.stat().st_size and self._are_files_identical(scanned_path, final_pdf):
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
        
        success, error_msg = self._copy_file_universal(final_pdf, final_path, replace_existing=False)
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
            zotero_result = _safe_add_paper(final_metadata, attach_target)
            
            if zotero_result.get('success'):
                print(f"✅ Created Zotero item (key: {zotero_result.get('item_key', 'N/A')})")
                action = zotero_result.get('action', 'unknown')
                item_key = zotero_result.get('item_key')
                
                if action == 'duplicate_skipped':
                    print("⚠️  Item already exists in Zotero - skipped duplicate")
                    # Still consider this a success - item exists in Zotero
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
                elif action == 'added_with_pdf':
                    print("✅ PDF attached to new Zotero item")
                    # Offer to add a handwritten note
                    if item_key:
                        self._prompt_for_note(item_key)
                    
                    # Log to CSV
                    if hasattr(self, 'scanned_papers_logger'):
                        original_filename = pdf_path.name
                        if hasattr(self, '_original_scan_path') and self._original_scan_path:
                            original_filename = Path(self._original_scan_path).name
                        self.scanned_papers_logger.log_processing(
                            original_filename=original_filename,
                            status='success',
                            final_filename=final_path.name,
                            split=split_status,
                            borders=borders_status,
                            trim=trim_status,
                            zotero_item_code=item_key
                        )
                    
                    # Move original to done/
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
                elif action == 'added_without_pdf':
                    if copied_ok:
                        print("⚠️  Item created but PDF attachment failed")
                    else:
                        print("⚠️  Item created without attachment (file copy failed)")
                
                    # Offer to add a handwritten note
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
                            final_filename=final_path.name,
                            split=split_status,
                            borders=borders_status,
                            trim=trim_status,
                            zotero_item_code=item_key
                        )
                    
                    # Move original to done/
                    self.move_to_done(pdf_path)
                    print("✅ Processing complete!")
                    return True
                else:
                    # Unknown action but success=True - still treat as success
                    self.logger.warning(f"Unknown action '{action}' but zotero_result['success'] is True")
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
        
        Returns:
            One of:
            - 'back_to_item_selection': user requested back to selection list
            - 'quit_scan': user quit selected-item flow
            - 'quit_scan_manual_review': user quit and file moved to manual review
            - 'processed': PDF processing path completed/started
            - 'error': unexpected navigation result
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

        # Enrichment evaluation (store in context; apply via page). Clear any stale data first.
        ctx_dict.pop('enrichment', None)
        enrichment_bundle = self._auto_enrich_selected_item(metadata, selected_item)
        start_page = 'review_and_proceed'
        if enrichment_bundle and enrichment_bundle.get('status') != 'reject':
            ctx_dict['enrichment'] = enrichment_bundle
            if enrichment_bundle.get('status') == 'auto_accept':
                start_page = 'enrichment_review_auto'
            else:
                start_page = 'enrichment_review_manual'
        # #region agent log
        try:
            import time as _time, json as _json, os as _os
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as _f:
                _f.write(_json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run-enrich",
                    "hypothesisId": "H1",
                    "location": "paper_processor_daemon.py:handle_item_selected",
                    "message": "enrichment routing decision",
                    "data": {
                        "item_key": (selected_item.get("key") or selected_item.get("item_key")),
                        "start_page": start_page,
                        "bundle_is_none": enrichment_bundle is None,
                        "bundle_status": (enrichment_bundle or {}).get("status"),
                        "bundle_reason": (enrichment_bundle or {}).get("reason"),
                        "bundle_updates_count": len(((enrichment_bundle or {}).get("plan") or {}).get("updates", {}) or {}),
                        "bundle_manual_count": len(((enrichment_bundle or {}).get("plan") or {}).get("manual_fields", []) or []),
                    },
                    "timestamp": int(_time.time() * 1000)
                }) + "\n")
        except Exception:
            pass
        # #endregion
        
        # Create pages and navigation engine
        pages = create_all_pages(self)
        engine = NavigationEngine(pages, timeout_seconds=self.prompt_timeout)
        
        # Run page flow starting from enrichment review (if any) or REVIEW & PROCEED
        result = engine.run_page_flow(start_page, ctx_dict)
        
        # Handle navigation results
        if result.type == result.Type.RETURN_TO_CALLER:
            return 'back_to_item_selection'
        elif result.type == result.Type.QUIT_SCAN:
            if result.move_to_manual:
                self.move_to_manual_review(pdf_path)
                return 'quit_scan_manual_review'
            return 'quit_scan'
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
            if not isinstance(preprocessing_state_from_context, dict):
                preprocessing_state_from_context = {}
            
            # Carry forward conflict decision from the navigation flow.
            # The PDF preview handlers may overwrite ctx['preprocessing_state'],
            # so we explicitly re-attach this flag here.
            conflict_action = ctx_dict.get('conflict_action')
            if conflict_action:
                preprocessing_state_from_context['conflict_action'] = conflict_action
            # Use merged_metadata if available (from proceed_after_edit), otherwise use metadata from context or original
            metadata_to_use = ctx_dict.get('merged_metadata') or ctx_dict.get('metadata', metadata)
            # Use the preprocessed PDF if available, otherwise will do preprocessing
            self._process_selected_item(pdf_path, selected_item, target_filename, metadata_to_use, 
                                      preprocessed_pdf=final_processed_pdf, 
                                      preprocessing_state=preprocessing_state_from_context)
            return 'processed'
        
        # Should not reach here
        print("⚠️  Unexpected navigation result")
        return 'error'

    def _auto_enrich_selected_item(self, extracted_metadata: dict, zotero_item: dict) -> dict | None:
        """Evaluate online enrichment for an existing Zotero item.

        Returns an enrichment bundle (decision+plan+candidate) or None if no candidates.
        Does NOT apply any updates; application is handled by the enrichment review page.
        """
        try:
            item_key = zotero_item.get('key') or zotero_item.get('item_key')
            if not item_key:
                return None

            zotero_metadata = self.convert_zotero_item_to_metadata(zotero_item) or {}
            # #region agent log
            try:
                import time as _time, json as _json, os as _os
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run-enrich",
                        "hypothesisId": "H2",
                        "location": "paper_processor_daemon.py:_auto_enrich_selected_item",
                        "message": "entry",
                        "data": {
                            "item_key": item_key,
                            "z_doi": (zotero_metadata.get("doi") or ""),
                            "z_isbn": (zotero_metadata.get("isbn") or ""),
                            "z_issn": (zotero_metadata.get("issn") or ""),
                            "z_journal": (zotero_metadata.get("journal") or ""),
                            "z_url": (zotero_metadata.get("url") or ""),
                            "z_pages": (zotero_metadata.get("pages") or ""),
                            "z_volume": (zotero_metadata.get("volume") or ""),
                            "z_issue": (zotero_metadata.get("issue") or ""),
                            "z_publisher": (zotero_metadata.get("publisher") or ""),
                            "z_title_len": len(zotero_metadata.get("title") or ""),
                            "z_authors_count": len(zotero_metadata.get("authors") or []),
                            "ex_has_doi": bool((extracted_metadata or {}).get("doi")),
                            "ex_has_url": bool((extracted_metadata or {}).get("url")),
                            "ex_source": (extracted_metadata or {}).get("source") or (extracted_metadata or {}).get("data_source"),
                        },
                        "timestamp": int(_time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            # Use Zotero metadata as base; supplement with extracted fields if missing
            search_base = zotero_metadata.copy()
            for k, v in (extracted_metadata or {}).items():
                if k not in search_base or not search_base.get(k):
                    search_base[k] = v

            # Check if extracted_metadata is from a high-quality source (national-library, ISBN lookup, etc.)
            # These should be included as candidates for enrichment evaluation
            additional_candidates = []
            if extracted_metadata:
                source = extracted_metadata.get('data_source') or extracted_metadata.get('source') or extracted_metadata.get('extraction_method', '')
                # Include if from national-library, ISBN lookup, or other high-quality sources
                if any(keyword in str(source).lower() for keyword in ['national', 'library', 'isbn_lookup', 'isbn']):
                    # Normalize extracted metadata to candidate format (ensure it has required fields)
                    candidate = extracted_metadata.copy()
                    # Ensure it's marked as a candidate source
                    candidate['source'] = source
                    additional_candidates.append(candidate)

            candidates = self.enrichment_workflow.search_online(search_base, additional_candidates=additional_candidates)
            if not candidates:
                # #region agent log
                try:
                    import time as _time, json as _json, os as _os
                    log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                    with open(log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run-enrich",
                            "hypothesisId": "H1",
                            "location": "paper_processor_daemon.py:_auto_enrich_selected_item",
                            "message": "no candidates from search_online",
                            "data": {
                                "item_key": item_key,
                                "search_base_keys": sorted(list(search_base.keys()))[:25],
                                "search_title_len": len(search_base.get("title") or ""),
                                "search_authors_count": len(search_base.get("authors") or []),
                                "search_year": search_base.get("year"),
                                "search_journal": search_base.get("journal"),
                                "search_doi": search_base.get("doi"),
                                "search_url": search_base.get("url"),
                                "additional_candidates_count": len(additional_candidates),
                            },
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                return None

            summary = self.enrichment_workflow.evaluate_and_plan(zotero_metadata, candidates)
            decision = summary.get("decision")
            plan = summary.get("plan")
            candidate = summary.get("candidate")
            if not decision or not plan or not candidate:
                # #region agent log
                try:
                    import time as _time, json as _json, os as _os
                    log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                    with open(log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run-enrich",
                            "hypothesisId": "H3",
                            "location": "paper_processor_daemon.py:_auto_enrich_selected_item",
                            "message": "evaluate_and_plan returned incomplete",
                            "data": {
                                "item_key": item_key,
                                "has_decision": bool(decision),
                                "has_plan": bool(plan),
                                "has_candidate": bool(candidate),
                                "candidates_count": len(candidates),
                            },
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                return None

            status = decision.get("status")
            reason = decision.get("reason")
            # #region agent log
            try:
                import time as _time, json as _json, os as _os
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                ev = (decision or {}).get("evidence", {}) or {}
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run-enrich",
                        "hypothesisId": "H4",
                        "location": "paper_processor_daemon.py:_auto_enrich_selected_item",
                        "message": "decision computed",
                        "data": {
                            "item_key": item_key,
                            "status": status,
                            "reason": reason,
                            "confidence": decision.get("confidence"),
                            "e_title_similarity": ev.get("title_similarity"),
                            "e_author_overlap": (ev.get("author_overlap") or {}).get("matches"),
                            "e_author_total_zotero": (ev.get("author_overlap") or {}).get("total_zotero"),
                            "e_author_total_candidate": (ev.get("author_overlap") or {}).get("total_candidate"),
                            "e_year_match": ev.get("year_match"),
                            "e_type_match": ev.get("type_match"),
                            "e_identifier": ev.get("identifier"),
                            "candidate_source": (candidate or {}).get("source"),
                            "candidate_has_doi": bool((candidate or {}).get("doi")),
                            "candidate_title_len": len((candidate or {}).get("title") or ""),
                            "plan_updates": sorted(list((plan or {}).get("updates", {}).keys()))[:25],
                            "plan_manual_fields": sorted(list((plan or {}).get("manual_fields", [])))[:25],
                        },
                        "timestamp": int(_time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # #endregion

            return {
                "status": status,
                "reason": reason,
                "item_key": item_key,
                "zotero_metadata": zotero_metadata,
                "candidate": candidate,
                "decision": decision,
                "plan": plan,
            }
        except Exception as e:
            self.logger.warning(f"Auto-enrichment failed: {e}")
            return None
    
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
            
            # Check if this is actually a preprocessed file or the original
            # Compare with original path and check preprocessing_state
            is_original_file = (preprocessed_pdf.resolve() == pdf_path.resolve())
            
            if preprocessing_state:
                # Check if any preprocessing actually succeeded
                border_removed = preprocessing_state.get('border_removal', False)
                split_succeeded = preprocessing_state.get('split_succeeded', False)
                trim_applied = preprocessing_state.get('trim_leading', False)
                is_actually_preprocessed = border_removed or split_succeeded or trim_applied
            else:
                is_actually_preprocessed = False
            
            if is_original_file or not is_actually_preprocessed:
                # This is the original file (no preprocessing was done or preprocessing failed)
                self.logger.info(f"Using original PDF (no preprocessing was performed): {pdf_to_copy.name}")
            else:
                # This is actually a preprocessed file
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
                # Fast path: geometric 50/50 split first, postpone gutter detection + border removal.
                border_removal=False,
                split_method='50-50',
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
                    # #region agent log
                    try:
                        import time as _time, json as _json
                        log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                        with open(log_path, "a", encoding="utf-8") as f:
                            f.write(_json.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "MR_CALL2",
                                "location": "paper_processor_daemon.py:_handle_pdf_attachment_step",
                                "message": "Manual review requested (attachment step)",
                                "data": {"pdf_path": str(pdf_path)},
                                "timestamp": int(_time.time() * 1000),
                            }) + "\n")
                    except Exception:
                        pass
                    # #endregion
                    moved = self.move_to_manual_review(pdf_path)
                    if moved:
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
        
        # Use backend-aware existence check for cloud drives
        target_exists = self._pub_exists(target_path_full)
        # #region agent log
        try:
            import time as _time, json as _json
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(_json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'H5',
                    'location': 'paper_processor_daemon.py:_handle_pdf_attachment_step',
                    'message': 'Target existence check',
                    'data': {
                        'target_path': str(target_path_full),
                        'target_exists': bool(target_exists),
                        'access_mode': getattr(self, 'publications_access_mode', 'wsl')
                    },
                    'timestamp': int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion
        
        if target_exists:
            conflict_action = None
            if isinstance(preprocessing_state, dict):
                conflict_action = preprocessing_state.get('conflict_action')

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
                # If we already asked the user how to handle a filename collision
                # (via pdf_conflict_decision), avoid prompting again here.
                if conflict_action == 'replace':
                    replace_existing = True
                    print("✅ Auto-selected: Replace existing with scan (no extra prompt).")
                    break
                
                if conflict_action == 'keep_both':
                    stem = Path(target_filename).stem
                    suffix = Path(target_filename).suffix or ".pdf"
                    
                    # Try the same scanned naming pattern used elsewhere.
                    candidates = [
                        f"{stem}_scanned2{suffix}",
                        f"{stem}_scanned{suffix}",
                        f"{stem}_scanned3{suffix}",
                    ]
                    chosen_name = None
                    chosen_path = None
                    for cand in candidates:
                        cand_path = self.publications_dir / cand
                        if not self._pub_exists(cand_path):
                            chosen_name = cand
                            chosen_path = cand_path
                            break
                    
                    if chosen_name and chosen_path:
                        target_filename = chosen_name
                        target_path_full = chosen_path
                        replace_existing = False
                        print(f"✅ Auto-selected: Keep both (using {target_filename}).")
                    else:
                        # Fallback: if we cannot find a unique scanned name, last resort is replace.
                        replace_existing = True
                        print("⚠️  Keep-both requested but no unique name found; falling back to replace.")
                    break

                # Prompt for filename editing
                new_filename = self._prompt_filename_edit(
                    target_filename=target_filename,
                    zotero_metadata=zotero_metadata,
                    extracted_metadata=extracted_metadata
                )
                
                # Check if new filename exists
                new_path = self.publications_dir / new_filename
                if not self._pub_exists(new_path):
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
        
        # Step 2: Verify and log target filename before copy
        # Defensive check: ensure target_filename doesn't contain temp file patterns
        temp_file_patterns = ['PREPROCESSED_', '_no_borders', '_split', '_from_page', '_no_page1']
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
            # Check if this is a conflict error (error code 5 from PowerShell)
            if error and error.startswith("CONFLICT:"):
                # Re-enter conflict UI using unified API
                target_path_full = self.publications_dir / target_filename
                if self._pub_exists(target_path_full):
                    print("\n⚠️  File conflict detected during copy. Please resolve:")
                    print(f"  Existing file: {target_filename}")
                    print("\nOptions:")
                    print("[1] Replace existing PDF with scan")
                    print("[2] Skip attaching and finish")
                    print("  (z) Cancel (keep original)")
                    print()
                    
                    conflict_choice = input("Enter your choice: ").strip().lower()
                    
                    if conflict_choice == 'z':
                        self.move_to_done(pdf_path)
                        print("✅ Cancelled - kept original PDF")
                        return
                    elif conflict_choice == '2':
                        self.move_to_done(pdf_path)
                        print("✅ Skipped attachment and finished")
                        return
                    elif conflict_choice == '1':
                        # Retry copy with replace_existing=True
                        success, target_path, error = self._copy_to_publications_via_windows(pdf_to_copy, target_filename, replace_existing=True)
                        if not success:
                            print(f"❌ Copy failed: {error}")
                            print("📝 Moving to manual review")
                            self.move_to_manual_review(pdf_path)
                            return
                    else:
                        # Invalid choice, default to manual review
                        print(f"❌ Copy failed: {error}")
                        print("📝 Moving to manual review")
                        self.move_to_manual_review(pdf_path)
                        return
                else:
                    # File doesn't exist anymore (race condition?), proceed with manual review
                    print(f"❌ Copy failed: {error}")
                    print("📝 Moving to manual review")
                    self.move_to_manual_review(pdf_path)
                    return
            else:
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
            
            # Update abstract field if metadata has abstract and item doesn't have it yet
            if metadata and metadata.get('abstract'):
                abstract = metadata['abstract']
                print(f"3c/4 Updating abstract field if missing...")
                abstract_updated = self.zotero_processor.update_item_field_if_missing(item_key, 'abstractNote', abstract)
                if abstract_updated:
                    abstract_preview = abstract[:100] + "..." if len(abstract) > 100 else abstract
                    print(f"✅ Abstract updated: {abstract_preview}")
                else:
                    print("ℹ️  Abstract already exists or update failed")
            
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
        # Derive split status from preprocessing state
        if final_state.get('split_succeeded'):
            split_status = 'yes'
        elif final_state.get('split_attempted'):
            # Attempted but did not succeed (cancelled or failed)
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
        
        Uses unified publications API to work with both WSL-accessible and cloud drive paths.
        """
        try:
            # List all PDF files using unified API
            pdf_files = self._list_pdfs_in_publications()
            
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
        except Exception as e:
            # Cloud-drive publications may not be stat()-able from WSL; fall back to PowerShell.
            # #region agent log
            try:
                import os as _os, json as _json, time as _time
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "PDFSZ1",
                        "location": "paper_processor_daemon.py:_summarize_pdf_for_compare",
                        "message": "path.stat failed; attempting PowerShell fallback",
                        "data": {"path": str(path), "error_type": type(e).__name__, "access_mode": getattr(self, "publications_access_mode", "wsl")},
                        "timestamp": int(_time.time() * 1000),
                    }) + "\n")
            except Exception:
                pass
            # #endregion

            try:
                info = None
                if self._publications_use_powershell():
                    info = self._get_file_info_via_powershell(path, with_hash=False)
                if info and info.get('exists') and info.get('isFile') and info.get('size') is not None:
                    out['size_mb'] = float(info.get('size')) / 1024 / 1024
                    # Prefer ISO timestamps if available
                    out['created'] = info.get('ctime') or out.get('created')
                    out['modified'] = info.get('mtime') or out.get('modified')
                    # #region agent log
                    try:
                        import os as _os, json as _json, time as _time
                        log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                        with open(log_path, "a", encoding="utf-8") as _f:
                            _f.write(_json.dumps({
                                "sessionId": "debug-session",
                                "runId": "run1",
                                "hypothesisId": "PDFSZ2",
                                "location": "paper_processor_daemon.py:_summarize_pdf_for_compare",
                                "message": "PowerShell fallback size applied",
                                "data": {"path": str(path), "size": info.get('size')},
                                "timestamp": int(_time.time() * 1000),
                            }) + "\n")
                    except Exception:
                        pass
                    # #endregion
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
        
        # Enqueue for main-thread processing (avoids concurrent interactive prompts)
        self.daemon._paper_queue.put(file_path)
        queue_notice = self.daemon._register_new_scan_notice(file_path.name)
        if queue_notice:
            self.daemon.logger.info(queue_notice)


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

