#!/usr/bin/env python3
"""
Identifier validation for academic papers and documents.

Validates DOI, ISSN, ISBN, and URL formats to prevent hallucinated data.
"""

import re
from typing import Optional, Dict, Tuple
from urllib.parse import urlparse

from .isbn_matcher import ISBNMatcher


class IdentifierValidator:
    """Validates academic and document identifiers."""
    
    # Regex patterns
    DOI_PATTERN = re.compile(r'^10\.\d{4,}/[^\s]+$')
    ISSN_PATTERN = re.compile(r'^\d{4}-\d{3}[0-9X]$')
    ARXIV_NEW_PATTERN = re.compile(r'^\d{4}\.\d{4,5}$')  # 2301.12345
    ARXIV_OLD_PATTERN = re.compile(r'^[a-z\-]+(?:\.[A-Z]{2})?/\d{7}$')  # cs.AI/0001001
    
    # Suspicious patterns that indicate hallucination
    FAKE_PATTERNS = [
        r'^1234-5678$',  # ISSN
        r'^978-?123-?456-?789-?[0-9X]?$',  # ISBN
        r'^10\.1234/',  # DOI
        r'^10\.9999/',  # DOI
    ]
    
    @classmethod
    def validate_doi(cls, doi: Optional[str]) -> Tuple[bool, Optional[str], str]:
        """Validate DOI format.
        
        Args:
            doi: DOI string to validate
            
        Returns:
            (is_valid, cleaned_doi, reason)
        """
        if not doi:
            return (True, None, "No DOI provided")
        
        # Clean the DOI
        doi = doi.strip()
        
        # Remove common prefixes
        if doi.lower().startswith('doi:'):
            doi = doi[4:].strip()
        if doi.startswith('https://doi.org/'):
            doi = doi[16:].strip()
        if doi.startswith('http://dx.doi.org/'):
            doi = doi[18:].strip()
        
        # Check for suspicious patterns
        for pattern in cls.FAKE_PATTERNS:
            if re.match(pattern, doi):
                return (False, None, f"Suspicious pattern: {doi}")
        
        # Validate format
        if cls.DOI_PATTERN.match(doi):
            return (True, doi, "Valid DOI")
        else:
            return (False, None, f"Invalid DOI format: {doi}")
    
    @classmethod
    def validate_issn(cls, issn: Optional[str]) -> Tuple[bool, Optional[str], str]:
        """Validate ISSN format and checksum.
        
        Args:
            issn: ISSN string to validate
            
        Returns:
            (is_valid, cleaned_issn, reason)
        """
        if not issn:
            return (True, None, "No ISSN provided")
        
        # Clean the ISSN
        issn = issn.strip().upper()
        issn = issn.replace('ISSN', '').replace(':', '').strip()
        issn = issn.replace(' ', '-')
        
        # Check for suspicious patterns
        for pattern in cls.FAKE_PATTERNS:
            if re.match(pattern, issn):
                return (False, None, f"Suspicious pattern: {issn}")
        
        # Validate format
        if not cls.ISSN_PATTERN.match(issn):
            return (False, None, f"Invalid ISSN format: {issn}")
        
        # Validate checksum
        if cls._validate_issn_checksum(issn):
            return (True, issn, "Valid ISSN")
        else:
            return (False, None, f"Invalid ISSN checksum: {issn}")
    
    @classmethod
    def _validate_issn_checksum(cls, issn: str) -> bool:
        """Validate ISSN checksum.
        
        ISSN checksum algorithm:
        - Take first 7 digits
        - Multiply by weights 8,7,6,5,4,3,2
        - Sum the products
        - Check digit = 11 - (sum mod 11)
        - If check digit is 10, use 'X'
        
        Args:
            issn: ISSN in format 1234-5678 or 1234-567X
            
        Returns:
            True if checksum is valid
        """
        # Remove hyphen
        issn_digits = issn.replace('-', '')
        
        if len(issn_digits) != 8:
            return False
        
        try:
            # Calculate weighted sum of first 7 digits
            total = 0
            for i, digit in enumerate(issn_digits[:7]):
                weight = 8 - i
                total += int(digit) * weight
            
            # Calculate check digit
            remainder = total % 11
            if remainder == 0:
                expected_check = '0'
            else:
                check_value = 11 - remainder
                expected_check = 'X' if check_value == 10 else str(check_value)
            
            # Compare with actual check digit
            actual_check = issn_digits[7]
            return actual_check == expected_check
            
        except ValueError:
            return False
    
    @classmethod
    def validate_isbn(cls, isbn: Optional[str]) -> Tuple[bool, Optional[str], str]:
        """Validate ISBN format using existing ISBNMatcher.
        
        Args:
            isbn: ISBN string to validate
            
        Returns:
            (is_valid, cleaned_isbn, reason)
        """
        if not isbn:
            return (True, None, "No ISBN provided")
        
        # Check for suspicious patterns first
        isbn_stripped = isbn.strip().replace('-', '').replace(' ', '')
        for pattern in cls.FAKE_PATTERNS:
            if re.match(pattern, isbn_stripped):
                return (False, None, f"Suspicious pattern: {isbn}")
        
        # Use existing ISBNMatcher for validation
        is_valid, message = ISBNMatcher.validate_isbn(isbn)
        
        if is_valid:
            # Extract clean ISBN for return
            clean_isbn = ISBNMatcher.extract_clean_isbn(isbn)
            return (True, clean_isbn, message)
        else:
            return (False, None, message)
    
    @classmethod
    def validate_arxiv_id(cls, arxiv_id: Optional[str]) -> Tuple[bool, Optional[str], str]:
        """Validate arXiv ID format.
        
        Args:
            arxiv_id: arXiv ID string to validate
            
        Returns:
            (is_valid, cleaned_arxiv_id, reason)
        """
        if not arxiv_id:
            return (True, None, "No arXiv ID provided")
        
        # Clean the arXiv ID
        arxiv_id = arxiv_id.strip()
        arxiv_id = arxiv_id.replace('arXiv:', '').replace('arxiv:', '').strip()
        
        # Validate format (new or old)
        if cls.ARXIV_NEW_PATTERN.match(arxiv_id):
            return (True, arxiv_id, "Valid arXiv ID (new format)")
        elif cls.ARXIV_OLD_PATTERN.match(arxiv_id):
            return (True, arxiv_id, "Valid arXiv ID (old format)")
        else:
            return (False, None, f"Invalid arXiv ID format: {arxiv_id}")
    
    @classmethod
    def validate_url(cls, url: Optional[str]) -> Tuple[bool, Optional[str], str]:
        """Validate URL format.
        
        Args:
            url: URL string to validate
            
        Returns:
            (is_valid, cleaned_url, reason)
        """
        if not url:
            return (True, None, "No URL provided")
        
        url = url.strip()
        
        # Basic URL validation
        try:
            result = urlparse(url)
            if all([result.scheme, result.netloc]):
                # Check if it's http or https
                if result.scheme in ['http', 'https']:
                    return (True, url, "Valid URL")
                else:
                    return (False, None, f"Invalid URL scheme: {result.scheme}")
            else:
                return (False, None, f"Invalid URL format: {url}")
        except Exception as e:
            return (False, None, f"URL parsing error: {e}")
    
    @classmethod
    def validate_all(cls, metadata: Dict) -> Dict:
        """Validate all identifiers in metadata dictionary.
        
        Args:
            metadata: Dictionary with potential identifiers
            
        Returns:
            Dictionary with validated identifiers and confidence scores
        """
        validated = {}
        confidence_flags = []
        
        # Validate DOI
        doi_valid, doi_clean, doi_reason = cls.validate_doi(metadata.get('doi'))
        validated['doi'] = doi_clean
        validated['doi_valid'] = doi_valid
        validated['doi_reason'] = doi_reason
        if not doi_valid and metadata.get('doi'):
            confidence_flags.append(f"Invalid DOI: {doi_reason}")
        
        # Validate ISSN
        issn_valid, issn_clean, issn_reason = cls.validate_issn(metadata.get('issn'))
        validated['issn'] = issn_clean
        validated['issn_valid'] = issn_valid
        validated['issn_reason'] = issn_reason
        if not issn_valid and metadata.get('issn'):
            confidence_flags.append(f"Invalid ISSN: {issn_reason}")
        
        # Validate ISBN
        isbn_valid, isbn_clean, isbn_reason = cls.validate_isbn(metadata.get('isbn'))
        validated['isbn'] = isbn_clean
        validated['isbn_valid'] = isbn_valid
        validated['isbn_reason'] = isbn_reason
        if not isbn_valid and metadata.get('isbn'):
            confidence_flags.append(f"Invalid ISBN: {isbn_reason}")
        
        # Validate arXiv ID
        arxiv_valid, arxiv_clean, arxiv_reason = cls.validate_arxiv_id(metadata.get('arxiv_id'))
        validated['arxiv_id'] = arxiv_clean
        validated['arxiv_id_valid'] = arxiv_valid
        validated['arxiv_id_reason'] = arxiv_reason
        if not arxiv_valid and metadata.get('arxiv_id'):
            confidence_flags.append(f"Invalid arXiv ID: {arxiv_reason}")
        
        # Validate URL
        url_valid, url_clean, url_reason = cls.validate_url(metadata.get('url'))
        validated['url'] = url_clean
        validated['url_valid'] = url_valid
        validated['url_reason'] = url_reason
        if not url_valid and metadata.get('url'):
            confidence_flags.append(f"Invalid URL: {url_reason}")
        
        # Copy other metadata fields
        for key in ['title', 'authors', 'journal', 'publisher', 'year', 'document_type']:
            if key in metadata:
                validated[key] = metadata[key]
        
        # Calculate overall confidence
        validated['confidence_flags'] = confidence_flags
        validated['has_hallucinations'] = len(confidence_flags) > 0
        
        return validated
