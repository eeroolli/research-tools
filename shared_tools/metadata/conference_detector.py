#!/usr/bin/env python3
"""
Conference presentation detection for academic papers.

Detects papers that are conference presentations (not published proceedings)
based on heuristics like page count, word count, and content patterns.
"""

import pdfplumber
from pathlib import Path
from typing import Dict, Tuple
import re


class ConferenceDetector:
    """Detect if a PDF is a conference presentation."""
    
    def __init__(self):
        self.conference_keywords = [
            'conference', 'workshop', 'symposium', 'colloquium',
            'presentation', 'presented at', 'presented to',
            'proceedings', 'summit', 'forum', 'meeting'
        ]
        
        self.location_patterns = [
            r'\b[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?,\s+[A-Z]{2,}',  # City, STATE/COUNTRY
            r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:-\d{1,2})?,?\s+\d{4}',  # Date
        ]
    
    def detect(self, pdf_path: Path) -> Tuple[bool, Dict]:
        """
        Detect if PDF is a conference presentation.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (is_conference, details_dict)
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Get first page text
                first_page_text = pdf.pages[0].extract_text() if pdf.pages else ""
                page_count = len(pdf.pages)
                
                # Calculate word count on first page
                words = first_page_text.split()
                word_count = len(words)
                
                # Check for indicators
                has_conference_keyword = self._has_conference_keyword(first_page_text)
                has_location = self._has_location_pattern(first_page_text)
                has_date = self._has_date_pattern(first_page_text)
                
                # Check for lack of identifiers
                has_doi = bool(re.search(r'10\.\d{4,}/\S+', first_page_text))
                has_issn = bool(re.search(r'\d{4}-\d{3}[\dX]', first_page_text))
                has_isbn = bool(re.search(r'978-\d{1,5}-\d{1,7}-\d{1,7}-\d', first_page_text))
                
                # Heuristic scoring
                score = 0
                reasons = []
                
                # Sparse first page (no abstract)
                if word_count < 100 and page_count > 5:
                    score += 3
                    reasons.append(f"Sparse first page ({word_count} words, {page_count} pages)")
                
                # Has conference keywords
                if has_conference_keyword:
                    score += 2
                    reasons.append("Contains conference-related keywords")
                
                # Has location/date
                if has_location or has_date:
                    score += 2
                    reasons.append("Contains location/date information")
                
                # Lacks identifiers
                if not has_doi and not has_issn and not has_isbn:
                    score += 2
                    reasons.append("No DOI, ISSN, or ISBN found")
                
                # Decision threshold
                is_conference = score >= 4
                
                details = {
                    'confidence_score': score,
                    'word_count': word_count,
                    'page_count': page_count,
                    'has_conference_keyword': has_conference_keyword,
                    'has_location': has_location,
                    'has_date': has_date,
                    'has_doi': has_doi,
                    'has_issn': has_issn,
                    'has_isbn': has_isbn,
                    'reasons': reasons
                }
                
                return is_conference, details
        
        except Exception as e:
            return False, {'error': str(e)}
    
    def _has_conference_keyword(self, text: str) -> bool:
        """Check if text contains conference-related keywords."""
        text_lower = text.lower()
        return any(keyword in text_lower for keyword in self.conference_keywords)
    
    def _has_location_pattern(self, text: str) -> bool:
        """Check if text contains location patterns."""
        return any(re.search(pattern, text) for pattern in self.location_patterns)
    
    def _has_date_pattern(self, text: str) -> bool:
        """Check if text contains date patterns."""
        # Look for date patterns
        date_pattern = r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}(?:-\d{1,2})?,?\s+\d{4}'
        return bool(re.search(date_pattern, text))


if __name__ == "__main__":
    # Test
    detector = ConferenceDetector()
    
    test_pdf = Path("/mnt/i/FraScanner/papers/EN_20251011_150000_5.pdf")
    
    if test_pdf.exists():
        is_conf, details = detector.detect(test_pdf)
        
        print(f"Is conference presentation: {is_conf}")
        print(f"Confidence score: {details.get('confidence_score', 0)}")
        print(f"\nDetails:")
        for key, value in details.items():
            if key != 'reasons':
                print(f"  {key}: {value}")
        
        if details.get('reasons'):
            print(f"\nReasons:")
            for reason in details['reasons']:
                print(f"  - {reason}")
    else:
        print(f"Test file not found: {test_pdf}")

