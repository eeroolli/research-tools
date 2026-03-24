#!/usr/bin/env python3
"""
Manual diagnostic script to extract years from PDFs using the IdentifierExtractor.

This was originally `tests/test_year_extraction.py` but has been moved out of
the automated test suite. Use it as:

    python scripts/analysis/year_extraction_demo.py <path_to_pdf>
"""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.utils.identifier_extractor import IdentifierExtractor
import pdfplumber


def run_year_extraction(pdf_path: Path) -> None:
    """Extract and display years found in a PDF."""
    print("\n" + "=" * 80)
    print(f"Testing: {pdf_path.name}")
    print("=" * 80)

    try:
        # Extract text from first page
        with pdfplumber.open(pdf_path) as pdf:
            if len(pdf.pages) == 0:
                print("❌ PDF has no pages")
                return

            first_page = pdf.pages[0]
            text = first_page.extract_text()

            if not text:
                print("❌ No text extracted from first page")
                return

            # Show first 500 chars for context
            print("\nFirst page text (first 500 chars):")
            print("-" * 80)
            print(text[:500])
            print("-" * 80)

            # Extract years
            all_years = IdentifierExtractor.extract_years(text)
            best_year = IdentifierExtractor.extract_best_year(text)

            print(f"\n📅 All years found: {all_years}")
            print(f"✅ Best year (publication year): {best_year}")

            if all_years and not best_year:
                print(f"⚠️  Note: Found {len(all_years)} year(s) but all were filtered out as body text")

            if best_year:
                # Show context around best year
                year_pos = text.find(f"({best_year})")
                if year_pos == -1:
                    year_pos = text.find(f"© {best_year}")
                if year_pos == -1:
                    year_pos = text.find(f"©{best_year}")

                if year_pos >= 0:
                    context_start = max(0, year_pos - 100)
                    context_end = min(len(text), year_pos + 100)
                    context = text[context_start:context_end]
                    print("\nContext around best year:")
                    print("-" * 80)
                    print(context)
                    print("-" * 80)

    except Exception as e:  # pragma: no cover - diagnostic script
        print(f"❌ Error processing PDF: {e}")
        import traceback

        traceback.print_exc()


def main() -> None:
    """Main function to test year extraction."""
    if len(sys.argv) > 1:
        pdf_path = Path(sys.argv[1])
        if not (pdf_path.exists() and pdf_path.suffix.lower() == ".pdf"):
            print(f"❌ File not found or not a PDF: {pdf_path}")
            sys.exit(1)
        run_year_extraction(pdf_path)
        return

    # Look for PDFs in common locations
    test_dirs = [
        Path("/mnt/i/FraScanner/papers/failed"),
        Path("papers/failed"),
        Path("papers"),
        Path("data/papers"),
        Path("."),
    ]

    pdf_files = []
    for test_dir in test_dirs:
        if test_dir.exists():
            pdfs = list(test_dir.glob("*.pdf"))
            if pdfs:
                pdf_files.extend(pdfs)
                print(f"Found {len(pdfs)} PDF(s) in {test_dir}")

    if not pdf_files:
        print("No PDF files found in common directories.")
        print("\nUsage: python year_extraction_demo.py <path_to_pdf>")
        print("Or place PDFs in: papers/failed/, papers/, or data/papers/")
        return

    # Test up to 10 PDFs
    for candidate in pdf_files[:10]:
        run_year_extraction(candidate)


if __name__ == "__main__":
    main()

