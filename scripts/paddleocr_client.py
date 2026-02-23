#!/usr/bin/env python3
"""
PaddleOCR API Client

Sends PDF files to PaddleOCR API server for OCR processing.
Handles file renaming based on detected language and orientation.

Usage:
    python scripts/paddleocr_client.py <input_pdf> [--output output.pdf] [--api-url http://localhost:8080]
"""

import sys
import argparse
import requests
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.paddleocr_rename import rename_pdf_with_metadata


def send_pdf_to_api(
    pdf_path: Path,
    api_url: str,
    with_metadata: bool = True
) -> tuple[Optional[Path], Optional[dict]]:
    """Send PDF to PaddleOCR API and save result.
    
    Args:
        pdf_path: Path to input PDF
        api_url: API server URL
        with_metadata: Whether to request metadata (language, orientation)
        
    Returns:
        Tuple of (output_pdf_path, metadata_dict) or (None, None) on error
    """
    endpoint = '/ocr_with_metadata' if with_metadata else '/ocr'
    url = f"{api_url.rstrip('/')}{endpoint}"
    
    print(f"Sending PDF to API: {url}")
    print(f"  File: {pdf_path.name}")
    
    try:
        with open(pdf_path, 'rb') as f:
            files = {'file': (pdf_path.name, f, 'application/pdf')}
            response = requests.post(url, files=files, timeout=300)  # 5 minute timeout
        
        if response.status_code != 200:
            print(f"❌ API error: {response.status_code}")
            try:
                error_data = response.json()
                print(f"   {error_data.get('error', 'Unknown error')}")
            except:
                print(f"   {response.text[:200]}")
            return None, None
        
        # Extract metadata from headers if available
        metadata = {}
        if with_metadata:
            metadata['language'] = response.headers.get('X-OCR-Language', 'unknown')
            metadata['language_prefix'] = response.headers.get('X-OCR-Language-Prefix', '')
            metadata['is_two_up'] = response.headers.get('X-OCR-Is-Two-Up', 'false').lower() == 'true'
            metadata['aspect_ratio'] = float(response.headers.get('X-OCR-Aspect-Ratio', '0'))
        
        # Save OCR'd PDF
        output_path = pdf_path.parent / f"ocr_{pdf_path.name}"
        with open(output_path, 'wb') as f:
            f.write(response.content)
        
        print(f"✅ OCR'd PDF saved: {output_path.name}")
        if metadata:
            print(f"   Language: {metadata.get('language', 'unknown')}")
            print(f"   Two-up: {metadata.get('is_two_up', False)}")
        
        return output_path, metadata
        
    except requests.exceptions.RequestException as e:
        print(f"❌ Network error: {e}")
        return None, None
    except Exception as e:
        print(f"❌ Error: {e}")
        return None, None


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Send PDF to PaddleOCR API for OCR processing"
    )
    parser.add_argument(
        'input_pdf',
        type=Path,
        help='Input PDF file'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help='Output PDF path (default: ocr_<input_name>.pdf)'
    )
    parser.add_argument(
        '--api-url',
        type=str,
        default='http://localhost:8080',
        help='PaddleOCR API server URL (default: http://localhost:8080)'
    )
    parser.add_argument(
        '--no-rename',
        action='store_true',
        help='Do not rename file with language/orientation info'
    )
    parser.add_argument(
        '--output-dir',
        type=Path,
        default=None,
        help='Output directory for renamed file (if not specified, uses input directory)'
    )
    
    args = parser.parse_args()
    
    # Validate input
    if not args.input_pdf.exists():
        print(f"❌ Error: File not found: {args.input_pdf}")
        return 1
    
    if not args.input_pdf.suffix.lower() == '.pdf':
        print(f"❌ Error: File must be a PDF: {args.input_pdf}")
        return 1
    
    # Check API health
    try:
        health_url = f"{args.api_url.rstrip('/')}/health"
        response = requests.get(health_url, timeout=5)
        if response.status_code != 200:
            print(f"⚠️  Warning: API health check failed (status {response.status_code})")
            print(f"   Continuing anyway...")
    except Exception as e:
        print(f"⚠️  Warning: Could not check API health: {e}")
        print(f"   Continuing anyway...")
    
    # Send PDF to API
    output_path, metadata = send_pdf_to_api(args.input_pdf, args.api_url, with_metadata=True)
    
    if not output_path:
        return 1
    
    # Rename file if metadata available and not disabled
    if not args.no_rename and metadata:
        language = metadata.get('language')
        is_two_up = metadata.get('is_two_up', False)
        
        if language and language != 'unknown':
            final_path = rename_pdf_with_metadata(
                output_path,
                language=language,
                is_two_up=is_two_up,
                output_dir=args.output_dir
            )
            print(f"✅ Final file: {final_path.name}")
        else:
            print(f"⚠️  Language not detected, keeping original filename")
            final_path = output_path
    else:
        final_path = output_path
    
    # Move to output location if specified
    if args.output and final_path != args.output:
        final_path.rename(args.output)
        final_path = args.output
        print(f"✅ Moved to: {args.output}")
    
    print(f"\n✅ Processing complete: {final_path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())

