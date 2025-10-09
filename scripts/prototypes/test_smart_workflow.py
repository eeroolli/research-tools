#!/usr/bin/env python3
"""
Test the smart paper processing workflow with multiple PDFs.

Compares processing times and success rates.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.metadata.paper_processor import PaperMetadataProcessor


def main():
    scanner_dir = Path("/mnt/i/FraScanner")
    
    # Test with various document types
    test_files = [
        # Journal article with DOI (should be fast)
        "Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf",
        # Technical report (may not have DOI)
        "Anand et al._GPT4All Training an Assistant-style Chatbot with Large Scale Data Distillation from GPT-3.5-Turbo.pdf",
        # Legal document (no DOI expected)
        "2012_CHARTER OF FUNDAMENTAL RIGHTS OF THE EUROPEAN UNION.pdf",
        # Academic paper
        "Agerström et al._2012_Warm and Competent Hassan = Cold and Incompetent Eric A Harsh Equation of Real-Life Hiring Discrimi.pdf",
    ]
    
    processor = PaperMetadataProcessor(email="test@example.com")
    
    print("=" * 80)
    print("SMART WORKFLOW TEST - Multiple Document Types")
    print("=" * 80)
    
    results = []
    for filename in test_files:
        pdf_path = scanner_dir / filename
        if pdf_path.exists():
            result = processor.process_pdf(pdf_path, use_ollama_fallback=False)
            results.append(result)
        else:
            print(f"\n⚠️  File not found: {filename}")
    
    # Summary
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    
    successful = [r for r in results if r['success']]
    print(f"\nTotal processed: {len(results)}")
    print(f"Successful: {len(successful)}")
    print(f"Failed: {len(results) - len(successful)}")
    
    print("\nBy method:")
    by_method = {}
    for r in results:
        method = r['method'] or 'none'
        by_method[method] = by_method.get(method, 0) + 1
    for method, count in by_method.items():
        print(f"  {method}: {count}")
    
    print("\nProcessing times:")
    for r in results:
        status = "✅" if r['success'] else "❌"
        print(f"  {status} {r['file'][:60]}: {r['processing_time_seconds']:.1f}s ({r['method']})")
    
    avg_time = sum(r['processing_time_seconds'] for r in results) / len(results) if results else 0
    print(f"\nAverage time: {avg_time:.1f} seconds")
    print("\nNote: With Ollama fallback for documents without DOI, average would be 60-120 seconds")


if __name__ == "__main__":
    main()
