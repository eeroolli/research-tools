#!/usr/bin/env python3
"""
Fast regex-based identifier extraction from PDF text.

Extracts DOI, ISBN, ISSN, and URLs using regex patterns before
resorting to slower AI-based extraction.
"""

import re
from typing import Optional, List, Tuple
from .isbn_matcher import ISBNMatcher


class IdentifierExtractor:
    """Fast regex-based identifier extraction."""
    
    # DOI patterns - handles various formats
    DOI_PATTERNS = [
        # With https://doi.org/ prefix
        r'https?://doi\.org/(10\.\d{4,}/[^\s\)]+)',
        # With http://dx.doi.org/ prefix
        r'https?://dx\.doi\.org/(10\.\d{4,}/[^\s\)]+)',
        # With doi: prefix
        r'doi:\s*(10\.\d{4,}/[^\s\)]+)',
        # Raw DOI
        r'\b(10\.\d{4,}/[^\s\)]+)',
    ]
    
    # ISSN pattern: 1234-5678 or 1234-567X
    ISSN_PATTERN = r'\bISSN[:\s]*(\d{4}-\d{3}[0-9X])\b'
    
    # URL patterns - http(s) URLs
    URL_PATTERN = r'https?://[^\s<>"\'{}\[\]\\|^`]+'
    
    # arXiv patterns
    ARXIV_PATTERNS = [
        # New format: 2301.12345 or arXiv:2301.12345
        r'arXiv:\s*(\d{4}\.\d{4,5})',
        r'\b(\d{4}\.\d{4,5})\b',  # Bare format
        # Old format: cs.AI/0001001
        r'arXiv:\s*([a-z\-]+(?:\.[A-Z]{2})?/\d{7})',
        r'\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})\b',
    ]
    
    @classmethod
    def extract_dois(cls, text: str) -> List[str]:
        """Extract all DOIs from text.
        
        Args:
            text: Text to search for DOIs
            
        Returns:
            List of cleaned DOI strings (without prefixes)
        """
        dois = []
        
        for pattern in cls.DOI_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                # Extract the DOI (without prefix)
                if len(match.groups()) > 0:
                    doi = match.group(1)
                else:
                    doi = match.group(0)
                
                # Clean any remaining prefixes
                doi = re.sub(r'^(doi:|https?://.*?/)', '', doi, flags=re.IGNORECASE)
                doi = doi.strip()
                
                # Remove trailing punctuation that might be captured
                doi = re.sub(r'[.,;:\s]+$', '', doi)
                
                if doi and doi not in dois:
                    dois.append(doi)
        
        return dois
    
    @classmethod
    def extract_issns(cls, text: str) -> List[str]:
        """Extract all ISSNs from text.
        
        Args:
            text: Text to search for ISSNs
            
        Returns:
            List of ISSN strings in format 1234-5678
        """
        issns = []
        
        matches = re.finditer(cls.ISSN_PATTERN, text, re.IGNORECASE)
        for match in matches:
            issn = match.group(1).upper()
            if issn not in issns:
                issns.append(issn)
        
        return issns
    
    @classmethod
    def extract_isbns(cls, text: str) -> List[str]:
        """Extract all ISBNs from text using existing ISBNMatcher.
        
        Args:
            text: Text to search for ISBNs
            
        Returns:
            List of cleaned ISBN strings
        """
        isbns = []
        
        # ISBN patterns - look for ISBN prefix followed by numbers
        isbn_patterns = [
            r'ISBN[:\s-]*([0-9X\-\s]{10,17})',  # With ISBN prefix
            r'\b(97[89][\d\-\s]{10,16})\b',  # ISBN-13 starting with 978/979
        ]
        
        for pattern in isbn_patterns:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                isbn_text = match.group(1)
                # Use existing ISBNMatcher to clean and validate
                clean_isbn = ISBNMatcher.extract_clean_isbn(isbn_text)
                if clean_isbn and clean_isbn not in isbns:
                    # Validate it's a real ISBN
                    is_valid, _ = ISBNMatcher.validate_isbn(clean_isbn)
                    if is_valid:
                        isbns.append(clean_isbn)
        
        return isbns
    
    @classmethod
    def extract_urls(cls, text: str) -> List[str]:
        """Extract all URLs from text.
        
        Args:
            text: Text to search for URLs
            
        Returns:
            List of URL strings
        """
        urls = []
        
        matches = re.finditer(cls.URL_PATTERN, text)
        for match in matches:
            url = match.group(0)
            # Remove trailing punctuation
            url = re.sub(r'[.,;:\s]+$', '', url)
            if url not in urls:
                urls.append(url)
        
        return urls
    
    @classmethod
    def extract_arxiv_ids(cls, text: str) -> List[str]:
        """Extract all arXiv IDs from text.
        
        Args:
            text: Text to search for arXiv IDs
            
        Returns:
            List of arXiv ID strings
        """
        arxiv_ids = []
        
        for pattern in cls.ARXIV_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                arxiv_id = match.group(1)
                # Validate basic format
                if arxiv_id and arxiv_id not in arxiv_ids:
                    # Skip if it looks like a version number or other numeric pattern
                    # Only accept if it starts with digit or known arXiv subject
                    if re.match(r'^\d{4}\.\d{4,5}$', arxiv_id) or '/' in arxiv_id:
                        arxiv_ids.append(arxiv_id)
        
        return arxiv_ids
    
    @classmethod
    def extract_all(cls, text: str) -> dict:
        """Extract all identifiers from text.
        
        Args:
            text: Text to search
            
        Returns:
            Dictionary with lists of found identifiers
        """
        return {
            'dois': cls.extract_dois(text),
            'issns': cls.extract_issns(text),
            'isbns': cls.extract_isbns(text),
            'arxiv_ids': cls.extract_arxiv_ids(text),
            'urls': cls.extract_urls(text),
        }
    
    @classmethod
    def extract_first_page_identifiers(cls, pdf_path) -> dict:
        """Extract identifiers from first page of PDF.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Dictionary with found identifiers
        """
        try:
            import pdfplumber
        except ImportError:
            print("Error: pdfplumber not installed")
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'urls': []}
        
        try:
            from pathlib import Path
            pdf_path = Path(pdf_path)
            
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'urls': []}
                
                # Extract text from first page
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                
                if not text:
                    return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'urls': []}
                
                # Extract all identifiers
                return cls.extract_all(text)
                
        except Exception as e:
            print(f"Error extracting identifiers from {pdf_path}: {e}")
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'urls': []}


if __name__ == "__main__":
    # Quick test
    test_text = """
    Article https://doi.org/10.1038/s42256-025-01072-0
    
    ISSN: 2522-5839
    ISBN: 978-0-262-03384-8
    
    Visit our website at https://www.nature.com/articles/s42256-025-01072-0
    
    DOI: 10.1234/fake.doi
    """
    
    print("Testing identifier extraction:")
    print("=" * 60)
    results = IdentifierExtractor.extract_all(test_text)
    
    print(f"\nDOIs found: {results['dois']}")
    print(f"ISSNs found: {results['issns']}")
    print(f"ISBNs found: {results['isbns']}")
    print(f"URLs found: {results['urls']}")
