#!/usr/bin/env python3
"""
Manual diagnostic script for handwritten note detection.

This was originally `tests/test_handwritten_detection.py` but has been moved
out of the automated test suite. Use it as a CLI tool instead of via pytest.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor


def run_handwritten_detection() -> None:
    """Run handwritten note detection against the example file."""

    # Example file path (Windows format)
    test_file = Path(r"G:\My Drive\publications\Ytrehus_2000_Myter_i_forskning_om_innvandrere_scan.pdf")

    # Also try WSL format
    test_file_wsl = Path("/mnt/g/My Drive/publications/Ytrehus_2000_Myter_i_forskning_om_innvandrere_scan.pdf")

    # Check which path exists
    if test_file.exists():
        pdf_path = test_file
        print(f"✅ Found file (Windows path): {pdf_path}")
    elif test_file_wsl.exists():
        pdf_path = test_file_wsl
        print(f"✅ Found file (WSL path): {pdf_path}")
    else:
        print("❌ File not found at either location:")
        print(f"   Windows: {test_file}")
        print(f"   WSL: {test_file_wsl}")
        return

    # Initialize processor
    processor = PaperMetadataProcessor()

    # Test detection method
    print("\n" + "=" * 80)
    print("Testing handwritten note detection...")
    print("=" * 80)

    is_handwritten = processor._check_if_handwritten_note(pdf_path, page_offset=0, max_pages_to_check=2)  # type: ignore[attr-defined]

    print(f"\n📊 Detection Result:")
    print(f"   Detected as handwritten note: {is_handwritten}")

    # Check threshold
    threshold = processor._read_handwritten_threshold_from_config()  # type: ignore[attr-defined]
    print(f"   Threshold: {threshold} characters")

    # Extract text to show what was found
    print(f"\n📄 Extracting text from first 2 pages...")
    try:
        import pdfplumber

        with pdfplumber.open(pdf_path) as pdf:
            total_chars = 0
            for i in range(min(2, len(pdf.pages))):
                page_text = pdf.pages[i].extract_text() or ""
                chars = len(page_text.strip())
                total_chars += chars
                print(f"   Page {i+1}: {chars} characters")
                if chars > 0:
                    preview = page_text.strip()[:100].replace("\n", " ")
                    print(f"      Preview: {preview}...")

            avg_chars = total_chars / min(2, len(pdf.pages)) if len(pdf.pages) > 0 else 0
            print(f"\n   Total characters (first 2 pages): {total_chars}")
            print(f"   Average per page: {avg_chars:.1f}")
            print(f"   Below threshold ({threshold}): {avg_chars < threshold}")
    except Exception as e:  # pragma: no cover - diagnostic script
        print(f"   ⚠️  Error extracting text: {e}")

    # Test full processing (should detect and skip Ollama)
    print("\n" + "=" * 80)
    print("Testing full processing workflow...")
    print("=" * 80)

    result = processor.process_pdf(pdf_path, use_ollama_fallback=True, page_offset=0)

    print(f"\n📊 Processing Result:")
    print(f"   Method: {result.get('method')}")
    print(f"   Success: {result.get('success')}")
    print(f"   Document type: {result.get('metadata', {}).get('document_type', 'N/A')}")
    print(f"   Processing time: {result.get('processing_time_seconds', 0):.2f}s")

    if result.get("method") == "handwritten_note_detected":
        print("\n✅ SUCCESS: Handwritten note correctly detected and Ollama skipped!")
    else:
        print(f"\n⚠️  WARNING: Expected 'handwritten_note_detected' but got '{result.get('method')}'")


if __name__ == "__main__":
    run_handwritten_detection()

