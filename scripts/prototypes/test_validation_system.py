#!/usr/bin/env python3
"""
Test the validation system with the batch of PDFs to verify hallucination detection.
"""

import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.ai.ollama_client import OllamaClient


def test_pdf(pdf_path: Path, client: OllamaClient):
    """Test a single PDF with validation."""
    print("\n" + "=" * 80)
    print(f"FILE: {pdf_path.name}")
    print("=" * 80)
    
    try:
        metadata = client.extract_from_pdf_first_page(pdf_path, validate=True)
        
        if metadata:
            # Display results
            print(f"\n✅ Extraction completed")
            print(f"  Type: {metadata.get('document_type', 'unknown')}")
            print(f"  Title: {metadata.get('title', 'N/A')[:80]}")
            print(f"  Authors: {', '.join(metadata.get('authors', [])[:3])}")
            print(f"  Year: {metadata.get('year', 'N/A')}")
            
            # Show identifier validation
            print(f"\n🔍 Identifier Validation:")
            print(f"  DOI: {metadata.get('doi', 'None')} [{metadata.get('doi_reason', 'N/A')}]")
            print(f"  ISSN: {metadata.get('issn', 'None')} [{metadata.get('issn_reason', 'N/A')}]")
            print(f"  ISBN: {metadata.get('isbn', 'None')} [{metadata.get('isbn_reason', 'N/A')}]")
            print(f"  URL: {metadata.get('url', 'None')} [{metadata.get('url_reason', 'N/A')}]")
            
            # Check for hallucinations
            if metadata.get('has_hallucinations'):
                print(f"\n⚠️  HALLUCINATION WARNING:")
                for flag in metadata.get('confidence_flags', []):
                    print(f"    ❌ {flag}")
            else:
                print(f"\n✅ No hallucinations detected")
                
        else:
            print("❌ Extraction failed")
            
    except Exception as e:
        print(f"❌ ERROR: {e}")


def main():
    scanner_dir = Path("/mnt/i/FraScanner")
    
    # Test with documents we know have issues
    test_files = [
        # The Norwegian report that hallucinated data
        "Håndhevingsapparatet på diskrimineringsområdet - Gjennomgang og vurdering.pdf",
        # A clean journal article
        "Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf",
        # Legal document (no authors expected)
        "2012_CHARTER OF FUNDAMENTAL RIGHTS OF THE EUROPEAN UNION.pdf",
    ]
    
    print("VALIDATION SYSTEM TEST")
    print("Testing hallucination detection with improved prompt and validation")
    print("=" * 80)
    
    client = OllamaClient()
    
    for filename in test_files:
        pdf_path = scanner_dir / filename
        if pdf_path.exists():
            test_pdf(pdf_path, client)
        else:
            print(f"\n⚠️  File not found: {filename}")
    
    print("\n" + "=" * 80)
    print("TEST COMPLETE")
    print("=" * 80)


if __name__ == "__main__":
    main()
