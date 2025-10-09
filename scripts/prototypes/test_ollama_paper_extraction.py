#!/usr/bin/env python3
"""
Test script for Ollama-based paper identifier extraction.

Tests the ability of Ollama (llama2:7b) to extract structured metadata
from academic paper first pages.

Usage:
    python scripts/test_ollama_paper_extraction.py
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import Dict, Optional, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not found. Install with: conda install pdfplumber -c conda-forge")
    sys.exit(1)


class OllamaClient:
    """Simple Ollama client for paper metadata extraction."""
    
    def __init__(self, model_name: str = "llama2:7b"):
        self.model_name = model_name
        
    def extract_paper_metadata(self, text: str) -> Optional[Dict]:
        """Extract structured metadata from paper text using Ollama.
        
        Args:
            text: OCR or extracted text from paper first page
            
        Returns:
            Dictionary with extracted metadata or None if failed
        """
        prompt = self._build_extraction_prompt(text)
        
        try:
            # Run ollama with the prompt
            result = subprocess.run(
                ["ollama", "run", self.model_name, prompt],
                capture_output=True,
                text=True,
                timeout=60  # 60 second timeout
            )
            
            if result.returncode != 0:
                print(f"Error running Ollama: {result.stderr}")
                return None
            
            # Parse the response
            response_text = result.stdout.strip()
            return self._parse_ollama_response(response_text)
            
        except subprocess.TimeoutExpired:
            print("Error: Ollama timed out after 60 seconds")
            return None
        except Exception as e:
            print(f"Error running Ollama: {e}")
            return None
    
    def _build_extraction_prompt(self, text: str) -> str:
        """Build the extraction prompt for Ollama."""
        return f"""Extract structured information from this academic paper text. Return ONLY valid JSON with these fields:
- doi (string or null if not found)
- issn (string or null if not found - look for ISSN format like 1234-5678)
- isbn (string or null if not found - look for ISBN format)
- title (string)
- authors (array of strings, or empty array if not found)
- journal (string or null if not found - journal name or report series)
- publisher (string or null if not found)
- year (string or null if not found)
- document_type (one of: "journal_article", "book_chapter", "report", "legal_document", "conference_paper", "unknown")

Text from paper first page:
{text[:3000]}

Return ONLY the JSON object, no explanatory text before or after."""
    
    def _parse_ollama_response(self, response: str) -> Optional[Dict]:
        """Parse Ollama's response and extract JSON."""
        # Try to find JSON in the response
        # Look for { ... } pattern
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


def extract_first_page_text(pdf_path: Path) -> Optional[str]:
    """Extract text from the first page of a PDF.
    
    Args:
        pdf_path: Path to the PDF file
        
    Returns:
        Extracted text or None if failed
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                print(f"Error: PDF has no pages: {pdf_path}")
                return None
            
            first_page = pdf.pages[0]
            text = first_page.extract_text()
            
            if not text or len(text.strip()) < 50:
                print(f"Warning: Very little text extracted from {pdf_path.name}")
                return text
            
            return text
            
    except Exception as e:
        print(f"Error extracting text from {pdf_path}: {e}")
        return None


def display_extraction_result(filename: str, metadata: Optional[Dict], original_text: str):
    """Display the extraction results in a readable format."""
    print("\n" + "="*80)
    print(f"FILE: {filename}")
    print("="*80)
    
    if metadata:
        print("\n✅ EXTRACTED METADATA:")
        print(f"  Document Type: {metadata.get('document_type', 'unknown')}")
        print(f"  Title: {metadata.get('title', 'N/A')}")
        print(f"  Authors: {', '.join(metadata.get('authors', [])) if metadata.get('authors') else 'N/A'}")
        print(f"  Journal/Series: {metadata.get('journal', 'N/A')}")
        print(f"  Publisher: {metadata.get('publisher', 'N/A')}")
        print(f"  Year: {metadata.get('year', 'N/A')}")
        print(f"  DOI: {metadata.get('doi', 'N/A')}")
        print(f"  ISSN: {metadata.get('issn', 'N/A')}")
        print(f"  ISBN: {metadata.get('isbn', 'N/A')}")
        
        print("\n📄 FULL JSON:")
        print(json.dumps(metadata, indent=2))
    else:
        print("\n❌ EXTRACTION FAILED")
    
    print("\n📝 FIRST 500 CHARS OF EXTRACTED TEXT:")
    print("-" * 80)
    print(original_text[:500] if original_text else "No text extracted")
    print("-" * 80)


def test_single_pdf(pdf_path: Path, ollama_client: OllamaClient):
    """Test extraction on a single PDF."""
    print(f"\n🔍 Processing: {pdf_path.name}")
    
    # Extract text from first page
    text = extract_first_page_text(pdf_path)
    if not text:
        print(f"❌ Failed to extract text from {pdf_path.name}")
        return
    
    print(f"✅ Extracted {len(text)} characters from first page")
    
    # Use Ollama to extract metadata
    print("🤖 Sending to Ollama for analysis...")
    metadata = ollama_client.extract_paper_metadata(text)
    
    # Display results
    display_extraction_result(pdf_path.name, metadata, text)


def list_pdfs(directory: Path) -> List[Path]:
    """List all PDF files in directory."""
    pdfs = sorted(directory.glob("*.pdf"))
    return pdfs


def main():
    """Main test function."""
    # Configuration
    scanner_dir = Path("/mnt/i/FraScanner")
    
    # Check if directory exists
    if not scanner_dir.exists():
        print(f"Error: Directory does not exist: {scanner_dir}")
        sys.exit(1)
    
    # List available PDFs
    pdfs = list_pdfs(scanner_dir)
    if not pdfs:
        print(f"Error: No PDFs found in {scanner_dir}")
        sys.exit(1)
    
    print("="*80)
    print("OLLAMA PAPER EXTRACTION TEST")
    print("="*80)
    print(f"\nFound {len(pdfs)} PDFs in {scanner_dir}")
    print("\nAvailable PDFs:")
    for i, pdf in enumerate(pdfs, 1):
        size_mb = pdf.stat().st_size / (1024 * 1024)
        print(f"  {i:2d}. {pdf.name} ({size_mb:.1f} MB)")
    
    # User selection
    print("\nOptions:")
    print("  Enter number (1-{}) to test single PDF".format(len(pdfs)))
    print("  Enter 'all' to test all PDFs")
    print("  Enter 'q' to quit")
    
    choice = input("\nYour choice: ").strip().lower()
    
    if choice == 'q':
        print("Exiting.")
        return
    
    # Initialize Ollama client
    ollama_client = OllamaClient(model_name="llama2:7b")
    
    if choice == 'all':
        # Test all PDFs
        for pdf in pdfs:
            test_single_pdf(pdf, ollama_client)
            print("\n" + "="*80 + "\n")
    else:
        # Test single PDF
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(pdfs):
                test_single_pdf(pdfs[idx], ollama_client)
            else:
                print(f"Error: Invalid number. Choose 1-{len(pdfs)}")
        except ValueError:
            print("Error: Invalid input. Enter a number, 'all', or 'q'")


if __name__ == "__main__":
    main()
