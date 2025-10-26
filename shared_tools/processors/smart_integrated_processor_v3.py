"""
Smart integrated image processor v2 - with better success criteria
"""

import cv2
import numpy as np
from pyzbar import pyzbar
import pytesseract
import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, Tuple, List
import time
import re
from collections import Counter
import concurrent.futures
import signal
import configparser
from ..utils.thread_pool_manager import thread_pool_manager

@dataclass
class ImageData:
    """Processed image data"""
    filename: str
    barcode: Optional[str] = None
    ocr_text: Optional[str] = None
    preprocessing_used: str = "none"
    attempts: int = 0
    processing_time: float = 0.0
    all_isbns: List[str] = None  # Store all found ISBNs

@dataclass
class ImageStats:
    """Image statistics for intelligent processing"""
    is_landscape: bool
    should_rotate: bool  # New field for rotation decision
    is_dark: bool
    white_percentage: float
    has_color: bool
    mean_brightness: float

class SmartIntegratedProcessorV3:
    """Smart processor with Intel GPU optimization and fast processing"""
    
    def __init__(self, photo_batch: List[Path] = None):
        self.logger = logging.getLogger(__name__)
        cv2.setUseOptimized(True)
        
        # Load configuration
        config = configparser.ConfigParser()
        config.read("config/process_books.conf")
        self.ocr_timeout = config.getint('processing', 'ocr_timeout', fallback=60)
        
        # Initialize CPU throttling
        max_concurrent = config.getint('processing', 'max_concurrent_tesseract', fallback=4)
        cpu_threshold = config.getfloat('processing', 'cpu_threshold', fallback=80.0)
        throttle_delay = config.getfloat('processing', 'throttle_delay', fallback=1.0)
        check_interval = config.getfloat('processing', 'cpu_check_interval', fallback=2.0)
        
        thread_pool_manager.initialize(
            max_workers=max_concurrent,
            cpu_threshold=cpu_threshold,
            throttle_delay=throttle_delay,
            check_interval=check_interval
        )
        
        # Enable Intel GPU acceleration
        try:
            cv2.setUseOptimized(True)
            # Intel GPU acceleration
            cv2.ocl.setUseOpenCL(True)
            # Set number of threads for Intel optimization
            cv2.setNumThreads(4)
            self.logger.info("Intel GPU acceleration enabled")
        except Exception as e:
            self.logger.warning(f"Intel GPU acceleration not available: {e}")
            # Fall back to basic optimization
            try:
                cv2.setUseOptimized(True)
            except:
                pass
        
        # Maximum attempts based on image difficulty
        self.max_attempts_easy = 8  # Increased from 5
        self.max_attempts_hard = 20
        
        # ISBN pattern for quick check
        self.isbn_pattern = re.compile(r'\b(?:ISBN|isbn|Isbn)|\b\d{9,13}[\dX]\b|\b\d{1,5}[\s\-]\d{1,7}[\s\-]\d{1,7}[\s\-][\dX]\b')
        
        # Fast processing settings
        self.fast_resize_factor = 0.25  # Process at 25% size first
        
        # Analyze batch to detect full frame size
        self.full_frame_size = None
        self.long_side_full = None
        self.short_side_full = None
        if photo_batch:
            self.detect_full_frame_size(photo_batch)
    
    def has_potential_isbn(self, text: str) -> bool:
        """Check if text likely contains ISBN"""
        if not text:
            return False
        
        # Check for ISBN keyword or ISBN-like patterns
        return bool(self.isbn_pattern.search(text))
    
    def _process_strategies_with_images(self, strategies, rotated_images, result, size_suffix, size_description):
        """
        Process strategies with given rotated images.
        
        Args:
            strategies: List of (strategy_name, strategy_func) tuples
            rotated_images: Dict of rotation_name -> image
            result: ImageData object to update
            size_suffix: Suffix for preprocessing_used (e.g., "_small", "_full")
            size_description: Description for logging (e.g., "small image", "full-size")
            
        Returns:
            bool: True if ISBN found, False otherwise
        """
        found_isbn = False
        
        for strategy_name, strategy_func in strategies:
            result.attempts += 1
            print(f"    Trying strategy {result.attempts}/{len(strategies)*2}: {strategy_name} ({size_description})")
            self.logger.debug(f"Attempt {result.attempts}: {strategy_name} ({size_description})")
            
            try:
                # Apply timeout to entire strategy (all rotations)
                strategy_start_time = time.time()
                
                # Submit all rotation attempts using global thread pool
                future_to_rotation = {}
                for rotation_name, rotated_img in rotated_images.items():
                    future = thread_pool_manager.submit(strategy_func, rotated_img)
                    future_to_rotation[future] = rotation_name
                
                # Wait for first successful result or timeout
                try:
                    for future in concurrent.futures.as_completed(future_to_rotation, timeout=self.ocr_timeout):
                        text = future.result()
                        if text and self.has_potential_isbn(text):  # Found text with potential ISBN
                            rotation_name = future_to_rotation[future]
                            strategy_time = time.time() - strategy_start_time
                            result.ocr_text = text
                            result.preprocessing_used = f"{strategy_name}_{rotation_name}{size_suffix}"
                            self.logger.info(f"✅ Found potential ISBN text with {strategy_name} on {rotation_name} ({size_description}) after {result.attempts} attempts (strategy took {strategy_time:.1f}s)")
                            found_isbn = True
                            break
                        elif text:  # Found text but no ISBN pattern
                            rotation_name = future_to_rotation[future]
                            strategy_time = time.time() - strategy_start_time
                            self.logger.debug(f"Found text with {strategy_name} on {rotation_name} ({size_description}) but no ISBN pattern (strategy took {strategy_time:.1f}s)")
                            # Continue trying other strategies
                except concurrent.futures.TimeoutError:
                    strategy_time = time.time() - strategy_start_time
                    self.logger.warning(f"Strategy {strategy_name} ({size_description}) timeout after {self.ocr_timeout}s (actual time: {strategy_time:.1f}s)")
                
                if found_isbn:
                    break
                        
            except Exception as e:
                self.logger.debug(f"Strategy {strategy_name} ({size_description}) failed: {e}")
                continue
        
        return found_isbn
    
    def detect_full_frame_size(self, photo_batch: List[Path]):
        """Detect the full frame size from first 10 photos"""
        sizes = []
        
        # Check first 10 photos (or all if less)
        for photo_path in photo_batch[:10]:
            try:
                img = cv2.imread(str(photo_path))
                if img is not None:
                    h, w = img.shape[:2]
                    # Order sizes to always have largest dimension first
                    long_side = max(w, h)
                    short_side = min(w, h)
                    sizes.append((long_side, short_side))
                else:
                    sizes.append((h, w)) # when they are the same size
            except:
                continue
        
        if not sizes:
            return
        
        # Count size frequencies
        size_counts = Counter(sizes)
        
        # Find most common size (if it appears in >40% of samples)
        most_common_size, count = size_counts.most_common(1)[0]
        
        if count >= len(sizes) * 0.4:  # 40% threshold
            self.long_side_full, self.short_side_full = most_common_size
            self.full_frame_size = (self.long_side_full, self.short_side_full)
            self.logger.info(f"Detected full frame size: {self.long_side_full}x{self.short_side_full} "
                           f"(found in {count}/{len(sizes)} photos)")
    
    def is_cropped_photo(self, image_size: Tuple[int, int]) -> bool:
        """Determine if photo is cropped based on size"""
        if not self.full_frame_size:
            return False
        
        width, height = image_size

        # Normalize current photo dimensions
        long_side = max(width, height)
        short_side = min(width, height)

        # Photo is cropped if either dimension is smaller than full frame
        is_cropped = long_side < self.long_side_full or short_side < self.short_side_full
        
        if is_cropped:
            self.logger.info(f"Detected cropped photo: {width}x{height} vs full frame {self.long_side_full}x{self.short_side_full}")
        
        return is_cropped
    
    def fast_rotation_detection(self, image: np.ndarray) -> Optional[str]:
        """Fast rotation detection using small image and ISBN keyword"""
        # Safety check
        if image is None or image.size == 0:
            return None
            
        # Resize to 25% for fast processing
        height, width = image.shape[:2]
        small_height = int(height * self.fast_resize_factor)
        small_width = int(width * self.fast_resize_factor)
        small_image = cv2.resize(image, (small_width, small_height))
        
        # Create rotated versions of small image
        rotations = {
            'original': small_image,
            'rotated_270': cv2.rotate(small_image, cv2.ROTATE_90_COUNTERCLOCKWISE),
            'rotated_90': cv2.rotate(small_image, cv2.ROTATE_90_CLOCKWISE),
            'rotated_180': cv2.rotate(small_image, cv2.ROTATE_180)
        }
        
        # Try fast OCR on each rotation
        for rotation_name, rotated_img in rotations.items():
            try:
                # Fast OCR without timeout (timeout not supported by pytesseract)
                text = pytesseract.image_to_string(rotated_img, config='--oem 3 --psm 6')
                if 'ISBN' in text.upper() or self.has_potential_isbn(text):
                    self.logger.info(f"Fast rotation detection: found ISBN pattern in {rotation_name}")
                    return rotation_name
            except Exception as e:
                self.logger.debug(f"Fast rotation detection failed for {rotation_name}: {e}")
                continue
        
        return None
    
    def analyze_image(self, image: np.ndarray) -> ImageStats:
        """Analyze image statistics for intelligent processing decisions"""
        height, width = image.shape[:2]
        is_landscape = width > height
        
        # Check if cropped using batch-based detection
        is_cropped = self.is_cropped_photo((width, height))
        
        # Determine if we should rotate
        # If landscape AND not cropped, probably needs rotation
        # If landscape AND cropped, keep as is
        should_rotate = is_landscape and not is_cropped
        
        has_color = len(image.shape) == 3
        
        # Convert to grayscale for analysis
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if has_color else image
        
        # Calculate brightness statistics
        mean_brightness = np.mean(gray)
        
        # Calculate white percentage (pixels > 200)
        white_pixels = np.sum(gray > 200)
        total_pixels = gray.shape[0] * gray.shape[1]
        white_percentage = (white_pixels / total_pixels) * 100
        
        # Determine if image is dark (needs inversion)
        is_dark = white_percentage < 15 or mean_brightness < 100
        
        stats = ImageStats(
            is_landscape=is_landscape,
            should_rotate=should_rotate,
            is_dark=is_dark,
            white_percentage=white_percentage,
            has_color=has_color,
            mean_brightness=mean_brightness
        )
        
        self.logger.info(f"Image stats: size={width}x{height}, landscape={is_landscape}, "
                        f"cropped={is_cropped}, should_rotate={should_rotate}, "
                        f"dark={is_dark}, white%={white_percentage:.1f}, brightness={mean_brightness:.0f}")
        
        return stats
    
    def orient_image(self, image: np.ndarray, stats: ImageStats) -> np.ndarray:
        """Orient image to portrait only if needed"""
        if stats.should_rotate:
            self.logger.info("Rotating landscape to portrait")
            return cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        elif stats.is_landscape:
            self.logger.info("Keeping landscape orientation (detected as cropped image)")
        return image
    
    def _perform_ocr(self, image: np.ndarray, config: str) -> Optional[str]:
        """Perform OCR with given config and timeout - only return if likely contains ISBN"""
        try:
            # Use timeout to prevent hanging on difficult images
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(pytesseract.image_to_string, image, config=config)
                text = future.result(timeout=self.ocr_timeout)
            
            # Only return text if it looks like it might contain ISBN
            if text.strip() and self.has_potential_isbn(text):
                self.logger.debug(f"Found potential ISBN text with {config}")
                return text.strip()
            elif text.strip():
                self.logger.debug(f"Found text but no ISBN pattern with {config}: {text[:30]}...")
                
        except concurrent.futures.TimeoutError:
            self.logger.warning(f"OCR timeout after {self.ocr_timeout}s with {config}")
        except Exception as e:
            self.logger.debug(f"OCR failed with {config}: {e}")
        return None
    
    def get_processing_strategies(self, image: np.ndarray, stats: ImageStats) -> List[Tuple[str, callable]]:
        """Get ordered list of processing strategies based on image statistics"""
        strategies = []
        
        # Barcode detection is now done early in process_photo
        # No need to include it in strategies
        
        # For dark images, try inversion early
        if stats.is_dark:
            strategies.append(("inverted_full", lambda img: self._ocr_inverted_full(img)))
            strategies.append(("inverted_top", lambda img: self._ocr_inverted_top(img)))
        
        # Standard strategies with rotation
        strategies.append(("top_third_standard", lambda img: self._ocr_top_third_standard(img)))
        strategies.append(("full_standard", lambda img: self._ocr_full_standard(img)))
        
        # Adaptive threshold
        strategies.append(("adaptive_threshold", lambda img: self._ocr_adaptive(img)))
        
        # Color channel separation (if color and especially if dark)
        if stats.has_color:
            strategies.append(("red_channel", lambda img: self._ocr_red_channel(img)))
            if stats.is_dark:
                strategies.append(("red_inverted", lambda img: self._ocr_red_inverted(img)))
        
        # High contrast
        strategies.append(("high_contrast", lambda img: self._ocr_high_contrast(img)))
        
        # Different OCR modes
        strategies.append(("ocr_single_line", lambda img: self._ocr_single_line(img)))
        strategies.append(("ocr_sparse_text", lambda img: self._ocr_sparse_text(img)))
        
        # Try rotations as last resort
        if not stats.should_rotate:  # Only if we didn't already rotate
            strategies.append(("rotation_90", lambda img: self._ocr_rotated(img, 90)))
        
        return strategies
    
    def _extract_top_third(self, image: np.ndarray) -> np.ndarray:
        """Extract top third of image"""
        height = image.shape[0]
        return image[0:height//3, :]
    
    def _ocr_inverted_full(self, image: np.ndarray) -> Optional[str]:
        """OCR on inverted full image"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        inverted = cv2.bitwise_not(gray)
        return self._perform_ocr(inverted, "--oem 3 --psm 6")
    
    def _ocr_inverted_top(self, image: np.ndarray) -> Optional[str]:
        """OCR on inverted top third"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        top = self._extract_top_third(gray)
        inverted = cv2.bitwise_not(top)
        return self._perform_ocr(inverted, "--oem 3 --psm 8")
    
    def _ocr_top_third_standard(self, image: np.ndarray) -> Optional[str]:
        """OCR on top third with standard preprocessing"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        top_third = self._extract_top_third(gray)
        
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(top_third)
        
        return self._perform_ocr(enhanced, "--oem 3 --psm 8")
    
    def _ocr_full_standard(self, image: np.ndarray) -> Optional[str]:
        """OCR on full image with standard preprocessing"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8,8))
        enhanced = clahe.apply(gray)
        
        return self._perform_ocr(enhanced, "--oem 3 --psm 6")
    
    def _ocr_adaptive(self, image: np.ndarray) -> Optional[str]:
        """OCR with adaptive threshold"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                        cv2.THRESH_BINARY, 11, 2)
        
        return self._perform_ocr(adaptive, "--oem 3 --psm 11")
    
    def _ocr_red_channel(self, image: np.ndarray) -> Optional[str]:
        """OCR on red channel"""
        if len(image.shape) != 3:
            return None
        
        _, _, r = cv2.split(image)
        return self._perform_ocr(r, "--oem 3 --psm 8")
    
    def _ocr_red_inverted(self, image: np.ndarray) -> Optional[str]:
        """OCR on inverted red channel"""
        if len(image.shape) != 3:
            return None
        
        _, _, r = cv2.split(image)
        inverted = cv2.bitwise_not(r)
        return self._perform_ocr(inverted, "--oem 3 --psm 8")
    
    def _ocr_high_contrast(self, image: np.ndarray) -> Optional[str]:
        """OCR with high contrast preprocessing"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        
        alpha = 2.5
        beta = 0
        contrast = cv2.convertScaleAbs(gray, alpha=alpha, beta=beta)
        
        _, binary = cv2.threshold(contrast, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        
        return self._perform_ocr(binary, "--oem 3 --psm 7")
    
    def _ocr_single_line(self, image: np.ndarray) -> Optional[str]:
        """OCR optimized for single line"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        return self._perform_ocr(gray, "--oem 3 --psm 7")
    
    def _ocr_sparse_text(self, image: np.ndarray) -> Optional[str]:
        """OCR optimized for sparse text"""
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if len(image.shape) == 3 else image
        return self._perform_ocr(gray, "--oem 3 --psm 11")
    
    def _ocr_rotated(self, image: np.ndarray, angle: int) -> Optional[str]:
        """OCR with rotation"""
        if angle == 90:
            rotated = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        elif angle == 180:
            rotated = cv2.rotate(image, cv2.ROTATE_180)
        else:
            rotated = image
            
        gray = cv2.cvtColor(rotated, cv2.COLOR_BGR2GRAY) if len(rotated.shape) == 3 else rotated
        return self._perform_ocr(gray, "--oem 3 --psm 6")
    
    def detect_barcode(self, image: np.ndarray) -> Optional[str]:
        """Detect barcode with confidence and preprocessing for difficult cases"""
        try:
            # Try original image first
            barcodes = pyzbar.decode(image)
            for barcode in barcodes:
                if barcode.type in ['EAN13', 'EAN8', 'CODE128']:
                    data = barcode.data.decode('utf-8')
                    self.logger.info(f"Barcode detected: {data}")
                    return data
            
            # If no barcode found, try with preprocessing for difficult cases
            # Convert to grayscale for better contrast
            if len(image.shape) == 3:
                gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            else:
                gray = image.copy()
            
            # Check if we have a non-white background (low white percentage)
            white_pixels = np.sum(gray > 200)
            total_pixels = gray.shape[0] * gray.shape[1]
            white_percentage = (white_pixels / total_pixels) * 100
            
            # Try with enhanced contrast
            enhanced = cv2.convertScaleAbs(gray, alpha=1.5, beta=30)
            barcodes = pyzbar.decode(enhanced)
            for barcode in barcodes:
                if barcode.type in ['EAN13', 'EAN8', 'CODE128']:
                    data = barcode.data.decode('utf-8')
                    self.logger.info(f"Barcode detected (enhanced): {data}")
                    return data
            
            # If low white percentage, try extreme contrast enhancement
            if white_percentage < 30:  # Less than 30% white pixels
                self.logger.debug(f"Low white percentage ({white_percentage:.1f}%), trying extreme contrast")
                
                # Apply non-linear contrast enhancement to amplify dark/light differences
                # Use gamma correction with gamma < 1 to make dark areas darker and light areas lighter
                gamma = 0.3  # Strong gamma correction for maximum contrast
                extreme_contrast = np.power(gray / 255.0, gamma) * 255.0
                extreme_contrast = extreme_contrast.astype(np.uint8)
                barcodes = pyzbar.decode(extreme_contrast)
                for barcode in barcodes:
                    if barcode.type in ['EAN13', 'EAN8', 'CODE128']:
                        data = barcode.data.decode('utf-8')
                        self.logger.info(f"Barcode detected (extreme contrast): {data}")
                        return data
                
                # Try histogram equalization for very difficult cases
                equalized = cv2.equalizeHist(gray)
                barcodes = pyzbar.decode(equalized)
                for barcode in barcodes:
                    if barcode.type in ['EAN13', 'EAN8', 'CODE128']:
                        data = barcode.data.decode('utf-8')
                        self.logger.info(f"Barcode detected (equalized): {data}")
                        return data
            
            # Try with adaptive threshold for very difficult cases
            adaptive = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 11, 2)
            barcodes = pyzbar.decode(adaptive)
            for barcode in barcodes:
                if barcode.type in ['EAN13', 'EAN8', 'CODE128']:
                    data = barcode.data.decode('utf-8')
                    self.logger.info(f"Barcode detected (adaptive): {data}")
                    return data
                    
        except Exception as e:
            self.logger.debug(f"Barcode detection failed: {e}")
        return None
    
    def detect_barcode_with_rotation(self, image: np.ndarray) -> Optional[str]:
        """Detect barcode trying multiple orientations"""
        # Try original orientation
        result = self.detect_barcode(image)
        if result:
            return result
        
        # Try 270° rotation (counter-clockwise)
        rotated_270 = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
        result = self.detect_barcode(rotated_270)
        if result:
            self.logger.info("Barcode detected after 270° rotation")
            return result
        
        # Try 90° rotation (clockwise)
        rotated_90 = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
        result = self.detect_barcode(rotated_90)
        if result:
            self.logger.info("Barcode detected after 90° rotation")
            return result
        
        # Try 180° rotation
        rotated_180 = cv2.rotate(image, cv2.ROTATE_180)
        result = self.detect_barcode(rotated_180)
        if result:
            self.logger.info("Barcode detected after 180° rotation")
            return result
        
        return None
    
    def process_photo(self, photo_path: Path) -> ImageData:
        """Process photo with smart strategy ordering"""
        start_time = time.time()
        result = ImageData(filename=photo_path.name, all_isbns=[])
        
        try:
            # Load image
            image = cv2.imread(str(photo_path))
            if image is None:
                self.logger.error(f"Could not load {photo_path}")
                return result
            
            self.logger.info(f"\nProcessing {photo_path.name}")
            
            # Analyze image statistics
            stats = self.analyze_image(image)
            
            # First try barcode detection with rotation (fastest)
            barcode_result = self.detect_barcode_with_rotation(image)
            if barcode_result:
                result.attempts += 1  # Count early barcode detection as attempt 1
                self.logger.info(f"Barcode found early: {barcode_result}")
                result.barcode = barcode_result
                result.preprocessing_used = "barcode_early"
                result.processing_time = time.time() - start_time
                return result
            
            # If no barcode, try fast rotation detection for OCR
            fast_rotation = self.fast_rotation_detection(image)
            if fast_rotation and fast_rotation != 'original':
                self.logger.info(f"Fast rotation detection: applying {fast_rotation}")
                if fast_rotation == 'rotated_270':
                    image = cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE)
                elif fast_rotation == 'rotated_90':
                    image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
                elif fast_rotation == 'rotated_180':
                    image = cv2.rotate(image, cv2.ROTATE_180)
            else:
                # Fall back to original orientation logic
                image = self.orient_image(image, stats)
            
            # Create small image for fast processing (same as fast_rotation_detection)
            height, width = image.shape[:2]
            small_height = int(height * self.fast_resize_factor)
            small_width = int(width * self.fast_resize_factor)
            small_image = cv2.resize(image, (small_width, small_height))
            
            # Create rotated versions for both sizes
            rotated_images_full = {
                'original': image,
                'rotated_270': cv2.rotate(image, cv2.ROTATE_90_COUNTERCLOCKWISE),
                'rotated_90': cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE),
                'rotated_180': cv2.rotate(image, cv2.ROTATE_180)
            }
            
            rotated_images_small = {
                'original': small_image,
                'rotated_270': cv2.rotate(small_image, cv2.ROTATE_90_COUNTERCLOCKWISE),
                'rotated_90': cv2.rotate(small_image, cv2.ROTATE_90_CLOCKWISE),
                'rotated_180': cv2.rotate(small_image, cv2.ROTATE_180)
            }
            
            # Get processing strategies
            strategies = self.get_processing_strategies(image, stats)
            
            self.logger.info(f"Will try up to {len(strategies) * 2} strategies (two-tier: small images first, then full-size)")
            
            # TIER 1: Try small images first (faster, better for blurry images)
            found_isbn = False
            self.logger.info("Tier 1: Processing with small images (25% size)")
            found_isbn = self._process_strategies_with_images(strategies, rotated_images_small, result, "_small", "small image")
            
            # TIER 2: If no success with small images, try full-size images
            if not found_isbn:
                self.logger.info("Tier 2: Processing with full-size images (fallback)")
                found_isbn = self._process_strategies_with_images(strategies, rotated_images_full, result, "_full", "full-size")
            
            if not found_isbn:
                self.logger.warning(f"❌ No ISBN-like text found after {result.attempts} attempts")
            
        except Exception as e:
            self.logger.error(f"Error processing {photo_path}: {e}")
        
        result.processing_time = time.time() - start_time
        self.logger.info(f"Processing took {result.processing_time:.1f} seconds")
        
        return result
