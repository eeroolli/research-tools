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
from pathlib import Path
from watchdog.observers.polling import PollingObserver as Observer
from watchdog.events import FileSystemEventHandler

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


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
        self.publications_dir.mkdir(parents=True, exist_ok=True)
    
    def setup_logging(self):
        """Setup logging configuration."""
        log_level = logging.DEBUG if self.debug else logging.INFO
        
        logging.basicConfig(
            level=log_level,
            format='[%(asctime)s] %(levelname)s: %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        
        self.logger = logging.getLogger(__name__)
    
    def display_metadata(self, metadata: dict, pdf_path: Path, extraction_time: float):
        """Display extracted metadata to user.
        
        Args:
            metadata: Extracted metadata dict
            pdf_path: Path to PDF file
            extraction_time: Time taken for extraction
        """
        print("\n" + "="*60)
        print(f"SCANNED DOCUMENT: {pdf_path.name}")
        print("="*60)
        print(f"\nMetadata extracted in {extraction_time:.1f}s")
        print("\nEXTRACTED METADATA:")
        print("-" * 40)
        print(f"Title:    {metadata.get('title', 'Unknown')}")
        
        authors = metadata.get('authors', [])
        if authors:
            author_str = ', '.join(authors[:3])
            if len(authors) > 3:
                author_str += f" (+{len(authors)-3} more)"
            print(f"Authors:  {author_str}")
        else:
            print(f"Authors:  Unknown")
        
        print(f"Year:     {metadata.get('year', 'Unknown')}")
        print(f"Type:     {metadata.get('document_type', 'unknown')}")
        print(f"Journal:  {metadata.get('journal', 'N/A')}")
        print(f"DOI:      {metadata.get('doi', 'Not found')}")
        
        if metadata.get('abstract'):
            abstract = metadata['abstract'][:150]
            print(f"Abstract: {abstract}..." if len(metadata['abstract']) > 150 else f"Abstract: {abstract}")
        
        print("-" * 40)
    
    def display_interactive_menu(self) -> str:
        """Display interactive menu and get user choice.
        
        Returns:
            User's menu choice as string
        """
        print("\nWHAT WOULD YOU LIKE TO DO?")
        print()
        print("[1] Use extracted metadata as-is")
        print("[2] Edit metadata manually")
        print("[3] Search local Zotero database")
        print("[4] Skip document (not academic)")
        print("[5] Manual processing later")
        print("[q] Quit daemon")
        print()
        
        while True:
            choice = input("Your choice: ").strip().lower()
            if choice in ['1', '2', '3', '4', '5', 'q']:
                return choice
            else:
                print("Invalid choice. Please try again.")
    
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
        """Process a single paper.
        
        Args:
            pdf_path: Path to PDF file
        """
        self.logger.info(f"New scan: {pdf_path.name}")
        
        try:
            # Step 1: Extract metadata
            self.logger.info("Extracting metadata...")
            result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=True)
            
            if not result['success'] or not result['metadata']:
                self.logger.warning("No metadata extracted")
                self.move_to_failed(pdf_path)
                return
            
            metadata = result['metadata']
            self.logger.info(f"Title: {metadata.get('title', 'Unknown')[:60]}...")
            authors = metadata.get('authors', [])
            if authors:
                author_str = ', '.join(authors[:2])
                if len(authors) > 2:
                    author_str += f" (+{len(authors)-2} more)"
                self.logger.info(f"Authors: {author_str}")
            
            # Step 2: Generate filename
            new_filename = self.generate_filename(metadata)
            self.logger.debug(f"New filename: {new_filename}")
            
            # Step 3: Copy to final destination
            final_path = self.copy_to_publications(pdf_path, new_filename)
            if not final_path:
                self.logger.error("Failed to copy to publications")
                self.move_to_failed(pdf_path)
                return
            
            # Step 4: Add to Zotero
            self.logger.info("Adding to Zotero...")
            zotero_result = self.zotero_processor.add_paper(metadata, final_path)
            
            if zotero_result['success']:
                if zotero_result['action'] == 'duplicate_skipped':
                    self.logger.info(f"Duplicate skipped ({result['processing_time_seconds']:.1f}s)")
                else:
                    self.logger.info(f"Added to Zotero ({result['processing_time_seconds']:.1f}s)")
                
                # Step 5: Move original to done/
                self.move_to_done(pdf_path)
            else:
                self.logger.error(f"Zotero error: {zotero_result.get('error')}")
                self.move_to_failed(pdf_path)
            
        except Exception as e:
            self.logger.error(f"Processing error: {e}", exc_info=self.debug)
            self.move_to_failed(pdf_path)
    
    def generate_filename(self, metadata: dict) -> str:
        """Generate filename from metadata.
        
        Format: Author_Year_Title.pdf (all underscores, no spaces)
        
        Args:
            metadata: Paper metadata
            
        Returns:
            Generated filename
        """
        # Reuse logic from process_scanned_papers.py
        from scripts.process_scanned_papers import ScannedPaperProcessor
        processor = ScannedPaperProcessor(self.watch_dir)
        return processor._generate_filename(metadata)
    
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
        self.logger.info("Ready for scans!")
        self.logger.info("="*60)
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            self.shutdown(None, None)
    
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
        
        self.remove_pid_file()
        self.logger.info("Daemon stopped")
        self.logger.info("="*60)
        sys.exit(0)


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
    # Quick test for Task 1 - testing menu display functions
    # TODO: Restore main() call in Task 2
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--test-menu':
        daemon = PaperProcessorDaemon(Path("/tmp"), debug=True)
        metadata = {
            'title': 'Test Paper',
            'authors': ['Smith, J.', 'Johnson, A.'],
            'year': '2024',
            'document_type': 'journal_article',
            'doi': '10.1234/test'
        }
        daemon.display_metadata(metadata, Path("test.pdf"), 5.3)
        choice = daemon.display_interactive_menu()
        print(f"You chose: {choice}")
    else:
        main()

