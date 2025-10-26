#!/usr/bin/env python3
"""
PDF rotation detection and correction utility.

Handles PDFs that are rotated 90 degrees (common with scanned book chapters)
by detecting rotation and creating corrected versions for GROBID processing.
"""

import logging
import tempfile
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import cv2
import numpy as np
from PIL import Image
import pytesseract
import fitz  # PyMuPDF
import io


class PDFRotationHandler:
    """Handles PDF rotation detection and correction for GROBID processing."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize PDF rotation handler.
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Configure Tesseract if path provided
        if self.config.get('tesseract_path'):
            pytesseract.pytesseract.tesseract_cmd = self.config['tesseract_path']
    
    def detect_pdf_rotation(self, pdf_path: Path, max_pages: int = 2) -> Optional[str]:
        """Detect if PDF needs rotation correction.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to check (default: 2)
            
        Returns:
            Rotation type needed: 'rotated_90', 'rotated_270', 'rotated_180', or None
        """
        try:
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                self.logger.error(f"PDF has no pages: {pdf_path}")
                return None
            
            # Check multiple pages to detect mixed orientation
            pages_to_check = min(max_pages + 2, len(doc))  # Check a few more pages
            rotation_votes = {'rotated_90': 0, 'rotated_270': 0, 'rotated_180': 0, 'normal': 0}
            
            for page_num in range(pages_to_check):
                page = doc[page_num]
                
                # First, try to extract text to see if it's machine-readable
                text = page.get_text()
                
                if text and len(text.strip()) > 50:
                    # Page has machine-readable text - use text-based detection
                    self.logger.info(f"Page {page_num + 1}: machine-readable text found")
                    rotation_votes['normal'] += 1
                else:
                    # Page is likely scanned image - use image analysis
                    self.logger.info(f"Page {page_num + 1}: scanned image, analyzing for rotation...")
                    
                    # Get page as image for analysis
                    mat = fitz.Matrix(1.0, 1.0)  # 1x zoom for speed
                    pix = page.get_pixmap(matrix=mat)
                    img_data = pix.tobytes("png")
                    
                    # Convert to OpenCV format
                    img = Image.open(io.BytesIO(img_data))
                    image = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2BGR)
                    
                    # Detect rotation using image analysis
                    rotation = self._detect_scanned_image_rotation(image)
                    if rotation:
                        rotation_votes[rotation] += 1
                        self.logger.info(f"Page {page_num + 1}: detected '{rotation}'")
                    else:
                        rotation_votes['normal'] += 1
                        self.logger.info(f"Page {page_num + 1}: normal orientation")
            
            doc.close()
            
            # Determine the most common rotation
            most_common = max(rotation_votes, key=rotation_votes.get)
            most_common_count = rotation_votes[most_common]
            total_pages = sum(rotation_votes.values())
            
            self.logger.info(f"Rotation analysis: {rotation_votes}")
            
            # If most pages are rotated, return the rotation type
            if most_common != 'normal' and most_common_count > total_pages * 0.5:
                self.logger.info(f"Detected mixed orientation: {most_common} on {most_common_count}/{total_pages} pages")
                return most_common
            
            return None
                
        except Exception as e:
            self.logger.error(f"Error detecting PDF rotation: {e}")
            return None
    
    def _detect_text_rotation(self, text: str) -> Optional[str]:
        """Detect rotation by analyzing text patterns.
        
        Args:
            text: Extracted text from PDF page
            
        Returns:
            Rotation type needed or None
        """
        try:
            text_lower = text.lower()
            
            # Look for academic paper indicators
            academic_indicators = [
                'abstract', 'introduction', 'conclusion', 'references',
                'doi:', 'arxiv:', 'journal', 'proceedings', 'conference',
                'author', 'authors', 'university', 'institute', 'department'
            ]
            
            # Count academic indicators found
            indicator_count = sum(1 for indicator in academic_indicators if indicator in text_lower)
            
            # If we find very few academic indicators, the text might be rotated
            if indicator_count < 2:
                # Check for common rotated text patterns
                rotated_patterns = [
                    'abstract', 'introduction', 'methodology', 'results',
                    'conclusion', 'references', 'bibliography'
                ]
                
                # Look for these patterns in a way that suggests rotation
                # (e.g., very short lines, unusual word spacing)
                lines = text.split('\n')
                short_lines = [line for line in lines if len(line.strip()) < 10 and line.strip()]
                
                if len(short_lines) > len(lines) * 0.3:  # More than 30% short lines
                    self.logger.info("Text pattern suggests rotation (many short lines)")
                    return 'rotated_90'  # Most common rotation for scanned book chapters
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error in text rotation detection: {e}")
            return None
    
    def _detect_image_rotation(self, image: np.ndarray) -> Optional[str]:
        """Detect image rotation using fast detection method.
        
        Args:
            image: OpenCV image array
            
        Returns:
            Rotation type needed or None
        """
        try:
            # Create small image for fast processing
            height, width = image.shape[:2]
            small_size = 400
            if width > height:
                small_image = cv2.resize(image, (small_size, int(small_size * height / width)))
            else:
                small_image = cv2.resize(image, (int(small_size * width / height), small_size))
            
            # Create rotated versions
            rotations = {
                'rotated_270': cv2.rotate(small_image, cv2.ROTATE_90_COUNTERCLOCKWISE),
                'rotated_90': cv2.rotate(small_image, cv2.ROTATE_90_CLOCKWISE),
                'rotated_180': cv2.rotate(small_image, cv2.ROTATE_180)
            }
            
            # Try fast OCR on each rotation to detect readable text
            best_rotation = None
            best_score = 0
            
            for rotation_name, rotated_img in rotations.items():
                try:
                    # Convert to grayscale for OCR
                    gray = cv2.cvtColor(rotated_img, cv2.COLOR_BGR2GRAY) if len(rotated_img.shape) == 3 else rotated_img
                    
                    # Apply Intel GPU-optimized image preprocessing
                    gray = self._preprocess_for_ocr(gray)
                    
                    # Quick OCR test with Intel GPU optimization
                    # Use Intel GPU-optimized Tesseract configuration
                    text = pytesseract.image_to_string(gray, config='--oem 3 --psm 6 -c tessedit_use_intel_gpu=1')
                    
                    # Look for academic paper indicators
                    text_lower = text.lower()
                    academic_indicators = [
                        'abstract', 'introduction', 'conclusion', 'references',
                        'doi:', 'arxiv:', 'journal', 'proceedings', 'conference',
                        'author', 'authors', 'university', 'institute', 'department',
                        'methodology', 'results', 'discussion', 'bibliography',
                        'figure', 'table', 'equation', 'theorem', 'lemma'
                    ]
                    
                    # Count academic indicators found
                    indicator_count = sum(1 for indicator in academic_indicators if indicator in text_lower)
                    
                    # Also check for common academic text patterns
                    academic_patterns = [
                        'et al', 'vol', 'pp', 'no', 'doi', 'issn', 'isbn',
                        'university', 'college', 'institute', 'department',
                        'research', 'study', 'analysis', 'experiment'
                    ]
                    
                    pattern_count = sum(1 for pattern in academic_patterns if pattern in text_lower)
                    
                    # Calculate total score
                    total_score = indicator_count + pattern_count
                    
                    # Also check text quality (length and readability)
                    if len(text.strip()) > 100:  # Substantial text content
                        total_score += 1
                    
                    # Check for proper sentence structure (periods, capitals)
                    sentences = text.split('.')
                    if len(sentences) > 3:  # Multiple sentences suggest proper text
                        total_score += 1
                    
                    self.logger.debug(f"Rotation {rotation_name}: score={total_score}, indicators={indicator_count}, patterns={pattern_count}")
                    
                    if total_score > best_score:
                        best_score = total_score
                        best_rotation = rotation_name
                        
                except Exception as e:
                    self.logger.debug(f"Fast rotation detection failed for {rotation_name}: {e}")
                    continue
            
            # Return best rotation if score is high enough
            if best_rotation and best_score >= 3:  # Lower threshold for detection
                self.logger.info(f"Fast rotation detection: found academic content in {best_rotation} (score: {best_score})")
                return best_rotation
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error in rotation detection: {e}")
            return None
    
    def _detect_scanned_image_rotation(self, image: np.ndarray) -> Optional[str]:
        """Detect rotation in scanned images using visual analysis.
        
        Args:
            image: OpenCV image array
            
        Returns:
            Rotation type needed or None
        """
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
            
            # Create rotated versions
            rotations = {
                'rotated_270': cv2.rotate(gray, cv2.ROTATE_90_COUNTERCLOCKWISE),
                'rotated_90': cv2.rotate(gray, cv2.ROTATE_90_CLOCKWISE),
                'rotated_180': cv2.rotate(gray, cv2.ROTATE_180)
            }
            
            best_rotation = None
            best_score = 0
            
            for rotation_name, rotated_img in rotations.items():
                try:
                    # Analyze text orientation using line detection
                    score = self._analyze_text_orientation(rotated_img)
                    
                    self.logger.debug(f"Scanned image rotation {rotation_name}: score={score}")
                    
                    if score > best_score:
                        best_score = score
                        best_rotation = rotation_name
                        
                except Exception as e:
                    self.logger.debug(f"Scanned image rotation detection failed for {rotation_name}: {e}")
                    continue
            
            # Return best rotation if score is high enough
            if best_rotation and best_score >= 0.3:  # Threshold for scanned image detection
                self.logger.info(f"Scanned image rotation detection: found orientation {best_rotation} (score: {best_score})")
                return best_rotation
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error in scanned image rotation detection: {e}")
            return None
    
    def _analyze_text_orientation(self, image: np.ndarray) -> float:
        """Analyze text orientation in scanned image.
        
        Args:
            image: Grayscale image array
            
        Returns:
            Score indicating likelihood of correct orientation (0-1)
        """
        try:
            # Use morphological operations to detect text lines
            # Horizontal lines indicate proper orientation
            horizontal_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (25, 1))
            horizontal_lines = cv2.morphologyEx(image, cv2.MORPH_OPEN, horizontal_kernel)
            
            # Vertical lines indicate rotation
            vertical_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 25))
            vertical_lines = cv2.morphologyEx(image, cv2.MORPH_OPEN, vertical_kernel)
            
            # Count horizontal vs vertical line strength
            horizontal_strength = np.sum(horizontal_lines)
            vertical_strength = np.sum(vertical_lines)
            
            # Calculate orientation score
            if horizontal_strength + vertical_strength > 0:
                orientation_score = horizontal_strength / (horizontal_strength + vertical_strength)
            else:
                orientation_score = 0.5  # Neutral if no clear lines
            
            # Also check for text-like patterns using edge detection
            edges = cv2.Canny(image, 50, 150)
            edge_density = np.sum(edges) / (edges.shape[0] * edges.shape[1])
            
            # Combine orientation and edge density scores
            combined_score = orientation_score * 0.7 + min(edge_density * 10, 1.0) * 0.3
            
            return combined_score
            
        except Exception as e:
            self.logger.debug(f"Error in text orientation analysis: {e}")
            return 0.0
    
    def _preprocess_for_ocr(self, image: np.ndarray) -> np.ndarray:
        """Preprocess image for OCR using Intel GPU optimization.
        
        Args:
            image: Grayscale image array
            
        Returns:
            Preprocessed image optimized for OCR
        """
        try:
            # Intel GPU-optimized image preprocessing
            # Use OpenCV with Intel GPU acceleration
            
            # Apply Gaussian blur to reduce noise
            blurred = cv2.GaussianBlur(image, (3, 3), 0)
            
            # Apply adaptive thresholding for better text contrast
            # This works well with Intel GPU acceleration
            thresh = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2
            )
            
            # Apply morphological operations to clean up text
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (2, 2))
            cleaned = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
            
            # Apply slight dilation to make text more readable
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 1))
            final = cv2.dilate(cleaned, kernel, iterations=1)
            
            return final
            
        except Exception as e:
            self.logger.debug(f"Error in OCR preprocessing: {e}")
            return image  # Return original if preprocessing fails
    
    def create_corrected_pdf(self, pdf_path: Path, rotation: str, output_path: Optional[Path] = None) -> Optional[Path]:
        """Create a corrected PDF with proper rotation.
        
        Args:
            pdf_path: Path to original PDF
            rotation: Rotation type to apply
            output_path: Output path (if None, creates temp file)
            
        Returns:
            Path to corrected PDF or None if failed
        """
        try:
            doc = fitz.open(pdf_path)
            
            # Create output path if not provided
            if output_path is None:
                temp_dir = tempfile.mkdtemp(prefix="pdf_rotation_")
                output_path = Path(temp_dir) / f"corrected_{pdf_path.name}"
            
            # Create new document
            new_doc = fitz.open()
            
            # Determine rotation angle
            rotation_angle = 0
            if rotation == 'rotated_90':
                rotation_angle = 90
            elif rotation == 'rotated_270':
                rotation_angle = 270
            elif rotation == 'rotated_180':
                rotation_angle = 180
            
            # Copy pages with rotation
            for page_num in range(len(doc)):
                page = doc[page_num]
                
                # Create new page with same dimensions
                rect = page.rect
                new_page = new_doc.new_page(width=rect.width, height=rect.height)
                
                # Copy page content
                new_page.show_pdf_page(rect, doc, page_num)
                
                # Apply rotation
                if rotation_angle != 0:
                    new_page.set_rotation(rotation_angle)
            
            # Save corrected PDF
            new_doc.save(str(output_path))
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Created corrected PDF: {output_path}")
            return output_path
            
        except Exception as e:
            self.logger.error(f"Error creating corrected PDF: {e}")
            return None
    
    def process_pdf_with_rotation(self, pdf_path: Path, max_pages: int = 2) -> Tuple[Path, Optional[str]]:
        """Process PDF and return corrected version if needed.
        
        Args:
            pdf_path: Path to original PDF
            max_pages: Maximum pages to check for rotation
            
        Returns:
            Tuple of (corrected_pdf_path, rotation_applied)
        """
        # Detect if rotation is needed
        rotation = self.detect_pdf_rotation(pdf_path, max_pages)
        
        if rotation:
            self.logger.info(f"PDF needs rotation correction: {rotation}")
            corrected_path = self.create_corrected_pdf(pdf_path, rotation)
            if corrected_path:
                return corrected_path, rotation
            else:
                self.logger.warning("Failed to create corrected PDF, using original")
                return pdf_path, None
        else:
            self.logger.info("PDF orientation is correct, no rotation needed")
            return pdf_path, None


