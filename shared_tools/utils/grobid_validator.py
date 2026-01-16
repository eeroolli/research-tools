#!/usr/bin/env python3
"""
Validate GROBID-extracted authors against PDF text to filter hallucinations.
"""

import logging
import re
from typing import Optional, List

from .identifier_extractor import IdentifierExtractor
import os
import json
import time


class GrobidValidator:
    """Validate GROBID authors by checking presence in PDF text."""

    @classmethod
    def validate_authors(
        cls,
        metadata: dict,
        pdf_path,
        regex_authors: Optional[List[str]] = None,
        logger: Optional[logging.Logger] = None,
        force_text_validation: bool = False,
    ) -> dict:
        """Filter GROBID authors that do not appear in document text.
        
        Args:
            metadata: Metadata dict (expects 'authors' and 'extraction_method')
            pdf_path: Path to PDF
            regex_authors: Optional regex authors found earlier as fallback
            logger: Optional logger for diagnostics
        
        Returns:
            Updated metadata with filtered authors.
        """
        # #region agent log
        try:
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'A1',
                    'location': 'grobid_validator.py:validate_authors',
                    'message': 'Entry',
                    'data': {
                        'has_authors': bool(metadata.get('authors')),
                        'extraction_method': metadata.get('extraction_method', metadata.get('method', '')),
                        'has_pdf_path': bool(pdf_path),
                        'regex_authors_count': len(regex_authors) if regex_authors else 0
                    },
                    'timestamp': int(time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        if not metadata.get('authors'):
            return metadata

        extraction_method = metadata.get('extraction_method', metadata.get('method', ''))
        if extraction_method != 'grobid' and not force_text_validation:
            return metadata

        original_authors = metadata['authors']

        # Extract text from first few pages (lowercased for matching)
        doc_text = IdentifierExtractor.extract_text(pdf_path, page_offset=0, max_pages=3)
        doc_text = doc_text.lower() if doc_text else ""

        # #region agent log
        try:
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'A2',
                    'location': 'grobid_validator.py:validate_authors',
                    'message': 'Extracted doc text',
                    'data': {
                        'doc_text_len': len(doc_text),
                        'pages_scanned': 3,
                        'authors_count': len(original_authors)
                    },
                    'timestamp': int(time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        if not doc_text:
            return metadata

        authors_in_text = []
        authors_not_in_text = []
        expanded_names = []  # Track full names found from partials

        for author in original_authors:
            author_lower = author.lower()

            # Handle both "Last, First" and "First Last" formats
            if ',' in author_lower:
                parts = author_lower.split(',')
                last_name = parts[0].strip() if parts else ""
                first_name = parts[1].strip() if len(parts) > 1 else ""
            else:
                parts = author_lower.split()
                if len(parts) >= 2:
                    first_name = parts[0].strip()
                    last_name = parts[-1].strip()
                elif len(parts) == 1:
                    first_name = ""
                    last_name = parts[0].strip()
                else:
                    first_name = ""
                    last_name = ""

            found_in_text = False
            last_name_found = False
            is_partial = False
            full_name_from_partial = None

            # Check if this is a partial name (e.g., "Eric M.", "J. F.")
            # Partial names: 1-2 words ending in "." or very short (2-4 chars total)
            author_words = author.split()
            if len(author_words) <= 2:
                # Check if ends with period (like "Eric M." or "J. F.")
                if author.rstrip().endswith('.'):
                    is_partial = True
                # Or very short (2-4 characters total)
                elif len(author.strip()) <= 4:
                    is_partial = True

            # If partial, search for full names starting with this partial
            if is_partial:
                # Escape the partial for regex (use lowercase since doc_text is lowercased)
                partial_lower = author.rstrip('.').strip().lower()
                partial_escaped = re.escape(partial_lower)
                # Pattern: partial + optional period + whitespace + word(s) starting with capital
                # Note: doc_text is lowercased, but we search for patterns that would indicate a capitalized word
                # We'll search for the partial followed by whitespace and then a word (which we'll capitalize when reconstructing)
                partial_pattern = r'\b' + partial_escaped + r'\.?\s+([a-z]+(?:\s+[a-z]+)?)'
                matches = re.finditer(partial_pattern, doc_text)
                for match in matches:
                    # Found a full name starting with this partial
                    # Reconstruct with proper capitalization
                    matched_part = match.group(1)
                    # Capitalize first letter of each word in the matched part
                    matched_words = matched_part.split()
                    capitalized_words = [word.capitalize() for word in matched_words]
                    capitalized_part = ' '.join(capitalized_words)
                    
                    # Reconstruct full name preserving original author capitalization
                    if author[0].isupper():
                        # Preserve original case of partial
                        full_name_from_partial = author.rstrip('.') + ' ' + capitalized_part
                    else:
                        # Use lowercase partial + capitalized part
                        full_name_from_partial = author.rstrip('.').strip() + ' ' + capitalized_part
                    
                    # Add to expanded names list (will be added to authors_in_text later)
                    if full_name_from_partial not in expanded_names:
                        expanded_names.append(full_name_from_partial)
                    found_in_text = True  # Partial is valid if we found a full name
                    break

            if last_name and len(last_name) > 2:
                last_name_escaped = re.escape(last_name)
                pattern = r'\b' + last_name_escaped + r'\b'
                if re.search(pattern, doc_text):
                    last_name_found = True
                    found_in_text = True
                elif last_name in doc_text:
                    idx = doc_text.find(last_name)
                    if idx >= 0:
                        before_ok = (idx == 0 or not doc_text[idx - 1].isalnum())
                        after_ok = (idx + len(last_name) >= len(doc_text) or not doc_text[idx + len(last_name)].isalnum())
                        if before_ok and after_ok:
                            last_name_found = True
                            found_in_text = True

            if last_name_found and first_name and len(first_name) > 1:
                first_pattern = r'\b' + re.escape(first_name) + r'\b'
                last_pattern = r'\b' + re.escape(last_name) + r'\b'
                first_matches = list(re.finditer(first_pattern, doc_text))
                last_matches = list(re.finditer(last_pattern, doc_text))
                proximity_threshold = 40
                for fm in first_matches:
                    for lm in last_matches:
                        distance = abs(fm.start() - lm.start())
                        if distance <= proximity_threshold:
                            found_in_text = True
                            break
                    if found_in_text:
                        break

            if not found_in_text and author_lower:
                author_pattern = r'\b' + re.escape(author_lower) + r'\b'
                if re.search(author_pattern, doc_text):
                    found_in_text = True

            if found_in_text:
                authors_in_text.append(author)
            else:
                authors_not_in_text.append(author)

        # Add expanded full names to authors_in_text (if not already present)
        for expanded_name in expanded_names:
            # Check if this expanded name is already in the list (case-insensitive)
            expanded_lower = expanded_name.lower()
            already_present = any(a.lower() == expanded_lower for a in authors_in_text)
            if not already_present:
                authors_in_text.append(expanded_name)

        total = len(original_authors)
        if total > 0:
            if authors_not_in_text and logger:
                logger.info(f"Filtering {len(authors_not_in_text)} GROBID author(s) not in PDF: {authors_not_in_text}")

            metadata['authors'] = authors_in_text

            if not authors_in_text:
                # Try regex fallback if provided
                if regex_authors:
                    valid_regex_authors = []
                    for author in regex_authors:
                        words = author.split()
                        if 2 <= len(words) <= 4 and words[-1] and words[-1][0].isupper():
                            valid_regex_authors.append(author)
                    if valid_regex_authors:
                        metadata['authors'] = valid_regex_authors
                        return metadata

                metadata['authors'] = []
                if logger:
                    logger.warning("All GROBID authors filtered out; none appear in PDF text")
                # #region agent log
                try:
                    log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                    with open(log_path, 'a', encoding='utf-8') as f:
                        f.write(json.dumps({
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'A3',
                            'location': 'grobid_validator.py:validate_authors',
                            'message': 'All authors filtered',
                            'data': {
                                'authors_in_text': 0,
                                'authors_not_in_text': len(authors_not_in_text),
                                'used_regex_fallback': bool(regex_authors)
                            },
                            'timestamp': int(time.time() * 1000)
                        }) + '\n')
                except Exception:
                    pass
                # #endregion
                return metadata

        # #region agent log
        try:
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'A4',
                    'location': 'grobid_validator.py:validate_authors',
                    'message': 'Exit',
                    'data': {
                        'authors_in_text': len(authors_in_text),
                        'authors_not_in_text': len(authors_not_in_text)
                    },
                    'timestamp': int(time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        return metadata
