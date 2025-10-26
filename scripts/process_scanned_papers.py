#!/usr/bin/env python3
"""
Process scanned papers from /mnt/i/FraScanner/

Workflow:
1. Extract metadata using smart workflow (regex → API → Ollama fallback)
2. Generate filename: Author(s)_Year_Title.pdf (all underscores, no spaces!)
3. Move to done/ or failed/
4. Log to paper_processing_log.csv

No Zotero integration yet - validate files first!
"""

import sys
import csv
import shutil
import configparser
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor


class ScannedPaperProcessor:
    """Process scanned papers with smart metadata extraction."""
    
    def __init__(self, scanner_dir: Path, email: Optional[str] = None):
        """Initialize processor.
        
        Args:
            scanner_dir: Directory containing scanned PDFs
            email: Email for CrossRef polite pool
        """
        self.scanner_dir = Path(scanner_dir)
        self.done_dir = self.scanner_dir / "done"
        self.failed_dir = self.scanner_dir / "failed"
        self.log_file = self.scanner_dir / "paper_processing_log.csv"
        
        # Create directories
        self.done_dir.mkdir(exist_ok=True)
        self.failed_dir.mkdir(exist_ok=True)
        
        # Initialize metadata processor
        self.metadata_processor = PaperMetadataProcessor(email=email)
        
        # Load filename pattern configuration
        self.load_filename_config()
        
        # Initialize log file if needed
        if not self.log_file.exists():
            self._init_log_file()
    
    def _init_log_file(self):
        """Initialize CSV log file with headers (European CSV2 format: semicolon-delimited, quoted)."""
        with open(self.log_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
            writer.writerow([
                'timestamp',
                'original_filename',
                'new_filename',
                'status',
                'method',
                'processing_time_seconds',
                'doi',
                'title',
                'authors',
                'journal',
                'year',
                'error_message'
            ])
    
    def load_filename_config(self):
        """Load filename pattern configuration from config files."""
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent
        
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        # Get active pattern (default to 1)
        # Handle inline comments by extracting just the number
        active_pattern_str = config.get('FILENAME_PATTERNS', 'active_pattern', fallback='1')
        try:
            # Extract just the number part before any comment
            active_pattern_str = active_pattern_str.split('#')[0].split('//')[0].strip()
            self.active_pattern = int(active_pattern_str)
        except (ValueError, TypeError):
            self.active_pattern = 1  # Fallback to default
        
        # Get pattern templates
        self.pattern_templates = {}
        for i in range(1, 7):
            pattern_key = f'pattern{i}'
            if config.has_option('FILENAME_PATTERNS', pattern_key):
                self.pattern_templates[i] = config.get('FILENAME_PATTERNS', pattern_key)
        
        # Get author formatting options
        self.author_format_single = config.get('FILENAME_PATTERNS', 'author_format_single', 
                                               fallback='{lastname}')
        self.author_format_two = config.get('FILENAME_PATTERNS', 'author_format_two', 
                                           fallback='{lastname1}_and_{lastname2}')
        self.author_format_multiple = config.get('FILENAME_PATTERNS', 'author_format_multiple', 
                                                fallback='{lastname1}_et_al')
        self.author_max_names = config.getint('FILENAME_PATTERNS', 'author_max_names', fallback=3)
        
        # Get title formatting options
        self.title_max_length = config.getint('FILENAME_PATTERNS', 'title_max_length', fallback=100)
        self.title_clean_spaces = config.getboolean('FILENAME_PATTERNS', 'title_clean_spaces', fallback=True)
        self.title_clean_special_chars = config.getboolean('FILENAME_PATTERNS', 'title_clean_special_chars', fallback=True)
    
    def _format_authors_for_filename(self, authors: list) -> str:
        """Format authors for filename using configurable patterns.
        
        Args:
            authors: List of author names
            
        Returns:
            Formatted author string
        """
        if not authors:
            return "Unknown"
        
        # Extract last names
        last_names = []
        for author in authors[:self.author_max_names]:
            if ',' in author:
                # Handle "Last, First" format
                last_name = author.split(',')[0].strip()
            else:
                # Handle "First Last" format
                last_name = author.split()[-1] if author.split() else author
            last_names.append(last_name)
        
        if len(last_names) == 1:
            # Single author
            return self.author_format_single.format(lastname=last_names[0])
        
        elif len(last_names) == 2:
            # Two authors
            return self.author_format_two.format(
                lastname1=last_names[0], 
                lastname2=last_names[1]
            )
        
        else:
            # Three or more authors
            return self.author_format_multiple.format(lastname1=last_names[0])
    
    def _clean_for_filename(self, text: str, max_length: int = None) -> str:
        """Clean text for use in filename using configurable options.
        
        Args:
            text: Text to clean
            max_length: Maximum length (uses config default if None)
            
        Returns:
            Cleaned text safe for filename
        """
        if not text:
            return ""
        
        if max_length is None:
            max_length = self.title_max_length
        
        # Use pathvalidate for proper cross-platform filename sanitization
        from pathvalidate import sanitize_filename
        
        # Replace spaces with underscores if configured
        if self.title_clean_spaces:
            text = text.replace(' ', '_')
        
        # Use pathvalidate for proper cross-platform filename sanitization
        if self.title_clean_special_chars:
            text = sanitize_filename(text, replacement_text='_')
            
            # Handle additional readability improvements
            replacements = {
                '&': 'and',  # Replace & with 'and' for readability
            }
            
            for old, new in replacements.items():
                text = text.replace(old, new)
        
        # Remove multiple consecutive underscores
        while '__' in text:
            text = text.replace('__', '_')
        
        # Truncate if too long
        if len(text) > max_length:
            text = text[:max_length].rstrip('_')
        
        return text
    
    def _generate_filename(self, metadata: Dict, original_filename: str = None) -> str:
        """Generate filename using configurable patterns.
        
        Args:
            metadata: Metadata dictionary
            original_filename: Original filename to extract extension from (optional)
            
        Returns:
            Generated filename
        """
        # Get the active pattern template
        if self.active_pattern not in self.pattern_templates:
            # Fallback to pattern 1 if active pattern not found
            pattern_template = "{authors}_{year}_{title}"
        else:
            pattern_template = self.pattern_templates[self.active_pattern]
        
        # Extract and format components
        authors = metadata.get('authors', [])
        year = metadata.get('year', 'Unknown')
        title = metadata.get('title', 'Unknown_Title')
        doi = metadata.get('doi', '')
        
        # Format authors
        author_part = self._format_authors_for_filename(authors)
        
        # Clean title
        title_part = self._clean_for_filename(title)
        
        # Format year
        year_part = str(year) if year else 'Unknown'
        
        # Format DOI for safe filename use
        doi_safe = ""
        if doi:
            doi_safe = doi.replace('/', '_').replace(':', '_').replace('.', '_')
        
        # Replace placeholders in template
        filename = pattern_template.format(
            authors=author_part,
            year=year_part,
            title=title_part,
            doi_safe=doi_safe
        )
        
        # Ensure it ends with .pdf
        if not filename.endswith('.pdf'):
            filename += '.pdf'
        
        return filename
    
    def _handle_duplicate_filename(self, target_path: Path) -> Path:
        """Handle duplicate filenames by adding number.
        
        Args:
            target_path: Proposed target path
            
        Returns:
            Unique target path
        """
        if not target_path.exists():
            return target_path
        
        # Add number like existing files do
        stem = target_path.stem
        suffix = target_path.suffix
        parent = target_path.parent
        
        counter = 2
        while True:
            new_path = parent / f"{stem}{counter}{suffix}"
            if not new_path.exists():
                return new_path
            counter += 1
    
    def process_pdf(self, pdf_path: Path, use_ollama_fallback: bool = True) -> Dict:
        """Process a single PDF.
        
        Args:
            pdf_path: Path to PDF file
            use_ollama_fallback: Whether to use Ollama if no identifiers
            
        Returns:
            Processing result dictionary
        """
        print(f"\n{'='*80}")
        print(f"Processing: {pdf_path.name}")
        print(f"{'='*80}")
        
        # Extract metadata
        result = self.metadata_processor.process_pdf(pdf_path, use_ollama_fallback)
        
        if result['success'] and result['metadata']:
            # Generate filename
            new_filename = self._generate_filename(result['metadata'])
            print(f"\n📝 Generated filename: {new_filename}")
            
            # Move to done/
            target_path = self.done_dir / new_filename
            target_path = self._handle_duplicate_filename(target_path)
            
            try:
                shutil.copy2(pdf_path, target_path)
                print(f"✅ Moved to: {target_path.relative_to(self.scanner_dir)}")
                
                # Log success
                self._log_processing(
                    original_filename=pdf_path.name,
                    new_filename=target_path.name,
                    status='success',
                    method=result['method'],
                    processing_time=result['processing_time_seconds'],
                    metadata=result['metadata']
                )
                
                return {'success': True, 'new_path': target_path, **result}
                
            except Exception as e:
                print(f"❌ Error moving file: {e}")
                self._log_processing(
                    original_filename=pdf_path.name,
                    status='error',
                    error_message=str(e)
                )
                return {'success': False, 'error': str(e), **result}
        
        else:
            # Move to failed/
            target_path = self.failed_dir / pdf_path.name
            target_path = self._handle_duplicate_filename(target_path)
            
            try:
                shutil.copy2(pdf_path, target_path)
                print(f"⚠️  No metadata extracted - moved to: {target_path.relative_to(self.scanner_dir)}")
                
                # Log failure
                self._log_processing(
                    original_filename=pdf_path.name,
                    new_filename=target_path.name,
                    status='failed',
                    method=result.get('method'),
                    processing_time=result.get('processing_time_seconds', 0),
                    error_message="No metadata extracted"
                )
                
                return {'success': False, 'new_path': target_path, **result}
                
            except Exception as e:
                print(f"❌ Error moving file: {e}")
                self._log_processing(
                    original_filename=pdf_path.name,
                    status='error',
                    error_message=str(e)
                )
                return {'success': False, 'error': str(e), **result}
    
    def _log_processing(self, original_filename: str, new_filename: str = None,
                       status: str = None, method: str = None,
                       processing_time: float = 0, metadata: Dict = None,
                       error_message: str = None):
        """Log processing to CSV.
        
        Args:
            original_filename: Original PDF filename
            new_filename: New filename (if successful)
            status: Processing status
            method: Extraction method used
            processing_time: Time taken in seconds
            metadata: Extracted metadata
            error_message: Error message if failed
        """
        with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
            writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
            
            timestamp = datetime.now().isoformat()
            
            if metadata:
                doi = metadata.get('doi', '')
                title = metadata.get('title', '')
                authors = ', '.join(metadata.get('authors', [])[:3])
                journal = metadata.get('journal', '')
                year = metadata.get('year', '')
            else:
                doi = title = authors = journal = year = ''
            
            writer.writerow([
                timestamp,
                original_filename,
                new_filename or '',
                status or '',
                method or '',
                f"{processing_time:.1f}",
                doi,
                title,
                authors,
                journal,
                year,
                error_message or ''
            ])
    
    def process_all_pdfs(self, use_ollama_fallback: bool = True):
        """Process all PDFs in scanner directory.
        
        Args:
            use_ollama_fallback: Whether to use Ollama for papers without identifiers
        """
        # Find all PDFs (excluding subdirectories)
        pdfs = [f for f in self.scanner_dir.glob("*.pdf")]
        
        if not pdfs:
            print(f"No PDFs found in {self.scanner_dir}")
            return
        
        print(f"\n{'='*80}")
        print(f"Found {len(pdfs)} PDF(s) to process")
        print(f"{'='*80}")
        
        results = []
        for pdf in pdfs:
            result = self.process_pdf(pdf, use_ollama_fallback)
            results.append(result)
        
        # Summary
        print(f"\n{'='*80}")
        print("PROCESSING SUMMARY")
        print(f"{'='*80}")
        
        successful = [r for r in results if r.get('success')]
        failed = [r for r in results if not r.get('success')]
        
        print(f"\nTotal processed: {len(results)}")
        print(f"✅ Successful: {len(successful)}")
        print(f"❌ Failed: {len(failed)}")
        
        if successful:
            avg_time = sum(r.get('processing_time_seconds', 0) for r in successful) / len(successful)
            print(f"\nAverage processing time: {avg_time:.1f} seconds")
        
        print(f"\nLog file: {self.log_file}")
        print(f"Done directory: {self.done_dir}")
        print(f"Failed directory: {self.failed_dir}")


def main():
    """Main entry point."""
    import configparser
    
    # Load configuration to get scanner directory
    config = configparser.ConfigParser()
    root_dir = Path(__file__).parent.parent
    config.read([
        root_dir / 'config.conf',
        root_dir / 'config.personal.conf'
    ])
    
    scanner_dir = Path(config.get('PATHS', 'scanner_papers_dir', 
                                   fallback='/mnt/i/FraScanner/papers'))
    
    if not scanner_dir.exists():
        print(f"Error: Scanner directory not found: {scanner_dir}")
        return
    
    # Initialize processor (reads email from config.personal.conf)
    processor = ScannedPaperProcessor(scanner_dir=scanner_dir)
    
    # Process all PDFs
    # Ollama fallback enabled for:
    # - Web articles/news (URL found but no DOI/ISBN)
    # - Book chapters (no identifiers)
    # - Scanned papers without identifiers
    processor.process_all_pdfs(use_ollama_fallback=True)


if __name__ == "__main__":
    main()