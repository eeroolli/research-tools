#!/usr/bin/env python3
"""
Author extraction utilities using regex patterns.

Extracts likely author names from OCR text, with filtering of
institution/place/title-like phrases to reduce false positives.
"""

import re
from typing import List, Set


class AuthorExtractor:
    """Regex-based author extraction helpers."""

    # Allow diacritics and punctuation in names (Unicode-friendly)
    WORD = r"[A-ZÀ-ÖØ-Ý][\w’'\-\.À-ÖØ-öø-ÿĀ-žŽșțȘȚ]+"

    # Patterns for explicit author labels and name shapes
    AUTHOR_PATTERNS = [
        # "By [Author]" or "Authors: [Author1], [Author2]" or "Author(s): [Author]"
        rf'(?:By|Authors?|Author\(s\))\s*:?\s*([^\n]+)',
        # "Author Name" at start of line
        rf'^({WORD}[^\S\r\n]+{WORD}(?:[^\S\r\n]+{WORD})*)',
        # "Lastname, Firstname"
        rf'({WORD}),[^\S\r\n]*{WORD}(?:[^\S\r\n]+{WORD})*',
        # "Firstname Lastname"
        rf'({WORD}[^\S\r\n]+{WORD}(?:[^\S\r\n]+{WORD})*)',
        # "Lastname & Lastname" or "Lastname and Lastname"
        rf'({WORD})[^\S\r\n]+(?:and|&)[^\S\r\n]+({WORD})',
    ]

    # Common academic name patterns (looser)
    NAME_PATTERNS = [
        rf'{WORD}[^\S\r\n]+{WORD}',              # First Last
        rf'{WORD},[^\S\r\n]*{WORD}',            # Last, First
        rf'{WORD}[^\S\r\n]+[A-Z]\.[^\S\r\n]*{WORD}',   # First M. Last
    ]

    # Words that indicate non-author entities (institutions, places, common phrases)
    NON_AUTHOR_WORDS: Set[str] = {
        'foundation', 'grant', 'national', 'science', 'association', 'stable', 'statistics',
        'university', 'chicago', 'department', 'professor', 'methods', 'section', 'analysis',
        'response', 'responses', 'multinomial', 'general', 'social', 'let', 'american', 'statistical',
        # Place names
        'angeles', 'california', 'london', 'school', 'norway', 'stavanger', 'bergen', 'poland',
        'united', 'kingdom', 'perspective', 'perspectives', 'society', 'societies',
        # Book/series terms
        'edited', 'series', 'editor', 'multidisciplinary', 'international', 'comparative',
        'global', 'civil', 'political', 'new', 'first', 'century', 'order', 'continuation',
        'experiments', 'integration', 'market', 'labour', 'privatization', 'approaches',
        'innovation', 'organizational', 'measuring', 'philanthropic', 'foundations'
    }

    @classmethod
    def extract_authors_with_regex(cls, text: str) -> List[str]:
        """Extract authors using explicit author/name patterns."""
        authors = set()

        # Try each pattern
        for pattern in cls.AUTHOR_PATTERNS:
            matches = re.findall(pattern, text, re.MULTILINE | re.IGNORECASE | re.UNICODE)
            for match in matches:
                if isinstance(match, tuple):
                    for group in match:
                        if group and len(group.strip()) > 2:
                            authors.add(group.strip())
                else:
                    if match and len(match.strip()) > 2:
                        authors.add(match.strip())

        cleaned_authors = []
        for author in authors:
            author = re.sub(r'^(By|Authors?|Author)\s*:?\s*', '', author, flags=re.IGNORECASE)
            author = re.sub(r'\s+', ' ', author.strip())
            if len(author.split()) >= 2 and len(author) > 3:
                cleaned_authors.append(author)

        seen = set()
        unique_authors = []
        for author in cleaned_authors:
            if author.lower() not in seen:
                seen.add(author.lower())
                unique_authors.append(author)

        # #region agent log
        try:
            import os, json, time as _time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "author-extractor",
                    "hypothesisId": "A2",
                    "location": "author_extractor.py:extract_authors_with_regex",
                    "message": "Author regex extraction",
                    "data": {
                        "text_length": len(text) if text else 0,
                        "raw_candidates": len(authors),
                        "unique_authors": unique_authors[:10],
                        "unique_count": len(unique_authors)
                    },
                    "timestamp": int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        return unique_authors

    @classmethod
    def extract_authors_simple(cls, text: str) -> List[str]:
        """Simple regex extraction focusing on common academic patterns."""
        authors = set()

        # Special-case labeled authors: capture after "Author(s):" up to newline
        for label_match in re.finditer(r'Author\(s\)\s*:\s*([^\n]+)', text, re.IGNORECASE | re.UNICODE):
            label_chunk = label_match.group(1)
            # Split on comma / semicolon / "and" / "&"
            for part in re.split(r'[;,]|\\band\\b|&', label_chunk):
                candidate = part.strip()
                if not candidate:
                    continue
                # Keep at most 4 words to avoid trailing text, but preserve diacritics
                words = candidate.split()
                if len(words) > 4:
                    candidate = ' '.join(words[:4])
                authors.add(candidate)

        for pattern in cls.NAME_PATTERNS:
            matches = re.findall(pattern, text, re.UNICODE)
            for match in matches:
                if match and len(match.strip()) > 3:
                    authors.add(match.strip())

        # "and" / "&" separated names
        and_pattern = rf'({cls.WORD}(?:[^\S\r\n]+{cls.WORD})*)[^\S\r\n]+(?:and|&)[^\S\r\n]+({cls.WORD}(?:[^\S\r\n]+{cls.WORD})*)'
        for match in re.findall(and_pattern, text, re.UNICODE | re.IGNORECASE):
            if match[0] and match[1]:
                authors.add(match[0].strip())
                authors.add(match[1].strip())

        cleaned_authors = []
        for author in authors:
            author = re.sub(r'\s+', ' ', author.strip())
            author = re.sub(r'^(By|Authors?|Author\(s\))\s*:?\s*', '', author, flags=re.IGNORECASE).strip()

            if len(author) < 4:
                continue

            author_words_lower = set(word.lower().rstrip(',') for word in author.split())
            has_non_author_word = bool(author_words_lower & cls.NON_AUTHOR_WORDS)

            author_lower = author.lower()
            if re.search(r',\s*(norway|california|united|kingdom|poland|angeles)', author_lower):
                continue
            if re.search(r'\b(edited|series|editor|perspectives?|society|societies)\b', author_lower):
                continue
            if re.match(r'^(the|a|an|first|new|global|international|comparative)\s+', author_lower):
                continue

            words = author.split()
            # If OCR glued extra words, keep only first two to avoid rejecting valid names
            if len(words) > 4:
                author = ' '.join(words[:2])
                words = author.split()
            if len(words) >= 2:
                last_word = words[-1]
                if len(last_word) < 2:
                    continue

            if has_non_author_word:
                continue

            if len(author.split()) >= 2 and len(author) > 3:
                cleaned_authors.append(author)

        seen = set()
        unique_authors = []
        for author in cleaned_authors:
            if author.lower() not in seen:
                seen.add(author.lower())
                unique_authors.append(author)

        # #region agent log
        try:
            import os, json, time as _time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "author-extractor",
                    "hypothesisId": "A3",
                    "location": "author_extractor.py:extract_authors_simple",
                    "message": "Author simple extraction",
                    "data": {
                        "text_length": len(text) if text else 0,
                        "raw_candidates": len(authors),
                        "unique_authors": unique_authors[:10],
                        "unique_count": len(unique_authors)
                    },
                    "timestamp": int(_time.time() * 1000)
                }) + '\n')
        except Exception:
            pass
        # #endregion

        return unique_authors
