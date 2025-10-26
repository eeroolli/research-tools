#!/usr/bin/env python3
"""
Ollama client for paper metadata extraction with validation.

Uses local Ollama LLM to extract structured metadata from academic papers,
with validation to prevent hallucinations.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.utils.identifier_validator import IdentifierValidator


class OllamaClient:
    """Client for Ollama-based paper metadata extraction."""
    
    def __init__(self, model_name: str = "llama2:7b", timeout: int = 180):
        """Initialize Ollama client.
        
        Args:
            model_name: Name of the Ollama model to use
            timeout: Timeout in seconds for Ollama requests
        """
        self.model_name = model_name
        self.timeout = timeout
        self.validator = IdentifierValidator()
    
    def extract_paper_metadata(self, text: str, validate: bool = True, 
                              document_context: str = "general", progress_callback=None, found_info: dict = None, debug: bool = False) -> Optional[Dict]:
        """Extract structured metadata from paper text using Ollama.
        
        Args:
            text: OCR or extracted text from paper (typically first page)
            validate: Whether to validate extracted identifiers
            document_context: Context hint - "news_article", "book_chapter", or "general"
            
        Returns:
            Dictionary with extracted and validated metadata, or None if failed
        """
        # Build the extraction prompt with context-specific instructions
        prompt = self._build_extraction_prompt(text, document_context)
        
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
            
            # Run ollama with the prompt
            result = subprocess.run(
                ["ollama", "run", self.model_name, prompt],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                print(f"Error running Ollama: {result.stderr}")
                return None
            
            # Parse the response
            response_text = result.stdout.strip()
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
    
    def _build_extraction_prompt(self, text: str, document_context: str = "general") -> str:
        """Build the extraction prompt for Ollama with context-specific instructions.
        
        Args:
            text: Text to extract metadata from
            document_context: Context hint for specialized extraction
            
        Returns:
            Formatted prompt string
        """
        # Base instructions
        base_instructions = """CRITICAL INSTRUCTIONS:
- Return ONLY information you can see in the text
- If you cannot find a field, use null - DO NOT GUESS OR INVENT
- DO NOT make up fake identifiers like "1234-5678" or "John Doe"
- ONLY extract what is actually present in the text
- FOR AUTHORS: Look for ALL authors mentioned - check title page, headers, footers, and bylines
- AUTHORS can be separated by commas, "and", "&", or line breaks
- Look for patterns like "By [Name]", "Authors: [Names]", "[Name] and [Name]", etc."""
        
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
- Extract BOTH chapter AND book info
- Headers/footers VALUABLE - contain book title (repeating!), chapter title, authors, pages
- REPEATING text = metadata (not noise!)
- Patterns: "By", "In:", "Edited by", "Chapter N"
- Return: title (chapter), authors (chapter), book_title, book_authors, book_editors, pages
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
{text[:3000]}

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
                                   document_context: str = "general") -> Optional[Dict]:
        """Extract metadata from the first page of a PDF.
        
        Args:
            pdf_path: Path to PDF file
            validate: Whether to validate extracted identifiers
            
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
                
                first_page = pdf.pages[0]
                text = first_page.extract_text()
                
                if not text or len(text.strip()) < 50:
                    print(f"Warning: Very little text extracted from {pdf_path.name}")
                    return None
                
                return self.extract_paper_metadata(text, validate=validate, 
                                                  document_context=document_context)
                
        except Exception as e:
            print(f"Error extracting text from {pdf_path}: {e}")
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
