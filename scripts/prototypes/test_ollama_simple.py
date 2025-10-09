#!/usr/bin/env python3
"""Simple Ollama test - extracts metadata from a single PDF."""

import sys
import json
import subprocess
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    import pdfplumber
except ImportError:
    print("Error: pdfplumber not found")
    sys.exit(1)


def extract_first_page_text(pdf_path: Path) -> str:
    """Extract text from first page."""
    with pdfplumber.open(pdf_path) as pdf:
        return pdf.pages[0].extract_text()


def extract_metadata(text: str) -> dict:
    """Use Ollama to extract structured metadata."""
    prompt = f"""Extract structured information from this academic paper text. Return ONLY valid JSON with these fields:
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

    result = subprocess.run(
        ["ollama", "run", "llama2:7b", prompt],
        capture_output=True,
        text=True,
        timeout=120
    )
    
    response = result.stdout.strip()
    
    # Extract JSON
    start = response.find('{')
    end = response.rfind('}')
    if start != -1 and end != -1:
        json_str = response[start:end+1]
        return json.loads(json_str)
    return None


def main():
    # Test with a specific PDF - the Nature paper about brain/LLM alignment
    pdf_path = Path("/mnt/i/FraScanner/Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf")
    
    print(f"Testing: {pdf_path.name}")
    print("=" * 80)
    
    # Extract text
    print("\n1. Extracting text from first page...")
    text = extract_first_page_text(pdf_path)
    print(f"   ✓ Extracted {len(text)} characters")
    
    # Show first 500 chars
    print("\n2. First 500 chars of extracted text:")
    print("-" * 80)
    print(text[:500])
    print("-" * 80)
    
    # Extract metadata with Ollama
    print("\n3. Sending to Ollama for metadata extraction...")
    print("   (This will take 30-60 seconds...)")
    metadata = extract_metadata(text)
    
    if metadata:
        print("\n✅ SUCCESS - Extracted metadata:")
        print("=" * 80)
        print(json.dumps(metadata, indent=2))
        print("=" * 80)
    else:
        print("\n❌ FAILED - Could not extract metadata")


if __name__ == "__main__":
    main()
