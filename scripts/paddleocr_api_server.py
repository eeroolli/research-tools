#!/usr/bin/env python3
"""
PaddleOCR HTTP API Server

Provides HTTP API endpoints for OCR processing with automatic language and orientation detection.
Runs inside Docker container on p1, accessible from blacktower.

Endpoints:
    POST /ocr - Process PDF and return OCR'd PDF
    POST /ocr_with_metadata - Process PDF and return OCR'd PDF + metadata (language, orientation)
    GET /health - Health check
"""

import sys
import os
import logging
import tempfile
from pathlib import Path
from typing import Dict, Optional, Tuple, List
import json

from flask import Flask, request, jsonify, send_file
from werkzeug.utils import secure_filename
import numpy as np

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB max file size

# Global PaddleOCR instance (initialized on first use)
_ocr_instance = None
_ocr_languages = ['en', 'no', 'sv', 'fi', 'de']  # Multi-language support


def get_ocr_instance():
    """Get or initialize PaddleOCR instance."""
    global _ocr_instance
    if _ocr_instance is None:
        try:
            from paddleocr import PaddleOCR
            logger.info("Initializing PaddleOCR with multi-language support...")
            # PaddleOCR: use first language for initialization, but can handle multiple
            # For true multi-language, we'd need to detect per-page, but this works for most cases
            # Try newer API first (device parameter), fallback to older API (use_gpu parameter)
            try:
                _ocr_instance = PaddleOCR(
                    use_textline_orientation=True,  # Newer parameter name
                    lang='en',  # Start with English, detect actual language from text
                    device='gpu'  # Newer API
                )
            except (TypeError, ValueError, AttributeError):
                # Fallback to older API
                try:
                    _ocr_instance = PaddleOCR(
                        use_angle_cls=True,  # Older parameter name
                        lang='en',
                        use_gpu=True  # Older API
                    )
                except (TypeError, ValueError):
                    # Last resort: minimal parameters
                    _ocr_instance = PaddleOCR(lang='en')
            logger.info("✅ PaddleOCR initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize PaddleOCR: {e}")
            raise
    return _ocr_instance


def detect_language_from_text(text: str, min_chars: int = 100) -> Optional[str]:
    """Detect language from OCR text using langdetect.
    
    Args:
        text: OCR'd text
        min_chars: Minimum characters needed for detection
        
    Returns:
        Language code (en, no, sv, fi, de) or None if detection fails
    """
    if len(text.strip()) < min_chars:
        return None
    
    try:
        from langdetect import detect, LangDetectException
        # Use first 1000 chars for faster detection
        sample_text = text[:1000].strip()
        if not sample_text:
            return None
        
        detected = detect(sample_text)
        
        # Map ISO 639-1 codes to our language codes
        lang_map = {
            'en': 'en',
            'no': 'no',  # Norwegian
            'nn': 'no',  # Norwegian Nynorsk
            'sv': 'sv',  # Swedish
            'fi': 'fi',  # Finnish
            'de': 'de'   # German
        }
        
        return lang_map.get(detected, None)
    except (ImportError, LangDetectException, Exception) as e:
        logger.warning(f"Language detection failed: {e}")
        return None


def map_language_to_prefix(lang_code: Optional[str]) -> str:
    """Map language code to filename prefix.
    
    Args:
        lang_code: Language code (en, no, sv, fi, de) or None
        
    Returns:
        Filename prefix (EN_, NO_, SE_, FI_, DE_) or empty string
    """
    if not lang_code:
        return ""
    
    prefix_map = {
        'en': 'EN_',
        'no': 'NO_',
        'sv': 'SE_',  # Swedish -> SE_ (matches daemon convention)
        'fi': 'FI_',
        'de': 'DE_'
    }
    
    return prefix_map.get(lang_code.lower(), '')


def detect_two_up_orientation(pdf_path: Path) -> Tuple[bool, float]:
    """Detect if PDF has two-up (landscape) pages.
    
    Args:
        pdf_path: Path to PDF file
        
    Returns:
        Tuple of (is_two_up: bool, aspect_ratio: float)
    """
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_path)) as pdf:
            if len(pdf.pages) == 0:
                return False, 0.0
            
            # Check first page aspect ratio
            first = pdf.pages[0]
            width, height = first.width, first.height
            
            if not width or not height:
                return False, 0.0
            
            aspect_ratio = width / height
            
            # Landscape pages with aspect ratio > 1.3 are likely two-up
            is_two_up = aspect_ratio > 1.3
            
            return is_two_up, aspect_ratio
    except Exception as e:
        logger.warning(f"Two-up detection failed: {e}")
        return False, 0.0


def create_searchable_pdf_paddleocr(
    input_pdf: Path,
    output_pdf: Path,
    use_gpu: bool = True
) -> Tuple[bool, str]:
    """Create searchable PDF using PaddleOCR.
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path
        use_gpu: Whether to use GPU
        
    Returns:
        Tuple of (success: bool, extracted_text: str)
    """
    try:
        import fitz  # PyMuPDF
        from pdf2image import convert_from_path
    except ImportError as e:
        logger.error(f"Missing dependency: {e}")
        return False, ""
    
    ocr = get_ocr_instance()
    
    # Convert PDF to images
    logger.info("Converting PDF to images...")
    try:
        images = convert_from_path(str(input_pdf), dpi=300)
    except Exception as e:
        logger.error(f"Failed to convert PDF to images: {e}")
        return False, ""
    
    # Open PDF
    doc = fitz.open(input_pdf)
    new_doc = fitz.open()
    
    all_text = []
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
        
        # Copy original page content (preserves PDF structure and compression)
        # This is more efficient than re-rendering and preserves the original file size
        new_page.show_pdf_page(
            new_page.rect,
            doc,
            page_num,
            clip=orig_page.rect
        )
        
        # Note: Text layer will be added on top of the copied page content
        
        # Extract text and add as invisible layer
        page_text = ""
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
                
                page_text += text + " "
                
                # Calculate bounding box - handle different bbox formats
                try:
                    # PaddleOCR bbox format: [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
                    if isinstance(bbox, (list, tuple)) and len(bbox) > 0:
                        # Check if bbox contains points (lists/tuples with 2 elements)
                        if isinstance(bbox[0], (list, tuple)) and len(bbox[0]) >= 2:
                            x_coords = [point[0] for point in bbox if isinstance(point, (list, tuple)) and len(point) >= 2]
                            y_coords = [point[1] for point in bbox if isinstance(point, (list, tuple)) and len(point) >= 2]
                        # Alternative format: [x1, y1, x2, y2, x3, y3, x4, y4] (flat list)
                        elif len(bbox) >= 8:
                            x_coords = [bbox[i] for i in range(0, len(bbox), 2)]
                            y_coords = [bbox[i] for i in range(1, len(bbox), 2)]
                        else:
                            logger.warning(f"Unexpected bbox format: {bbox}, skipping")
                            continue
                    else:
                        logger.warning(f"Invalid bbox type: {type(bbox)}, skipping")
                        continue
                except (IndexError, TypeError) as e:
                    logger.warning(f"Error processing bbox {bbox}: {e}, skipping")
                    continue
                
                x_min, x_max = min(x_coords), max(x_coords)
                y_min, y_max = min(y_coords), max(y_coords)
                height = y_max - y_min
                
                # Scale coordinates from image pixels to PDF points
                scale_x = orig_page.rect.width / image.width
                scale_y = orig_page.rect.height / image.height
                
                # Convert to PDF coordinates
                pdf_x = x_min * scale_x
                pdf_y = (image.height - y_max) * scale_y
                
                # Estimate font size
                font_size = max(6, height * scale_y * 0.8)
                
                # Add invisible text layer for searchability
                # Use insert_text with render_mode=3 (invisible) to make PDF searchable
                try:
                    # Ensure text is added after page content
                    text_rect = fitz.Rect(pdf_x, pdf_y, pdf_x + len(text) * font_size * 0.6, pdf_y + font_size)
                    new_page.insert_text(
                        (pdf_x, pdf_y),
                        text,
                        fontsize=font_size,
                        render_mode=3,  # Invisible text (for searchability)
                        color=(0, 0, 0)  # Black (invisible but searchable)
                    )
                    logger.debug(f"  Added text: '{text[:30]}...' at ({pdf_x:.1f}, {pdf_y:.1f})")
                except Exception as e:
                    logger.warning(f"  Could not insert text '{text[:20]}...': {e}")
                    continue
        
        all_text.append(page_text.strip())
    
    # Save searchable PDF
    logger.info(f"Saving searchable PDF: {output_pdf}")
    logger.info(f"Total text extracted: {len(' '.join(all_text))} characters")
    new_doc.save(str(output_pdf), garbage=4, deflate=True)  # Optimize PDF
    new_doc.close()
    doc.close()
    
    full_text = " ".join(all_text)
    logger.info(f"✅ Searchable PDF created: {output_pdf}")
    logger.info(f"   Text length: {len(full_text)} characters")
    return True, full_text


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    try:
        # Try to get OCR instance to verify it's working
        ocr = get_ocr_instance()
        return jsonify({
            'status': 'healthy',
            'service': 'paddleocr-api',
            'gpu_available': True  # Assume GPU if we got here
        }), 200
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e)
        }), 500


@app.route('/ocr', methods=['POST'])
def ocr_endpoint():
    """Process PDF and return OCR'd PDF.
    
    Request:
        - file: PDF file (multipart/form-data)
        
    Response:
        - OCR'd PDF file
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400
    
    # Save uploaded file to temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_pdf = temp_path / secure_filename(file.filename)
        output_pdf = temp_path / f"ocr_{secure_filename(file.filename)}"
        
        file.save(str(input_pdf))
        logger.info(f"Processing PDF: {file.filename}")
        
        # Create searchable PDF
        success, text = create_searchable_pdf_paddleocr(input_pdf, output_pdf)
        
        if not success:
            return jsonify({'error': 'OCR processing failed'}), 500
        
        # Return OCR'd PDF
        return send_file(
            str(output_pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ocr_{file.filename}"
        )


@app.route('/ocr_with_metadata', methods=['POST'])
def ocr_with_metadata_endpoint():
    """Process PDF and return OCR'd PDF + metadata (language, orientation).
    
    Request:
        - file: PDF file (multipart/form-data)
        
    Response:
        - JSON with metadata and file download link, or
        - Direct file download with metadata in headers
    """
    if 'file' not in request.files:
        return jsonify({'error': 'No file provided'}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected'}), 400
    
    if not file.filename.lower().endswith('.pdf'):
        return jsonify({'error': 'File must be a PDF'}), 400
    
    # Save uploaded file to temp directory
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_pdf = temp_path / secure_filename(file.filename)
        output_pdf = temp_path / f"ocr_{secure_filename(file.filename)}"
        
        file.save(str(input_pdf))
        logger.info(f"Processing PDF with metadata: {file.filename}")
        
        # Create searchable PDF
        success, text = create_searchable_pdf_paddleocr(input_pdf, output_pdf)
        
        if not success:
            return jsonify({'error': 'OCR processing failed'}), 500
        
        # Detect language from OCR text
        detected_lang = detect_language_from_text(text)
        lang_prefix = map_language_to_prefix(detected_lang)
        
        # Detect orientation (two-up pages)
        is_two_up, aspect_ratio = detect_two_up_orientation(output_pdf)
        
        # Prepare metadata
        metadata = {
            'language': detected_lang or 'unknown',
            'language_prefix': lang_prefix,
            'is_two_up': is_two_up,
            'aspect_ratio': round(aspect_ratio, 2),
            'suggested_suffix': '_double.pdf' if is_two_up else '.pdf',
            'text_length': len(text),
            'pages': len(text.split('\n\n')) if text else 0
        }
        
        # Return JSON with metadata and file
        # For simplicity, we'll return the file directly with metadata in response
        response = send_file(
            str(output_pdf),
            mimetype='application/pdf',
            as_attachment=True,
            download_name=f"ocr_{file.filename}"
        )
        
        # Add metadata to response headers
        response.headers['X-OCR-Language'] = detected_lang or 'unknown'
        response.headers['X-OCR-Language-Prefix'] = lang_prefix
        response.headers['X-OCR-Is-Two-Up'] = str(is_two_up).lower()
        response.headers['X-OCR-Aspect-Ratio'] = str(aspect_ratio)
        
        return response


if __name__ == '__main__':
    # Get port from environment or default to 8080
    port = int(os.environ.get('PADDLEOCR_API_PORT', 8080))
    host = os.environ.get('PADDLEOCR_API_HOST', '0.0.0.0')
    
    logger.info(f"Starting PaddleOCR API server on {host}:{port}")
    logger.info("Server runs as persistent service - handles multiple requests efficiently")
    # Use threaded=True to handle concurrent requests (useful for high-frequency scanning)
    app.run(host=host, port=port, debug=False, threaded=True)

