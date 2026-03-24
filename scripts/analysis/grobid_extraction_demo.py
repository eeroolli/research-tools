#!/usr/bin/env python3
"""
Manual diagnostic script for GROBID extraction.

This was originally `tests/test_grobid_extraction.py` but has been moved
out of the automated test suite. Use it as:

    python scripts/analysis/grobid_extraction_demo.py <pdf_path>
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.api.grobid_client import GrobidClient


def run_grobid_extraction(pdf_path: Path) -> None:
    """Test GROBID extraction on a book chapter PDF."""
    print(f"Testing GROBID extraction on: {pdf_path.name}")
    print("=" * 70)

    # Initialize GROBID client
    grobid = GrobidClient()

    # Check if available
    if not grobid.is_available(verbose=True):
        print("\n❌ GROBID not available. Start it with: docker start grobid")
        return

    print("\n✅ GROBID available")
    print("\n⏳ Processing PDF...")
    print("   (This may take 20-60 seconds for the whole PDF)")

    # Test with full PDF (no page limit) to see what GROBID gets
    metadata = grobid.extract_metadata(pdf_path, max_pages=0, handle_rotation=False)

    if metadata:
        print("\n" + "=" * 70)
        print("✅ GROBID EXTRACTION RESULTS")
        print("=" * 70)

        print(f"\nDocument Type: {metadata.get('document_type', 'unknown')}")
        print(f"Extraction Method: {metadata.get('extraction_method', 'unknown')}")
        print(f"Extraction Note: {metadata.get('extraction_note', 'N/A')}")

        print("\nChapter Metadata:")
        print(f"  Title: {metadata.get('title', 'N/A')}")

        authors = metadata.get("authors", [])
        if authors:
            print(f"  Authors: {', '.join(authors)}")

        print(f"  Year: {metadata.get('year', 'N/A')}")
        print(f"  DOI: {metadata.get('doi', 'N/A')}")
        print(f"  Pages: {metadata.get('pages', 'N/A')}")
        print(f"  Language: {metadata.get('language', 'N/A')}")

        print("\nConference/Event Metadata:")
        print(f"  Conference: {metadata.get('conference', 'N/A')}")

        print("\nPublication Metadata:")
        print(f"  Publisher: {metadata.get('publisher', 'N/A')}")
        print(f"  Journal (might be book/conference title): {metadata.get('journal', 'N/A')}")

        keywords = metadata.get("keywords", [])
        if keywords:
            print(f"  Keywords: {', '.join(keywords[:10])}")

        abstract = metadata.get("abstract", "")
        if abstract:
            print("\nAbstract (first 200 chars):")
            print(f"  {abstract[:200]}...")

        # Show all fields
        print("\n" + "=" * 70)
        print("ALL METADATA FIELDS:")
        print("=" * 70)
        for key, value in metadata.items():
            if isinstance(value, list):
                print(f"  {key}: {value}")
            elif isinstance(value, str) and len(value) > 100:
                print(f"  {key}: {value[:100]}...")
            else:
                print(f"  {key}: {value}")

    else:
        print("\n❌ GROBID extraction failed")

    # Cleanup
    grobid.cleanup_temp_files()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python grobid_extraction_demo.py <pdf_path>")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    run_grobid_extraction(pdf_path)


if __name__ == "__main__":
    main()

