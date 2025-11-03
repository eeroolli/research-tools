#!/usr/bin/env python3
"""
Shared filename generation utility for papers and books.
Supports configurable patterns for different document types.
"""

import configparser
from pathlib import Path
from typing import Dict, List


class FilenameGenerator:
    """Configurable filename generator for academic documents (papers and books)."""
    
    def __init__(self):
        """Initialize filename generator."""
        self.load_config()
    
    def load_config(self):
        """Load filename pattern configuration from config files."""
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent.parent
        
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        # Get active pattern (default to 1)
        self.active_pattern = config.getint('FILENAME_PATTERNS', 'active_pattern', fallback=1)
        
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
    
    def format_authors(self, authors: List[str]) -> str:
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
    
    def clean_title(self, text: str, max_length: int = None) -> str:
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
        
        # Replace spaces with underscores if configured
        if self.title_clean_spaces:
            text = text.replace(' ', '_')
        
        # Remove or replace problematic characters if configured
        if self.title_clean_special_chars:
            # Use pathvalidate for proper cross-platform filename sanitization
            from pathvalidate import sanitize_filename
            
            # Use 'universal' platform to sanitize for all OS (Windows + POSIX)
            # This ensures filenames work across WSL, Windows, and cloud storage (Google Drive, etc.)
            text = sanitize_filename(text, replacement_text='_', platform='universal')
            
            # Handle additional readability improvements and problematic characters
            # Commas are technically valid on Windows but cause issues in paths and cloud storage
            replacements = {
                '&': 'and',  # Replace & with 'and' for readability
                ',': '_',    # Remove commas (problematic in paths and cloud storage)
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
    
    def generate_filename(self, metadata: Dict, original_filename: str = None, is_scan: bool = False) -> str:
        """Generate filename using configurable patterns.
        
        Args:
            metadata: Metadata dictionary with title, authors, year, etc.
            original_filename: Original filename to extract extension from (optional)
            is_scan: If True, appends '_scan' to filename (for scanned documents)
            
        Returns:
            Generated filename with appropriate extension
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
        isbn = metadata.get('isbn', '')
        
        # Format authors
        author_part = self.format_authors(authors)
        
        # Clean title
        title_part = self.clean_title(title)
        
        # Format year
        year_part = str(year) if year else 'Unknown'
        
        # Format DOI for safe filename use
        doi_safe = ""
        if doi:
            doi_safe = doi.replace('/', '_').replace(':', '_').replace('.', '_')
        
        # Format ISBN for safe filename use
        isbn_safe = ""
        if isbn:
            isbn_safe = isbn.replace('-', '').replace(' ', '')
        
        # Replace placeholders in template
        filename = pattern_template.format(
            authors=author_part,
            year=year_part,
            title=title_part,
            doi_safe=doi_safe,
            isbn_safe=isbn_safe
        )
        
        # Add _scan suffix if this is a scanned document
        if is_scan:
            filename += '_scan'
        
        # Determine file extension
        extension = self._get_file_extension(metadata, original_filename)
        
        # Remove periods from filename (except for final extension dot)
        # Always split off extension, remove periods from base, then rejoin
        if '.' in filename:
            # Split into base and extension (handle multiple dots by taking last as extension)
            parts = filename.rsplit('.', 1)
            if len(parts) == 2:
                base, ext = parts
                base = base.replace('.', '_')  # Remove all periods from base
                filename = f"{base}.{ext}"
            else:
                # No extension found, remove periods then add extension
                filename = filename.replace('.', '_')
                filename += f'.{extension}'
        else:
            # No extension yet, remove periods then add extension
            filename = filename.replace('.', '_')
            filename += f'.{extension}'
        
        return filename
    
    def _get_file_extension(self, metadata: Dict, original_filename: str = None) -> str:
        """Determine appropriate file extension based on metadata and original filename.
        
        Args:
            metadata: Document metadata
            original_filename: Original filename (optional)
            
        Returns:
            File extension (without dot)
        """
        # If original filename provided, try to extract extension from it
        if original_filename:
            original_path = Path(original_filename)
            if original_path.suffix:
                return original_path.suffix[1:].lower()  # Remove dot
        
        # Check if document type gives us a hint
        doc_type = metadata.get('document_type', '').lower()
        
        # Map document types to likely file extensions
        type_to_extension = {
            'book': 'pdf',  # Books are often PDFs
            'ebook': 'epub',  # E-books are often EPUB
            'journal_article': 'pdf',  # Journal articles are usually PDFs
            'conference_paper': 'pdf',  # Conference papers are usually PDFs
            'thesis': 'pdf',  # Theses are usually PDFs
            'report': 'pdf',  # Reports are usually PDFs
            'manuscript': 'pdf',  # Manuscripts are usually PDFs
            'preprint': 'pdf',  # Preprints are usually PDFs
            'working_paper': 'pdf',  # Working papers are usually PDFs
            'news_article': 'pdf',  # News articles are usually PDFs
            'web_article': 'pdf',  # Web articles are saved as PDFs
        }
        
        # Try to get extension from document type
        if doc_type in type_to_extension:
            return type_to_extension[doc_type]
        
        # Check if we have format information in metadata
        file_format = metadata.get('format', '').lower()
        if file_format:
            # Clean up format string (remove dots, spaces)
            format_clean = file_format.replace('.', '').replace(' ', '').lower()
            # Common format mappings
            if format_clean in ['pdf', 'epub', 'mobi', 'azw', 'azw3', 'txt', 'html', 'docx', 'doc']:
                return format_clean
        
        # Default to PDF for academic documents
        return 'pdf'
    
    def generate(self, metadata: Dict, is_scan: bool = False) -> str:
        """Generate filename without extension (convenience method).
        
        Args:
            metadata: Metadata dictionary with title, authors, year, etc.
            is_scan: If True, appends '_scan' to filename
            
        Returns:
            Generated filename WITHOUT extension
        """
        full_filename = self.generate_filename(metadata, is_scan=is_scan)
        # Remove extension
        if '.' in full_filename:
            return full_filename.rsplit('.', 1)[0]
        return full_filename


def create_filename_generator() -> FilenameGenerator:
    """Create a unified filename generator for academic documents (papers and books)."""
    return FilenameGenerator()


if __name__ == "__main__":
    # Test the filename generator with different file types
    gen = create_filename_generator()
    
    print("Testing unified filename generator with different file types:")
    print("=" * 60)
    
    # Test cases with different document types and file formats
    test_cases = [
        {
            'metadata': {
                'title': 'Introduction to Machine Learning',
                'authors': ['John Smith', 'Jane Doe'],
                'year': '2023',
                'isbn': '978-0-12-345678-9',
                'document_type': 'book'
            },
            'original_filename': 'book.epub',
            'description': 'Book as EPUB'
        },
        {
            'metadata': {
                'title': 'Deep Learning Research Paper',
                'authors': ['Alice Johnson'],
                'year': '2024',
                'doi': '10.1234/example.12345',
                'document_type': 'journal_article'
            },
            'original_filename': 'paper.pdf',
            'description': 'Journal article as PDF'
        },
        {
            'metadata': {
                'title': 'My PhD Thesis',
                'authors': ['Bob Wilson'],
                'year': '2023',
                'document_type': 'thesis'
            },
            'original_filename': None,
            'description': 'Thesis (no original filename)'
        },
        {
            'metadata': {
                'title': 'Web Article About AI',
                'authors': ['Carol Davis'],
                'year': '2024',
                'document_type': 'web_article'
            },
            'original_filename': 'article.html',
            'description': 'Web article as HTML'
        },
        {
            'metadata': {
                'title': 'E-book Novel',
                'authors': ['David Brown'],
                'year': '2023',
                'document_type': 'ebook',
                'format': 'mobi'
            },
            'original_filename': None,
            'description': 'E-book with format metadata'
        }
    ]
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['description']}")
        print(f"  Metadata: {test_case['metadata']}")
        if test_case['original_filename']:
            print(f"  Original: {test_case['original_filename']}")
        
        filename = gen.generate_filename(test_case['metadata'], test_case['original_filename'])
        print(f"  Generated: {filename}")
