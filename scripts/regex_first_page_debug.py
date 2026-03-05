#!/usr/bin/env python3
"""
Debug script: run regex author extraction on the FIRST PAGE ONLY of a PDF.
Use this to verify what text is on page 1 and which authors the regex finds.
Usage: python scripts/regex_first_page_debug.py <path_to_pdf>
"""

import sys
from pathlib import Path

# Add project root so shared_tools is importable
project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))


def main():
    if len(sys.argv) < 2:
        print("Usage: python regex_first_page_debug.py <path_to_pdf>")
        print(
            "Example: python scripts/regex_first_page_debug.py /mnt/i/FraScanner/papers/EN_20260304-110953_001_double.pdf"
        )
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"File not found: {pdf_path}")
        sys.exit(1)

    import pdfplumber
    from shared_tools.utils.author_extractor import AuthorExtractor

    print("=" * 60)
    print("First page only (page index 0)")
    print("=" * 60)

    with pdfplumber.open(pdf_path) as pdf:
        if len(pdf.pages) == 0:
            print("No pages in PDF.")
            sys.exit(1)
        page0 = pdf.pages[0]
        first_page_text = page0.extract_text() or ""

    print(f"\n--- Extracted text length: {len(first_page_text)} chars ---\n")
    print(first_page_text[:4000])  # First 4000 chars so we see most of the page
    if len(first_page_text) > 4000:
        print("\n... [truncated] ...")

    print("\n" + "=" * 60)
    print("Authors from AuthorExtractor.extract_authors_simple(first_page_text)")
    print("=" * 60)

    regex_authors = AuthorExtractor.extract_authors_simple(first_page_text)
    print(f"Count: {len(regex_authors)}")
    for i, name in enumerate(regex_authors, 1):
        print(f"  {i}. {name}")

    print("\nDone.")


if __name__ == "__main__":
    main()
