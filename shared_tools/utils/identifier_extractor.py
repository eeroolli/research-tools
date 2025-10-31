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
        # With doi: prefix (standard)
        r'doi:\s*(10\.\d{4,}/[^\s\)]+)',
        # OCR error variants: DO!, DO1, DOl, DOI (case-insensitive)
        r'DO[!1lI]:\s*(10\.\d{4,}/[^\s\)]+)',
        # Standalone OCR error variants with word boundary
        r'\bDO[!1lI]\s*:\s*(10\.\d{4,}/[^\s\)]+)',
        # Raw DOI (no prefix)
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
                
                # Clean any remaining prefixes (including OCR errors)
                doi = re.sub(r'^(doi:|DO[!1lI]:|https?://.*?/)', '', doi, flags=re.IGNORECASE)
                doi = doi.strip()
                
                # Normalize any OCR artifacts in the DOI itself
                # Replace common OCR errors: "O" misread as "0" or "o", "I" as "1" or "l", etc.
                # But be careful - we don't want to corrupt valid DOIs
                # Only fix if we see obvious OCR errors in the prefix-like part
                
                # Remove trailing punctuation that might be captured
                doi = re.sub(r'[.,;:\s]+$', '', doi)
                
                if doi and doi not in dois:
                    dois.append(doi)
        
        return dois
    
    @classmethod
    def extract_issns(cls, text: str) -> List[str]:
        """Extract all ISSNs from text, preferring online over print.
        
        Args:
            text: Text to search for ISSNs
            
        Returns:
            List of ISSN strings in format 1234-5678, with online ISSN first
            when both print and online ISSNs are present.
        """
        issns_with_context = []  # List of (issn, is_online) tuples
        
        matches = re.finditer(cls.ISSN_PATTERN, text, re.IGNORECASE)
        for match in matches:
            issn = match.group(1).upper()
            start_pos = match.start()
            end_pos = match.end()
            
            # Look for context markers in the surrounding text (20 chars after ISSN)
            # Only check immediate context to avoid noise from distant keywords
            context_start = max(0, start_pos)
            context_end = min(len(text), end_pos + 20)
            context = text[context_start:context_end].lower()
            
            # Check proximity to online and print markers
            online_markers = [
                'online', 'electronic', 'e-issn', 'eissn', 
                'issn (online)', 'issn online', 'online issn'
            ]
            print_markers = [
                'print', 'p-issn', 'pissn', 'issn print', 'print issn'
            ]
            
            # Find closest online and print markers in local context only
            min_online_dist = float('inf')
            min_print_dist = float('inf')
            
            # Calculate distance from end of ISSN (where markers typically appear)
            issn_end_in_context = end_pos - context_start
            
            for marker in online_markers:
                pos = context.find(marker)
                if pos != -1:
                    # Distance from ISSN end to marker start
                    dist = abs(pos - issn_end_in_context)
                    min_online_dist = min(min_online_dist, dist)
            
            for marker in print_markers:
                pos = context.find(marker)
                if pos != -1:
                    # Distance from ISSN end to marker start
                    dist = abs(pos - issn_end_in_context)
                    min_print_dist = min(min_print_dist, dist)
            
            # Determine if this is an online ISSN
            # Only classify if marker found in immediate context (within 20 chars)
            # If both found, online wins if it's closer; if only one found, use that
            is_online = False
            if min_online_dist < float('inf'):
                if min_print_dist == float('inf'):
                    # Only online marker found
                    is_online = True
                else:
                    # Both found - online wins if closer or equal distance
                    is_online = min_online_dist <= min_print_dist
            
            # Store ISSN with context
            if (issn, is_online) not in issns_with_context:
                issns_with_context.append((issn, is_online))
        
        # Separate online and print/other ISSNs
        online_issns = [issn for issn, is_online in issns_with_context if is_online]
        other_issns = [issn for issn, is_online in issns_with_context if not is_online]
        
        # Return with online ISSNs first, then others (print/unspecified)
        result = online_issns + other_issns
        
        # Remove duplicates while preserving order
        seen = set()
        unique_result = []
        for issn in result:
            if issn not in seen:
                seen.add(issn)
                unique_result.append(issn)
        
        return unique_result
    
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
        
        Excludes JSTOR URLs (which are extracted separately) to avoid double counting.
        
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
            # Skip JSTOR URLs - they're handled separately
            if 'jstor.org' in url.lower():
                continue
            if url not in urls:
                urls.append(url)
        
        return urls
    
    @classmethod
    def extract_jstor_ids(cls, text: str) -> List[str]:
        """Extract JSTOR stable URL IDs from text.
        
        Args:
            text: Text to search for JSTOR URLs
            
        Returns:
            List of JSTOR stable URL IDs (e.g., "2289064")
        """
        jstor_ids = []
        
        # JSTOR stable URL pattern: http(s)://www.jstor.org/stable/NUMBER
        jstor_pattern = r'https?://(?:www\.)?jstor\.org/stable/(\d+)'
        
        matches = re.finditer(jstor_pattern, text, re.IGNORECASE)
        for match in matches:
            jstor_id = match.group(1)
            if jstor_id and jstor_id not in jstor_ids:
                jstor_ids.append(jstor_id)
        
        return jstor_ids
    
    @classmethod
    def extract_arxiv_ids(cls, text: str) -> List[str]:
        """Extract all arXiv IDs from text.
        
        Args:
            text: Text to search for arXiv IDs
            
        Returns:
            List of arXiv ID strings
        """
        arxiv_ids = []
        
        # Known arXiv subject categories (used in old format like "cs.AI/0001001")
        ARXIV_SUBJECTS = {
            'cs', 'math', 'physics', 'astro-ph', 'cond-mat', 'gr-qc', 
            'hep', 'nlin', 'nucl', 'quantum', 'stat', 'econ', 'eess',
            'q-bio', 'q-fin', 'stat-ap', 'stat-co', 'stat-me', 'stat-ot',
            'stat-th', 'math-ph', 'math-ac', 'math-ag', 'math-at', 'math-ca',
            'math-ct', 'math-cv', 'math-dg', 'math-ds', 'math-fa', 'math-gm',
            'math-gn', 'math-gr', 'math-gt', 'math-ho', 'math-it', 'math-kt',
            'math-lo', 'math-mg', 'math-mp', 'math-na', 'math-nt', 'math-oa',
            'math-oc', 'math-pr', 'math-qa', 'math-ra', 'math-rt', 'math-sg',
            'math-sp', 'math-st', 'astro-ph.co', 'astro-ph.ep', 'astro-ph.ga',
            'astro-ph.he', 'astro-ph.im', 'astro-ph.sr'
        }
        
        for pattern in cls.ARXIV_PATTERNS:
            matches = re.finditer(pattern, text, re.IGNORECASE)
            for match in matches:
                arxiv_id = match.group(1)
                # Validate basic format
                if arxiv_id and arxiv_id not in arxiv_ids:
                    # Check if "arxiv" appears within 20 characters of the match
                    match_start = match.start()
                    context_start = max(0, match_start - 20)
                    context_end = min(len(text), match.end() + 20)
                    context = text[context_start:context_end].lower()
                    
                    if 'arxiv' not in context:
                        # Skip if no "arxiv" mention nearby
                        continue
                    
                    # Skip if it looks like a version number or other numeric pattern
                    # Only accept if it starts with digit or known arXiv subject
                    if re.match(r'^\d{4}\.\d{4,5}$', arxiv_id):
                        # New format (e.g., 2301.12345)
                        arxiv_ids.append(arxiv_id)
                    elif '/' in arxiv_id:
                        # Old format (e.g., cs.AI/0001001)
                        # Extract the subject prefix
                        subject = arxiv_id.split('/')[0].lower()
                        # Check if it's a valid arXiv subject
                        if subject in ARXIV_SUBJECTS:
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
            'jstor_ids': cls.extract_jstor_ids(text),
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
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': []}
        
        try:
            from pathlib import Path
            pdf_path = Path(pdf_path)
            
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': []}
                
                # Extract text from first page
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                
                if not text:
                    return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': []}
                
                # Extract all identifiers
                return cls.extract_all(text)
                
        except Exception as e:
            print(f"Error extracting identifiers from {pdf_path}: {e}")
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': []}


if __name__ == "__main__":
    # Quick test
    test_text = """
    Article https://doi.org/10.1038/s42256-025-01072-0
    
    ISSN: 2522-5839
    ISBN: 978-0-262-03384-8
    
    Visit our website at https://www.nature.com/articles/s42256-025-01072-0
    
    DOI: 10.1234/fake.doi
    
    OCR error test: DO!: 10.1080/13501780701394094
    Another OCR error: DO1: 10.1000/test.doi
    Yet another: DOl: 10.2000/example.doi
    """
    
    print("Testing identifier extraction:")
    print("=" * 60)
    results = IdentifierExtractor.extract_all(test_text)
    
    print(f"\nDOIs found: {results['dois']}")
    print(f"ISSNs found: {results['issns']}")
    print(f"ISBNs found: {results['isbns']}")
    print(f"URLs found: {results['urls']}")
    
    # Verify OCR error handling
    expected_ocr_dois = ['10.1080/13501780701394094', '10.1000/test.doi', '10.2000/example.doi']
    print(f"\nOCR error test DOIs: {expected_ocr_dois}")
    print(f"All OCR DOIs found: {all(doi in results['dois'] for doi in expected_ocr_dois)}")
