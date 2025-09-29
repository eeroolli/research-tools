"""
Unified metadata extractor for both academic papers and books.
"""
from typing import Dict, Optional, Any, List
from dataclasses import dataclass
from enum import Enum


class DocumentType(Enum):
    """Document types supported by the metadata extractor."""
    PAPER = "paper"
    BOOK = "book"


@dataclass
class MetadataResult:
    """Standardized metadata result format."""
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    abstract: Optional[str] = None
    publication_date: Optional[str] = None
    language: Optional[str] = None
    subjects: Optional[List[str]] = None
    tags: Optional[List[str]] = None
    confidence: float = 0.0
    source: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None


class MetadataExtractor:
    """Unified metadata extractor for papers and books."""
    
    def __init__(self, config: Dict[str, Any]):
        """Initialize the metadata extractor with configuration."""
        self.config = config
        self.api_clients = {}
        self._setup_api_clients()
    
    def _setup_api_clients(self):
        """Set up API clients for different metadata sources."""
        from ..api.config_driven_manager import ConfigDrivenNationalLibraryManager
        self.national_library_manager = ConfigDrivenNationalLibraryManager()
    
    def extract_paper_metadata(self, doi: Optional[str] = None, 
                             title: Optional[str] = None, 
                             authors: Optional[List[str]] = None,
                             language: Optional[str] = None,
                             **kwargs) -> MetadataResult:
        """
        Extract metadata for academic papers.
        
        Args:
            doi: Digital Object Identifier
            title: Paper title
            authors: List of author names
            language: Detected language code
            **kwargs: Additional parameters
            
        Returns:
            MetadataResult with extracted metadata
        """
        result = MetadataResult()
        
        # 1. Try DOI-based lookup first (CrossRef, OpenAlex)
        if doi:
            result = self._lookup_by_doi(doi, 'paper')
            if result.confidence > 70:
                return result
        
        # 2. Try national library search based on language
        if language and (title or authors):
            national_results = self._search_national_libraries(
                title=title, authors=authors, language=language, item_type='papers'
            )
            if national_results:
                result = self._merge_national_results(national_results, result)
        
        # 3. Fall back to international sources
        if result.confidence < 50:
            international_result = self._search_international_sources(
                title=title, authors=authors, item_type='papers'
            )
            result = self._merge_results(result, international_result)
        
        # 4. Use AI enhancement if needed
        if result.confidence < 70:
            result = self.enhance_with_ai(result, DocumentType.PAPER)
        
        return result
    
    def extract_book_metadata(self, isbn: Optional[str] = None,
                            title: Optional[str] = None,
                            authors: Optional[List[str]] = None,
                            **kwargs) -> MetadataResult:
        """
        Extract metadata for books.
        
        Args:
            isbn: ISBN (10 or 13 digits)
            title: Book title
            authors: List of author names
            **kwargs: Additional parameters
            
        Returns:
            MetadataResult with extracted metadata
        """
        result = MetadataResult()
        
        # 1. Determine country from ISBN prefix
        country_code = None
        if isbn:
            country_code = self.get_country_from_isbn(isbn)
        
        # 2. Try country-specific national library first
        if country_code and (title or authors or isbn):
            national_results = self._search_national_libraries(
                isbn=isbn, title=title, authors=authors, 
                country_code=country_code, item_type='books'
            )
            if national_results:
                result = self._merge_national_results(national_results, result)
        
        # 3. Fall back to international sources (Library of Congress, OpenLibrary, Google Books)
        if result.confidence < 50:
            international_result = self._search_international_sources(
                isbn=isbn, title=title, authors=authors, item_type='books'
            )
            result = self._merge_results(result, international_result)
        
        # 4. Use AI enhancement if needed
        if result.confidence < 70:
            result = self.enhance_with_ai(result, DocumentType.BOOK)
        
        return result
    
    def enhance_with_ai(self, partial_metadata: MetadataResult, 
                       document_type: DocumentType) -> MetadataResult:
        """
        Enhance partial metadata using AI.
        
        Args:
            partial_metadata: Partially filled metadata
            document_type: Type of document (paper or book)
            
        Returns:
            Enhanced MetadataResult
        """
        # TODO: Implement AI enhancement
        # Use LLM to fill in missing fields, validate data, etc.
        return partial_metadata
    
    def get_country_from_isbn(self, isbn: str) -> Optional[str]:
        """
        Determine country from ISBN prefix.
        
        Args:
            isbn: ISBN to analyze
            
        Returns:
            Country code or None if not determinable
        """
        if not isbn or len(isbn) < 3:
            return None
        
        # ISBN-13 country codes (first 3 digits after 978/979)
        if isbn.startswith('978'):
            prefix = isbn[3:6]
        elif isbn.startswith('979'):
            prefix = isbn[3:6]
        else:
            return None
        
        # Country code mapping
        country_codes = {
            '82': 'NO',  # Norway
            '951': 'FI', # Finland
            '91': 'SE',  # Sweden
            '87': 'DK',  # Denmark
            '0': 'US',   # United States
            '1': 'US',   # United States
            '2': 'FR',   # France
            '3': 'DE',   # Germany
            '4': 'JP',   # Japan
            '5': 'RU',   # Russia
            '7': 'CN',   # China
        }
        
        # Check for exact matches first
        if prefix in country_codes:
            return country_codes[prefix]
        
        # Check for partial matches
        for code, country in country_codes.items():
            if prefix.startswith(code):
                return country
        
        return None
    
    def _search_national_libraries(self, isbn: Optional[str] = None, 
                                 title: Optional[str] = None,
                                 authors: Optional[List[str]] = None,
                                 language: Optional[str] = None,
                                 country_code: Optional[str] = None,
                                 item_type: str = 'both') -> Optional[Dict[str, Any]]:
        """Search national libraries based on language or country."""
        if not hasattr(self, 'national_library_manager'):
            return None
        
        # Build search query
        query_parts = []
        if title:
            query_parts.append(title)
        if authors:
            query_parts.extend(authors[:2])  # Limit to first 2 authors
        if isbn:
            query_parts.append(isbn)
        
        query = ' '.join(query_parts)
        if not query:
            return None
        
        try:
            if country_code:
                return self.national_library_manager.search_by_country(
                    query, country_code, item_type
                )
            elif language:
                return self.national_library_manager.search_by_language(
                    query, language, item_type
                )
        except Exception as e:
            logging.error(f"National library search failed: {e}")
        
        return None
    
    def _search_international_sources(self, isbn: Optional[str] = None,
                                    title: Optional[str] = None,
                                    authors: Optional[List[str]] = None,
                                    item_type: str = 'both') -> MetadataResult:
        """Search international metadata sources."""
        result = MetadataResult()
        
        # TODO: Implement international sources (CrossRef, OpenAlex, etc.)
        # This would include API calls to:
        # - CrossRef API for papers
        # - OpenLibrary API for books
        # - Google Books API
        # - Library of Congress API
        
        return result
    
    def _lookup_by_doi(self, doi: str, document_type: str) -> MetadataResult:
        """Lookup metadata by DOI."""
        result = MetadataResult()
        
        # TODO: Implement DOI lookup
        # This would call CrossRef API or similar
        
        return result
    
    def _merge_national_results(self, national_results: Dict[str, Any], 
                              result: MetadataResult) -> MetadataResult:
        """Merge national library results into metadata result."""
        if not national_results:
            return result
        
        # Process papers if available
        papers = national_results.get('papers', [])
        if papers:
            paper = papers[0]  # Take first result
            result.title = paper.get('title', result.title)
            result.authors = paper.get('authors', result.authors)
            result.abstract = paper.get('abstract', result.abstract)
            result.language = paper.get('language', result.language)
            result.source = paper.get('source', result.source)
            result.confidence = max(result.confidence, 75.0)  # National libraries are reliable
        
        # Process books if available
        books = national_results.get('books', [])
        if books:
            book = books[0]  # Take first result
            result.title = book.get('title', result.title)
            result.authors = book.get('authors', result.authors)
            result.language = book.get('language', result.language)
            result.source = book.get('source', result.source)
            result.confidence = max(result.confidence, 75.0)  # National libraries are reliable
        
        return result
    
    def _merge_results(self, result1: MetadataResult, result2: MetadataResult) -> MetadataResult:
        """Merge two metadata results, preferring higher confidence values."""
        merged = MetadataResult()
        
        # Use higher confidence result as base
        if result1.confidence > result2.confidence:
            base, other = result1, result2
        else:
            base, other = result2, result1
        
        # Copy base values
        merged.title = base.title
        merged.authors = base.authors
        merged.abstract = base.abstract
        merged.publication_date = base.publication_date
        merged.language = base.language
        merged.subjects = base.subjects
        merged.tags = base.tags
        merged.confidence = base.confidence
        merged.source = base.source
        
        # Fill in missing values from other result
        if not merged.title and other.title:
            merged.title = other.title
        if not merged.authors and other.authors:
            merged.authors = other.authors
        if not merged.abstract and other.abstract:
            merged.abstract = other.abstract
        if not merged.language and other.language:
            merged.language = other.language
        
        # Combine tags
        if merged.tags and other.tags:
            merged.tags = list(set(merged.tags + other.tags))
        elif other.tags:
            merged.tags = other.tags
        
        return merged
