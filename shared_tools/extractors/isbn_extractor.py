"""
ISBN extraction with fixed regex patterns and Nordic support
"""

import re
import logging
from typing import Optional, List, Tuple
from dataclasses import dataclass

@dataclass
class ISBNResult:
    """Result of ISBN extraction"""
    isbn: str
    source: str  # 'barcode' or 'ocr'
    confidence: float
    raw_text: Optional[str] = None

class ISBNExtractor:
    """Extract ISBNs from text with proper validation"""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Fixed ISBN patterns that preserve digit order and handle various spacing
        self.patterns = [
            # ISBN with flexible spacing around hyphens
            (re.compile(r'ISBN[\s:\-]*(\d{3}\s*[\-\s]+\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])', re.I), 'isbn13_spaced'),
            (re.compile(r'ISBN[\s:\-]*(\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])', re.I), 'isbn10_spaced'),
            
            # Standard ISBN with single hyphens/spaces
            (re.compile(r'ISBN[\s:\-]*(\d{3}[\s\-]\d{1,5}[\s\-]\d{1,7}[\s\-]\d{1,7}[\s\-][\dX])', re.I), 'isbn13_formatted'),
            (re.compile(r'ISBN[\s:\-]*(\d{1,5}[\s\-]\d{1,7}[\s\-]\d{1,7}[\s\-][\dX])', re.I), 'isbn10_formatted'),
            
            # Clean ISBN (no formatting)
            (re.compile(r'ISBN[\s:\-]*(\d{13})(?!\d)', re.I), 'isbn13_clean'),
            (re.compile(r'ISBN[\s:\-]*(\d{10})(?!\d)', re.I), 'isbn10_clean'),
            (re.compile(r'ISBN[\s:\-]*(\d{9}X)', re.I), 'isbn10_x'),
            
            # ISBN patterns WITHOUT "ISBN" prefix (for cases where OCR misses the prefix)
            (re.compile(r'(?:^|\D)(\d{3}\s*[\-\s]+\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])(?!\d)', re.I), 'isbn13_no_prefix'),
            (re.compile(r'(?:^|\D)(\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])(?!\d)', re.I), 'isbn10_no_prefix'),
            (re.compile(r'(?:^|\D)(\d{13})(?!\d)', re.I), 'isbn13_clean_no_prefix'),
            (re.compile(r'(?:^|\D)(\d{10})(?!\d)', re.I), 'isbn10_clean_no_prefix'),
            
            # Nordic specific patterns with flexible spacing
            (re.compile(r'(?:^|\D)(82\s*[\-\s]+\d{2}\s*[\-\s]+\d{5}\s*[\-\s]+\d)(?!\d)'), 'norwegian'),
            (re.compile(r'(?:^|\D)(91\s*[\-\s]+\d{2}\s*[\-\s]+\d{5}\s*[\-\s]+\d)(?!\d)'), 'swedish'),
            (re.compile(r'(?:^|\D)(87\s*[\-\s]+\d{2}\s*[\-\s]+\d{5}\s*[\-\s]+\d)(?!\d)'), 'danish'),
            (re.compile(r'(?:^|\D)(951\s*[\-\s]+\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])(?!\d)'), 'finnish'),
            (re.compile(r'(?:^|\D)(952\s*[\-\s]+\d{1,5}\s*[\-\s]+\d{1,7}\s*[\-\s]+[\dX])(?!\d)'), 'finnish'),
        ]
    
    def clean_isbn(self, isbn_match: str) -> str:
        """Clean ISBN match - preserve original digit order!"""
        # Remove all non-alphanumeric characters
        return ''.join(c for c in isbn_match if c.isdigit() or c.upper() == 'X')
    
    def validate_isbn_checksum(self, isbn: str) -> bool:
        """Validate ISBN checksum"""
        if len(isbn) == 10:
            return self._validate_isbn10(isbn)
        elif len(isbn) == 13:
            return self._validate_isbn13(isbn)
        return False
    
    def _validate_isbn10(self, isbn: str) -> bool:
        """Validate ISBN-10 checksum"""
        try:
            total = sum((i + 1) * (int(digit) if digit != 'X' else 10) 
                       for i, digit in enumerate(isbn))
            return total % 11 == 0
        except:
            return False
    
    def _validate_isbn13(self, isbn: str) -> bool:
        """Validate ISBN-13 checksum"""
        try:
            total = sum(int(digit) * (3 if i % 2 else 1) 
                       for i, digit in enumerate(isbn[:-1]))
            check = (10 - (total % 10)) % 10
            return check == int(isbn[-1])
        except:
            return False
    
    def extract_from_text(self, text: str) -> List[ISBNResult]:
        """Extract all valid ISBNs from text"""
        results = []
        
        # Log the text we're searching
        if 'ISBN' in text.upper():
            self.logger.debug(f"Text contains ISBN: {text[:100]}")
        

        
        for pattern, pattern_name in self.patterns:
            matches = pattern.findall(text)
            
            for match in matches:
                clean_isbn = self.clean_isbn(match)
                
                # Log what we found
                if match:
                    self.logger.debug(f"Pattern {pattern_name} matched: '{match}' -> '{clean_isbn}'")
                
                # Validate length
                if len(clean_isbn) not in [10, 13]:
                    continue
                
                # Calculate confidence based on pattern and validation
                confidence = 0.9 if 'isbn' in pattern_name.lower() else 0.7
                
                if self.validate_isbn_checksum(clean_isbn):
                    confidence += 0.1
                
                # Nordic ISBNs get a boost
                if pattern_name in ['norwegian', 'swedish', 'danish', 'finnish']:
                    confidence = min(confidence + 0.05, 1.0)
                
                result = ISBNResult(
                    isbn=clean_isbn,
                    source='ocr',
                    confidence=confidence,
                    raw_text=match
                )
                
                results.append(result)
                self.logger.info(f"Found ISBN via {pattern_name}: {clean_isbn}")
        
        # Remove duplicates, keep highest confidence
        unique_isbns = {}
        for result in results:
            if result.isbn not in unique_isbns or result.confidence > unique_isbns[result.isbn].confidence:
                unique_isbns[result.isbn] = result
        
        return list(unique_isbns.values())
