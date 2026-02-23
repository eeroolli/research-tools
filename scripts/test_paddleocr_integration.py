#!/usr/bin/env python3
"""
PaddleOCR Integration Test Script

Tests complete workflow including:
- Client → API → Renaming
- Multiple PDFs
- Network access
- Performance benchmarks
"""

import sys
import argparse
import time
from pathlib import Path
from typing import List, Dict
import subprocess

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.paddleocr_client import send_pdf_to_api, main as client_main


def test_client_workflow(api_url: str, pdf_path: Path, output_dir: Path = None) -> bool:
    """Test complete client workflow.
    
    Args:
        api_url: API server URL
        pdf_path: Path to test PDF
        output_dir: Optional output directory
        
    Returns:
        success: bool
    """
    print(f"\n{'='*60}")
    print("Test: Complete Client Workflow")
    print(f"{'='*60}")
    
    if not pdf_path.exists():
        print(f"❌ Test PDF not found: {pdf_path}")
        return False
    
    try:
        # Use client script
        cmd = [
            sys.executable,
            'scripts/paddleocr_client.py',
            str(pdf_path),
            '--api-url', api_url
        ]
        
        if output_dir:
            cmd.extend(['--output-dir', str(output_dir)])
        
        print(f"Running: {' '.join(cmd)}")
        start_time = time.time()
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        elapsed = time.time() - start_time
        
        print(result.stdout)
        if result.stderr:
            print(result.stderr)
        
        if result.returncode == 0:
            print(f"✅ Client workflow completed in {elapsed:.1f}s")
            return True
        else:
            print(f"❌ Client workflow failed (exit code {result.returncode})")
            return False
    except subprocess.TimeoutExpired:
        print(f"❌ Client workflow timed out (>10 minutes)")
        return False
    except Exception as e:
        print(f"❌ Client workflow failed: {e}")
        return False


def test_multiple_pdfs(api_url: str, pdf_paths: List[Path], max_concurrent: int = 3) -> bool:
    """Test processing multiple PDFs.
    
    Args:
        api_url: API server URL
        pdf_paths: List of PDF paths
        max_concurrent: Maximum concurrent requests
        
    Returns:
        success: bool
    """
    print(f"\n{'='*60}")
    print(f"Test: Multiple PDFs ({len(pdf_paths)} files)")
    print(f"{'='*60}")
    
    if not pdf_paths:
        print("⚠️  No PDFs provided")
        return False
    
    results = []
    start_time = time.time()
    
    # Process PDFs (can be done sequentially or in parallel)
    for i, pdf_path in enumerate(pdf_paths, 1):
        if not pdf_path.exists():
            print(f"⚠️  Skipping {pdf_path.name} (not found)")
            continue
        
        print(f"\nProcessing {i}/{len(pdf_paths)}: {pdf_path.name}")
        success, metadata = send_pdf_to_api(pdf_path, api_url, with_metadata=True)
        results.append((pdf_path.name, success, metadata))
        
        if success:
            print(f"  ✅ Success")
            if metadata:
                print(f"     Language: {metadata.get('language', 'unknown')}")
                print(f"     Two-up: {metadata.get('is_two_up', False)}")
        else:
            print(f"  ❌ Failed")
    
    elapsed = time.time() - start_time
    successful = sum(1 for _, success, _ in results if success)
    
    print(f"\n{'='*60}")
    print(f"Results: {successful}/{len(results)} successful")
    print(f"Total time: {elapsed:.1f}s")
    print(f"Average time per PDF: {elapsed/len(results):.1f}s")
    
    return successful == len(results)


def benchmark_performance(api_url: str, pdf_path: Path, iterations: int = 3) -> Dict:
    """Benchmark API performance.
    
    Args:
        api_url: API server URL
        pdf_path: Path to test PDF
        iterations: Number of iterations
        
    Returns:
        performance_metrics: Dict
    """
    print(f"\n{'='*60}")
    print(f"Benchmark: Performance ({iterations} iterations)")
    print(f"{'='*60}")
    
    if not pdf_path.exists():
        print(f"❌ Test PDF not found: {pdf_path}")
        return {}
    
    times = []
    
    for i in range(iterations):
        print(f"Iteration {i+1}/{iterations}...")
        start_time = time.time()
        success, _ = send_pdf_to_api(pdf_path, api_url, with_metadata=True)
        elapsed = time.time() - start_time
        
        if success:
            times.append(elapsed)
            print(f"  Time: {elapsed:.1f}s")
        else:
            print(f"  ❌ Failed")
    
    if times:
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        print(f"\nPerformance metrics:")
        print(f"  Average: {avg_time:.1f}s")
        print(f"  Min: {min_time:.1f}s")
        print(f"  Max: {max_time:.1f}s")
        
        return {
            'average': avg_time,
            'min': min_time,
            'max': max_time,
            'iterations': len(times)
        }
    else:
        print("❌ All iterations failed")
        return {}


def main():
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="PaddleOCR Integration Tests"
    )
    parser.add_argument(
        '--api-url',
        type=str,
        default='http://localhost:8080',
        help='API server URL (default: http://localhost:8080)'
    )
    parser.add_argument(
        '--test-pdf',
        type=Path,
        default=None,
        help='Test PDF file for workflow and benchmark tests'
    )
    parser.add_argument(
        '--test-pdfs',
        type=str,
        default=None,
        help='Comma-separated list of PDF paths for multiple PDF test'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Output directory for processed PDFs'
    )
    parser.add_argument(
        '--benchmark',
        action='store_true',
        help='Run performance benchmark'
    )
    parser.add_argument(
        '--iterations',
        type=int,
        default=3,
        help='Number of benchmark iterations (default: 3)'
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("PaddleOCR Integration Test Suite")
    print("="*60)
    print(f"API URL: {args.api_url}")
    
    results = {}
    
    # Test 1: Complete client workflow
    if args.test_pdf:
        results['workflow'] = test_client_workflow(args.api_url, args.test_pdf, args.output_dir)
    
    # Test 2: Multiple PDFs
    if args.test_pdfs:
        pdf_paths = [Path(p.strip()) for p in args.test_pdfs.split(',')]
        results['multiple'] = test_multiple_pdfs(args.api_url, pdf_paths)
    
    # Test 3: Performance benchmark
    if args.benchmark and args.test_pdf:
        results['benchmark'] = benchmark_performance(args.api_url, args.test_pdf, args.iterations)
    
    # Summary
    print(f"\n{'='*60}")
    print("Integration Test Summary")
    print(f"{'='*60}")
    for test_name, result in results.items():
        if isinstance(result, bool):
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"  {test_name:20s}: {status}")
        else:
            print(f"  {test_name:20s}: {result}")
    
    all_passed = all(r for r in results.values() if isinstance(r, bool))
    if all_passed:
        print("\n✅ All integration tests passed!")
        return 0
    else:
        print("\n❌ Some integration tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())

