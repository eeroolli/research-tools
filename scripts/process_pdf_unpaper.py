#!/usr/bin/env python3
"""
Process PDF with unpaper to clean scanned pages.

Usage:
    python process_pdf_unpaper.py <input.pdf> [output.pdf]
    
If output.pdf is not specified, creates <input>_unpaper.pdf in the same directory.
"""

import sys
import subprocess
import tempfile
import shutil
from pathlib import Path


def check_dependencies():
    """Check if required tools are available."""
    missing = []
    
    for tool in ['pdftoppm', 'unpaper', 'convert']:
        if not shutil.which(tool):
            missing.append(tool)
    
    if missing:
        print("Error: Missing required tools:")
        for tool in missing:
            print(f"  - {tool}")
        print("\nInstall with:")
        print("  sudo apt-get install poppler-utils unpaper imagemagick")
        return False
    
    return True


def process_pdf_with_unpaper(input_pdf: Path, output_pdf: Path = None) -> bool:
    """Process PDF with unpaper to clean scanned pages.
    
    Args:
        input_pdf: Path to input PDF
        output_pdf: Path to output PDF (default: input_unpaper.pdf)
        
    Returns:
        True if successful, False otherwise
    """
    if not input_pdf.exists():
        print(f"Error: Input PDF not found: {input_pdf}")
        return False
    
    if output_pdf is None:
        output_pdf = input_pdf.parent / f"{input_pdf.stem}_unpaper.pdf"
    
    # Create temporary directory for processing
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        
        print(f"Processing {input_pdf.name}...")
        print(f"Output will be: {output_pdf.name}")
        
        # Step 1: Convert PDF to PNG images
        print("\n1/3 Converting PDF to images...")
        try:
            result = subprocess.run(
                ['pdftoppm', '-png', '-r', '300', str(input_pdf), str(tmp_path / 'page')],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error converting PDF to images: {e}")
            print(f"stderr: {e.stderr}")
            return False
        
        # Find all page images
        page_images = sorted(tmp_path.glob('page-*.png'))
        if not page_images:
            print("Error: No page images generated")
            return False
        
        print(f"  Found {len(page_images)} pages")
        
        # Step 2: Process each image with unpaper
        print("\n2/3 Processing images with unpaper...")
        cleaned_images = []
        
        for i, img_path in enumerate(page_images, 1):
            cleaned_path = tmp_path / f"{img_path.stem}_clean.png"
            
            try:
                result = subprocess.run(
                    ['unpaper', '--overwrite', str(img_path), str(cleaned_path)],
                    check=True,
                    capture_output=True,
                    text=True
                )
                cleaned_images.append(cleaned_path)
                print(f"  Page {i}/{len(page_images)}: cleaned", end='\r')
            except subprocess.CalledProcessError as e:
                print(f"\nError processing page {i}: {e}")
                print(f"stderr: {e.stderr}")
                # Continue with other pages
        
        print(f"\n  Processed {len(cleaned_images)} pages")
        
        if not cleaned_images:
            print("Error: No pages were successfully processed")
            return False
        
        # Step 3: Convert cleaned images back to PDF
        print("\n3/3 Converting images back to PDF...")
        try:
            # Sort cleaned images to ensure correct order
            cleaned_images_sorted = sorted(cleaned_images)
            
            result = subprocess.run(
                ['convert'] + [str(img) for img in cleaned_images_sorted] + [str(output_pdf)],
                check=True,
                capture_output=True,
                text=True
            )
        except subprocess.CalledProcessError as e:
            print(f"Error creating output PDF: {e}")
            print(f"stderr: {e.stderr}")
            return False
        
        # Check output file size
        if output_pdf.exists():
            size_mb = output_pdf.stat().st_size / (1024 * 1024)
            print(f"\n✅ Success! Output PDF: {output_pdf.name} ({size_mb:.1f} MB)")
            return True
        else:
            print("Error: Output PDF was not created")
            return False


def main():
    if len(sys.argv) < 2:
        print("Usage: process_pdf_unpaper.py <input.pdf> [output.pdf]")
        sys.exit(1)
    
    if not check_dependencies():
        sys.exit(1)
    
    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    success = process_pdf_with_unpaper(input_pdf, output_pdf)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()

