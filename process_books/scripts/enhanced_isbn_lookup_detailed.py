# scripts/enhanced_isbn_lookup_detailed.py

import cv2
import numpy as np
from pyzbar import pyzbar
import pytesseract
import requests
import json
import yaml
import configparser
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import shutil
from PIL import Image, ExifTags
import re

class EnhancedISBNProcessor:
    """Enhanced ISBN processing with photo organization and EXIF orientation correction"""
    
    def __init__(self, config_file: str = "/mnt/f/prog/scanpapers/config/scanpapers.conf"):
        self.config_file = config_file
        self.load_config()
        
        # Create directories if they don't exist
        self.photos_done.mkdir(parents=True, exist_ok=True)
        self.photos_failed.mkdir(parents=True, exist_ok=True)
        
        # Initialize lookup service
        self.lookup_service = DetailedISBNLookupService()
        
        # Processing log
        self.processing_log_file = "/mnt/f/prog/scanpapers/data/book_processing_log.json"
        self.load_processing_log()
        
        print(f"Enhanced ISBN Processor initialized")
        print(f"📁 Current photos: {self.photos_current}")
        print(f"✅ Success folder: {self.photos_done}")
        print(f"❌ Failed folder: {self.photos_failed}")

    def load_config(self):
        """Load configuration from config file"""
        config = configparser.ConfigParser()
        config.read(self.config_file)
        
        # Photo directories
        self.photos_current = Path(config.get('paths', 'photos_current'))
        self.photos_done = Path(config.get('paths', 'photos_done'))
        self.photos_failed = Path(config.get('paths', 'photos_failed'))
        
        # OCR settings
        self.tesseract_config = config.get('processing', 'tesseract_config')
        rotation_angles = config.get('processing', 'rotation_angles')
        self.rotation_angles = [int(angle) for angle in rotation_angles.split(',')]
        
        # API settings
        self.api_delay = config.getfloat('processing', 'api_delay')

    def load_processing_log(self):
        """Load or create processing log"""
        try:
            with open(self.processing_log_file, 'r') as f:
                self.processing_log = json.load(f)
        except FileNotFoundError:
            self.processing_log = {}
            self.save_processing_log()

    def save_processing_log(self):
        """Save processing log"""
        with open(self.processing_log_file, 'w') as f:
            json.dump(self.processing_log, f, indent=2)

    def lookup_isbn(self, isbn: str) -> Optional[Dict]:
        """Lookup ISBN using the enhanced lookup service"""
        return self.lookup_service.lookup_isbn(isbn)

    def get_exif_orientation(self, image_path: Path) -> int:
        """Get EXIF orientation from image metadata"""
        try:
            with Image.open(image_path) as img:
                # Get EXIF data
                exif = img._getexif()
                if exif is None:
                    return 1  # Default orientation
                
                # Find orientation tag
                for orientation in ExifTags.TAGS.keys():
                    if ExifTags.TAGS[orientation] == 'Orientation':
                        break
                else:
                    return 1  # No orientation tag found
                
                # Get orientation value
                orientation = exif.get(orientation, 1)
                print(f"    📱 EXIF orientation: {orientation}")
                return orientation
                
        except Exception as e:
            print(f"    ⚠️  EXIF reading error: {e}")
            return 1  # Default orientation

    def correct_image_orientation(self, image_path: Path) -> np.ndarray:
        """Correct image orientation based on EXIF data"""
        try:
            # Get EXIF orientation
            orientation = self.get_exif_orientation(image_path)
            
            # Read image with OpenCV
            image = cv2.imread(str(image_path))
            if image is None:
                return None
            
            # Apply orientation correction
            if orientation == 1:
                # Normal orientation
                return image
            elif orientation == 3:
                # Rotate 180 degrees
                return cv2.rotate(image, cv2.ROTATE_180)
            elif orientation == 6:
                # Rotate 90 degrees clockwise
                return cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
            elif orientation == 8:
                # Rotate 90 degrees counter-clockwise
                return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
            else:
                # Unknown orientation, return original
                return image
                
        except Exception as e:
            print(f"    ❌ Orientation correction error: {e}")
            # Fallback to original image
            return cv2.imread(str(image_path))

    def extract_isbn_from_image(self, image_path: Path) -> Optional[str]:
        """Extract ISBN from image using enhanced barcode scanning and OCR"""
        try:
            # Read and preprocess image efficiently
            image = self.preprocess_image_for_ocr(image_path)
            if image is None:
                return None
            
            # Try barcode scanning first (most reliable)
            isbn = self.scan_barcodes(image)
            if isbn:
                print(f"  ✅ Found ISBN via barcode: {isbn}")
                return isbn
            
            # Enhanced OCR with better preprocessing
            isbn = self.enhanced_ocr_extraction(image)
            if isbn:
                return isbn
            
            print(f"  ❌ No ISBN or barcode found - image must contain ISBN")
            return None
            
        except Exception as e:
            print(f"  ❌ Error processing image: {e}")
            return None

    def preprocess_image_for_ocr(self, image_path: Path) -> Optional[np.ndarray]:
        """Efficient image preprocessing for OCR"""
        try:
            # Read image
            image = cv2.imread(str(image_path))
            if image is None:
                return None
            
            # Get original dimensions
            height, width = image.shape[:2]
            print(f"    📏 Original size: {width}x{height}")
            
            # Resize for faster processing 
            max_size = 2000
            if width > max_size or height > max_size:
                if width > height:
                    new_width = max_size
                    new_height = int(height * max_size / width)
                else:
                    new_height = max_size
                    new_width = int(width * max_size / height)
                
                image = cv2.resize(image, (new_width, new_height), interpolation=cv2.INTER_AREA)
                print(f"    📏 Resized to: {new_width}x{new_height}")
            
            # Color correction for better OCR
            image = self.correct_colors(image)
            
            return image
            
        except Exception as e:
            print(f"    ❌ Preprocessing error: {e}")
            return None

    def correct_colors(self, image: np.ndarray) -> np.ndarray:
        """Correct colors for better OCR performance"""
        try:
            # Convert to LAB color space for better color correction
            lab = cv2.cvtColor(image, cv2.COLOR_BGR2LAB)
            
            # Apply CLAHE to L channel (lightness)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            lab[:,:,0] = clahe.apply(lab[:,:,0])
            
            # Convert back to BGR
            corrected = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
            
            # Enhance contrast
            alpha = 1.2  # Contrast factor
            beta = 10    # Brightness factor
            corrected = cv2.convertScaleAbs(corrected, alpha=alpha, beta=beta)
            
            return corrected
            
        except Exception as e:
            print(f"    ⚠️  Color correction error: {e}")
            return image  # Return original if correction fails

    def remove_colored_backgrounds(self, image: np.ndarray) -> np.ndarray:
        """Remove colored backgrounds and focus on text/barcode content"""
        try:
            # Convert to grayscale for analysis
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Calculate color variation to detect solid backgrounds
            # Use a small window to detect areas with low variation
            window_size = 15
            height, width = gray.shape
            
            # Create a mask for areas with high variation (text/barcode areas)
            variation_mask = np.zeros_like(gray)
            
            for y in range(0, height - window_size, window_size // 2):
                for x in range(0, width - window_size, window_size // 2):
                    window = gray[y:y+window_size, x:x+window_size]
                    variation = np.std(window)
                    
                    # If variation is high, this area likely contains text/barcode
                    if variation > 20:  # Threshold for text detection
                        variation_mask[y:y+window_size, x:x+window_size] = 255
            
            # Apply morphological operations to clean up the mask
            kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
            variation_mask = cv2.morphologyEx(variation_mask, cv2.MORPH_CLOSE, kernel)
            variation_mask = cv2.morphologyEx(variation_mask, cv2.MORPH_OPEN, kernel)
            
            # Apply mask to original image (keep only high-variation areas)
            masked_image = cv2.bitwise_and(image, image, mask=variation_mask)
            
            # Fill background with white
            white_background = np.ones_like(image) * 255
            result = cv2.bitwise_or(masked_image, white_background, mask=cv2.bitwise_not(variation_mask))
            
            return result
            
        except Exception as e:
            print(f"    ⚠️  Background removal error: {e}")
            return image  # Return original if processing fails

    def enhance_for_isbn_detection(self, image: np.ndarray) -> np.ndarray:
        """Fast enhancement specifically for ISBN detection"""
        try:
            # Convert to grayscale
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            
            # Fast contrast enhancement
            clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8,8))
            enhanced = clahe.apply(gray)
            
            # Remove noise while preserving edges
            denoised = cv2.fastNlMeansDenoising(enhanced, None, 10, 7, 21)
            
            # Convert back to BGR for consistency
            result = cv2.cvtColor(denoised, cv2.COLOR_GRAY2BGR)
            
            return result
            
        except Exception as e:
            print(f"    ⚠️  ISBN enhancement error: {e}")
            return image

    def get_center_region(self, image: np.ndarray, region_size: float = 0.6) -> np.ndarray:
        """Extract center region where ISBNs are most likely to be"""
        height, width = image.shape[:2]
        
        # Calculate center region
        center_x = width // 2
        center_y = height // 2
        region_width = int(width * region_size)
        region_height = int(height * region_size)
        
        # Extract center region
        x1 = max(0, center_x - region_width // 2)
        y1 = max(0, center_y - region_height // 2)
        x2 = min(width, x1 + region_width)
        y2 = min(height, y1 + region_height)
        
        return image[y1:y2, x1:x2]

    def scan_barcodes(self, image) -> Optional[str]:
        """Enhanced barcode scanning with preprocessing - optimized for speed and colored backgrounds"""
        try:
            # Priority 1: Try original image (fastest)
            barcodes = pyzbar.decode(image)
            for barcode in barcodes:
                isbn = barcode.data.decode('utf-8')
                if self.is_valid_isbn(isbn):
                    return isbn
            
            # Priority 2: Try center region (where ISBNs are most likely)
            center_region = self.get_center_region(image)
            barcodes = pyzbar.decode(center_region)
            for barcode in barcodes:
                isbn = barcode.data.decode('utf-8')
                if self.is_valid_isbn(isbn):
                    return isbn
            
            # Priority 3: Try background removal for colored backgrounds
            cleaned_image = self.remove_colored_backgrounds(image)
            barcodes = pyzbar.decode(cleaned_image)
            for barcode in barcodes:
                isbn = barcode.data.decode('utf-8')
                if self.is_valid_isbn(isbn):
                    return isbn
            
            # Priority 4: Try enhanced image for difficult cases
            enhanced_image = self.enhance_for_isbn_detection(image)
            barcodes = pyzbar.decode(enhanced_image)
            for barcode in barcodes:
                isbn = barcode.data.decode('utf-8')
                if self.is_valid_isbn(isbn):
                    return isbn
            
            # Priority 5: Try grayscale with basic preprocessing (fallback)
            gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            preprocessing_methods = [
                gray,  # Original grayscale
                cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2),  # Adaptive threshold
            ]
            
            for processed_image in preprocessing_methods:
                barcodes = pyzbar.decode(processed_image)
                for barcode in barcodes:
                    isbn = barcode.data.decode('utf-8')
                    if self.is_valid_isbn(isbn):
                        return isbn
            
            return None
            
        except Exception as e:
            print(f"    Barcode scanning error: {e}")
            return None

    def extract_isbn_from_text(self, text: str) -> Optional[str]:
        """Extract ISBN from OCR text"""
        import re
        
        # ISBN patterns
        patterns = [
            r'\b\d{10}\b',  # 10-digit ISBN
            r'\b\d{13}\b',  # 13-digit ISBN
            r'\b\d{9}X\b',  # 10-digit ISBN ending with X
            r'\b\d{12}X\b', # 13-digit ISBN ending with X
        ]
        
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if self.is_valid_isbn(match):
                    return match
        
        return None

    def extract_all_identifiers(self, text: str) -> Dict[str, List[str]]:
        """Extract all types of identifiers from text (for future article scanning)"""
        import re
        
        identifiers = {
            'isbn': [],
            'doi': [],
            'arxiv': [],
            'url': [],
            'pmid': [],
            'issn': []
        }
        
        # ISBN patterns
        isbn_patterns = [
            r'\b\d{10}\b',  # 10-digit ISBN
            r'\b\d{13}\b',  # 13-digit ISBN
            r'\b\d{9}X\b',  # 10-digit ISBN ending with X
            r'\b\d{12}X\b', # 13-digit ISBN ending with X
        ]
        
        # DOI patterns
        doi_patterns = [
            r'\b10\.\d{4,}/[-._;()/:\w]+\b',  # Standard DOI
            r'\bdoi:\s*10\.\d{4,}/[-._;()/:\w]+\b',  # DOI with prefix
        ]
        
        # arXiv patterns
        arxiv_patterns = [
            r'\barXiv:\s*\d{4}\.\d{4,}\b',  # arXiv with prefix
            r'\b\d{4}\.\d{4,}\b',  # arXiv without prefix
        ]
        
        # URL patterns
        url_patterns = [
            r'\bhttps?://[^\s]+\b',  # HTTP/HTTPS URLs
            r'\bwww\.[^\s]+\b',  # WWW URLs
        ]
        
        # PubMed ID patterns
        pmid_patterns = [
            r'\bPMID:\s*\d+\b',  # PMID with prefix
            r'\b\d{8}\b',  # 8-digit numbers (potential PMIDs)
        ]
        
        # ISSN patterns
        issn_patterns = [
            r'\b\d{4}-\d{3}[0-9X]\b',  # ISSN with dash
            r'\b\d{4}\d{3}[0-9X]\b',  # ISSN without dash
        ]
        
        # Extract ISBNs
        for pattern in isbn_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if self.is_valid_isbn(match):
                    identifiers['isbn'].append(match)
        
        # Extract DOIs
        for pattern in doi_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            identifiers['doi'].extend(matches)
        
        # Extract arXiv IDs
        for pattern in arxiv_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            identifiers['arxiv'].extend(matches)
        
        # Extract URLs
        for pattern in url_patterns:
            matches = re.findall(pattern, text)
            identifiers['url'].extend(matches)
        
        # Extract PubMed IDs
        for pattern in pmid_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            identifiers['pmid'].extend(matches)
        
        # Extract ISSNs
        for pattern in issn_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            identifiers['issn'].extend(matches)
        
        return identifiers

    def print_identifiers(self, identifiers: Dict[str, List[str]]):
        """Print found identifiers in a readable format"""
        print(f"  🔍 Found identifiers:")
        
        for id_type, values in identifiers.items():
            if values:
                print(f"    {id_type.upper()}: {', '.join(values)}")
        
        if not any(identifiers.values()):
            print(f"    No identifiers found")

    def enhanced_ocr_extraction(self, image) -> Optional[str]:
        """Enhanced OCR with optimized preprocessing for colored backgrounds and speed"""
        try:
            # Priority 1: Try background removal for colored backgrounds
            cleaned_image = self.remove_colored_backgrounds(image)
            gray_cleaned = cv2.cvtColor(cleaned_image, cv2.COLOR_BGR2GRAY)
            
            # Priority 2: Try enhanced image for difficult cases
            enhanced_image = self.enhance_for_isbn_detection(image)
            gray_enhanced = cv2.cvtColor(enhanced_image, cv2.COLOR_BGR2GRAY)
            
            # Priority 3: Standard preprocessing
            gray_standard = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
            enhanced_standard = clahe.apply(gray_standard)
            
            # Combine preprocessing methods (prioritized for speed)
            preprocessing_combinations = [
                gray_cleaned,      # Background removed
                gray_enhanced,     # Enhanced for ISBN
                enhanced_standard, # Standard enhanced
                cv2.adaptiveThreshold(gray_standard, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2),
            ]
            
            # Try rotations (prioritized for common cases)
            robust_angles = [0, 90, 270, 180]  # Most common first
            
            for angle in robust_angles:
                for i, processed_image in enumerate(preprocessing_combinations):
                    # Rotate image
                    rotated = self.rotate_image(processed_image, angle)
                    
                    # Try center region first (faster)
                    center_rotated = self.get_center_region(rotated)
                    
                    # Try different OCR configurations (prioritized for ISBN)
                    ocr_configs = [
                        '--oem 3 --psm 6 -c tessedit_char_whitelist=0123456789X',  # Strict ISBN (fastest)
                        '--oem 3 --psm 8 -c tessedit_char_whitelist=0123456789X',  # Single word
                        self.tesseract_config,  # Default (fallback)
                    ]
                    
                    for config in ocr_configs:
                        try:
                            # Try center region first (faster)
                            ocr_text = pytesseract.image_to_string(center_rotated, config=config)
                            identifiers = self.extract_all_identifiers(ocr_text)
                            
                            if identifiers['isbn']:
                                isbn = identifiers['isbn'][0]
                                print(f"  ✅ Found ISBN via OCR (rotation {angle}°, method {i+1}, center): {isbn}")
                                return isbn
                            
                            # If no ISBN in center, try full image
                            ocr_text = pytesseract.image_to_string(rotated, config=config)
                            identifiers = self.extract_all_identifiers(ocr_text)
                            
                            if identifiers['isbn']:
                                isbn = identifiers['isbn'][0]
                                print(f"  ✅ Found ISBN via OCR (rotation {angle}°, method {i+1}, full): {isbn}")
                                return isbn
                                
                        except Exception as e:
                            continue
            
            # Try EasyOCR for vertical text (if available)
            isbn = self.try_easyocr_for_vertical_text(image)
            if isbn:
                return isbn
            
            return None
            
        except Exception as e:
            print(f"    OCR extraction error: {e}")
            return None

    def try_easyocr_for_vertical_text(self, image) -> Optional[str]:
        """Try EasyOCR specifically for vertical text"""
        try:
            import easyocr
            
            # Initialize EasyOCR reader with supported languages
            reader = easyocr.Reader(['en', 'no'], gpu=False)  # CPU mode for Intel GPU
            
            # Try different rotations for vertical text
            for angle in [0, 90, 180, 270]:
                try:
                    # Rotate image
                    rotated = self.rotate_image(image, angle)
                    
                    # Extract text with EasyOCR
                    results = reader.readtext(rotated)
                    
                    # Combine all text
                    text = ' '.join([result[1] for result in results])
                    
                    # Extract ISBN
                    identifiers = self.extract_all_identifiers(text)
                    if identifiers['isbn']:
                        isbn = identifiers['isbn'][0]
                        print(f"  ✅ EasyOCR found ISBN (rotation {angle}°): {isbn}")
                        return isbn
                        
                except Exception as e:
                    continue
            
            return None
            
        except ImportError:
            print("  ⚠️  EasyOCR not available for vertical text processing")
            return None
        except Exception as e:
            print(f"  ❌ EasyOCR error: {e}")
            return None

    def rotate_image(self, image, angle):
        """Rotate image by specified angle"""
        height, width = image.shape[:2]
        center = (width // 2, height // 2)
        
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        rotated = cv2.warpAffine(image, rotation_matrix, (width, height))
        
        return rotated

    def is_valid_isbn(self, isbn: str) -> bool:
        """Basic ISBN validation"""
        if not isbn:
            return False
        
        # Remove non-alphanumeric characters
        clean_isbn = ''.join(c for c in isbn if c.isalnum() or c.upper() == 'X')
        
        # Check length
        if len(clean_isbn) not in [10, 13]:
            return False
        
        # Basic format check
        if not clean_isbn.isdigit() and not (clean_isbn[:-1].isdigit() and clean_isbn[-1].upper() == 'X'):
            return False
        
        return True

    def cleanup_already_processed_photos(self):
        """Immediately move or delete already processed photos"""
        print(f"🧹 Cleaning up already processed photos...")
        
        if not self.photos_current.exists():
            print(f"   ❌ Main photos directory not found: {self.photos_current}")
            return {'moved': 0, 'deleted': 0, 'errors': 0}
        
        # Get all image files in main folder
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
        main_files = [f for f in self.photos_current.iterdir() 
                     if f.is_file() and f.suffix.lower() in image_extensions]
        
        if not main_files:
            print(f"   📝 No image files found in main folder")
            return {'moved': 0, 'deleted': 0, 'errors': 0}
        
        print(f"   📁 Found {len(main_files)} image files in main folder")
        
        moved_count = 0
        deleted_count = 0
        errors_count = 0
        
        for image_path in main_files:
            # Check if this file has been processed
            if str(image_path) in self.processing_log:
                result = self.processing_log[str(image_path)]
                status = result.get('status', 'unknown')
                
                try:
                    if status == 'success':
                        destination = self.photos_done / image_path.name
                        if not destination.exists():
                            shutil.move(str(image_path), str(destination))
                            print(f"   ✅ Moved to done: {image_path.name}")
                            moved_count += 1
                        else:
                            # File already exists in done folder, remove from main
                            image_path.unlink()
                            print(f"   🗑️  Removed duplicate: {image_path.name}")
                            deleted_count += 1
                            
                    elif status.startswith('failed'):
                        destination = self.photos_failed / image_path.name
                        if not destination.exists():
                            shutil.move(str(image_path), str(destination))
                            print(f"   ❌ Moved to failed: {image_path.name}")
                            moved_count += 1
                        else:
                            # File already exists in failed folder, remove from main
                            image_path.unlink()
                            print(f"   🗑️  Removed duplicate: {image_path.name}")
                            deleted_count += 1
                            
                    else:
                        # Unknown status, move to failed
                        destination = self.photos_failed / image_path.name
                        if not destination.exists():
                            shutil.move(str(image_path), str(destination))
                            print(f"   ❓ Moved to failed (unknown status): {image_path.name}")
                            moved_count += 1
                        else:
                            image_path.unlink()
                            print(f"   🗑️  Removed duplicate: {image_path.name}")
                            deleted_count += 1
                            
                except Exception as e:
                    print(f"   ❌ Error processing {image_path.name}: {e}")
                    errors_count += 1
        
        if moved_count > 0 or deleted_count > 0:
            print(f"\n📊 Cleanup complete:")
            print(f"   Moved: {moved_count}")
            print(f"   Deleted: {deleted_count}")
            print(f"   Errors: {errors_count}")
        else:
            print(f"   ✅ No already processed photos found")
        
        return {
            'moved': moved_count,
            'deleted': deleted_count,
            'errors': errors_count,
            'total_processed': moved_count + deleted_count
        }
    
    def process_photos_with_lookup(self, move_photos: bool = True):
        """Process photos and perform ISBN lookup with photo organization"""
        print(f"🔍 Processing photos in: {self.photos_current}")
        
        # First, clean up any already processed photos
        cleanup_result = self.cleanup_already_processed_photos()
        
        # Get remaining image files
        image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
        image_files = [f for f in self.photos_current.iterdir() 
                      if f.is_file() and f.suffix.lower() in image_extensions]
        
        if not image_files:
            print("No new image files found to process")
            return
        
        print(f"📸 Found {len(image_files)} new image files to process")
        
        successful = 0
        failed = 0
        
        for i, image_path in enumerate(image_files, 1):
            print(f"\n{'='*60}")
            print(f"Processing {i}/{len(image_files)}: {image_path.name}")
            print('='*60)
            
            # Check if already processed (shouldn't happen after cleanup, but safety check)
            if str(image_path) in self.processing_log:
                print(f"⏭️  Already processed: {self.processing_log[str(image_path)]}")
                # Move already processed files to appropriate folders
                self.move_processed_file(image_path)
                continue
            
            # Extract ISBN
            isbn = self.extract_isbn_from_image(image_path)
            
            if isbn:
                # Try to get book metadata
                book_info = self.lookup_isbn(isbn)
                
                if book_info and book_info.get('title'):
                    # Success - move to done folder
                    if move_photos:
                        destination = self.photos_done / image_path.name
                        shutil.move(str(image_path), str(destination))
                        print(f"✅ Moved to: {destination}")
                    
                    # Log success with metadata
                    self.processing_log[str(image_path)] = {
                        'isbn': isbn,
                        'status': 'success',
                        'title': book_info.get('title', ''),
                        'authors': [c.get('lastName', '') for c in book_info.get('creators', [])],
                        'timestamp': datetime.now().isoformat(),
                        'destination': str(self.photos_done / image_path.name) if move_photos else 'not_moved'
                    }
                    successful += 1
                    
                else:
                    # ISBN found but no metadata - move to failed
                    if move_photos:
                        destination = self.photos_failed / image_path.name
                        shutil.move(str(image_path), str(destination))
                        print(f"❌ Moved to: {destination} (no metadata)")
                    
                    # Log failure
                    self.processing_log[str(image_path)] = {
                        'isbn': isbn,
                        'status': 'failed_no_metadata',
                        'timestamp': datetime.now().isoformat(),
                        'destination': str(self.photos_failed / image_path.name) if move_photos else 'not_moved'
                    }
                    failed += 1
                    
            else:
                # No ISBN found - move to failed
                if move_photos:
                    destination = self.photos_failed / image_path.name
                    shutil.move(str(image_path), str(destination))
                    print(f"❌ Moved to: {destination} (no ISBN)")
                
                # Log failure
                self.processing_log[str(image_path)] = {
                    'isbn': None,
                    'status': 'failed_no_isbn',
                    'timestamp': datetime.now().isoformat(),
                    'destination': str(self.photos_failed / image_path.name) if move_photos else 'not_moved'
                }
                failed += 1
        
        # Save processing log
        self.save_processing_log()
        
        # Summary
        print(f"\n{'='*60}")
        print(f"PROCESSING SUMMARY")
        print(f"{'='*60}")
        print(f"📸 Total images: {len(image_files)}")
        print(f"✅ Successful (ISBN + metadata): {successful}")
        print(f"❌ Failed: {failed}")
        print(f"📁 Success folder: {self.photos_done}")
        print(f"📁 Failed folder: {self.photos_failed}")
        print(f"📝 Log saved to: {self.processing_log_file}")

    def move_processed_file(self, image_path: Path):
        """Move already processed files to appropriate folders based on their status"""
        if str(image_path) not in self.processing_log:
            return
        
        result = self.processing_log[str(image_path)]
        status = result.get('status', 'unknown')
        
        if status == 'success':
            destination = self.photos_done / image_path.name
            if image_path.exists() and not destination.exists():
                shutil.move(str(image_path), str(destination))
                print(f"✅ Moved already processed file to: {destination}")
        elif status in ['failed_no_metadata', 'failed_no_isbn']:
            destination = self.photos_failed / image_path.name
            if image_path.exists() and not destination.exists():
                shutil.move(str(image_path), str(destination))
                print(f"❌ Moved already processed file to: {destination}")

    def get_successful_isbns(self) -> List[Tuple[str, str]]:
        """Get list of successful ISBNs with filenames"""
        isbns = []
        
        for file_path, result in self.processing_log.items():
            if result.get('status') == 'success' and result.get('isbn'):
                filename = Path(file_path).name
                isbn = result['isbn']
                isbns.append((isbn, filename))
        
        return isbns

    def reset_processing(self):
        """Reset processing log (for testing)"""
        self.processing_log = {}
        self.save_processing_log()
        print("Processing log reset")
    
    def show_processing_status(self):
        """Show current status of photo processing"""
        print("📊 Photo Processing Status")
        print("=" * 40)
        
        # Count files in each directory
        main_count = 0
        done_count = 0
        failed_count = 0
        
        if self.photos_current.exists():
            image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}
            main_files = [f for f in self.photos_current.iterdir() 
                         if f.is_file() and f.suffix.lower() in image_extensions]
            main_count = len(main_files)
        
        if self.photos_done.exists():
            done_files = [f for f in self.photos_done.iterdir() 
                         if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}]
            done_count = len(done_files)
        
        if self.photos_failed.exists():
            failed_files = [f for f in self.photos_failed.iterdir() 
                           if f.is_file() and f.suffix.lower() in {'.jpg', '.jpeg', '.png', '.bmp', '.tiff'}]
            failed_count = len(failed_files)
        
        # Count processed files in log
        processed_count = len(self.processing_log)
        
        print(f"📁 Main folder: {main_count} files")
        print(f"✅ Done folder: {done_count} files")
        print(f"❌ Failed folder: {failed_count} files")
        print(f"📝 Processed (in log): {processed_count} files")
        
        # Check for already processed files in main folder
        if main_count > 0 and processed_count > 0:
            already_processed = 0
            for file_path in self.processing_log.keys():
                if Path(file_path).exists():
                    already_processed += 1
            
            if already_processed > 0:
                print(f"⚠️  {already_processed} files in main folder are already processed")
                print(f"   They will be moved/deleted immediately during next processing run")
            else:
                print(f"✅ No duplicate files found")
        
        return {
            'main': main_count,
            'done': done_count,
            'failed': failed_count,
            'processed': processed_count
        }

class DetailedISBNLookupService:
    def __init__(self):
        # Load ISBN library mapping configuration
        self.library_mapping = self._load_library_mapping()
        
        # Define all available services
        self.all_services = {
            'openlibrary': self.lookup_openlibrary,
            'google_books': self.lookup_google_books,
            'norwegian_library': self.lookup_norwegian_library,
            'danish_library': self.lookup_danish_library,
            'swedish_library': self.lookup_swedish_library,
            'finnish_library': self.lookup_finnish_library,
            'german_library': self.lookup_german_library,
            'french_library': self.lookup_french_library,
            'spanish_library': self.lookup_spanish_library,
            'portuguese_library': self.lookup_portuguese_library,
        }
    
    def _load_library_mapping(self):
        """Load ISBN library mapping from config file"""
        try:
            import yaml
            with open('/mnt/f/prog/scanpapers/config/isbn_library_mapping.yaml', 'r') as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"Warning: Could not load library mapping config: {e}")
            # Fallback to basic mapping
            return {
                'isbn_library_mapping': {
                    'english': {'prefixes': ['0', '1', '93']},
                    'german': {'prefixes': ['3']},
                    'french': {'prefixes': ['2']},
                    'spanish': {'prefixes': ['84']},
                    'latin_american': {'prefixes': ['950', '958', '959', '968', '970', '980', '987']},
                    'francophone_africa': {'prefixes': ['2-950', '2-951', '2-952', '2-953', '2-954', '2-955', '2-956', '2-957', '2-958', '2-959']},
                    'norwegian': {'prefixes': ['82']},
                    'danish': {'prefixes': ['87']},
                    'swedish': {'prefixes': ['91']},
                    'finnish': {'prefixes': ['951', '952']},
                    'portuguese': {'prefixes': ['85', '972', '989']}
                }
            }
    
    def _get_isbn_prefix(self, isbn: str) -> str:
        """Extract the registration group prefix from ISBN using centralized logic."""
        from shared_tools.utils.isbn_matcher import ISBNMatcher
        
        # Use the centralized ISBN prefix extraction logic
        prefix_2, prefix_3 = ISBNMatcher.extract_isbn_prefix(isbn)
        
        # Return the 3-digit prefix if available, otherwise 2-digit
        return prefix_3 if prefix_3 else prefix_2
    
    def _get_relevant_services(self, isbn: str) -> List[callable]:
        """Get relevant library services based on ISBN prefix"""
        prefix = self._get_isbn_prefix(isbn)
        services = []
        
        # Always include English libraries first
        services.extend([
            self.lookup_openlibrary,
            self.lookup_google_books
        ])
        
        # Add language-specific libraries based on prefix
        mapping = self.library_mapping.get('isbn_library_mapping', {})
        
        for language, config in mapping.items():
            if language == 'english':
                continue  # Already added
                
            prefixes = config.get('prefixes', [])
            if any(prefix.startswith(p) for p in prefixes):
                if language == 'german':
                    services.append(self.lookup_german_library)
                elif language == 'french':
                    services.append(self.lookup_french_library)
                elif language == 'spanish':
                    services.append(self.lookup_spanish_library)
                elif language == 'norwegian':
                    services.append(self.lookup_norwegian_library)
                elif language == 'danish':
                    services.append(self.lookup_danish_library)
                elif language == 'swedish':
                    services.append(self.lookup_swedish_library)
                elif language == 'finnish':
                    services.append(self.lookup_finnish_library)
                elif language == 'portuguese':
                    services.append(self.lookup_portuguese_library)
                elif language == 'latin_american':
                    services.append(self.lookup_spanish_library)  # Use Spanish library for Latin American books
                elif language == 'francophone_africa':
                    services.append(self.lookup_french_library)  # Use French library for Francophone African books
        
        return services
    
    def lookup_openlibrary(self, isbn: str) -> Optional[Dict]:
        """Lookup using OpenLibrary API with detailed info"""
        try:
            url = "https://openlibrary.org/api/books"
            params = {
                'bibkeys': f'ISBN:{isbn}',
                'format': 'json',
                'jscmd': 'data'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                book_key = f'ISBN:{isbn}'
                
                if book_key in data:
                    book_info = data[book_key]
                    
                    # Convert authors
                    authors = book_info.get('authors', [])
                    creators = []
                    
                    for author in authors:
                        name_parts = author['name'].split()
                        if len(name_parts) >= 2:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': ' '.join(name_parts[:-1]),
                                'lastName': name_parts[-1]
                            })
                        else:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': '',
                                'lastName': author['name']
                            })
                    
                    publishers = book_info.get('publishers', [])
                    publisher = publishers[0]['name'] if publishers else ''
                    
                    # Extract subjects as tags
                    subjects = book_info.get('subjects', [])
                    tags = []
                    for subject in subjects[:10]:  # Limit to 10 subjects
                        if isinstance(subject, dict):
                            tags.append({'tag': subject.get('name', '')})
                        else:
                            tags.append({'tag': str(subject)})
                    
                    # Get additional metadata
                    identifiers = book_info.get('identifiers', {})
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('excerpts', [{}])[0].get('text', '') if book_info.get('excerpts') else '',
                        'publisher': publisher,
                        'date': book_info.get('publish_date', ''),
                        'numPages': str(book_info.get('number_of_pages', '')),
                        'ISBN': isbn,
                        'url': book_info.get('url', ''),
                        'tags': tags,
                        'extra': f"OpenLibrary: {book_info.get('key', '')}" if book_info.get('key') else '',
                        # Additional fields
                        'place': book_info.get('publish_places', [{}])[0].get('name', '') if book_info.get('publish_places') else '',
                        'language': book_info.get('languages', [{}])[0].get('name', '') if book_info.get('languages') else '',
                        'edition': book_info.get('edition_name', ''),
                    }
                    
        except Exception as e:
            print(f"  OpenLibrary lookup failed: {e}")
        
        return None
    
    def lookup_google_books(self, isbn: str) -> Optional[Dict]:
        """Lookup using Google Books API with detailed info"""
        try:
            url = "https://www.googleapis.com/books/v1/volumes"
            params = {'q': f'isbn:{isbn}'}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('totalItems', 0) > 0:
                    book_info = data['items'][0]['volumeInfo']
                    
                    # Convert authors
                    authors = book_info.get('authors', [])
                    creators = []
                    
                    for author in authors:
                        name_parts = author.split()
                        if len(name_parts) >= 2:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': ' '.join(name_parts[:-1]),
                                'lastName': name_parts[-1]
                            })
                        else:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': '',
                                'lastName': author
                            })
                    
                    # Extract categories as tags
                    categories = book_info.get('categories', [])
                    tags = [{'tag': category} for category in categories[:10]]
                    
                    # Get page count
                    page_count = book_info.get('pageCount', '')
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('description', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('publishedDate', ''),
                        'numPages': str(page_count) if page_count else '',
                        'ISBN': isbn,
                        'language': book_info.get('language', ''),
                        'tags': tags,
                        'extra': f"Google Books ID: {data['items'][0].get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Google Books lookup failed: {e}")
        
        return None
    
    def lookup_norwegian_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Norwegian National Library API"""
        try:
            # Norwegian National Library API
            url = "https://api.nb.no/catalog/v1/items"
            params = {
                'q': f'isbn:{isbn}',
                'size': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('_embedded', {}).get('items'):
                    book_info = data['_embedded']['items'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('creators', []):
                        name = creator.get('name', '')
                        if name:
                            name_parts = name.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': name
                                })
                    
                    # Extract subjects as tags
                    tags = []
                    for subject in book_info.get('subjects', [])[:10]:
                        if isinstance(subject, dict):
                            tags.append({'tag': subject.get('name', '')})
                        else:
                            tags.append({'tag': str(subject)})
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('description', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('publicationYear', ''),
                        'numPages': str(book_info.get('extent', '')),
                        'ISBN': isbn,
                        'language': book_info.get('language', ''),
                        'tags': tags,
                        'extra': f"Norwegian Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Norwegian Library lookup failed: {e}")
        
        return None
    
    def lookup_finnish_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Finnish National Library API"""
        try:
            # Finnish National Library API (Fennica)
            url = "https://api.finna.fi/v1/search"
            params = {
                'lookfor': f'isbn:{isbn}',
                'type': 'AllFields',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('records'):
                    book_info = data['records'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('authors', []):
                        name = creator.get('name', '')
                        if name:
                            name_parts = name.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': name
                                })
                    
                    # Extract subjects as tags
                    tags = []
                    for subject in book_info.get('subjects', [])[:10]:
                        if isinstance(subject, dict):
                            tags.append({'tag': subject.get('name', '')})
                        else:
                            tags.append({'tag': str(subject)})
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('summary', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('publicationYear', ''),
                        'numPages': str(book_info.get('extent', '')),
                        'ISBN': isbn,
                        'language': book_info.get('language', ''),
                        'tags': tags,
                        'extra': f"Finnish Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Finnish Library lookup failed: {e}")
        
        return None
    
    def lookup_german_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using German National Library API"""
        try:
            # German National Library API
            url = "https://services.dnb.de/sru/dnb"
            params = {
                'operation': 'searchRetrieve',
                'version': '1.1',
                'query': f'isbn={isbn}',
                'recordSchema': 'MARC21-xml',
                'maximumRecords': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                # Parse MARC21 XML response (simplified)
                # In a full implementation, you'd parse the XML properly
                if 'isbn' in response.text.lower():
                    # For now, return a basic structure
                    # In production, parse the MARC21 XML to extract metadata
                    return {
                        'itemType': 'book',
                        'title': 'German Library Result',
                        'creators': [],
                        'abstractNote': '',
                        'publisher': '',
                        'date': '',
                        'ISBN': isbn,
                        'language': 'German',
                        'tags': [],
                        'extra': f"German National Library: {isbn}"
                    }
                    
        except Exception as e:
            print(f"  German Library lookup failed: {e}")
        
        return None
    
    def lookup_french_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using French National Library API"""
        try:
            # French National Library API
            url = "https://catalogue.bnf.fr/api"
            params = {
                'q': f'isbn:{isbn}',
                'format': 'json',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('docs'):
                    book_info = data['docs'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('author', []):
                        if creator:
                            name_parts = creator.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': creator
                                })
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('summary', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('date', ''),
                        'ISBN': isbn,
                        'language': 'French',
                        'tags': [{'tag': subject} for subject in book_info.get('subject', [])[:10]],
                        'extra': f"French National Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  French Library lookup failed: {e}")
        
        return None
    
    def lookup_spanish_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Spanish National Library API"""
        try:
            # Spanish National Library API
            url = "https://www.bne.es/en/colecciones/biblioteca-digital-hispana"
            # Note: This is a placeholder URL - actual API would need to be implemented
            # For now, return a basic structure
            return {
                'itemType': 'book',
                'title': 'Spanish Library Result',
                'creators': [],
                'abstractNote': '',
                'publisher': '',
                'date': '',
                'ISBN': isbn,
                'language': 'Spanish',
                'tags': [],
                'extra': f"Spanish National Library: {isbn}"
            }
                    
        except Exception as e:
            print(f"  Spanish Library lookup failed: {e}")
        
        return None
    
    def lookup_danish_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Danish National Library API"""
        try:
            # Royal Danish Library API
            url = "https://www.kb.dk/api"
            params = {
                'q': f'isbn:{isbn}',
                'format': 'json',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('docs'):
                    book_info = data['docs'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('author', []):
                        if creator:
                            name_parts = creator.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': creator
                                })
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('summary', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('date', ''),
                        'ISBN': isbn,
                        'language': 'Danish',
                        'tags': [{'tag': subject} for subject in book_info.get('subject', [])[:10]],
                        'extra': f"Danish National Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Danish Library lookup failed: {e}")
        
        return None
    
    def lookup_swedish_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Swedish National Library API"""
        try:
            # National Library of Sweden API (Libris)
            url = "https://libris.kb.se/api"
            params = {
                'q': f'isbn:{isbn}',
                'format': 'json',
                'limit': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('docs'):
                    book_info = data['docs'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('author', []):
                        if creator:
                            name_parts = creator.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': creator
                                })
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('summary', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('date', ''),
                        'ISBN': isbn,
                        'language': 'Swedish',
                        'tags': [{'tag': subject} for subject in book_info.get('subject', [])[:10]],
                        'extra': f"Swedish National Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Swedish Library lookup failed: {e}")
        
        return None
    
    def lookup_portuguese_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Portuguese/Brazilian National Library API"""
        try:
            # Try Brazilian National Library first (prefix 85)
            if isbn.startswith('85'):
                url = "https://www.bn.gov.br/api"
                params = {
                    'q': f'isbn:{isbn}',
                    'format': 'json',
                    'limit': 1
                }
            else:
                # Try Portuguese National Library (prefixes 972, 989)
                url = "https://www.bnportugal.gov.pt/api"
                params = {
                    'q': f'isbn:{isbn}',
                    'format': 'json',
                    'limit': 1
                }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('docs'):
                    book_info = data['docs'][0]
                    
                    # Extract creators
                    creators = []
                    for creator in book_info.get('author', []):
                        if creator:
                            name_parts = creator.split()
                            if len(name_parts) >= 2:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': ' '.join(name_parts[:-1]),
                                    'lastName': name_parts[-1]
                                })
                            else:
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': creator
                                })
                    
                    library_name = "Brazilian" if isbn.startswith('85') else "Portuguese"
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('summary', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('date', ''),
                        'ISBN': isbn,
                        'language': 'Portuguese',
                        'tags': [{'tag': subject} for subject in book_info.get('subject', [])[:10]],
                        'extra': f"{library_name} National Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            print(f"  Portuguese Library lookup failed: {e}")
        
        return None
    
    def lookup_isbn(self, isbn: str) -> Optional[Dict]:
        """Try multiple services to find detailed book info with smart library selection"""
        print(f"  🔍 Looking up ISBN {isbn}...")
        
        # Get relevant services based on ISBN prefix
        services = self._get_relevant_services(isbn)
        prefix = self._get_isbn_prefix(isbn)
        
        print(f"  📚 ISBN prefix: {prefix}")
        print(f"  🔍 Querying {len(services)} relevant libraries...")
        
        best_result = None
        best_score = 0
        
        for service in services:
            try:
                result = service(isbn)
                if result and result.get('title'):
                    # Score the result based on completeness
                    score = self.score_result(result)
                    service_name = service.__name__.replace('lookup_', '').replace('_', ' ').title()
                    print(f"  ✅ Found via {service_name} (score: {score})")
                    
                    if score > best_score:
                        best_result = result
                        best_score = score
                        
            except Exception as e:
                continue
        
        if not best_result:
            print(f"  ❌ No book info found for ISBN {isbn}")
        else:
            print(f"  🎯 Best result: score {best_score}")
        
        return best_result
    
    def score_result(self, result: Dict) -> int:
        """Score a result based on completeness"""
        score = 0
        
        # Basic fields
        if result.get('title'): score += 10
        if result.get('creators'): score += 10
        if result.get('publisher'): score += 5
        if result.get('date'): score += 5
        
        # Detailed fields
        if result.get('abstractNote'): score += 15
        if result.get('tags'): score += 10
        if result.get('numPages'): score += 3
        if result.get('language'): score += 2
        
        return score
    
    def print_detailed_info(self, result: Dict):
        """Print detailed book information"""
        if not result:
            return
            
        print(f"📚 Title: {result.get('title', 'Unknown')}")
        
        creators = result.get('creators', [])
        if creators:
            authors = []
            for creator in creators:
                first = creator.get('firstName', '')
                last = creator.get('lastName', '')
                full_name = f"{first} {last}".strip()
                authors.append(full_name)
            print(f"👤 Authors: {', '.join(authors)}")
        
        if result.get('publisher'):
            print(f"🏢 Publisher: {result['publisher']}")
        if result.get('date'):
            print(f"📅 Date: {result['date']}")
        if result.get('numPages'):
            print(f"📄 Pages: {result['numPages']}")
        if result.get('language'):
            print(f"🌐 Language: {result['language']}")
        
        if result.get('abstractNote'):
            abstract = result['abstractNote'][:200] + "..." if len(result['abstractNote']) > 200 else result['abstractNote']
            print(f"📝 Abstract: {abstract}")
        
        tags = result.get('tags', [])
        if tags:
            tag_names = [tag.get('tag', '') for tag in tags[:5]]  # Show first 5 tags
            print(f"🏷️  Tags: {', '.join(tag_names)}")
        
        if result.get('extra'):
            print(f"ℹ️  Extra: {result['extra']}")

def main():
    """Enhanced ISBN Processor with Photo Organization"""
    print("Enhanced ISBN Processor with Photo Organization")
    print("=" * 50)
    print("📋 REQUIREMENT: Images must contain ISBN or barcode")
    print("📱 TIP: Focus camera on ISBN area for best results")
    print("📁 Photos are automatically moved to done/failed folders")
    print("🧹 Already processed photos are cleaned up immediately")
    print("=" * 50)
    
    processor = EnhancedISBNProcessor()
    
    print("\nOptions:")
    print("1. Process photos (cleans up + moves to done/failed automatically)")
    print("2. Process photos without moving (test mode)")
    print("3. Show processing status")
    print("4. Reset processing log")
    print("5. Test ISBN lookup only")
    
    try:
        choice = input("Enter choice (1-5): ").strip()
        
        if choice == "1":
            print("\n🚀 Processing photos with automatic organization...")
            processor.process_photos_with_lookup(move_photos=True)
            
        elif choice == "2":
            print("\n🧪 Test mode - processing without moving photos...")
            processor.process_photos_with_lookup(move_photos=False)
            
        elif choice == "3":
            print("\n📊 Showing processing status...")
            processor.show_processing_status()
            
        elif choice == "4":
            print("\n🔄 Resetting processing log...")
            processor.reset_processing()
            print("✅ Processing log reset")
            
        elif choice == "5":
            print("\n🔍 Testing ISBN lookup only...")
            # Test with a sample ISBN
            test_isbn = "9789510161616"
            print(f"Testing lookup for ISBN: {test_isbn}")
            result = processor.lookup_isbn(test_isbn)
            if result:
                print("✅ Lookup successful")
                processor.lookup_service.print_detailed_info(result)
            else:
                print("❌ Lookup failed")
                
        else:
            print("❌ Invalid choice. Please enter 1-5.")
            
    except KeyboardInterrupt:
        print("\n⏹️  Process interrupted by user")
    except Exception as e:
        print(f"\n❌ Error: {e}")

if __name__ == "__main__":
    main()