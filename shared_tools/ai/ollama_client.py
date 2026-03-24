#!/usr/bin/env python3
"""
Ollama client for paper metadata extraction with validation.

Uses local Ollama LLM to extract structured metadata from academic papers,
with validation to prevent hallucinations.
"""

import json
import re
import subprocess
import sys
import configparser
import requests
from pathlib import Path
from typing import Dict, List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.utils.identifier_validator import IdentifierValidator


class OllamaClient:
    """Client for Ollama-based paper metadata extraction."""
    
    def __init__(self, model_name: str = None, timeout: int = None):
        """Initialize Ollama client.
        
        Args:
            model_name: Name of the Ollama model to use (overrides config if provided)
            timeout: Timeout in seconds for Ollama requests (overrides config if provided)
        """
        self.validator = IdentifierValidator()
        self._load_ollama_config(model_name, timeout)
    
    def _load_ollama_config(self, model_name_override: str = None, timeout_override: int = None):
        """Load Ollama configuration from config files.
        
        Args:
            model_name_override: Override model name from config (optional)
            timeout_override: Override timeout from config (optional)
        """
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent.parent
        
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        # Get Ollama host and port
        self.ollama_host = config.get('OLLAMA', 'host', fallback='localhost')
        self.ollama_port = config.getint('OLLAMA', 'port', fallback=11434)
        
        # Determine base model (single-model, backward compatible)
        base_default = model_name_override or "llama2:7b"
        base_model = config.get('OLLAMA', 'model', fallback=base_default)
        if model_name_override:
            # Explicit override wins over config
            base_model = model_name_override
        self.ollama_model = base_model
        
        # Role-specific models (metadata vs title), falling back to base model
        metadata_model_cfg = config.get('OLLAMA', 'metadata_model', fallback='').strip()
        title_model_cfg = config.get('OLLAMA', 'title_model', fallback='').strip()
        
        if model_name_override:
            # If caller forces a model, use it for all roles
            self.metadata_model = base_model
            self.title_model = base_model
        else:
            self.metadata_model = metadata_model_cfg or base_model
            self.title_model = title_model_cfg or base_model
        
        # Get timeout (use override if provided, otherwise config, otherwise default)
        default_timeout = timeout_override or 180
        self.timeout = config.getint('OLLAMA', 'timeout', fallback=default_timeout)
        if timeout_override:
            self.timeout = timeout_override
        
        # Get retry configuration
        self.max_retries = config.getint('OLLAMA', 'max_retries', fallback=2)
        self.retry_delay = config.getint('OLLAMA', 'retry_delay', fallback=5)
        
        # Get title shortening configuration
        self.title_shorten_preserve_words = config.getint('OLLAMA', 'title_shorten_preserve_words', fallback=4)
        self.title_shorten_max_length = config.getint('OLLAMA', 'title_shorten_max_length', fallback=70)
        
        # Temperature configuration with safe defaults
        def _get_float_option(section: str, option: str, default: float) -> float:
            try:
                raw = config.get(section, option, fallback='').strip()
                if not raw:
                    return default
                return float(raw)
            except Exception:
                return default
        
        # Conservative defaults: low temperature for metadata, near-zero for filenames
        self.metadata_temperature = _get_float_option('OLLAMA', 'metadata_temperature', 0.1)
        self.title_temperature = _get_float_option('OLLAMA', 'title_temperature', 0.0)
        
        # Build base URL
        self.ollama_base_url = f"http://{self.ollama_host}:{self.ollama_port}"
        
        # Fallback hosts from config (used when hostname doesn't resolve, e.g. host = p1)
        fallback_str = config.get('OLLAMA', 'fallback_hosts', fallback='').strip()
        self.fallback_hosts = [h.strip() for h in fallback_str.split(',') if h.strip()] if fallback_str else []
    
    def extract_paper_metadata(self, text: str, validate: bool = True, 
                              document_context: str = "general", language: str = None,
                              progress_callback=None, found_info: dict = None, debug: bool = False) -> Optional[Dict]:
        """Extract structured metadata from paper text using Ollama.
        
        Args:
            text: OCR or extracted text from paper (typically first page)
            validate: Whether to validate extracted identifiers
            document_context: Context hint - "news_article", "book_chapter", or "general"
            language: Language code (e.g., "NO", "EN", "DE", "FI", "SE") - helps with extraction accuracy
            
        Returns:
            Dictionary with extracted and validated metadata, or None if failed
        """
        # Build the extraction prompt with context-specific instructions
        prompt = self._build_extraction_prompt(text, document_context, language=language)
        
        try:
            # Debug: Show extracted text if requested
            if debug:
                print(f"\n🔍 DEBUG: Extracted text (first 1000 chars):")
                print("=" * 60)
                print(text[:1000])
                print("=" * 60)
            
            # Start progress indicator if callback provided
            if progress_callback:
                import threading
                import time
                
                def show_progress():
                    elapsed = 0
                    while True:
                        time.sleep(1)
                        elapsed += 1
                        progress_callback(found_info or {}, elapsed)
                        if elapsed >= self.timeout:
                            break
                
                progress_thread = threading.Thread(target=show_progress, daemon=True)
                progress_thread.start()
            
            # Use HTTP API to connect to configured Ollama host (p1 or localhost)
            # Try primary host first, then fallback to IPs if hostname doesn't resolve
            hosts_to_try = [self.ollama_base_url]
            for fallback_host in self.fallback_hosts:
                hosts_to_try.append(f"http://{fallback_host}:{self.ollama_port}")
            
            last_error = None
            response = None
            for base_url in hosts_to_try:
                try:
                    url = f"{base_url}/api/generate"
                    model = (getattr(self, "metadata_model", None) or self.ollama_model)
                    temperature = getattr(self, "metadata_temperature", 0.1)
                    payload = {
                        "model": model,
                        "prompt": prompt,
                        "stream": False,
                        "options": {
                            "temperature": temperature
                        }
                    }
                    
                    response = requests.post(url, json=payload, timeout=self.timeout)
                    response.raise_for_status()
                    break  # Success, exit loop
                except (requests.exceptions.ConnectionError, requests.exceptions.Timeout, 
                        requests.exceptions.RequestException) as e:
                    last_error = e
                    continue  # Try next host
            
            if response is None:
                # All hosts failed
                if last_error:
                    raise last_error
                else:
                    raise requests.exceptions.ConnectionError("Failed to connect to Ollama on all hosts")
            
            result = response.json()
            response_text = result.get('response', '').strip()
            
            # Parse the response
            metadata = self._parse_ollama_response(response_text)
            
            if not metadata:
                return None
            
            # Validate authors against source text to filter out hallucinations
            if 'authors' in metadata and isinstance(metadata.get('authors'), list):
                original_authors = metadata.get('authors', [])
                validated_authors = self._validate_authors_against_text(original_authors, text)
                
                if len(validated_authors) != len(original_authors):
                    # Some authors were filtered out
                    filtered_count = len(original_authors) - len(validated_authors)
                    logger = getattr(self, 'logger', None)
                    if logger:
                        logger.warning(f"Filtered out {filtered_count} hallucinated author(s) that don't appear in source text")
                    else:
                        print(f"Warning: Filtered out {filtered_count} hallucinated author(s) that don't appear in source text")
                
                # Update metadata with validated authors
                metadata['authors'] = validated_authors
            
            # Also validate book_authors and book_editors for book chapters
            if 'book_authors' in metadata and isinstance(metadata.get('book_authors'), list):
                original_book_authors = metadata.get('book_authors', [])
                validated_book_authors = self._validate_authors_against_text(original_book_authors, text)
                metadata['book_authors'] = validated_book_authors if validated_book_authors else None
            
            if 'book_editors' in metadata and isinstance(metadata.get('book_editors'), list):
                original_book_editors = metadata.get('book_editors', [])
                validated_book_editors = self._validate_authors_against_text(original_book_editors, text)
                metadata['book_editors'] = validated_book_editors if validated_book_editors else None
            
            # Validate if requested
            if validate:
                metadata = self.validator.validate_all(metadata)
            
            return metadata
            
        except Exception as e:
            # Check if it's a requests timeout
            if 'timeout' in str(e).lower() or 'timed out' in str(e).lower():
                print(f"Error: Ollama timed out after {self.timeout} seconds")
            else:
                print(f"Error calling Ollama API: {e}")
            return None
    
    def _build_extraction_prompt(self, text: str, document_context: str = "general", language: str = None) -> str:
        """Build the extraction prompt for Ollama with context-specific instructions.
        
        Args:
            text: Text to extract metadata from
            document_context: Context hint for specialized extraction
            language: Language code (NO, EN, DE, FI, SV, etc.) for language-aware extraction
            
        Returns:
            Formatted prompt string
        """
        # Language-specific instructions
        language_instructions = ""
        if language:
            lang_map = {
                'NO': 'Norwegian',
                'EN': 'English', 
                'DE': 'German',
                'FI': 'Finnish',
                'SV': 'Swedish'  # Swedish (matches filename prefix SV_ and ISO code sv)
            }
            lang_name = lang_map.get(language.upper(), language.upper())
            
            if language.upper() == 'NO':
                language_instructions = f"""
LANGUAGE CONTEXT: This document is in {lang_name}.
- Author patterns: "Av [Name]", "Forfatter: [Name]", "[Name] og [Name]"
- Date formats: "23. april 2025", "23.4.2025", "2025-04-23"
- Common terms: "Forlag" (publisher), "Tidsskrift" (journal), "Kapittel" (chapter)
- Extract authors, titles, and metadata in {lang_name} format
"""
            elif language.upper() == 'DE':
                language_instructions = f"""
LANGUAGE CONTEXT: This document is in {lang_name}.
- Author patterns: "Von [Name]", "Autor: [Name]", "[Name] und [Name]"
- Date formats: "23. April 2025", "23.04.2025"
- Common terms: "Verlag" (publisher), "Zeitschrift" (journal), "Kapitel" (chapter)
- Extract authors, titles, and metadata in {lang_name} format
"""
            elif language.upper() == 'FI':
                language_instructions = f"""
LANGUAGE CONTEXT: This document is in Finnish.
- Author patterns: "Tekijä:", "Tekijät:", "[Name] ja [Name]" (and)
- Date formats: "23. huhtikuuta 2025", "23.4.2025", "2025-04-23"
- Common terms: "Kustantaja" (publisher), "Lehti"/"Aikakauslehti" (journal), "Luku" (chapter)
- Extract authors, titles, and metadata in Finnish format
"""
            elif language.upper() == 'SV':
                language_instructions = f"""
LANGUAGE CONTEXT: This document is in Swedish.
- Author patterns: "Av [Name]", "Av: [Name]", "[Name] och [Name]"
- Date formats: "23 april 2025", "23.4.2025", "2025-04-23"
- Common terms: "Förlag" (publisher), "Tidskrift" (journal), "Kapitel" (chapter)
- Extract authors, titles, and metadata in Swedish format
"""
        
        # Base instructions - CRITICAL: emphasize NOT inventing authors
        base_instructions = """CRITICAL INSTRUCTIONS - READ CAREFULLY:
- Return ONLY information you can see in the text
- If you cannot find a field, use null - DO NOT GUESS OR INVENT
- DO NOT make up fake identifiers like "1234-5678" or "John Doe"

FOR AUTHORS - THIS IS CRITICAL:
- If you see NO author names in the text, return: "authors": []
- DO NOT invent author names like "John Smith", "Torunn Arntsen Sørheim", or any other names
- DO NOT guess author names based on context or make assumptions
- Empty array [] is the CORRECT response when no authors are found
- ONLY extract author names that are explicitly written in the text
- Look for ALL authors mentioned - check title page, headers, footers, and bylines
- AUTHORS can be separated by commas, "and", "og" (Norwegian), "und" (German), "&", or line breaks
- Look for patterns like "By [Name]", "Av [Name]" (Norwegian), "Von [Name]" (German), "Authors: [Names]", "[Name] and [Name]", etc.
- If you cannot find any author names after searching thoroughly, return "authors": [] - DO NOT INVENT NAMES"""
        
        # Comprehensive hints for ALL document types (always included - Ollama uses what applies)
        comprehensive_hints = """

EXTRACTION PATTERNS (use what applies to this document):

NEWS/WEB ARTICLES:
- Author: "By [Name]", "Av [Name]" (Norwegian), "Von [Name]" (German)
- Dates vary: "April 23, 2025" (US), "23 April 2025" (EU), "23.4.2025" (Nordic)
- Publisher: news organization
- URL in header/footer
- document_type: "news_article"

BOOK CHAPTERS:
- Extract BOTH chapter AND book info - this is a book chapter!
- RUNNING HEADS (page headers/footers) are CRITICAL metadata sources:
  * ODD-NUMBERED PAGES (1,3,5,7...): Header/footer often shows CHAPTER TITLE or chapter number
  * EVEN-NUMBERED PAGES (2,4,6,8...): Header/footer often shows BOOK TITLE
- LANDSCAPE/TWO-UP FORMAT: If text is very wide, look on RIGHT SIDE for chapter info, LEFT SIDE is usually from facing page
- REPEATING text = metadata (not noise!) - book titles repeat on every page
- Patterns to find: "Chapter N:", "In: [Book Title]", "Edited by [Name]", "[Chapter Title] | [Book Title]"
- Chapter authors usually on first page below chapter title
- Book authors/editors often in header/footer or on first page
- Look for "pp." or "pages" numbers
- Return: title (chapter), authors (chapter), book_title, book_authors, book_editors, pages, chapter_number
- document_type: "book_chapter"
- Ignore bibliography/references/footnotes/endnotes/etc. (particularly if the first page is a even numbered page)

JOURNAL ARTICLES:
- DOI: "DOI:", "https://doi.org/" or "10.xxxx/xxxxx"
- Authors after title
- Journal, volume, issue, pages, ISSN
- document_type: "journal_article"
- Ignore bibliography/references/footnotes/endnotes/etc. (particularly if the first page is a even numbered page)


REPORTS:
- ISSN or ISBN possible
- Organization name
- document_type: "report"

WORKING PAPERS:
- Usually from institutions (universities, think tanks, research centers)
- Often have "Working Paper" in title or header
- May have working paper numbers (e.g., "WP-2024-01")
- Institution name usually prominent
- URL often provided for download
- document_type: "working_paper"

MANUSCRIPTS:
- Unpublished papers without institutional affiliation
- Usually just authors and title
- No publisher or institution
- document_type: "manuscript"
"""
        
        return f"""Extract structured information from this document text. 

{base_instructions}
{language_instructions}
{comprehensive_hints}

Return ONLY valid JSON with these exact fields:
- doi (string or null) - Digital Object Identifier, format: 10.xxxx/xxxxx
- issn (string or null) - ISSN format: 1234-5678
- isbn (string or null) - ISBN-10 or ISBN-13
- url (string or null) - Full URL if this is a web article/news article
- title (string) - Document title (chapter title if book chapter)
- authors (array of strings) - List of author names (chapter authors if book chapter). MUST be empty array [] if no authors found in text. DO NOT invent names.
- journal (string or null) - Journal name, report series, or publisher
- publisher (string or null) - Publishing organization
- year (string or null) - Publication year
- pages (string or null) - Page range (e.g., "145-178" or "pp. 89-120")
- document_type (string) - One of: journal_article, report, legal_document, conference_paper, news_article, book_chapter, working_paper, manuscript, unknown

FOR BOOK CHAPTERS ONLY (if document_type is "book_chapter"):
- book_title (string or null) - The book title (often in headers/footers)
- book_authors (array of strings or null) - Book authors if single-author book
- book_editors (array of strings or null) - Book editors if edited volume
- chapter_number (string or null) - Chapter number if visible (e.g., "5" or "Chapter 5")

Text from document:
{text[:5000]}

Remember: Return ONLY the JSON object. No explanatory text before or after. Use null for missing fields. For authors, use [] (empty array) if no authors are found - DO NOT invent author names."""
    
    def _validate_authors_against_text(self, authors: List[str], text: str) -> List[str]:
        """Validate that extracted authors actually appear in the source text.
        
        Filters out hallucinated author names that don't appear in the text.
        Uses fuzzy matching to handle minor OCR errors.
        
        Args:
            authors: List of author names extracted by Ollama
            text: Source text from the document
            
        Returns:
            List of authors that can be verified in the text (empty list if none found)
        """
        if not authors:
            return []
        
        if not text:
            # No text to validate against - return empty
            return []
        
        text_lower = text.lower()
        validated_authors = []
        
        for author in authors:
            if not author or not author.strip():
                continue
            
            author_clean = author.strip()
            author_lower = author_clean.lower()
            
            # Check if author name appears in text (case-insensitive)
            # Try full name first
            if author_lower in text_lower:
                validated_authors.append(author_clean)
                continue
            
            # Try splitting name into parts (handle "First Last" or "Last, First")
            name_parts = []
            if ',' in author_clean:
                # "Last, First" format
                parts = [p.strip() for p in author_clean.split(',')]
                name_parts = parts
            else:
                # "First Last" format
                name_parts = author_clean.split()
            
            # Check if at least the last name appears in text
            if len(name_parts) >= 1:
                last_name = name_parts[-1].lower() if name_parts else ""
                if last_name and len(last_name) > 2:  # Only check if last name is substantial
                    if last_name in text_lower:
                        validated_authors.append(author_clean)
                        continue
            
            # If we get here, author name not found in text - likely hallucinated
            # Log it but don't include in validated list
            logger = getattr(self, 'logger', None)
            if logger:
                logger.warning(f"Author '{author_clean}' not found in source text - filtering out (likely hallucinated)")
            else:
                print(f"Warning: Author '{author_clean}' not found in source text - filtering out (likely hallucinated)")
        
        return validated_authors
    
    def _parse_ollama_response(self, response: str) -> Optional[Dict]:
        """Parse Ollama's response and extract JSON.
        
        Args:
            response: Raw response from Ollama
            
        Returns:
            Parsed metadata dictionary or None if parsing failed
        """
        # Try to find JSON in the response
        start_idx = response.find('{')
        end_idx = response.rfind('}')
        
        if start_idx == -1 or end_idx == -1:
            print("Error: Could not find JSON in Ollama response")
            return None
        
        json_str = response[start_idx:end_idx+1]
        
        try:
            data = json.loads(json_str)
            return data
        except json.JSONDecodeError as e:
            print(f"Error parsing JSON from Ollama: {e}")
            print(f"JSON string: {json_str[:200]}...")
            return None
    
    def extract_from_pdf_first_page(self, pdf_path: Path, validate: bool = True,
                                   document_context: str = "general", page_offset: int = 0) -> Optional[Dict]:
        """Extract metadata from the first page of a PDF.
        
        Args:
            pdf_path: Path to PDF file
            validate: Whether to validate extracted identifiers
            document_context: Context hint for extraction ("general", "book_chapter", etc.)
            page_offset: 0-indexed page offset (0 = page 1, 1 = page 2, etc.) to skip pages before document starts
            
        Returns:
            Validated metadata dictionary or None if failed
        """
        try:
            import pdfplumber
        except ImportError:
            print("Error: pdfplumber not installed. Install with: conda install pdfplumber -c conda-forge")
            return None
        
        try:
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) == 0:
                    print(f"Error: PDF has no pages: {pdf_path}")
                    return None
                
                # Check if page_offset is valid
                if page_offset >= len(pdf.pages):
                    print(f"Error: Page offset {page_offset + 1} exceeds PDF page count {len(pdf.pages)}")
                    return None
                
                target_page = pdf.pages[page_offset]
                text = target_page.extract_text()
                
                if not text or len(text.strip()) < 50:
                    print(f"Warning: Very little text extracted from {pdf_path.name} (page {page_offset + 1})")
                    return None
                
                return self.extract_paper_metadata(text, validate=validate, 
                                                  document_context=document_context, language=None)
                
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
            return None
    
    def shorten_title(self, title: str, preserve_first_n_words: int = None) -> Optional[str]:
        """Shorten a title using Ollama API while preserving the first N words.
        
        Args:
            title: Title to shorten (already in filename format with underscores)
            preserve_first_n_words: Number of words from the start to preserve (uses config default if None)
            
        Returns:
            Shortened title or None if Ollama is unavailable/fails
        """
        # Use config value if not provided
        if preserve_first_n_words is None:
            preserve_first_n_words = self.title_shorten_preserve_words
        if not title:
            return None
        
        # Split title into words (by underscores)
        words = title.split('_')
        
        if len(words) <= preserve_first_n_words:
            # Title is already short enough or has fewer words than we want to preserve
            return title
        
        # Extract first N words to preserve
        preserved_words = words[:preserve_first_n_words]
        preserved_part = '_'.join(preserved_words)
        
        # Extract the part that can be shortened
        rest_words = words[preserve_first_n_words:]
        rest_part = '_'.join(rest_words)
        
        # Calculate available length for shortened part
        # Full title limit minus preserved part length minus 1 for the underscore separator
        preserved_part_length = len(preserved_part)
        available_length = self.title_shorten_max_length - preserved_part_length - 1
        
        # #region agent log
        import json as json_module
        from pathlib import Path
        log_path = Path('.cursor/debug.log')
        try:
            with open(log_path, 'a', encoding='utf-8') as f:
                log_entry = {
                    'sessionId': 'debug-session',
                    'runId': 'run1',
                    'hypothesisId': 'E',
                    'location': 'ollama_client.py:398',
                    'message': 'shorten_title before Ollama call',
                    'data': {
                        'preserved_part': preserved_part,
                        'preserved_part_length': preserved_part_length,
                        'rest_part': rest_part,
                        'full_title': title,
                        'max_full_title_length': self.title_shorten_max_length,
                        'available_length_for_shortened': available_length
                    },
                    'timestamp': int(__import__('time').time() * 1000)
                }
                f.write(json_module.dumps(log_entry) + '\n')
        except Exception:
            pass
        # #endregion
        
        # Build prompt for Ollama - request JSON format for reliable parsing
        prompt = f"""Shorten this filename title part and return ONLY valid JSON.

INPUT:
- First {preserve_first_n_words} words (KEEP AS IS): {preserved_part} (length: {preserved_part_length} chars)
- Part to shorten: {rest_part}
- Full title maximum length: {self.title_shorten_max_length} characters

TASK:
Shorten the "Part to shorten" so that the FULL title (preserved part + shortened part + underscore) fits within {self.title_shorten_max_length} characters total.
The shortened part can use up to {available_length} characters (after accounting for preserved part length and underscore separator).
Keep the first {preserve_first_n_words} words unchanged.

PRIORITY RULES:
1. ALWAYS SHORTEN well-established abbreviations: languages (Chinese->CN, Japanese->JP, English->EN, German->DE, French->FR, Spanish->ES), countries (United_States->US, United_Kingdom->UK, China->CN, Japan->JP), measurement units (kilometer->km, centimeter->cm, kilogram->kg, millimeter->mm, etc.)
2. PRESERVE important words: proper names (people, places), specific concepts, technical terms
3. SHORTEN common words: articles (the, a, an), prepositions (of, in, on, at), common verbs (is, are, was)
4. Use abbreviations for common words when possible (e.g., "and" -> "&", "with" -> "w/")
5. Remove less critical connecting words if needed so the full title stays within {self.title_shorten_max_length} characters

SHORTENING EXAMPLES:
- "Chinese" -> "CN" (language, use ISO code)
- "Japanese" -> "JP" (language/country, use ISO code)
- "United_States" -> "US" (country, use standard abbreviation)
- "kilometer" -> "km" (measurement unit, use standard abbreviation)
- "Americans" -> "Americans" (keep if it's a key concept, not a country name)
- "among" -> "among" (or remove if not critical)
- "the" -> remove or keep as "the" (common word)
- "of" -> "of" or remove (common word)
- Proper names like "Einstein", "Tokyo", "Machine_Learning" -> KEEP FULLY

OUTPUT FORMAT:
Return ONLY valid JSON with this exact structure:
{{
  "shortened": "shortened_part_here"
}}

CRITICAL RULES:
- Return ONLY the JSON object, no explanations
- No text before or after the JSON
- Use underscores between words in the shortened value
- The "shortened" field should contain ONLY the shortened part (after first {preserve_first_n_words} words)
- Target length: full title (preserved + shortened + underscore) must be ≤ {self.title_shorten_max_length} characters
- Available for shortened part: up to {available_length} characters
- DO NOT use example text - shorten the actual input provided
- Preserve important words (names, locations, concepts) even if it means keeping them longer

NOW SHORTEN THIS:
{rest_part}

Return ONLY the JSON:"""

        # Try with retries to handle Docker container wake-up time
        # Use config values for retries
        for attempt in range(self.max_retries):
            try:
                # Build list of hosts to try: primary first, then fallbacks
                hosts_to_try = [self.ollama_base_url]
                for fallback_host in self.fallback_hosts:
                    hosts_to_try.append(f"http://{fallback_host}:{self.ollama_port}")
                
                # Try each host in order until one succeeds
                response = None
                last_error = None
                for base_url in hosts_to_try:
                    try:
                        # Make HTTP API request to Ollama
                        url = f"{base_url}/api/generate"
                        model = (getattr(self, "title_model", None) or self.ollama_model)
                        temperature = getattr(self, "title_temperature", 0.0)
                        payload = {
                            "model": model,
                            "prompt": prompt,
                            "stream": False,
                            "options": {
                                "temperature": temperature
                            }
                        }
                        
                        # Use configured timeout (from config, handles Docker container wake-up)
                        response = requests.post(url, json=payload, timeout=self.timeout)
                        response.raise_for_status()
                        break  # Success, exit host loop
                    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout,
                            requests.exceptions.RequestException) as e:
                        last_error = e
                        continue  # Try next host
                
                if response is None:
                    # All hosts failed, raise last error
                    if last_error:
                        raise last_error
                    else:
                        raise requests.exceptions.ConnectionError("Failed to connect to Ollama on all hosts")
                
                result = response.json()
                response_text = result.get('response', '').strip()
                
                # #region agent log
                try:
                    with open(log_path, 'a', encoding='utf-8') as f:
                        log_entry = {
                            'sessionId': 'debug-session',
                            'runId': 'run1',
                            'hypothesisId': 'E',
                            'location': 'ollama_client.py:454',
                            'message': 'Ollama raw response received',
                            'data': {
                                'raw_response': response_text,
                                'raw_response_length': len(response_text)
                            },
                            'timestamp': int(__import__('time').time() * 1000)
                        }
                        f.write(json_module.dumps(log_entry) + '\n')
                except Exception:
                    pass
                # #endregion
                
                # Try to extract JSON from the response
                shortened_rest = None
                
                # Method 1: Try to find JSON object in the response
                json_start = response_text.find('{')
                json_end = response_text.rfind('}')
                
                if json_start != -1 and json_end != -1 and json_end > json_start:
                    json_str = response_text[json_start:json_end + 1]
                    try:
                        parsed_json = json.loads(json_str)
                        shortened_rest = parsed_json.get('shortened', '').strip()
                    except json.JSONDecodeError:
                        # JSON parsing failed, try alternative methods
                        pass
                
                # Method 2: If JSON parsing failed, try to find the shortened value directly
                if not shortened_rest:
                    # Look for "shortened": "value" pattern
                    match = re.search(r'"shortened"\s*:\s*"([^"]+)"', response_text)
                    if match:
                        shortened_rest = match.group(1).strip()
                
                # Method 3: Fallback - try to extract text that looks like a filename
                if not shortened_rest:
                    # Look for text with underscores (filename pattern)
                    # Find the longest sequence of words separated by underscores
                    matches = re.findall(r'[A-Za-z][A-Za-z0-9_]*(?:_[A-Za-z][A-Za-z0-9_]*)+', response_text)
                    if matches:
                        # Take the longest match that looks like a filename
                        shortened_rest = max(matches, key=len)
                
                # If we still don't have a result, return None to trigger fallback
                if not shortened_rest:
                    return None
                
                # Validate: should only contain filename-safe characters
                # Allow letters, numbers, underscores, and hyphens (some models might use hyphens)
                if not all(c.isalnum() or c in ['_', '-'] for c in shortened_rest):
                    # Filter to only safe characters (convert hyphens to underscores for consistency)
                    shortened_rest = ''.join(c if c.isalnum() or c == '_' else '_' for c in shortened_rest.replace('-', '_'))
                
                # Reconstruct full title
                if shortened_rest:
                    shortened_title = f"{preserved_part}_{shortened_rest}"
                    
                    # Validate full title length - if it exceeds limit, truncate the shortened part
                    if len(shortened_title) > self.title_shorten_max_length:
                        # Calculate how much we can keep from shortened_rest
                        max_shortened_length = available_length
                        if len(shortened_rest) > max_shortened_length:
                            shortened_rest = shortened_rest[:max_shortened_length].rstrip('_')
                            shortened_title = f"{preserved_part}_{shortened_rest}"
                    
                    # #region agent log
                    try:
                        with open(log_path, 'a', encoding='utf-8') as f:
                            log_entry = {
                                'sessionId': 'debug-session',
                                'runId': 'run1',
                                'hypothesisId': 'E',
                                'location': 'ollama_client.py:502',
                                'message': 'Ollama shortened title reconstructed',
                                'data': {
                                    'shortened_rest': shortened_rest,
                                    'preserved_part': preserved_part,
                                    'final_shortened_title': shortened_title,
                                    'final_title_length': len(shortened_title),
                                    'max_allowed_length': self.title_shorten_max_length
                                },
                                'timestamp': int(__import__('time').time() * 1000)
                            }
                            f.write(json_module.dumps(log_entry) + '\n')
                    except Exception:
                        pass
                    # #endregion
                    
                    return shortened_title
                else:
                    # If Ollama returned empty, return None to trigger fallback
                    return None
                    
            except requests.exceptions.Timeout:
                # Timeout - might be container waking up, retry
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(self.retry_delay)
                    continue
                return None
            except requests.exceptions.ConnectionError:
                # Connection error - might be container not ready, retry
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(self.retry_delay)
                    continue
                return None
            except requests.exceptions.HTTPError as e:
                # HTTP error (e.g., model not found) - don't retry
                if e.response and e.response.status_code == 404:
                    # Model not found - return None for fallback
                    return None
                # Other HTTP errors - retry
                if attempt < self.max_retries - 1:
                    import time
                    time.sleep(self.retry_delay)
                    continue
                return None
            except requests.exceptions.RequestException:
                # Other request errors - return None for fallback
                return None
            except Exception:
                # Any other error - return None for fallback
                return None
        
        return None


if __name__ == "__main__":
    # Quick test of the client
    from pathlib import Path
    
    client = OllamaClient()
    
    # Test with a sample PDF
    test_pdf = Path("/mnt/i/FraScanner/Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf")
    
    if test_pdf.exists():
        print(f"Testing Ollama client with: {test_pdf.name}")
        print("=" * 80)
        
        metadata = client.extract_from_pdf_first_page(test_pdf, validate=True)
        
        if metadata:
            print("\n✅ SUCCESS - Extracted and validated metadata:")
            print(json.dumps(metadata, indent=2))
            
            if metadata.get('has_hallucinations'):
                print("\n⚠️  WARNING: Potential hallucinations detected:")
                for flag in metadata.get('confidence_flags', []):
                    print(f"  - {flag}")
        else:
            print("\n❌ FAILED")
    else:
        print(f"Test PDF not found: {test_pdf}")
