#!/usr/bin/env python3
"""
Author filtering coordination module.

Coordinates author filtering across multiple validators:
- Name-shape filtering for regex methods (2-4 tokens, capitalized)
- Conditional OCR correction (skip for regex methods to avoid hallucinations)
- PDF text validation via GrobidValidator
- Zotero-based filtering for non-reliable extraction methods
"""

import logging
import configparser
from pathlib import Path
from typing import Optional, List

from .grobid_validator import GrobidValidator
from .author_validator import AuthorValidator


class AuthorFilter:
    """Coordinate author filtering across multiple validators."""

    @staticmethod
    def filter_authors(
        metadata: dict,
        pdf_path: Optional[Path] = None,
        author_validator: Optional[AuthorValidator] = None,
        logger: Optional[logging.Logger] = None,
        regex_authors: Optional[List[str]] = None,
    ) -> dict:
        """Filter authors based on extraction method and available validators.
        
        Args:
            metadata: Metadata dict with 'authors' and 'extraction_method' fields
            pdf_path: Optional path to PDF for document text validation
            author_validator: Optional AuthorValidator for OCR correction and Zotero filtering
            logger: Optional logger for diagnostics
            
        Returns:
            Updated metadata dict with filtered authors
        """
        if not metadata.get('authors'):
            return metadata

        original_authors = metadata['authors']
        extraction_method = metadata.get('extraction_method', metadata.get('method', ''))
        
        # Identify regex methods
        regex_methods = {'regex_fallback', 'regex_web_article', 'regex'}
        is_regex_method = extraction_method in regex_methods

        # Normalize optional regex_authors list and apply max_known_authors threshold from config.
        # This ensures we only ever use a small, high-quality regex/Zotero author set.
        normalized_regex_authors: Optional[List[str]] = None
        max_known_authors: Optional[int] = None
        if regex_authors:
            cleaned = [a.strip() for a in regex_authors if isinstance(a, str) and a.strip()]
            if cleaned:
                try:
                    config = configparser.ConfigParser()
                    root_dir = Path(__file__).parent.parent.parent
                    config.read([
                        root_dir / 'config.conf',
                        root_dir / 'config.personal.conf'
                    ])
                    max_known_authors = config.getint('AUTHOR_MATCHING', 'max_known_authors', fallback=5)
                except Exception:
                    max_known_authors = 5

                # If too many regex authors survived filtering, treat the list as too noisy and ignore it.
                if max_known_authors is not None and len(cleaned) <= max_known_authors:
                    normalized_regex_authors = cleaned
                else:
                    normalized_regex_authors = None

        # Step 1: Apply name-shape filtering for regex methods (BEFORE OCR correction)
        if is_regex_method:
            name_shape_filtered = []
            for author in original_authors:
                if not author or not isinstance(author, str):
                    continue
                words = author.split()
                # Require 2-4 words/tokens
                if not (2 <= len(words) <= 4):
                    continue
                # Stricter name-shape: every token must look like a name part
                # (capitalized, ALLCAPS, or initial like "J."). This rejects phrases like "Your use".
                def looks_like_name_token(w: str) -> bool:
                    w = w.strip()
                    if not w:
                        return False
                    if len(w) == 2 and w[0].isupper() and w[1] == '.':
                        return True
                    if w.isupper() and len(w) >= 2:
                        return True
                    return len(w) > 1 and w[0].isupper()

                if all(looks_like_name_token(w) for w in words):
                    name_shape_filtered.append(author)
            
            if name_shape_filtered:
                original_authors = name_shape_filtered
                metadata['authors'] = name_shape_filtered
                if logger:
                    logger.debug(f"Name-shape filtering: {len(original_authors)} -> {len(name_shape_filtered)} authors")
                # #region agent log
                try:
                    import os as _os, json as _json, time as _time
                    log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                    with open(log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "author-filter",
                            "hypothesisId": "AF2",
                            "location": "author_filter.py:filter_authors",
                            "message": "name-shape filtering applied (regex method)",
                            "data": {
                                "extraction_method": extraction_method,
                                "before_count": len(metadata.get('authors', []) or []),
                                "after_count": len(name_shape_filtered),
                                "preview_after": name_shape_filtered[:10],
                            },
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion

        # Step 2: Apply OCR correction conditionally (skip for regex methods to avoid hallucinations)
        # Regex authors are extracted from PDF text, so they shouldn't be "corrected" into different names
        corrected_authors = []
        if author_validator and not is_regex_method:
            for author in original_authors:
                corrected = False
                # Strategy 1: Try lastname matching first (fast, handles cases like "Tu$ey, John W" -> "Tukey, John W")
                try:
                    validation = author_validator.validate_authors([author])
                    if validation['known_authors']:
                        # Found exact or lastname match - use it
                        corrected_authors.append(validation['known_authors'][0]['name'])
                        corrected = True
                        if logger:
                            logger.debug(f"Author matched via lastname: '{author}' -> '{validation['known_authors'][0]['name']}'")
                    elif validation['ocr_corrections']:
                        # Found OCR correction suggestion
                        corrected_authors.append(validation['ocr_corrections'][0]['corrected_name'])
                        corrected = True
                        if logger:
                            logger.debug(f"OCR correction via validate: '{author}' -> '{validation['ocr_corrections'][0]['corrected_name']}'")
                except Exception as e:
                    if logger:
                        logger.debug(f"Author validation failed for '{author}': {e}")
                
                # Strategy 2: If no match, try direct OCR correction (more aggressive, handles special chars)
                if not corrected:
                    try:
                        # Try with higher max_distance and lower similarity threshold
                        suggestion = author_validator.suggest_ocr_correction(author, max_distance=3)
                        if suggestion and suggestion.get('corrected_name'):
                            corrected_authors.append(suggestion['corrected_name'])
                            if logger:
                                logger.debug(f"OCR correction: '{author}' -> '{suggestion['corrected_name']}'")
                            corrected = True
                    except Exception as e:
                        if logger:
                            logger.debug(f"OCR correction failed for '{author}': {e}")
                
                # If no correction found, keep original
                if not corrected:
                    corrected_authors.append(author)
        else:
            corrected_authors = original_authors

        # Update metadata with corrected authors
        metadata['authors'] = corrected_authors
        original_authors = corrected_authors  # Use corrected authors for filtering

        # Step 3: Validate against PDF text (for GROBID and regex methods to filter hallucinations)
        if ((extraction_method == 'grobid') or is_regex_method) and pdf_path:
            metadata = GrobidValidator.validate_authors(
                metadata,
                pdf_path,
                regex_authors=normalized_regex_authors,
                logger=logger,
                force_text_validation=is_regex_method
            )

        # Step 3b: If we have a small, high-quality regex author list, merge it with the
        # current authors before Zotero-based filtering. GROBID authors stay first;
        # regex/Zotero authors are appended if not already present (case-insensitive).
        if normalized_regex_authors:
            current_authors = metadata.get('authors', []) or []
            merged: List[str] = []
            seen = set()

            for author in current_authors:
                if not isinstance(author, str):
                    continue
                key = author.lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(author)

            for author in normalized_regex_authors:
                key = author.lower()
                if key not in seen:
                    seen.add(key)
                    merged.append(author)

            metadata['authors'] = merged

        # Step 4: Zotero-based filtering (for non-reliable extraction methods)
        if not author_validator:
            return metadata

        # Skip filtering if extraction method is reliable (CrossRef, arXiv, DOI)
        # Note: GROBID already filtered above if pdf_path provided
        reliable_methods = ['crossref', 'arxiv', 'doi']
        if extraction_method in reliable_methods:
            return metadata

        # Use shared filtering method for consistent balanced mode logic
        # Initialize journal validator if needed
        journal_validator = None
        try:
            from .journal_validator import JournalValidator
            journal_validator = JournalValidator()
        except Exception as e:
            if logger:
                logger.debug(f"Could not initialize journal validator: {e}")

        filtered_authors = AuthorFilter.filter_authors_against_zotero(
            authors=metadata.get('authors', []),
            author_validator=author_validator,
            journal_validator=journal_validator,
            logger=logger
        )

        # Update metadata if filtering changed the authors
        if filtered_authors != metadata.get('authors', []):
            original_count = len(metadata.get('authors', []))
            metadata['authors'] = filtered_authors
            metadata['_original_author_count'] = original_count
            metadata['_filtered'] = True
            metadata['_filtering_reason'] = f"Filtered to {len(filtered_authors)} authors using balanced mode"

            if logger:
                logger.info(f"✅ Filtered authors: {original_count} -> {len(filtered_authors)}")

        return metadata

    @staticmethod
    def filter_authors_against_zotero(
        authors: List[str],
        author_validator: Optional[AuthorValidator] = None,
        journal_validator: Optional[object] = None,
        logger: Optional[logging.Logger] = None,
        strict_match: bool = False,
    ) -> List[str]:
        """Filter authors against Zotero author/journal lists using config mode.
        
        This is the shared filtering logic used for both regex and GROBID authors.
        Applies balanced mode: prefers Zotero matches, allows limited unknowns if no matches.
        
        Args:
            authors: List of author names to filter
            author_validator: AuthorValidator instance (will initialize if None)
            journal_validator: JournalValidator instance (will initialize if None)
            logger: Optional logger for diagnostics
            strict_match: If True (e.g. for regex-extracted authors), use only last-name
                matching in the validator to avoid false positives. Default False.
            
        Returns:
            Filtered list of authors based on config mode
        """
        if not authors:
            return []
        
        # Lazy initialization of validators if not provided
        if author_validator is None:
            try:
                author_validator = AuthorValidator()
            except Exception as e:
                # If validator fails (e.g., DB not found), skip filtering
                if logger:
                    logger.warning(f"Could not initialize author validator: {e}")
                else:
                    print(f"  ⚠️  Could not initialize author validator: {e}")
                return authors
        
        if journal_validator is None:
            try:
                from .journal_validator import JournalValidator
                journal_validator = JournalValidator()
            except Exception as e:
                # If validator fails, skip journal filtering
                if logger:
                    logger.warning(f"Could not initialize journal validator: {e}")
                else:
                    print(f"  ⚠️  Could not initialize journal validator: {e}")
                journal_validator = None
        
        # Step 1: Filter out journal names
        non_journal_candidates = []
        if journal_validator:
            for candidate in authors:
                # Check if candidate matches a known journal
                journal_result = journal_validator.validate_journal(candidate)
                if not journal_result.get('matched', False):
                    non_journal_candidates.append(candidate)
        else:
            non_journal_candidates = authors
        
        if not non_journal_candidates:
            return []
        
        # Step 2: Validate against Zotero authors
        validation_result = author_validator.validate_authors(
            non_journal_candidates, allow_partial_match=not strict_match
        )
        known_authors = validation_result.get('known_authors', [])
        unknown_authors = validation_result.get('unknown_authors', [])
        
        # Step 3: Apply filtering mode from config
        config = configparser.ConfigParser()
        # Get root directory (assuming this is in shared_tools/utils/)
        root_dir = Path(__file__).parent.parent.parent
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        mode = config.get('AUTHOR_MATCHING', 'mode', fallback='balanced')
        max_unknown = config.getint('AUTHOR_MATCHING', 'max_unknown_authors', fallback=2)
        
        filtered = []
        
        if mode == 'prefer_zotero_only':
            # Only keep known authors
            filtered = [author['name'] for author in known_authors]
        
        elif mode == 'balanced':
            # Prefer known authors, but allow limited unknowns if no matches
            if known_authors:
                # We have matches - only keep those
                filtered = [author['name'] for author in known_authors]
            else:
                # No matches - keep up to max_unknown_authors
                filtered = [author['name'] for author in unknown_authors[:max_unknown]]
        
        elif mode == 'permissive':
            # Keep all non-journal candidates
            filtered = non_journal_candidates
        
        return filtered
