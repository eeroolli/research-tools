#!/usr/bin/env python3
"""
Minimal scaffold for paper processing.

- Reads a PDF path
- Extracts first page text (if PyPDF2 is available)
- Calls shared identifier extractor stub
- Prints structured identifiers (JSON)

This is a placeholder to make Phase 4 work obvious without changing current behavior.
"""
from __future__ import annotations

import sys
import json
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PyPDF2 import PdfReader  # optional
except Exception:
    PdfReader = None  # type: ignore

from shared_tools.metadata.identifier_extractor import (
    extract_from_first_page_text,
    extract_with_ollama,
)


def extract_first_page_text(pdf_path: Path) -> str:
    """Extract first page text using PyPDF2 if available."""
    if not PdfReader:
        return ""
    try:
        reader = PdfReader(str(pdf_path))
        if not reader.pages:
            return ""
        return reader.pages[0].extract_text() or ""
    except Exception:
        return ""


def main():
    if len(sys.argv) < 2:
        print("Usage: python scripts/process_scanned_papers.py <path_to_pdf> [--ollama]")
        sys.exit(1)

    pdf_path = Path(sys.argv[1]).resolve()
    use_ollama = "--ollama" in sys.argv[2:]

    if not pdf_path.exists():
        print(json.dumps({"error": f"File not found: {pdf_path}"}, ensure_ascii=False))
        sys.exit(2)

    ocr_text = extract_first_page_text(pdf_path)

    if use_ollama:
        identifiers = extract_with_ollama(ocr_text)
    else:
        identifiers = extract_from_first_page_text(ocr_text)

    print(json.dumps({
        "file": str(pdf_path),
        "identifiers": {
            "doi": identifiers.doi,
            "title": identifiers.title,
            "authors": identifiers.authors,
            "journal": identifiers.journal,
            "year": identifiers.year,
            "language": identifiers.language,
            "confidence": identifiers.confidence,
            "extras": identifiers.extras,
        }
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


