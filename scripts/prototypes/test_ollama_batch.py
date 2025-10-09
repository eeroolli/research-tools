#!/usr/bin/env python3
"""Batch Ollama test - tests multiple document types."""

import sys
import json
import subprocess
from pathlib import Path

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


def test_pdf(pdf_path: Path):
    """Test a single PDF."""
    print("\n" + "=" * 80)
    print(f"FILE: {pdf_path.name}")
    print("=" * 80)
    
    try:
        # Extract text
        text = extract_first_page_text(pdf_path)
        print(f"✓ Extracted {len(text)} characters")
        
        # Extract metadata
        print(f"⏳ Sending to Ollama...")
        metadata = extract_metadata(text)
        
        if metadata:
            print("\n✅ SUCCESS:")
            print(f"  Type: {metadata.get('document_type', 'unknown')}")
            print(f"  Title: {metadata.get('title', 'N/A')[:80]}")
            print(f"  Authors: {', '.join(metadata.get('authors', [])[:3])}")
            print(f"  DOI: {metadata.get('doi', 'N/A')}")
            print(f"  ISSN: {metadata.get('issn', 'N/A')}")
            print(f"  ISBN: {metadata.get('isbn', 'N/A')}")
            print(f"  Year: {metadata.get('year', 'N/A')}")
            print(f"\n📄 Full JSON:")
            print(json.dumps(metadata, indent=2))
        else:
            print("❌ FAILED")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")


def main():
    scanner_dir = Path("/mnt/i/FraScanner")
    
    # Test specific document types
    test_files = [
        # Journal article (already tested, but included for completeness)
        "Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf",
        # Report from Norway
        "Håndhevingsapparatet på diskrimineringsområdet - Gjennomgang og vurdering.pdf",
        # Legal document
        "2012_CHARTER OF FUNDAMENTAL RIGHTS OF THE EUROPEAN UNION.pdf",
        # Technical/AI paper
        "Anand et al._GPT4All Training an Assistant-style Chatbot with Large Scale Data Distillation from GPT-3.5-Turbo.pdf",
    ]
    
    print("OLLAMA BATCH TEST - Testing Different Document Types")
    print("=" * 80)
    
    for filename in test_files:
        pdf_path = scanner_dir / filename
        if pdf_path.exists():
            test_pdf(pdf_path)
        else:
            print(f"\n⚠️  File not found: {filename}")
    
    print("\n" + "=" * 80)
    print("BATCH TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
