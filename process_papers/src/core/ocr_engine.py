"""
OCR engine for processing scanned academic papers.
"""
import os
import time
import io
import logging
from typing import Optional, Dict, Any, Tuple
from pathlib import Path
import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import cv2
import numpy as np


class OCREngine:
    """OCR engine optimized for academic papers with annotations."""
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize OCR engine.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config
        self.logger = logging.getLogger(__name__)
        
        # Configure Tesseract
        if self.config.get('tesseract_path'):
            pytesseract.pytesseract.tesseract_cmd = self.config['tesseract_path']
    
    def extract_text_from_pdf(self, pdf_path: str) -> Tuple[str, Dict[str, Any]]:
        """
        Extract text from PDF using OCR, preserving page structure.
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Tuple of (extracted_text, metadata)
        """
        self.logger.info(f"Processing PDF: {pdf_path}")
        
        # Open PDF
        doc = fitz.open(pdf_path)
        extracted_text = ""
        metadata = {
            'page_count': len(doc),
            'pages_processed': 0,
            'total_confidence': 0.0,
            'processing_time': 0.0
        }
        
        start_time = time.time()
        
        for page_num in range(len(doc)):
            try:
                page = doc[page_num]
                
                # Get page as image
                mat = fitz.Matrix(2.0, 2.0)  # 2x zoom for better OCR
                pix = page.get_pixmap(matrix=mat)
                img_data = pix.tobytes("png")
                
                # Convert to PIL Image
                img = Image.open(io.BytesIO(img_data))
                
                # OCR the page
                page_text, confidence = self._ocr_page(img)
                
                # Add page separator
                if page_text.strip():
                    extracted_text += f"\\n--- Page {page_num + 1} ---\\n{page_text}\\n"
                
                metadata['total_confidence'] += confidence
                metadata['pages_processed'] += 1
                
            except Exception as e:
                self.logger.error(f"Error processing page {page_num}: {e}")
                continue
        
        doc.close()
        
        metadata['processing_time'] = time.time() - start_time
        metadata['total_confidence'] /= max(metadata['pages_processed'], 1)
        
        self.logger.info(f"OCR completed: {metadata['pages_processed']} pages, "
                        f"confidence: {metadata['total_confidence']:.2f}")
        
        return extracted_text, metadata
    
    def _ocr_page(self, image: Image.Image) -> Tuple[str, float]:
        """
        Perform OCR on a single page image.
        
        Args:
            image: PIL Image of the page
            
        Returns:
            Tuple of (text, confidence)
        """
        # Convert to OpenCV format for preprocessing
        cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)
        
        # Preprocess image for better OCR
        processed_image = self._preprocess_for_ocr(cv_image)
        
        # Convert back to PIL
        pil_image = Image.fromarray(cv2.cvtColor(processed_image, cv2.COLOR_BGR2RGB))
        
        # Configure Tesseract for academic papers
        custom_config = r'--oem 3 --psm 6 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.,;:!?-()[]{}"\''
        
        # Perform OCR
        text = pytesseract.image_to_string(pil_image, config=custom_config)
        
        # Get confidence data
        try:
            data = pytesseract.image_to_data(pil_image, config=custom_config, output_type=pytesseract.Output.DICT)
            confidences = [int(conf) for conf in data['conf'] if int(conf) > 0]
            avg_confidence = sum(confidences) / len(confidences) if confidences else 0
        except:
            avg_confidence = 50.0  # Default confidence
        
        return text.strip(), avg_confidence
    
    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """
        Preprocess image to improve OCR accuracy.
        
        Args:
            image: OpenCV image
            
        Returns:
            Preprocessed image
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply adaptive thresholding to handle varying lighting
        thresh = cv2.adaptiveThreshold(
            gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
        )
        
        # Morphological operations to clean up text
        kernel = np.ones((1, 1), np.uint8)
        cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
        
        # Denoise
        denoised = cv2.medianBlur(cleaned, 3)
        
        return denoised
    
    def detect_annotations(self, image: np.ndarray) -> Dict[str, Any]:
        """
        Detect handwritten annotations in the image.
        
        Args:
            image: OpenCV image
            
        Returns:
            Dictionary with annotation information
        """
        # Convert to HSV for better color detection
        hsv = cv2.cvtColor(image, cv2.COLOR_BGR2HSV)
        
        # Define color ranges for common annotation colors
        color_ranges = {
            'red': ([0, 50, 50], [10, 255, 255]),
            'blue': ([100, 50, 50], [130, 255, 255]),
            'green': ([40, 50, 50], [80, 255, 255]),
            'yellow': ([20, 50, 50], [40, 255, 255])
        }
        
        detected_colors = []
        
        for color_name, (lower, upper) in color_ranges.items():
            lower = np.array(lower, dtype=np.uint8)
            upper = np.array(upper, dtype=np.uint8)
            
            # Create mask for this color
            mask = cv2.inRange(hsv, lower, upper)
            
            # Count pixels of this color
            pixel_count = cv2.countNonZero(mask)
            total_pixels = image.shape[0] * image.shape[1]
            percentage = (pixel_count / total_pixels) * 100
            
            if percentage > 0.1:  # Threshold for significant annotation
                detected_colors.append({
                    'color': color_name,
                    'percentage': percentage,
                    'pixel_count': pixel_count
                })
        
        return {
            'has_annotations': len(detected_colors) > 0,
            'detected_colors': detected_colors,
            'annotation_density': sum(c['percentage'] for c in detected_colors)
        }
