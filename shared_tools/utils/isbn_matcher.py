"""
Shared ISBN matching utilities for consistent ISBN comparison across the codebase.
"""
import re
from typing import Optional


class ISBNMatcher:
    """Shared ISBN matching utilities"""
    
    @staticmethod
    def normalize_isbn(isbn: str) -> str:
        """Normalize ISBN to standard format for comparison"""
        if not isbn:
            return ""
        
        # Remove all non-alphanumeric characters except X
        cleaned = ''.join(c for c in isbn.upper() if c.isalnum() or c == 'X')
        
        return cleaned
    
    @staticmethod
    def extract_clean_isbn(isbn_text: str) -> str:
        """Extract clean ISBN from text that might contain additional info like (pbk.) or (hardcover)"""
        if not isbn_text:
            return ""
        
        # Remove common additional info in parentheses
        # Remove text in parentheses like (pbk.), (hardcover), (paperback), etc.
        cleaned = re.sub(r'\s*\([^)]*\)', '', isbn_text)
        
        # First try to extract digits only (remove all non-digits except X)
        digits_only = ''.join(c for c in cleaned.upper() if c.isdigit() or c == 'X')
        
        # Check if we have a valid length ISBN
        if len(digits_only) in [10, 13]:
            return digits_only
        
        # If that didn't work, try regex patterns for formatted ISBNs
        # Look for ISBN-13 patterns: XXX-XXXX-XXXX-XXXX or XXX-XXXX-XXXX-X
        isbn13_pattern = re.search(r'(\d{3}[\s\-]?\d{1,5}[\s\-]?\d{1,7}[\s\-]?\d{1,7}[\s\-]?[\dX])', cleaned)
        if isbn13_pattern:
            # Extract just the digits
            match = isbn13_pattern.group(1)
            digits = ''.join(c for c in match if c.isdigit() or c == 'X')
            if len(digits) == 13:
                return digits
        
        # Look for ISBN-10 patterns: XXXXX-XXXX-X or XXXXX-XXXXX-X
        isbn10_pattern = re.search(r'(\d{1,5}[\s\-]?\d{1,7}[\s\-]?\d{1,7}[\s\-]?[\dX])', cleaned)
        if isbn10_pattern:
            # Extract just the digits
            match = isbn10_pattern.group(1)
            digits = ''.join(c for c in match if c.isdigit() or c == 'X')
            if len(digits) == 10:
                return digits
        
        return ""
    
    @staticmethod
    def validate_isbn(isbn: str) -> tuple[bool, str]:
        """
        Validate ISBN and provide detailed error messages.
        
        Args:
            isbn: ISBN string to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not isbn:
            return False, "ISBN is empty"
        
        # Clean the ISBN
        clean_isbn = ISBNMatcher.extract_clean_isbn(isbn)
        if not clean_isbn:
            return False, f"Unable to extract valid ISBN from: '{isbn}'"
        
        # Check length
        if len(clean_isbn) == 10:
            return ISBNMatcher._validate_isbn10(clean_isbn)
        elif len(clean_isbn) == 13:
            return ISBNMatcher._validate_isbn13(clean_isbn)
        else:
            return False, f"Invalid ISBN length: {len(clean_isbn)} digits (expected 10 or 13)"
    
    @staticmethod
    def _validate_isbn10(isbn: str) -> tuple[bool, str]:
        """Validate ISBN-10 format and checksum."""
        if len(isbn) != 10:
            return False, f"ISBN-10 must be exactly 10 digits, got {len(isbn)}"
        
        # Check for valid characters (digits 0-9 and X for check digit)
        for i, char in enumerate(isbn):
            if i == 9:  # Check digit position
                if not (char.isdigit() or char.upper() == 'X'):
                    return False, f"Invalid check digit '{char}' at position 10 (must be 0-9 or X)"
            else:
                if not char.isdigit():
                    return False, f"Invalid character '{char}' at position {i+1} (must be 0-9)"
        
        # Validate checksum
        checksum = 0
        for i, char in enumerate(isbn):
            if i == 9 and char.upper() == 'X':
                checksum += 10 * (10 - i)
            else:
                checksum += int(char) * (10 - i)
        
        if checksum % 11 != 0:
            return False, f"Invalid ISBN-10 checksum (expected multiple of 11, got {checksum})"
        
        return True, "Valid ISBN-10"
    
    @staticmethod
    def _validate_isbn13(isbn: str) -> tuple[bool, str]:
        """Validate ISBN-13 format and checksum."""
        if len(isbn) != 13:
            return False, f"ISBN-13 must be exactly 13 digits, got {len(isbn)}"
        
        # Check for valid characters (only digits 0-9)
        for i, char in enumerate(isbn):
            if not char.isdigit():
                return False, f"Invalid character '{char}' at position {i+1} (must be 0-9)"
        
        # Validate checksum using ISBN-13 algorithm
        checksum = 0
        for i, char in enumerate(isbn[:-1]):  # All digits except check digit
            weight = 1 if i % 2 == 0 else 3
            checksum += int(char) * weight
        
        check_digit = (10 - (checksum % 10)) % 10
        actual_check_digit = int(isbn[-1])
        
        if check_digit != actual_check_digit:
            return False, f"Invalid ISBN-13 checksum (expected {check_digit}, got {actual_check_digit})"
        
        return True, "Valid ISBN-13"
    
    @staticmethod
    def match_isbn(isbn1: str, isbn2: str) -> bool:
        """
        Enhanced ISBN matching using substring approach.
        
        Args:
            isbn1: First ISBN to compare
            isbn2: Second ISBN to compare
            
        Returns:
            True if the ISBNs represent the same book, False otherwise
        """
        if not isbn1 or not isbn2:
            return False
        
        # Normalize both ISBNs
        norm1 = ISBNMatcher.normalize_isbn(isbn1)
        norm2 = ISBNMatcher.normalize_isbn(isbn2)
        
        # Exact match
        if norm1 == norm2:
            return True
        
        # Check if one ISBN is contained in the other
        # ISBN-10 check digit is replaced by ISBN-13 check digit
        # So we compare first 9 digits of ISBN-10 with positions 3-12 of ISBN-13
        if len(norm1) == 10 and len(norm2) == 13:
            # Compare first 9 digits of ISBN-10 with positions 3-12 of ISBN-13
            return norm1[0:9] == norm2[3:12]
        elif len(norm1) == 13 and len(norm2) == 10:
            # Compare first 9 digits of ISBN-10 with positions 3-12 of ISBN-13
            return norm2[0:9] == norm1[3:12]
        
        return False
    
    @staticmethod
    def extract_isbn_prefix(isbn: str) -> tuple[str, str]:
        """
        Extract ISBN prefix for national library mapping.
        
        Args:
            isbn: ISBN string (can be formatted or clean)
            
        Returns:
            Tuple of (2-digit_prefix, 3-digit_prefix)
        """
        clean_isbn = ISBNMatcher.extract_clean_isbn(isbn)
        if not clean_isbn:
            return "", ""
        
        # Known prefixes for matching (sorted by length, longest first)
        known_prefixes = ['950', '951', '952', '958', '959', '968', '970', '972', '980', '987', '989', '82', '84', '85', '87', '91', '93', '0', '1', '2', '3']
        
        if len(clean_isbn) == 13:
            # ISBN-13: registration group starts after the EAN prefix (978, 979, etc.)
            if clean_isbn.startswith(('978', '979')):
                # For 978/979, the registration group starts at position 3
                # Try different lengths to match our known prefixes (longest first)
                for length in [5, 4, 3, 2, 1]:
                    prefix = clean_isbn[3:3+length]
                    if prefix in known_prefixes:
                        return prefix[:2], prefix[:3]
                # If no match, return first 2 and 3 digits after EAN prefix
                prefix_2 = clean_isbn[3:5]
                prefix_3 = clean_isbn[3:6]
                return prefix_2, prefix_3
            else:
                # For other ISBN-13 prefixes, try to extract meaningful prefix
                # This is less common but possible
                for length in [5, 4, 3, 2, 1]:
                    prefix = clean_isbn[:length]
                    if prefix in known_prefixes:
                        return prefix[:2], prefix[:3]
                return clean_isbn[:2], clean_isbn[:3]
                
        elif len(clean_isbn) == 10:
            # ISBN-10: registration group is first 1-5 digits
            # Try different lengths to match our known prefixes (longest first)
            for length in [5, 4, 3, 2, 1]:
                prefix = clean_isbn[:length]
                if prefix in known_prefixes:
                    return prefix[:2], prefix[:3]
            # If no match, return first 2 and 3 digits
            return clean_isbn[:2], clean_isbn[:3]
        
        # Fallback
        return clean_isbn[:2], clean_isbn[:3]
    
    @staticmethod
    def extract_and_match_isbn(search_isbn: str, item_isbn_text: str) -> bool:
        """
        Extract clean ISBN from item text and match against search ISBN.
        
        Args:
            search_isbn: The ISBN we're searching for
            item_isbn_text: The ISBN text from Zotero item (may contain formatting)
            
        Returns:
            True if the ISBNs match, False otherwise
        """
        if not search_isbn or not item_isbn_text:
            return False
        
        # Extract clean ISBN from item text
        clean_item_isbn = ISBNMatcher.extract_clean_isbn(item_isbn_text)
        if not clean_item_isbn:
            return False
        
        # Match the ISBNs
        return ISBNMatcher.match_isbn(search_isbn, clean_item_isbn)
