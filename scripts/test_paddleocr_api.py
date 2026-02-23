#!/usr/bin/env python3
"""
PaddleOCR API Test Script

Tests the PaddleOCR API server functionality including:
- Health checks
- Basic OCR processing
- Language detection
- Orientation detection
- Error handling
"""

import sys
import argparse
import requests
import time
from pathlib import Path
from typing import Dict, Optional, Tuple

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_health(api_url: str) -> Tuple[bool, Dict]:
    """Test health endpoint.
    
    Args:
        api_url: API server URL
        
    Returns:
        Tuple of (success: bool, response_data: dict)
    """
    print(f"\n{'='*60}")
    print("Test 1: Health Check")
    print(f"{'='*60}")
    
    try:
        url = f"{api_url.rstrip('/')}/health"
        print(f"Testing: {url}")
        response = requests.get(url, timeout=5)
        
        if response.status_code == 200:
            data = response.json()
            print(f"✅ Health check passed")
            print(f"   Status: {data.get('status')}")
            print(f"   Service: {data.get('service')}")
            print(f"   GPU available: {data.get('gpu_available', 'unknown')}")
            return True, data
        else:
            print(f"❌ Health check failed: Status {response.status_code}")
            return False, {}
    except requests.exceptions.RequestException as e:
        print(f"❌ Health check failed: {e}")
        return False, {}


def test_basic_ocr(api_url: str, pdf_path: Path) -> Tuple[bool, Optional[Path]]:
    """Test basic OCR endpoint.
    
    Args:
        api_url: API server URL
        pdf_path: Path to test PDF
        
    Returns:
        Tuple of (success: bool, output_pdf_path: Optional[Path])
    """
    print(f"\n{'='*60}")
    print("Test 2: Basic OCR Processing")
    print(f"{'='*60}")
    
    if not pdf_path.exists():
        print(f"❌ Test PDF not found: {pdf_path}")
        return False, None
    
    try:
        url = f"{api_url.rstrip('/')}/ocr"
        print(f"Testing: {url}")
        print(f"Input PDF: {pdf_path.name} ({pdf_path.stat().st_size / 1024:.1f} KB)")
        
        start_time = time.time()
        with open(pdf_path, 'rb') as f:
            files = {'file': (pdf_path.name, f, 'application/pdf')}
            response = requests.post(url, files=files, timeout=300)
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            output_path = pdf_path.parent / f"test_ocr_{pdf_path.name}"
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            output_size = output_path.stat().st_size
            print(f"✅ OCR processing completed")
            print(f"   Output: {output_path.name} ({output_size / 1024:.1f} KB)")
            print(f"   Processing time: {elapsed:.1f}s")
            print(f"   Output size: {output_size / pdf_path.stat().st_size * 100:.1f}% of input")
            return True, output_path
        else:
            print(f"❌ OCR processing failed: Status {response.status_code}")
            try:
                error_data = response.json()
                print(f"   Error: {error_data.get('error', 'Unknown error')}")
            except:
                print(f"   Response: {response.text[:200]}")
            return False, None
    except requests.exceptions.RequestException as e:
        print(f"❌ OCR processing failed: {e}")
        return False, None


def test_ocr_with_metadata(api_url: str, pdf_path: Path) -> Tuple[bool, Optional[Dict], Optional[Path]]:
    """Test OCR with metadata endpoint.
    
    Args:
        api_url: API server URL
        pdf_path: Path to test PDF
        
    Returns:
        Tuple of (success: bool, metadata: Optional[Dict], output_pdf_path: Optional[Path])
    """
    print(f"\n{'='*60}")
    print("Test 3: OCR with Metadata")
    print(f"{'='*60}")
    
    if not pdf_path.exists():
        print(f"❌ Test PDF not found: {pdf_path}")
        return False, None, None
    
    try:
        url = f"{api_url.rstrip('/')}/ocr_with_metadata"
        print(f"Testing: {url}")
        print(f"Input PDF: {pdf_path.name}")
        
        start_time = time.time()
        with open(pdf_path, 'rb') as f:
            files = {'file': (pdf_path.name, f, 'application/pdf')}
            response = requests.post(url, files=files, timeout=300)
        
        elapsed = time.time() - start_time
        
        if response.status_code == 200:
            # Extract metadata from headers
            metadata = {
                'language': response.headers.get('X-OCR-Language', 'unknown'),
                'language_prefix': response.headers.get('X-OCR-Language-Prefix', ''),
                'is_two_up': response.headers.get('X-OCR-Is-Two-Up', 'false').lower() == 'true',
                'aspect_ratio': float(response.headers.get('X-OCR-Aspect-Ratio', '0'))
            }
            
            output_path = pdf_path.parent / f"test_metadata_{pdf_path.name}"
            with open(output_path, 'wb') as f:
                f.write(response.content)
            
            print(f"✅ OCR with metadata completed")
            print(f"   Processing time: {elapsed:.1f}s")
            print(f"   Detected language: {metadata['language']}")
            print(f"   Language prefix: {metadata['language_prefix']}")
            print(f"   Is two-up: {metadata['is_two_up']}")
            print(f"   Aspect ratio: {metadata['aspect_ratio']:.2f}")
            print(f"   Output: {output_path.name}")
            return True, metadata, output_path
        else:
            print(f"❌ OCR with metadata failed: Status {response.status_code}")
            return False, None, None
    except requests.exceptions.RequestException as e:
        print(f"❌ OCR with metadata failed: {e}")
        return False, None, None


def test_error_handling(api_url: str) -> bool:
    """Test error handling.
    
    Args:
        api_url: API server URL
        
    Returns:
        success: bool
    """
    print(f"\n{'='*60}")
    print("Test 4: Error Handling")
    print(f"{'='*60}")
    
    tests_passed = 0
    tests_total = 0
    
    # Test 1: No file provided
    tests_total += 1
    try:
        url = f"{api_url.rstrip('/')}/ocr"
        response = requests.post(url, timeout=5)
        if response.status_code == 400:
            print("✅ Test 4.1: No file provided - correct error (400)")
            tests_passed += 1
        else:
            print(f"❌ Test 4.1: Expected 400, got {response.status_code}")
    except Exception as e:
        print(f"❌ Test 4.1: Exception: {e}")
    
    # Test 2: Invalid file type
    tests_total += 1
    try:
        url = f"{api_url.rstrip('/')}/ocr"
        # Create a dummy text file
        test_file = Path("/tmp/test_invalid.txt")
        test_file.write_text("This is not a PDF")
        with open(test_file, 'rb') as f:
            files = {'file': ('test.txt', f, 'text/plain')}
            response = requests.post(url, files=files, timeout=5)
        test_file.unlink()
        
        if response.status_code == 400:
            print("✅ Test 4.2: Invalid file type - correct error (400)")
            tests_passed += 1
        else:
            print(f"❌ Test 4.2: Expected 400, got {response.status_code}")
    except Exception as e:
        print(f"❌ Test 4.2: Exception: {e}")
    
    print(f"\nError handling tests: {tests_passed}/{tests_total} passed")
    return tests_passed == tests_total


def main():
    """Main test function."""
    parser = argparse.ArgumentParser(
        description="Test PaddleOCR API server"
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
        help='Test PDF file (optional, for OCR tests)'
    )
    parser.add_argument(
        '--skip-ocr',
        action='store_true',
        help='Skip OCR tests (only test health)'
    )
    
    args = parser.parse_args()
    
    print("="*60)
    print("PaddleOCR API Test Suite")
    print("="*60)
    print(f"API URL: {args.api_url}")
    
    results = {
        'health': False,
        'basic_ocr': False,
        'metadata': False,
        'error_handling': False
    }
    
    # Test 1: Health check
    results['health'], _ = test_health(args.api_url)
    
    if not results['health']:
        print("\n❌ Health check failed - API server may not be running")
        print("   Start the server with: ./scripts/docker_paddleocr_start.sh")
        return 1
    
    # Test 2: Error handling (doesn't require PDF)
    results['error_handling'] = test_error_handling(args.api_url)
    
    # Test 3 & 4: OCR tests (require PDF)
    if not args.skip_ocr:
        if args.test_pdf and args.test_pdf.exists():
            results['basic_ocr'], ocr_output = test_basic_ocr(args.api_url, args.test_pdf)
            if ocr_output:
                results['metadata'], metadata, _ = test_ocr_with_metadata(args.api_url, args.test_pdf)
        else:
            print("\n⚠️  Skipping OCR tests - no test PDF provided")
            print("   Use --test-pdf <path> to test OCR functionality")
    
    # Summary
    print(f"\n{'='*60}")
    print("Test Summary")
    print(f"{'='*60}")
    for test_name, passed in results.items():
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {test_name:20s}: {status}")
    
    all_passed = all(results.values())
    if all_passed:
        print("\n✅ All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed")
        return 1


if __name__ == '__main__':
    sys.exit(main())

