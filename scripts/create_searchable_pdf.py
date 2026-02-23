#!/usr/bin/env python3
"""
Create Searchable PDFs from Scanned Documents

This script uses OCR engines (EasyOCR, PaddleOCR, or Nougat) to create searchable PDFs
by embedding invisible text layers while preserving the original scanned images.

Usage:
    python scripts/create_searchable_pdf.py <input_pdf> [--engine easyocr] [--output output.pdf] [--languages en,no,sv]
    
Options:
    --engine: OCR engine to use (easyocr, paddleocr) - default: easyocr
    --output: Output PDF path (default: input_ocr.pdf)
    --languages: Comma-separated language codes (default: en)
    --gpu: Use GPU acceleration (default: True)
    --cpu: Force CPU mode
"""

import sys
import logging
from pathlib import Path
from typing import List, Tuple, Optional
import argparse

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def create_searchable_pdf_easyocr(
    input_pdf: Path,
    output_pdf: Path,
    languages: List[str] = ['en'],
    use_gpu: bool = True
) -> bool:
    """Create searchable PDF using EasyOCR.
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path
        languages: List of language codes
        use_gpu: Whether to use GPU
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import easyocr
        import fitz  # PyMuPDF
        from pdf2image import convert_from_path
        from PIL import Image
        import numpy as np
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Install with: pip install easyocr PyMuPDF pdf2image pillow numpy")
        return False
    
    logger.info(f"Creating searchable PDF with EasyOCR...")
    logger.info(f"  Input: {input_pdf}")
    logger.info(f"  Output: {output_pdf}")
    logger.info(f"  Languages: {', '.join(languages)}")
    logger.info(f"  GPU: {use_gpu}")
    
    # Initialize EasyOCR reader
    logger.info("Initializing EasyOCR...")
    try:
        reader = easyocr.Reader(languages, gpu=use_gpu)
    except Exception as e:
        logger.error(f"Failed to initialize EasyOCR: {e}")
        return False
    
    # Convert PDF to images
    logger.info("Converting PDF to images...")
    try:
        images = convert_from_path(str(input_pdf), dpi=300)
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return False
    
    # Open PDF
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()
    
    logger.info(f"Processing {len(images)} pages...")
    
    for page_num, (image, orig_page) in enumerate(zip(images, doc)):
        logger.info(f"  Processing page {page_num + 1}/{len(images)}...")
        
        # Convert PIL Image to numpy array
        image_array = np.array(image)
        
        # Run EasyOCR
        results = reader.readtext(image_array)
        
        # Create new page with same dimensions
        new_page = new_doc.new_page(width=orig_page.rect.width, height=orig_page.rect.height)
        
        # Insert original page image
        # Render original page as image
        mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
        pix = orig_page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        new_page.insert_image(orig_page.rect, stream=img_data)
        
        # Add OCR text as invisible layer
        for bbox, text, confidence in results:
            if confidence < 30:  # Skip low-confidence detections
                continue
            
            # EasyOCR bbox format: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
            # Calculate bounding box center and size
            x_coords = [point[0] for point in bbox]
            y_coords = [point[1] for point in bbox]
            
            x_min, x_max = min(x_coords), max(x_coords)
            y_min, y_max = min(y_coords), max(y_coords)
            width = x_max - x_min
            height = y_max - y_min
            
            # Scale coordinates from image pixels to PDF points
            scale_x = orig_page.rect.width / image.width
            scale_y = orig_page.rect.height / image.height
            
            # Convert to PDF coordinates (origin at bottom-left)
            pdf_x = x_min * scale_x
            pdf_y = (image.height - y_max) * scale_y  # Flip Y coordinate
            
            # Estimate font size from height
            font_size = max(6, height * scale_y * 0.8)
            
            # Add invisible text (render_mode=3 = invisible)
            try:
                new_page.insert_text(
                    (pdf_x, pdf_y),
                    text,
                    fontsize=font_size,
                    render_mode=3  # Invisible text for searchability
                )
            except Exception as e:
                logger.debug(f"  Could not insert text '{text[:20]}...': {e}")
                continue
    
    # Save searchable PDF
    logger.info(f"Saving searchable PDF: {output_pdf}")
    new_doc.save(str(output_pdf))
    new_doc.close()
    doc.close()
    
    logger.info(f"✅ Searchable PDF created: {output_pdf}")
    return True


def create_searchable_pdf_paddleocr(
    input_pdf: Path,
    output_pdf: Path,
    languages: List[str] = ['en'],
    use_gpu: bool = True
) -> bool:
    """Create searchable PDF using PaddleOCR.
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path
        languages: List of language codes (PaddleOCR uses different codes)
        use_gpu: Whether to use GPU
        
    Returns:
        True if successful, False otherwise
    """
    try:
        from paddleocr import PaddleOCR
        import fitz  # PyMuPDF
        from pdf2image import convert_from_path
        import numpy as np
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        logger.error("Install with: pip install paddleocr PyMuPDF pdf2image")
        return False
    
    logger.info(f"Creating searchable PDF with PaddleOCR...")
    logger.info(f"  Input: {input_pdf}")
    logger.info(f"  Output: {output_pdf}")
    logger.info(f"  Languages: {', '.join(languages)}")
    logger.info(f"  GPU: {use_gpu}")
    
    # Initialize PaddleOCR
    logger.info("Initializing PaddleOCR...")
    try:
        # PaddleOCR uses 'en' for English, 'ch' for Chinese, etc.
        lang = languages[0] if languages else 'en'
        ocr = PaddleOCR(use_angle_cls=True, lang=lang, use_gpu=use_gpu)
    except Exception as e:
        logger.error(f"Failed to initialize PaddleOCR: {e}")
        return False
    
    # Convert PDF to images
    logger.info("Converting PDF to images...")
    try:
        images = convert_from_path(str(input_pdf), dpi=300)
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return False
    
    # Open PDF
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()
    
    logger.info(f"Processing {len(images)} pages...")
    
    for page_num, (image, orig_page) in enumerate(zip(images, doc)):
        logger.info(f"  Processing page {page_num + 1}/{len(images)}...")
        
        # Convert PIL Image to numpy array
        image_array = np.array(image)
        
        # Run PaddleOCR
        try:
            result = ocr.ocr(image_array, cls=True)
        except:
            result = ocr.ocr(image_array)
        
        # Create new page with same dimensions
        new_page = new_doc.new_page(width=orig_page.rect.width, height=orig_page.rect.height)
        
        # Insert original page image
        mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
        pix = orig_page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        new_page.insert_image(orig_page.rect, stream=img_data)
        
        # Add OCR text as invisible layer
        if result and result[0]:
            for detection in result[0]:
                if not detection:
                    continue
                
                # PaddleOCR format: [[[x1, y1], [x2, y2], [x3, y3], [x4, y4]], (text, confidence)]
                bbox = detection[0]
                text_info = detection[1]
                
                if isinstance(text_info, (tuple, list)) and len(text_info) > 0:
                    text = text_info[0]
                    confidence = text_info[1] if len(text_info) > 1 else 1.0
                else:
                    text = str(text_info)
                    confidence = 1.0
                
                if confidence < 0.3:  # Skip low-confidence detections
                    continue
                
                # Calculate bounding box
                x_coords = [point[0] for point in bbox]
                y_coords = [point[1] for point in bbox]
                
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                width = x_max - x_min
                height = y_max - y_min
                
                # Scale coordinates from image pixels to PDF points
                scale_x = orig_page.rect.width / image.width
                scale_y = orig_page.rect.height / image.height
                
                # Convert to PDF coordinates
                pdf_x = x_min * scale_x
                pdf_y = (image.height - y_max) * scale_y
                
                # Estimate font size
                font_size = max(6, height * scale_y * 0.8)
                
                # Add invisible text
                try:
                    new_page.insert_text(
                        (pdf_x, pdf_y),
                        text,
                        fontsize=font_size,
                        render_mode=3  # Invisible text
                    )
                except Exception as e:
                    logger.debug(f"  Could not insert text '{text[:20]}...': {e}")
                    continue
    
    # Save searchable PDF
    logger.info(f"Saving searchable PDF: {output_pdf}")
    new_doc.save(str(output_pdf))
    new_doc.close()
    doc.close()
    
    logger.info(f"✅ Searchable PDF created: {output_pdf}")
    return True


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create searchable PDFs from scanned documents using OCR",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        'input_pdf',
        type=Path,
        help='Input PDF file (scanned document)'
    )
    parser.add_argument(
        '--output', '-o',
        type=Path,
        default=None,
        help='Output PDF path (default: input_ocr.pdf)'
    )
    parser.add_argument(
        '--engine',
        choices=['easyocr', 'paddleocr'],
        default='easyocr',
        help='OCR engine to use (default: easyocr)'
    )
    parser.add_argument(
        '--languages',
        type=str,
        default='en',
        help='Comma-separated language codes (default: en)'
    )
    parser.add_argument(
        '--gpu',
        action='store_true',
        default=True,
        help='Use GPU acceleration (default: True)'
    )
    parser.add_argument(
        '--cpu',
        action='store_true',
        help='Force CPU mode (overrides --gpu)'
    )
    
    args = parser.parse_args()
    
    # Validate input
    if not args.input_pdf.exists():
        logger.error(f"Input PDF not found: {args.input_pdf}")
        return 1
    
    # Determine output path
    if args.output is None:
        args.output = args.input_pdf.parent / f"{args.input_pdf.stem}_ocr{args.input_pdf.suffix}"
    
    # Parse languages
    languages = [lang.strip() for lang in args.languages.split(',')]
    
    # Determine GPU usage
    use_gpu = args.gpu and not args.cpu
    
    # Create searchable PDF
    success = False
    if args.engine == 'easyocr':
        success = create_searchable_pdf_easyocr(
            args.input_pdf,
            args.output,
            languages=languages,
            use_gpu=use_gpu
        )
    elif args.engine == 'paddleocr':
        success = create_searchable_pdf_paddleocr(
            args.input_pdf,
            args.output,
            languages=languages,
            use_gpu=use_gpu
        )
    
    return 0 if success else 1


if __name__ == '__main__':
    sys.exit(main())

