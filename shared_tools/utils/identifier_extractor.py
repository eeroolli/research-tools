#!/usr/bin/env python3
"""
Fast regex-based identifier extraction from PDF text.

Extracts DOI, ISBN, ISSN, and URLs using regex patterns before
resorting to slower AI-based extraction.
"""

import re
import os
import json
import time
import configparser
from pathlib import Path
from typing import Optional, List, Tuple
from .isbn_matcher import ISBNMatcher
from .text_ignore import filter_candidates, sanitize_text


class IdentifierExtractor:
    """Fast regex-based identifier extraction."""
    
    @classmethod
    def _get_accessed_context_window(cls) -> int:
        """Get the context window size for filtering years near 'Accessed:' from config.
        
        Returns:
            Context window size in characters (default: 30)
        """
        try:
            config = configparser.ConfigParser()
            root_dir = Path(__file__).parent.parent.parent
            config.read([
                root_dir / 'config.conf',
                root_dir / 'config.personal.conf'
            ])
            
            if config.has_option('IDENTIFIER_EXTRACTION', 'accessed_context_window'):
                return config.getint('IDENTIFIER_EXTRACTION', 'accessed_context_window')
        except Exception:
            pass
        
        # Default value if config not found or error
        return 30
    
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
        # OCR error: / misread as ) - with doi: prefix
        r'doi:\s*(10\.\d{4,}\)[^\s\)]+)',
        # OCR error: / misread as ) - raw DOI
        r'\b(10\.\d{4,}\)[^\s\)]+)',
    ]
    
    # ISSN pattern: 1234-5678 or 1234-567X
    ISSN_PATTERN = r'\bISSN[:\s]*(\d{4}-\d{3}[0-9X])\b'
    
    # URL patterns - http(s) URLs
    URL_PATTERN = r'https?://[^\s<>"\'{}\[\]\\|^`]+'

    @classmethod
    def extract_title_and_source_journal(cls, text: str) -> Tuple[str, str]:
        """Best-effort extraction of title and journal from OCR text.
        
        Intended for JSTOR-like front pages containing:
          - A line immediately above "Author(s): ..."
          - A "Source:" line with journal + volume/issue/pages
        """
        if not isinstance(text, str) or not text.strip():
            return "", ""

        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        title = ""
        journal = ""

        # Title heuristic: line immediately preceding "Author(s):"
        author_idx = None
        for i, ln in enumerate(lines):
            if re.search(r'\bauthor(?:s|\(s\))?\s*:', ln, re.IGNORECASE):
                author_idx = i
                break
        if author_idx is not None and author_idx > 0:
            candidate = lines[author_idx - 1]
            # Sometimes title and a "JOURNAL OF ..." fragment are on the same OCR line.
            m = re.search(r'\bjournal\s+of\b', candidate, re.IGNORECASE)
            if m and m.start() > 5:
                title = candidate[:m.start()].strip(" -–—:;,.")
            else:
                title = candidate.strip(" -–—:;,.")

        # Journal heuristic: parse "Source:" line (more reliable for journal name)
        for ln in lines:
            m = re.search(r'^\s*source\s*:\s*(.+)$', ln, re.IGNORECASE)
            if not m:
                continue
            src = m.group(1).strip()
            # Drop volume/issue/pages tail if present.
            # Note: don't use \b after "vol." because "." is not a word char.
            # Don't use \b here because tokens like "Vol." / "Mo." end with '.' (non-word char).
            tail = re.search(r',\s*(vol\.|volume|no\.|mo\.|number|issue|\(|pp\.|pages)', src, re.IGNORECASE)
            if tail:
                src = src[:tail.start()].strip()
            # Light OCR cleanup for "Journal"
            src = src.replace(".Tournal", "Journal").replace(".tournal", "Journal")
            src = " ".join(src.split())
            if len(src) > 3:
                journal = src
            break

        title = " ".join((title or "").split())
        journal = " ".join((journal or "").split())
        return title, journal
    
    # arXiv patterns
    ARXIV_PATTERNS = [
        # New format: 2301.12345 or arXiv:2301.12345
        r'arXiv:\s*(\d{4}\.\d{4,5})',
        r'\b(\d{4}\.\d{4,5})\b',  # Bare format
        # Old format: cs.AI/0001001
        r'arXiv:\s*([a-z\-]+(?:\.[A-Z]{2})?/\d{7})',
        r'\b([a-z\-]+(?:\.[A-Z]{2})?/\d{7})\b',
    ]
    
    # Year patterns - common publication year formats
    # Each pattern is a tuple: (pattern, pattern_type, priority_score)
    # Priority: higher score = more likely to be publication year
    YEAR_PATTERNS = [
        # Pattern 1: Year in parentheses (YYYY) - very reliable for publication year
        (r'\((\d{4})\)', 'parentheses', 10),
        # Pattern 2: Copyright symbol with space © YYYY - high priority
        (r'©\s+(\d{4})', 'copyright_spaced', 9),
        # Pattern 3: Copyright symbol without space ©YYYY - high priority
        (r'©(\d{4})', 'copyright', 9),
        # Pattern 4: Comma-space-year pattern (anything, YYYY)
        # Matches: "Plenum Press, New York, 1993" or "Something, 1993"
        (r',\s+(\d{4})\b', 'comma_year', 8),
        # Pattern 5: Standalone year with spaces (space YYYY word boundary)
        # Matches: " 2023", " 2023 ", "2023 " with word boundaries
        (r'\s+(\d{4})\b', 'standalone_spaced', 7),
        (r'\b(\d{4})\s+', 'standalone_spaced', 7),
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
                
                # Normalize OCR errors in the DOI itself
                # Replace ) with / when it appears after the prefix (common OCR error)
                # Pattern: 10.1016)something -> 10.1016/something
                # Only replace if it looks like a DOI structure (number)number)
                if re.match(r'10\.\d{4,}\)', doi):
                    doi = doi.replace(')', '/', 1)  # Replace first ) with /
                
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
        text = sanitize_text(text or "")
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
        
        return filter_candidates(urls)
    
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
    def extract_years(cls, text: str) -> List[str]:
        """Extract all publication years from text using common patterns.
        
        Looks for:
        - Years in parentheses: (YYYY)
        - Copyright symbol followed by year: © YYYY or ©YYYY
        
        Args:
            text: Text to search for years
            
        Returns:
            List of unique year strings (1900-2100) found in text
        """
        years = []
        seen_years = set()
        
        for pattern_data in cls.YEAR_PATTERNS:
            pattern = pattern_data[0]  # Extract pattern string
            matches = re.finditer(pattern, text)
            for match in matches:
                # All patterns capture year in group 1
                year_str = match.group(1)
                
                # Validate year is in reasonable range (1900-2100)
                try:
                    year = int(year_str)
                    if 1900 <= year <= 2100:
                        # Check if year appears near "Accessed:" - filter these out
                        position = match.start()
                        context_window = cls._get_accessed_context_window()
                        context_start = max(0, position - context_window)
                        context_end = min(len(text), position + context_window)
                        context = text[context_start:context_end].lower()
                        
                        # Skip years that appear near "Accessed:" (access dates, not publication dates)
                        if 'accessed' in context:
                            continue
                        
                        if year_str not in seen_years:
                            years.append(year_str)
                            seen_years.add(year_str)
                except ValueError:
                    continue
        
        return years
    
    @classmethod
    def extract_best_year(cls, text: str) -> Optional[str]:
        """Extract the most likely publication year from text.
        
        Scores years based on:
        - Position in text (earlier = higher score, especially first 30%)
        - Pattern type (parentheses and copyright = higher score)
        - Body text detection: years in body text sections (3+ similar-length lines) are ignored
        - Exception: footers are still checked (years in footers are valid)
        - Proximity to publication-related keywords
        
        Args:
            text: Text to search for years
            
        Returns:
            Best candidate year string (1900-2100) or None if no valid year found
        """
        if not text:
            return None
        
        text_length = len(text)
        candidates = []  # List of (year_str, score, position) tuples
        
        # Publication-related keywords that indicate this is likely the publication year
        publication_keywords = [
            'published', 'publication', 'copyright', '©', 'copyrighted',
            'vol', 'volume', 'issue', 'journal', 'article', 'paper'
        ]
        
        # Check word count - short pages (<50 words) like title pages don't need body text filtering
        word_count = len(text.split())
        skip_body_text_filter = word_count < 50
        
        # First pass: Identify body text regions (3+ consecutive lines of similar length)
        # Body text sections are where we'll ignore years (except in footers)
        # Skip this for short pages (title pages, thesis covers, etc.)
        lines = text.split('\n')
        body_text_regions = []  # List of (start_pos, end_pos) tuples for body text regions
        
        if skip_body_text_filter:
            # Short page - treat entire page as metadata, no body text filtering
            pass
        else:
            # Find body text regions by scanning for 3 consecutive similar-length lines
            for i in range(len(lines) - 2):
                # Check three consecutive lines
                three_lines = [lines[i].strip(), lines[i+1].strip(), lines[i+2].strip()]
                # Filter out empty lines for length calculation
                non_empty_lengths = [len(line) for line in three_lines if line]
                
                if len(non_empty_lengths) >= 3:
                    avg_length = sum(non_empty_lengths) / 3
                    # Skip very short lines (likely metadata)
                    if avg_length >= 20:
                        # Check if all three are within 15% of average (stricter = better body text detection)
                        variance_ok = all(
                            abs(length - avg_length) / avg_length <= 0.15
                            for length in non_empty_lengths
                        )
                        if variance_ok:
                            # Found body text region starting at line i
                            # Extend region until we find non-body-text lines
                            region_start = i
                            region_end = i + 2
                            
                            # Extend forward while lines remain similar
                            for j in range(i + 3, len(lines)):
                                current_line = lines[j].strip()
                                if not current_line:
                                    continue
                                current_length = len(current_line)
                                # Check if this line is similar to the body text pattern
                                if abs(current_length - avg_length) / avg_length <= 0.15:
                                    region_end = j
                                else:
                                    break
                            
                            # Check if this region is in footer (last 10% of text)
                            # Calculate position in text for this region
                            region_start_pos = sum(len(lines[k]) + 1 for k in range(region_start))  # +1 for newline
                            region_end_pos = sum(len(lines[k]) + 1 for k in range(region_end + 1))
                            position_ratio_end = region_end_pos / text_length if text_length > 0 else 0
                            
                            # Only mark as body text if NOT in footer (last 10%)
                            if position_ratio_end < 0.9:
                                body_text_regions.append((region_start_pos, region_end_pos))
        
        # Helper function to check if position is in body text
        def is_in_body_text(pos: int) -> bool:
            for start, end in body_text_regions:
                if start <= pos <= end:
                    return True
            return False
        
        # Second pass: Extract years, skipping those in body text regions
        for pattern_data in cls.YEAR_PATTERNS:
            pattern, pattern_type, base_score = pattern_data
            matches = re.finditer(pattern, text)
            
            for match in matches:
                year_str = match.group(1)
                
                # Validate year is in reasonable range
                try:
                    year = int(year_str)
                    if 1900 <= year <= 2100:
                        position = match.start()
                        position_ratio = position / text_length if text_length > 0 else 0
                        
                        # Skip years in body text regions (citations in paragraphs)
                        # Exception: footers are still checked
                        if is_in_body_text(position):
                            continue  # Skip this candidate - it's in body text
                        
                        # Check if year appears near "Accessed:" - filter these out (access dates, not publication dates)
                        context_window = cls._get_accessed_context_window()
                        context_start = max(0, position - context_window)
                        context_end = min(text_length, position + context_window)
                        context = text[context_start:context_end].lower()
                        if 'accessed' in context:
                            continue  # Skip this candidate - it's an access date, not publication year
                        
                        # Calculate score for years in short paragraphs (likely metadata)
                        score = base_score
                        
                        # Position bonus: earlier in text = higher score
                        # First 15% gets maximum bonus (very early = likely metadata)
                        if position_ratio <= 0.15:
                            position_bonus = 8 * (1 - position_ratio / 0.15)  # 0-8 bonus for very early
                        elif position_ratio <= 0.3:
                            position_bonus = 4 * (1 - (position_ratio - 0.15) / 0.15)  # 0-4 bonus
                        elif position_ratio <= 0.5:
                            position_bonus = 2 * (1 - (position_ratio - 0.3) / 0.2)  # 0-2 bonus
                        else:
                            position_bonus = 0
                        score += position_bonus
                        
                        # Keyword proximity bonus: check if publication keywords nearby
                        # Use wider context for keyword checking
                        keyword_context_start = max(0, position - 50)
                        keyword_context_end = min(text_length, position + 100)
                        keyword_context = text[keyword_context_start:keyword_context_end].lower()
                        
                        keyword_bonus = 0
                        for keyword in publication_keywords:
                            if keyword in keyword_context:
                                keyword_bonus += 3  # Increased bonus for publication keywords
                                break  # Only count once
                        score += keyword_bonus
                        
                        candidates.append((year_str, score, position, year))
                        
                except ValueError:
                    continue
        
        if not candidates:
            return None
        
        # Find the maximum (most recent) year among all candidates
        # You can't cite something from the future, so most recent year gets bonus
        max_year = max(candidate[3] for candidate in candidates) if candidates else None
        
        # Add recency bonus: most recent year gets +10 bonus
        # Format: (year_str, score, position, year_int)
        updated_candidates = []
        for year_str, score, position, year_int in candidates:
            if year_int == max_year:
                score += 10  # Bonus for most recent year
            updated_candidates.append((year_str, score, position))
        
        # Sort by score (descending), then by position (ascending) as tiebreaker
        updated_candidates.sort(key=lambda x: (-x[1], x[2]))
        
        # Return the highest scoring year
        return updated_candidates[0][0]
    
    @classmethod
    def extract_all(cls, text: str) -> dict:
        """Extract all identifiers from text.
        
        Args:
            text: Text to search
            
        Returns:
            Dictionary with lists of found identifiers
        """
        text = sanitize_text(text or "")
        title, journal = cls.extract_title_and_source_journal(text)
        return {
            'dois': cls.extract_dois(text),
            'issns': cls.extract_issns(text),
            'isbns': cls.extract_isbns(text),
            'arxiv_ids': cls.extract_arxiv_ids(text),
            'jstor_ids': cls.extract_jstor_ids(text),
            'urls': cls.extract_urls(text),
            'years': cls.extract_years(text),
            'best_year': cls.extract_best_year(text),
            'title': title,
            'journal': journal,
        }
    
    @classmethod
    def extract_text(
        cls,
        pdf_path,
        page_offset: int = 0,
        max_pages: int = 1,
        document_type: Optional[str] = None,
    ) -> str:
        """Extract text from PDF pages with optional document-type handling.
        
        Args:
            pdf_path: Path to PDF file
            page_offset: 0-indexed page offset (0 = first page)
            max_pages: Maximum pages to read starting from page_offset
            document_type: Optional hint (e.g., 'book_chapter' for landscape handling)
        
        Returns:
            Concatenated text from the selected pages, or empty string on failure.
        """
        try:
            import pdfplumber
        except ImportError:
            print("Error: pdfplumber not installed")
            return ""
        
        try:
            pdf_path = Path(pdf_path)
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0 or page_offset >= len(pdf.pages):
                    return ""
                
                texts = []
                end_page = min(len(pdf.pages), page_offset + max_pages)
                for idx in range(page_offset, end_page):
                    page = pdf.pages[idx]
                    if document_type == 'book_chapter' and idx == page_offset:
                        page_text = cls._extract_text_for_book_chapter(page)
                    else:
                        page_text = page.extract_text() or ""
                    if page_text:
                        texts.append(page_text)
                
                return "\n".join(texts).strip()
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
            return ""
    
    @classmethod
    def extract_first_page_identifiers(cls, pdf_path, document_type: Optional[str] = None, page_offset: int = 0) -> dict:
        """Extract identifiers from first page(s) of PDF.
        
        Scans page 1 always, plus pages 2-3 if they have < 4000 characters each.
        This helps find ISBNs/DOIs on book front matter without picking up
        quoted authors from article body text.
        
        Args:
            pdf_path: Path to PDF file
            document_type: Optional document type (e.g., 'book_chapter') for type-specific handling
                          - 'book_chapter': Handles landscape pages by ignoring left side if right has more content
            page_offset: 0-indexed page offset (0 = page 1, 1 = page 2, etc.) to skip pages before document starts
                          
        Returns:
            Dictionary with found identifiers
        """
        try:
            import pdfplumber
        except ImportError:
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': [], 'years': [], 'best_year': None, 'title': '', 'journal': ''}
        
        try:
            pdf_path = Path(pdf_path)
            combined_text = ""
            pages_scanned = []
            char_threshold = 4000
            
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0 or page_offset >= len(pdf.pages):
                    return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': [], 'years': [], 'best_year': None, 'title': '', 'journal': ''}
                
                # Always include page 1 (page_offset)
                page1 = pdf.pages[page_offset]
                if document_type == 'book_chapter':
                    page1_text = cls._extract_text_for_book_chapter(page1)
                else:
                    page1_text = page1.extract_text() or ""
                combined_text = page1_text
                pages_scanned.append(page_offset + 1)
                
                # Optionally include page 2 if it has < char_threshold characters
                if page_offset + 1 < len(pdf.pages):
                    page2 = pdf.pages[page_offset + 1]
                    page2_text = page2.extract_text() or ""
                    page2_len = len(page2_text)
                    # #region agent log
                    try:
                        import os, json, time
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({"sessionId":"debug-session","runId":"isbn-check","hypothesisId":"P2","location":"identifier_extractor.py:extract_first_page_identifiers","message":"Page 2 character check","data":{"page2_length":page2_len,"char_threshold":char_threshold,"page2_included":page2_len < char_threshold,"page2_preview":page2_text[:500] if page2_text else None},"timestamp":int(time.time()*1000)}) + '\n')
                    except: pass
                    # #endregion
                    if page2_len < char_threshold:
                        combined_text += "\n" + page2_text
                        pages_scanned.append(page_offset + 2)
                        
                        # Optionally include page 3 if page 2 was included AND page 3 has < char_threshold characters
                        if page_offset + 2 < len(pdf.pages):
                            page3 = pdf.pages[page_offset + 2]
                            page3_text = page3.extract_text() or ""
                            page3_len = len(page3_text)
                            # #region agent log
                            try:
                                with open(log_path, 'a', encoding='utf-8') as f:
                                    f.write(json.dumps({"sessionId":"debug-session","runId":"isbn-check","hypothesisId":"P3","location":"identifier_extractor.py:extract_first_page_identifiers","message":"Page 3 character check","data":{"page3_length":page3_len,"char_threshold":char_threshold,"page3_included":page3_len < char_threshold},"timestamp":int(time.time()*1000)}) + '\n')
                            except: pass
                            # #endregion
                            if page3_len < char_threshold:
                                combined_text += "\n" + page3_text
                                pages_scanned.append(page_offset + 3)
            
            # #region agent log
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"D","location":"identifier_extractor.py:extract_first_page_identifiers","message":"Pages scanned for identifiers","data":{"text_length":len(combined_text) if combined_text else 0,"text_preview":combined_text[:300] if combined_text else None,"page_offset":page_offset,"pages_scanned":pages_scanned,"char_threshold":char_threshold},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            
            if not combined_text:
                return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': [], 'years': [], 'best_year': None, 'title': '', 'journal': ''}
            
            # Extract all identifiers (NOT authors - those come from page 1 only via separate call)
            identifiers = cls.extract_all(combined_text)
            # #region agent log
            try:
                import os, json, time
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "RX_TJ1",
                        "location": "identifier_extractor.py:extract_first_page_identifiers",
                        "message": "Title/journal extracted (identifier extract_all)",
                        "data": {
                            "title": identifiers.get("title", ""),
                            "journal": identifiers.get("journal", ""),
                            "page1_head_200": (page1_text or "")[:200],
                        },
                        "timestamp": int(time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            # #region agent log
            try:
                import os, json, time
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"isbn-check","hypothesisId":"ID","location":"identifier_extractor.py:extract_first_page_identifiers","message":"Identifiers extracted","data":{"isbns":identifiers.get('isbns',[]),"dois":identifiers.get('dois',[]),"issns":identifiers.get('issns',[]),"pages_scanned":pages_scanned,"combined_text_length":len(combined_text)},"timestamp":int(time.time()*1000)}) + '\n')
            except: pass
            # #endregion
            return identifiers
        except Exception as e:
            print(f"Error extracting identifiers from {pdf_path}: {e}")
            return {'dois': [], 'issns': [], 'isbns': [], 'arxiv_ids': [], 'jstor_ids': [], 'urls': [], 'years': [], 'best_year': None, 'title': '', 'journal': ''}
    
    @classmethod
    def _extract_text_for_book_chapter(cls, page) -> str:
        """Extract text from book chapter page, handling landscape format.
        
        For landscape pages, the left side might be the end of the previous chapter.
        We detect this and ignore the left side if it has much less content than the right side.
        
        Args:
            page: pdfplumber page object
            
        Returns:
            Extracted text (right side only if landscape and left side has less content)
        """
        # Check if page is landscape (width > height)
        width = page.width
        height = page.height
        is_landscape = width > height
        
        if not is_landscape:
            # Portrait page - extract normally
            return page.extract_text() or ""
        
        # Landscape page - extract left and right sides separately
        # Split page into left and right halves
        mid_x = width / 2
        
        # Extract from left half
        left_bbox = (0, 0, mid_x, height)
        left_crop = page.crop(left_bbox)
        left_text = left_crop.extract_text() or ""
        left_words = len(left_text.split())
        
        # Extract from right half
        right_bbox = (mid_x, 0, width, height)
        right_crop = page.crop(right_bbox)
        right_text = right_crop.extract_text() or ""
        right_words = len(right_text.split())
        
        # Decision: if right side has significantly more words, ignore left side
        # Threshold: right side has at least 2x more words than left
        if right_words > 0 and left_words > 0:
            word_ratio = right_words / left_words
            if word_ratio >= 2.0:
                # Right side has much more content - use only right side
                return right_text
        
        # Otherwise, use both sides (left might be valid content)
        return (left_text + "\n" + right_text).strip()


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
    print(f"Years found: {results['years']}")
    
    # Test year extraction
    print("\n" + "=" * 60)
    print("Testing year extraction:")
    year_test_text = """
    This article was published in (2023)
    © 2022 All rights reserved
    Copyright ©2021
    Volume 45, Issue 3
    
    Lots of text here. As Wildavsky wrote (1995), this is important.
    This paragraph contains many words and would be considered body text.
    Douglas (1986) argued that we should consider this issue carefully.
    Smith and Jones (2000) found similar results in their research studies.
    Some text (1995) with year in parentheses later in document that is also body text.
    """
    year_results = IdentifierExtractor.extract_years(year_test_text)
    print(f"All years found: {year_results}")
    best_year = IdentifierExtractor.extract_best_year(year_test_text)
    print(f"Best year (should be 2023, 2022, or 2021 - citation years in body text ignored): {best_year}")
    expected_years = ['2023', '2022', '2021', '1995', '1986', '2000']
    print(f"Expected years in list: {expected_years}")
    print(f"All years found in list: {all(year in year_results for year in expected_years)}")
    # Best year should be early publication year, NOT citation years from body text
    print(f"Best year is publication year (body text citations ignored): {best_year in ['2023', '2022', '2021']}")
    
    # Verify OCR error handling
    expected_ocr_dois = ['10.1080/13501780701394094', '10.1000/test.doi', '10.2000/example.doi']
    print(f"\nOCR error test DOIs: {expected_ocr_dois}")
    print(f"All OCR DOIs found: {all(doi in results['dois'] for doi in expected_ocr_dois)}")
