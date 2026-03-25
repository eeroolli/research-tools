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

    @classmethod
    def _extract_names_from_text(cls, text: str) -> List[str]:
        """Run NAME_PATTERNS + and_pattern on text and return cleaned unique author list."""
        if not text or not text.strip():
            return []
        authors = set()
        for pattern in cls.NAME_PATTERNS:
            matches = re.findall(pattern, text, re.UNICODE)
            for match in matches:
                if match and len(match.strip()) > 3:
                    authors.add(match.strip())
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
            if author_words_lower & cls.NON_AUTHOR_WORDS:
                continue
            author_lower = author.lower()
            if re.search(r',\s*(norway|california|united|kingdom|poland|angeles)', author_lower):
                continue
            if re.search(r'\b(edited|series|editor|perspectives?|society|societies)\b', author_lower):
                continue
            if re.match(r'^(the|a|an|first|new|global|international|comparative)\s+', author_lower):
                continue
            words = author.split()
            if len(words) > 4:
                author = ' '.join(words[:2])
                words = author.split()
            if len(words) >= 2 and len(words[-1]) < 2:
                continue
            if len(author.split()) >= 2 and len(author) > 3:
                cleaned_authors.append(author)
        seen = set()
        unique = []
        for author in cleaned_authors:
            if author.lower() not in seen:
                seen.add(author.lower())
                unique.append(author)
        return unique

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
            # Strip common label prefixes
            author = re.sub(r'^(By|Authors?|Author\(s\))\s*:?\s*', '', author, flags=re.IGNORECASE)
            # Some patterns can capture just "(s): Alice Johnson, Bob Miller" – strip the suffix label too.
            author = re.sub(r'^\(s\)\s*:?\s*', '', author, flags=re.IGNORECASE)
            author = re.sub(r'\s+', ' ', author.strip())

            # Split on typical separators so "Alice Johnson, Bob Miller" becomes two authors
            parts = re.split(r'[;,]|\band\b|&', author)
            for part in parts:
                candidate = part.strip()
                if len(candidate.split()) >= 2 and len(candidate) > 3:
                    cleaned_authors.append(candidate)

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
        label_found = False
        for label_match in re.finditer(r'Author\(s\)\s*:\s*([^\n]+)', text, re.IGNORECASE | re.UNICODE):
            label_found = True
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

        # If we found an explicit Author(s) line, prefer it and avoid broader heuristics.
        # This prevents pulling in two-word title/journal phrases that are not authors.
        if label_found and authors:
            cleaned = []
            for author in authors:
                author = re.sub(r'\s+', ' ', author.strip())
                author = re.sub(r'^(By|Authors?|Author\(s\))\s*:?\s*', '', author, flags=re.IGNORECASE).strip()
                if len(author.split()) >= 2 and len(author) > 3:
                    cleaned.append(author)

            seen = set()
            unique_authors = []
            for author in cleaned:
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
                        "hypothesisId": "AF1",
                        "location": "author_extractor.py:extract_authors_simple",
                        "message": "Author(s) label found; returning label-only authors",
                        "data": {
                            "text_length": len(text) if text else 0,
                            "label_candidates": len(authors),
                            "unique_authors": unique_authors[:10],
                            "unique_count": len(unique_authors)
                        },
                        "timestamp": int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion

            return unique_authors

        # Header zone: body text starts where there are >10 consecutive non-empty lines
        lines = [ln.strip() for ln in text.splitlines()]
        body_start = None
        i = 0
        while i < len(lines):
            run = 0
            while i + run < len(lines) and lines[i + run]:
                run += 1
            if run > 10:
                body_start = i
                break
            i += run + 1
        if body_start is not None and body_start > 0:
            header_text = "\n".join(lines[:body_start])
            if header_text.strip():
                header_authors = cls._extract_names_from_text(header_text)
                if header_authors:
                    return header_authors

        return cls._extract_names_from_text(text)
