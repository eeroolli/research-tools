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
from typing import Dict, Optional

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
        
        # Get model name (use override if provided, otherwise config, otherwise default)
        default_model = model_name_override or "llama2:7b"
        self.ollama_model = config.get('OLLAMA', 'model', fallback=default_model)
        if model_name_override:
            self.ollama_model = model_name_override
        
        # Get timeout (use override if provided, otherwise config, otherwise default)
        default_timeout = timeout_override or 180
        self.timeout = config.getint('OLLAMA', 'timeout', fallback=default_timeout)
        if timeout_override:
            self.timeout = timeout_override
        
        # Get retry configuration
        self.max_retries = config.getint('OLLAMA', 'max_retries', fallback=2)
        self.retry_delay = config.getint('OLLAMA', 'retry_delay', fallback=5)
        
        # Build base URL
        self.ollama_base_url = f"http://{self.ollama_host}:{self.ollama_port}"
    
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
            url = f"{self.ollama_base_url}/api/generate"
            payload = {
                "model": self.ollama_model,
                "prompt": prompt,
                "stream": False
            }
            
            response = requests.post(url, json=payload, timeout=self.timeout)
            response.raise_for_status()
            
            result = response.json()
            response_text = result.get('response', '').strip()
            
            # Parse the response
            metadata = self._parse_ollama_response(response_text)
            
            if not metadata:
                return None
            
            # Validate if requested
            if validate:
                metadata = self.validator.validate_all(metadata)
            
            return metadata
            
        except subprocess.TimeoutExpired:
            print(f"Error: Ollama timed out after {self.timeout} seconds")
            return None
        except Exception as e:
            print(f"Error running Ollama: {e}")
            return None
    
    def _build_extraction_prompt(self, text: str, document_context: str = "general", language: str = None) -> str:
        """Build the extraction prompt for Ollama with context-specific instructions.
        
        Args:
            text: Text to extract metadata from
            document_context: Context hint for specialized extraction
            language: Language code (NO, EN, DE, FI, SE, etc.) for language-aware extraction
            
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
                'SE': 'Swedish'
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
            elif language.upper() == 'SE':
                language_instructions = f"""
LANGUAGE CONTEXT: This document is in Swedish.
- Author patterns: "Av [Name]", "Av: [Name]", "[Name] och [Name]"
- Date formats: "23 april 2025", "23.4.2025", "2025-04-23"
- Common terms: "Förlag" (publisher), "Tidskrift" (journal), "Kapitel" (chapter)
- Extract authors, titles, and metadata in Swedish format
"""
        
        # Base instructions
        base_instructions = """CRITICAL INSTRUCTIONS:
- Return ONLY information you can see in the text
- If you cannot find a field, use null - DO NOT GUESS OR INVENT
- DO NOT make up fake identifiers like "1234-5678" or "John Doe"
- ONLY extract what is actually present in the text
- FOR AUTHORS: Look for ALL authors mentioned - check title page, headers, footers, and bylines
- AUTHORS can be separated by commas, "and", "og" (Norwegian), "und" (German), "&", or line breaks
- Look for patterns like "By [Name]", "Av [Name]" (Norwegian), "Von [Name]" (German), "Authors: [Names]", "[Name] and [Name]", etc."""
        
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

JOURNAL ARTICLES:
- DOI: "DOI:", "https://doi.org/" or "10.xxxx/xxxxx"
- Authors after title
- Journal, volume, issue, pages, ISSN
- document_type: "journal_article"

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
- authors (array of strings) - List of author names (chapter authors if book chapter), empty array if none found
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

Remember: Return ONLY the JSON object. No explanatory text before or after. Use null for missing fields."""
    
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
    
    def shorten_title(self, title: str, preserve_first_n_words: int = 4) -> Optional[str]:
        """Shorten a title using Ollama API while preserving the first N words.
        
        Args:
            title: Title to shorten (already in filename format with underscores)
            preserve_first_n_words: Number of words from the start to preserve (default: 4)
            
        Returns:
            Shortened title or None if Ollama is unavailable/fails
        """
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
        
        # Build prompt for Ollama - request JSON format for reliable parsing
        prompt = f"""Shorten this filename title part and return ONLY valid JSON.

INPUT:
- First {preserve_first_n_words} words (KEEP AS IS): {preserved_part}
- Part to shorten: {rest_part}

TASK:
Shorten the "Part to shorten" using abbreviations and removing less important words.
Keep the first {preserve_first_n_words} words unchanged.

SHORTENING EXAMPLES:
- "Chinese" -> "Ch"
- "Japanese" -> "Jp"  
- "Americans" -> "Americans"
- "among" -> "among" (or remove if not critical)

OUTPUT FORMAT:
Return ONLY valid JSON with this exact structure:
{{
  "shortened": "Right_Spouse_Interracial_Marriage_among_Ch_and_Jp_Americans"
}}

CRITICAL RULES:
- Return ONLY the JSON object, no explanations
- No text before or after the JSON
- Use underscores between words in the shortened value
- The "shortened" field should contain ONLY the shortened part (after first {preserve_first_n_words} words)

EXAMPLE INPUT: "Right_Spouse_Interracial_Marriage_among_Chinese_and_Japanese_Americans"
EXAMPLE OUTPUT:
{{
  "shortened": "Right_Spouse_Interracial_Marriage_among_Ch_and_Jp_Americans"
}}

NOW SHORTEN THIS:
{rest_part}

Return ONLY the JSON:"""

        # Try with retries to handle Docker container wake-up time
        # Use config values for retries
        for attempt in range(self.max_retries):
            try:
                # Make HTTP API request to Ollama
                url = f"{self.ollama_base_url}/api/generate"
                payload = {
                    "model": self.ollama_model,
                    "prompt": prompt,
                    "stream": False
                }
                
                # Use configured timeout (from config, handles Docker container wake-up)
                response = requests.post(url, json=payload, timeout=self.timeout)
                response.raise_for_status()
                
                result = response.json()
                response_text = result.get('response', '').strip()
                
                # Debug: log raw response (uncomment to debug)
                # print(f"DEBUG: Raw Ollama response: {response_text}")
                
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
