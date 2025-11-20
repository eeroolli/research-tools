#!/usr/bin/env python3
"""
Test script for PDF rotation handling with GROBID.

This script demonstrates how the new PDF rotation detection and correction
works with GROBID for processing scanned book chapters that are rotated 90 degrees.
"""

import sys
import logging
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from shared_tools.api.grobid_client import GrobidClient
from shared_tools.pdf.pdf_rotation_handler import PDFRotationHandler

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def test_pdf_rotation(pdf_path: Path):
    """Test PDF rotation detection and correction."""
    
    if not pdf_path.exists():
        logger.error(f"PDF not found: {pdf_path}")
        return False
    
    logger.info(f"Testing PDF rotation handling: {pdf_path.name}")
    
    # Test 1: Direct rotation detection
    logger.info("\n=== Test 1: Direct Rotation Detection ===")
    rotation_handler = PDFRotationHandler()
    rotation = rotation_handler.detect_pdf_rotation(pdf_path)
    
    if rotation:
        logger.info(f"✅ Detected rotation needed: {rotation}")
    else:
        logger.info("ℹ️  No rotation correction needed")
    
    # Test 2: GROBID with rotation handling
    logger.info("\n=== Test 2: GROBID with Rotation Handling ===")
    grobid_client = GrobidClient()
    
    if not grobid_client.is_available():
        logger.error("❌ GROBID server not available")
        return False
    
    logger.info("✅ GROBID server available")
    
    # Extract metadata with rotation handling enabled
    logger.info("Extracting metadata with rotation handling...")
    metadata = grobid_client.extract_metadata(pdf_path, handle_rotation=True)
    
    if metadata:
        logger.info("✅ GROBID extraction successful:")
        for key, value in metadata.items():
            if isinstance(value, list):
                logger.info(f"  {key}: {', '.join(value)}")
            else:
                logger.info(f"  {key}: {value}")
    else:
        logger.error("❌ GROBID extraction failed")
        return False
    
    # Cleanup
    grobid_client.cleanup_temp_files()
    
    return True

def main():
    """Main function."""
    if len(sys.argv) != 2:
        print("Usage: python test_pdf_rotation.py <pdf_path>")
        print("\nThis script tests PDF rotation handling for GROBID processing.")
        print("It's designed to work with scanned book chapters that are rotated 90 degrees.")
        sys.exit(1)
    
    pdf_path = Path(sys.argv[1])
    
    print("=" * 80)
    print("PDF ROTATION HANDLING TEST")
    print("=" * 80)
    print(f"Testing: {pdf_path.name}")
    print(f"Purpose: Handle rotated PDFs (90° turned scanned book chapters)")
    print("=" * 80)
    
    success = test_pdf_rotation(pdf_path)
    
    if success:
        print("\n✅ Test completed successfully!")
        print("\nThe PDF rotation handling should now work with your GROBID processing.")
        print("Rotated PDFs will be automatically detected and corrected before sending to GROBID.")
    else:
        print("\n❌ Test failed!")
        print("Check the logs above for error details.")

if __name__ == "__main__":
    main()
