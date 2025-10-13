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
        
        # Initialize local Zotero search (read-only)
        try:
            self.local_zotero = ZoteroLocalSearch()
            self.logger.info("Connected to live Zotero database (read-only mode)")
        except Exception as e:
            self.logger.error(f"Failed to connect to Zotero database: {e}")
            self.local_zotero = None
        
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
            else:
                print(f"  {field_name}: {field_value}")
        
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
        print("[8] Other")
        print()
        
        doc_type_map = {
            '1': ('journal_article', 'Journal Article'),
            '2': ('book_chapter', 'Book Chapter'),
            '3': ('conference_paper', 'Conference Paper'),
            '4': ('book', 'Book'),
            '5': ('thesis', 'Thesis'),
            '6': ('report', 'Report'),
            '7': ('news_article', 'News Article'),
            '8': ('unknown', 'Other')
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
            result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback=True)
            
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
            
            # Step 3: Show interactive menu
            choice = self.display_interactive_menu()
            
            # Step 4: Handle user choice
            if choice == 'q':
                self.logger.info("User requested quit")
                self.shutdown(None, None)
            
            elif choice == '4':  # Skip
                self.move_to_skipped(pdf_path)
                self.logger.info("Document skipped by user")
            
            elif choice == '5':  # Manual processing
                self.logger.info("Moved to manual review")
                # Don't move file - leave in scanner directory for manual processing
            
            elif choice == '3':  # Search local Zotero
                matches = self.search_and_display_local_zotero(metadata)
                
                if matches:
                    print("\nWhat would you like to do?")
                    print("[1-5] Use this Zotero item (attach PDF)")
                    print("[n]   None of these - create new item")
                    print("[b]   Back to main menu")
                    
                    sub_choice = input("\nYour choice: ").strip().lower()
                    
                    if sub_choice == 'b':
                        # Show menu again (recursive call)
                        choice = self.display_interactive_menu()
                        # Handle new choice in next iteration
                        self.logger.info(f"Returned to main menu - choice: {choice}")
                        
                    elif sub_choice == 'n':
                        # Create new - use standard workflow
                        success = self.use_metadata_as_is(pdf_path, metadata)
                        if not success:
                            self.logger.info("Processing cancelled or failed")
                        
                    elif sub_choice.isdigit():
                        # User selected a match
                        idx = int(sub_choice)
                        if 1 <= idx <= min(5, len(matches)):
                            selected_match = matches[idx - 1]
                            success = self.attach_to_existing_zotero_item(pdf_path, selected_match, metadata)
                            if success:
                                self.logger.info("Successfully attached to existing Zotero item")
                            else:
                                self.logger.info("Failed to attach to Zotero item")
                        else:
                            print("Invalid selection")
                            
                else:
                    # No matches - offer other options
                    print("\nNo matches found. What next?")
                    print("[1] Use extracted metadata as-is")
                    print("[2] Edit metadata manually")
                    print("[4] Skip document")
                    print("[5] Manual processing later")
                    
                    fallback_choice = input("\nYour choice: ").strip()
                    
                    if fallback_choice == '1':
                        success = self.use_metadata_as_is(pdf_path, metadata)
                    elif fallback_choice == '2':
                        edited_metadata = self.edit_metadata_interactively(metadata)
                        confirm = input("\nProceed with edited metadata? (y/n): ").strip().lower()
                        if confirm == 'y':
                            success = self.use_metadata_as_is(pdf_path, edited_metadata)
                    elif fallback_choice == '4':
                        self.move_to_skipped(pdf_path)
                        self.logger.info("Document skipped by user")
                    else:
                        self.logger.info("Left for manual processing")
            
            else:
                # Choices 1, 2 - to be implemented in next tasks
                self.logger.info(f"Choice '{choice}' not yet implemented")
                self.logger.info("Leaving in scanner directory for now")
            
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
    main()

