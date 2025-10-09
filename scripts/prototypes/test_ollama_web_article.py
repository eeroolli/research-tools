#!/usr/bin/env python3
"""
Test Ollama extraction on web articles/news without DOI.

This tests the new workflow where URL triggers Ollama extraction.
"""

import sys
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor


def main():
    scanner_dir = Path("/mnt/i/FraScanner")
    
    # Test files with URLs but no DOI (web articles, news, blogs)
    test_files = [
        # NYT health article
        "Agrawal_2025_17 Ways to Cut Your Risk of Stroke, Dementia and Depression All at Once.pdf",
        # Opinion/news piece
        "Putnam and Reeves_2025_Boy Crisis of 2025, Meet the 'Boy Problem' of the 1900s.pdf",
    ]
    
    processor = PaperMetadataProcessor()  # Reads email from config
    
    print("=" * 80)
    print("OLLAMA WEB ARTICLE EXTRACTION TEST")
    print("Testing Ollama on web articles with URLs but no DOI")
    print("=" * 80)
    
    for filename in test_files:
        pdf_path = scanner_dir / filename
        if pdf_path.exists():
            result = processor.process_pdf(pdf_path, use_ollama_fallback=True)
            
            print("\n" + "=" * 80)
            print("EXTRACTION RESULT")
            print("=" * 80)
            print(f"File: {filename}")
            print(f"Success: {result['success']}")
            print(f"Method: {result['method']}")
            print(f"Time: {result.get('processing_time_seconds', 0):.1f}s")
            
            if result.get('metadata'):
                metadata = result['metadata']
                print(f"\nExtracted Metadata:")
                print(f"  Title: {metadata.get('title', 'N/A')}")
                print(f"  Authors: {metadata.get('authors', [])}")
                print(f"  Year: {metadata.get('year', 'N/A')}")
                print(f"  Document Type: {metadata.get('document_type', 'N/A')}")
                print(f"  URL: {metadata.get('url', 'N/A')}")
                print(f"  Publisher: {metadata.get('publisher', 'N/A')}")
                
                if metadata.get('has_hallucinations'):
                    print(f"\n⚠️  Hallucinations detected:")
                    for flag in metadata.get('confidence_flags', []):
                        print(f"    - {flag}")
                
                print(f"\nFull JSON:")
                print(json.dumps(metadata, indent=2))
            
            print("\n" + "=" * 80)
        else:
            print(f"\n⚠️  File not found: {filename}")


if __name__ == "__main__":
    main()
