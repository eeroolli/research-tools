#!/usr/bin/env python3
"""
Content-aware detection for border removal and gutter detection.

Uses binary search edge detection to find text content regions,
avoiding false positives from dark borders and edge artifacts.
"""

import logging
from typing import Optional, Tuple, Dict, Any, List
import cv2
import numpy as np
import fitz  # PyMuPDF
from pathlib import Path


class ContentDetector:
    """Detects text content regions using binary search edge detection."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize content detector.
        
        Args:
            config: Configuration dictionary with optional keys:
                - default_density_threshold: Default text density threshold (default: 0.15)
                - safety_margin_pct: Safety margin percentage (default: 0.10 = 10%)
                - middle_region_pct: Middle region percentage for sampling (default: 0.3 = 35-65%)
                - gutter_min_percent: Minimum gutter position as % of page width (default: 40)
                - gutter_max_percent: Maximum gutter position as % of page width (default: 60)
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Configuration parameters
        self.default_density_threshold = self.config.get('default_density_threshold', 0.15)
        self.safety_margin_pct = self.config.get('safety_margin_pct', 0.10)  # 10% buffer
        self.middle_region_pct = self.config.get('middle_region_pct', 0.3)  # 35-65% region
        self.gutter_min_percent = self.config.get('gutter_min_percent', 40)  # Minimum gutter position %
        self.gutter_max_percent = self.config.get('gutter_max_percent', 60)  # Maximum gutter position %
        
    def detect_text_density_threshold(
        self, 
        pdf_path: Path, 
        is_two_up: bool = False,
        sample_size: int = 100
    ) -> float:
        """Detect text density threshold from pages 2-3.
        
        For two-up pages: Samples from left column center (~25% width) and 
        right column center (~75% width), NOT from page center (which would hit gutter).
        
        For single pages: Samples from page center.
        
        Args:
            pdf_path: Path to PDF file
            is_two_up: True if PDF contains two-up pages (two columns)
            sample_size: Size of square sample region in pixels (default: 100x100)
            
        Returns:
            Text density threshold (0.0-1.0)
        """
        try:
            doc = fitz.open(str(pdf_path))
            if len(doc) < 2:
                self.logger.warning("PDF has < 2 pages, using default threshold")
                doc.close()
                return self.default_density_threshold
            
            # Skip page 1 (often special - title page, cover)
            # Use pages 2 and 3 (standard content pages)
            page_nums = [1, 2] if len(doc) > 2 else [1]
            
            densities = []
            
            for page_num in page_nums:
                if page_num >= len(doc):
                    continue
                    
                page = doc[page_num]
                
                # Render page as image (2x zoom)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert to numpy array
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                
                # Convert to grayscale
                if len(img.shape) == 3:
                    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img
                
                img_height, img_width = gray.shape
                
                if is_two_up:
                    # For two-up pages: sample from column centers
                    # Left column center: ~25% of page width
                    # Right column center: ~75% of page width
                    left_center_x = int(img_width * 0.25)
                    right_center_x = int(img_width * 0.75)
                    center_y = int(img_height * 0.5)
                    
                    # Sample from left column center
                    left_sample = self._sample_region(
                        gray, left_center_x, center_y, sample_size
                    )
                    if left_sample is not None:
                        left_density = self._calculate_density(left_sample)
                        densities.append(left_density)
                    
                    # Sample from right column center
                    right_sample = self._sample_region(
                        gray, right_center_x, center_y, sample_size
                    )
                    if right_sample is not None:
                        right_density = self._calculate_density(right_sample)
                        densities.append(right_density)
                else:
                    # For single pages: sample from page center
                    center_x = int(img_width * 0.5)
                    center_y = int(img_height * 0.5)
                    
                    sample = self._sample_region(gray, center_x, center_y, sample_size)
                    if sample is not None:
                        density = self._calculate_density(sample)
                        densities.append(density)
            
            doc.close()
            
            if not densities:
                self.logger.warning("No valid samples, using default threshold")
                return self.default_density_threshold
            
            # If densities are similar (within 10-15%): use average
            if len(densities) > 1:
                avg_density = np.mean(densities)
                std_density = np.std(densities)
                cv = std_density / (avg_density + 1e-6)  # Coefficient of variation
                
                if cv < 0.15:  # Within 15% variation
                    return float(avg_density)
                else:
                    # Pages differ significantly: use first page density
                    return float(densities[0])
            
            # Single sample: use it
            return float(densities[0])
            
        except Exception as e:
            self.logger.error(f"Error detecting text density threshold: {e}")
            return self.default_density_threshold
    
    def _sample_region(
        self, 
        image: np.ndarray, 
        center_x: int, 
        center_y: int, 
        size: int
    ) -> Optional[np.ndarray]:
        """Sample a square region from image.
        
        Args:
            image: Grayscale image
            center_x: X coordinate of center
            center_y: Y coordinate of center
            size: Size of square region
            
        Returns:
            Sampled region or None if out of bounds
        """
        h, w = image.shape
        half_size = size // 2
        
        x1 = max(0, center_x - half_size)
        y1 = max(0, center_y - half_size)
        x2 = min(w, center_x + half_size)
        y2 = min(h, center_y + half_size)
        
        if x2 <= x1 or y2 <= y1:
            return None
        
        return image[y1:y2, x1:x2]
    
    def _calculate_density(self, region: np.ndarray) -> float:
        """Calculate content density (non-white pixels / total pixels).
        
        Args:
            region: Image region
            
        Returns:
            Density value (0.0-1.0)
        """
        # Non-white pixels: grayscale < 240
        non_white = np.sum(region < 240)
        total = region.size
        return float(non_white / total) if total > 0 else 0.0
    
    def detect_content_edge_binary_search(
        self,
        image: np.ndarray,
        density_threshold: float,
        direction: str,
        start_pos: Optional[int] = None,
        edge_hint: Optional[int] = None,
        middle_region_pct: float = 0.3
    ) -> int:
        """Detect content edge using binary search.
        
        Args:
            image: Grayscale image
            density_threshold: Text density threshold
            direction: 'left', 'right', 'top', 'bottom'
            start_pos: Known text position (default: center of dimension)
            edge_hint: Approximate edge position (default: 5% of dimension)
            middle_region_pct: Percentage of page to sample from middle (default: 0.3 = 35-65%)
            
        Returns:
            Edge coordinate (x for left/right, y for top/bottom)
        """
        h, w = image.shape
        
        # Determine dimension and positions based on direction
        if direction in ('left', 'right'):
            dim_size = w
            if start_pos is None:
                start_pos = w // 2  # Center of width
            if edge_hint is None:
                edge_hint = int(w * 0.05) if direction == 'left' else int(w * 0.95)
            
            # Define middle region (35-65% of height)
            middle_top = int(h * (0.5 - middle_region_pct / 2))
            middle_bottom = int(h * (0.5 + middle_region_pct / 2))
            
        else:  # top or bottom
            dim_size = h
            if start_pos is None:
                start_pos = h // 2  # Center of height
            if edge_hint is None:
                edge_hint = int(h * 0.05) if direction == 'top' else int(h * 0.95)
            
            # Define middle region (35-65% of width)
            middle_left = int(w * (0.5 - middle_region_pct / 2))
            middle_right = int(w * (0.5 + middle_region_pct / 2))
        
        # Binary search parameters
        current_pos = start_pos
        min_jump = 2  # Minimum jump size for convergence
        max_iterations = 50
        iteration = 0
        
        # Track best edge position
        if direction == 'left':
            best_edge = edge_hint
            search_range = (edge_hint, start_pos)
        elif direction == 'right':
            best_edge = edge_hint
            search_range = (start_pos, edge_hint)
        elif direction == 'top':
            best_edge = edge_hint
            search_range = (edge_hint, start_pos)
        else:  # bottom
            best_edge = edge_hint
            search_range = (start_pos, edge_hint)
        
        while iteration < max_iterations:
            # Calculate jump size (large initial jumps, smaller near boundary)
            if direction in ('left', 'top'):
                jump = abs(current_pos - edge_hint) // 2
            else:
                jump = abs(edge_hint - current_pos) // 2
            
            if jump < min_jump:
                break  # Converged
            
            # Test position
            if direction == 'left':
                test_pos = current_pos - jump
                test_pos = max(edge_hint, min(test_pos, start_pos))
            elif direction == 'right':
                test_pos = current_pos + jump
                test_pos = max(start_pos, min(test_pos, edge_hint))
            elif direction == 'top':
                test_pos = current_pos - jump
                test_pos = max(edge_hint, min(test_pos, start_pos))
            else:  # bottom
                test_pos = current_pos + jump
                test_pos = max(start_pos, min(test_pos, edge_hint))
            
            # Sample strip at test position (only from middle region)
            if direction in ('left', 'right'):
                # Vertical edge: sample 20px wide strip from middle region
                strip_width = 20
                x1 = max(0, test_pos - strip_width // 2)
                x2 = min(w, test_pos + strip_width // 2)
                strip = image[middle_top:middle_bottom, x1:x2]
            else:
                # Horizontal edge: sample 20px tall strip from middle region
                strip_height = 20
                y1 = max(0, test_pos - strip_height // 2)
                y2 = min(h, test_pos + strip_height // 2)
                strip = image[y1:y2, middle_left:middle_right]
            
            if strip.size == 0:
                break
            
            # Calculate density
            density = self._calculate_density(strip)
            
            # Decision logic
            if density >= density_threshold:
                # Still in text, can move further toward edge
                current_pos = test_pos
                if direction in ('left', 'top'):
                    best_edge = min(best_edge, test_pos)
                else:
                    best_edge = max(best_edge, test_pos)
            elif density < density_threshold * 0.1:
                # Hit white border, move back toward center
                if direction in ('left', 'top'):
                    current_pos = test_pos + jump // 2
                else:
                    current_pos = test_pos - jump // 2
            else:
                # Mixed region (dark border or transition), refine
                if direction in ('left', 'top'):
                    current_pos = test_pos + jump // 4
                else:
                    current_pos = test_pos - jump // 4
            
            iteration += 1
        
        # Apply safety margin: move edge further out (toward margin) by 5-10%
        if direction in ('left', 'top'):
            safety_offset = int(dim_size * self.safety_margin_pct)
            final_edge = max(0, best_edge - safety_offset)
        else:
            safety_offset = int(dim_size * self.safety_margin_pct)
            final_edge = min(dim_size, best_edge + safety_offset)
        
        return final_edge
    
    def detect_content_region_binary_search(
        self,
        image: np.ndarray,
        density_threshold: float,
        center_x: Optional[int] = None,
        center_y: Optional[int] = None
    ) -> Tuple[int, int, int, int]:
        """Detect content region using binary search for all 4 directions.
        
        Args:
            image: Grayscale image
            density_threshold: Text density threshold
            center_x: Known text X position (default: center)
            center_y: Known text Y position (default: center)
            
        Returns:
            Tuple of (left, top, right, bottom) coordinates
        """
        h, w = image.shape
        
        # Detect all 4 edges
        left = self.detect_content_edge_binary_search(
            image, density_threshold, 'left', center_x
        )
        right = self.detect_content_edge_binary_search(
            image, density_threshold, 'right', center_x
        )
        top = self.detect_content_edge_binary_search(
            image, density_threshold, 'top', center_y
        )
        bottom = self.detect_content_edge_binary_search(
            image, density_threshold, 'bottom', center_y
        )
        
        return (left, top, right, bottom)
    
    def expand_content_box_for_headers_footers(
        self,
        bounding_box: Tuple[int, int, int, int],
        image_size: Tuple[int, int],
        top_padding: float = 0.1,
        bottom_padding: float = 0.1,
        side_padding: float = 0.05
    ) -> Tuple[int, int, int, int]:
        """Expand content box to preserve headers, footers, page numbers.
        
        Args:
            bounding_box: (left, top, right, bottom) coordinates
            image_size: (width, height) of image
            top_padding: Percentage of page height to extend upward (default: 10%)
            bottom_padding: Percentage of page height to extend downward (default: 10%)
            side_padding: Percentage of page width for left/right safety margin (default: 5%)
            
        Returns:
            Expanded bounding box (left, top, right, bottom)
        """
        left, top, right, bottom = bounding_box
        img_width, img_height = image_size
        
        # Expand top/bottom for headers/footers
        top_expand = int(img_height * top_padding)
        bottom_expand = int(img_height * bottom_padding)
        
        # Expand left/right for safety margin
        side_expand = int(img_width * side_padding)
        
        new_left = max(0, left - side_expand)
        new_top = max(0, top - top_expand)
        new_right = min(img_width, right + side_expand)
        new_bottom = min(img_height, bottom + bottom_expand)
        
        return (new_left, new_top, new_right, new_bottom)
    
    def detect_two_column_regions_binary_search(
        self,
        pdf_path: Path,
        density_threshold: Optional[float] = None,
        pages: Optional[List[int]] = None
    ) -> List[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], float, bool, List[str], int, int]]:
        """Detect two text columns using binary search edge detection.
        
        Returns per-page results with validation status.
        
        Args:
            pdf_path: Path to PDF file
            density_threshold: Text density threshold (if None, will detect)
            pages: List of page numbers to process (None = all pages)
            
        Returns:
            List of tuples: [(left_box, right_box, gutter_x_pts, is_valid, validation_errors, left_col_right_px, right_col_left_px), ...] per page
            where boxes are (left, top, right, bottom) in pixels,
            gutter_x_pts is in PDF points,
            is_valid indicates if validation passed,
            validation_errors is list of error messages if validation failed,
            left_col_right_px and right_col_left_px are pixel positions for overlap checking
        """
        if density_threshold is None:
            # Detect threshold (assumes two-up pages)
            density_threshold = self.detect_text_density_threshold(pdf_path, is_two_up=True)
        
        try:
            doc = fitz.open(str(pdf_path))
            page_nums = pages if pages is not None else list(range(len(doc)))
            
            results = []
            
            for page_num in page_nums:
                if page_num >= len(doc):
                    continue
                
                page = doc[page_num]
                page_rect = page.rect
                page_width_pts = page_rect.width
                page_height_pts = page_rect.height
                
                # Render page as image (2x zoom)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert to numpy array
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                
                # Convert to grayscale
                if len(img.shape) == 3:
                    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img
                
                img_height, img_width = gray.shape
                
                # Estimate column centers
                left_col_center_x = int(img_width * 0.25)
                right_col_center_x = int(img_width * 0.75)
                center_y = img_height // 2
                
                # Detect left column: find right edge (toward gutter) and left edge (toward margin)
                left_col_right = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'right', 
                    start_pos=left_col_center_x,
                    edge_hint=int(img_width * 0.5)
                )
                left_col_left = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'left',
                    start_pos=left_col_center_x,
                    edge_hint=0
                )
                
                # Detect right column: find left edge (toward gutter) and right edge (toward margin)
                right_col_left = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'left',
                    start_pos=right_col_center_x,
                    edge_hint=int(img_width * 0.5)
                )
                right_col_right = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'right',
                    start_pos=right_col_center_x,
                    edge_hint=img_width
                )
                
                # Detect top and bottom for both columns (use same values for simplicity)
                top = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'top', center_y
                )
                bottom = self.detect_content_edge_binary_search(
                    gray, density_threshold, 'bottom', center_y
                )
                
                # Create bounding boxes
                left_box = (left_col_left, top, left_col_right, bottom)
                right_box = (right_col_left, top, right_col_right, bottom)
                
                # Validate edge detection results using configured gutter range
                validation_errors = []
                is_valid = True
                
                # Convert gutter range from percentage to pixels
                gutter_min_px = (self.gutter_min_percent / 100.0) * img_width
                gutter_max_px = (self.gutter_max_percent / 100.0) * img_width
                min_gap_px = 0.05 * img_width  # Minimum 5% gap
                
                # Validation check 1: left_col_right < right_col_left (must have positive gap)
                if left_col_right >= right_col_left:
                    is_valid = False
                    validation_errors.append(
                        f"Invalid gap: left_col_right ({left_col_right}px) >= right_col_left ({right_col_left}px)"
                    )
                
                # Validation check 2: left_col_right <= gutter_max_percent%
                if left_col_right > gutter_max_px:
                    is_valid = False
                    left_col_right_pct = (left_col_right / img_width) * 100 if img_width > 0 else 0
                    validation_errors.append(
                        f"left_col_right ({left_col_right_pct:.1f}%) exceeds max gutter position ({self.gutter_max_percent}%)"
                    )
                
                # Validation check 3: right_col_left >= gutter_min_percent%
                if right_col_left < gutter_min_px:
                    is_valid = False
                    right_col_left_pct = (right_col_left / img_width) * 100 if img_width > 0 else 0
                    validation_errors.append(
                        f"right_col_left ({right_col_left_pct:.1f}%) is below min gutter position ({self.gutter_min_percent}%)"
                    )
                
                # Validation check 4: Gap >= 5% of page width (minimum gap size)
                gap_px = right_col_left - left_col_right
                if is_valid and gap_px < min_gap_px:
                    is_valid = False
                    gap_pct = (gap_px / img_width) * 100 if img_width > 0 else 0
                    validation_errors.append(
                        f"Gap ({gap_pct:.1f}%) is too small (minimum 5% required)"
                    )
                
                # Calculate gutter position (gap between columns) in PDF points
                # Gutter is between left_col_right and right_col_left
                gutter_px = (left_col_right + right_col_left) // 2
                gutter_x_pts = (gutter_px / img_width) * page_width_pts if img_width > 0 else page_width_pts / 2
                
                # Diagnostic logging: Log detected column edges and calculated gutter
                left_col_left_pct = (left_col_left / img_width) * 100 if img_width > 0 else 0
                left_col_right_pct = (left_col_right / img_width) * 100 if img_width > 0 else 0
                right_col_left_pct = (right_col_left / img_width) * 100 if img_width > 0 else 0
                right_col_right_pct = (right_col_right / img_width) * 100 if img_width > 0 else 0
                gutter_pct = (gutter_px / img_width) * 100 if img_width > 0 else 0
                
                if is_valid:
                    self.logger.debug(
                        f"Page {page_num + 1} column detection: "
                        f"left_col=[{left_col_left}px ({left_col_left_pct:.1f}%), {left_col_right}px ({left_col_right_pct:.1f}%)], "
                        f"right_col=[{right_col_left}px ({right_col_left_pct:.1f}%), {right_col_right}px ({right_col_right_pct:.1f}%)], "
                        f"gutter={gutter_px}px ({gutter_pct:.1f}%) = {gutter_x_pts:.1f}pts"
                    )
                else:
                    self.logger.warning(
                        f"Page {page_num + 1} edge detection validation failed: {'; '.join(validation_errors)}"
                    )
                
                # Return tuple with validation status: (left_box, right_box, gutter_x_pts, is_valid, validation_errors, left_col_right_px, right_col_left_px)
                # Include pixel positions for overlap checking in dual-method coordinator
                results.append((left_box, right_box, gutter_x_pts, is_valid, validation_errors, left_col_right, right_col_left))
            
            doc.close()
            return results
            
        except Exception as e:
            self.logger.error(f"Error detecting two-column regions: {e}")
            return []
    
    def detect_gutter_by_density_minimum(
        self,
        pdf_path: Path,
        pages: Optional[List[int]] = None,
        density_threshold: Optional[float] = None
    ) -> List[Tuple[float, Dict[str, Any], bool]]:
        """Detect gutter position using density minimum method with shape analysis.
        
        Calculates horizontal projection profile and finds minimum density position,
        then validates using shape analysis to distinguish real gutters from column edges.
        
        Args:
            pdf_path: Path to PDF file
            pages: List of page numbers to process (None = all pages)
            density_threshold: Text density threshold (if None, will detect)
            
        Returns:
            List of tuples per page: [(gutter_x_pts, shape_metrics, is_valid), ...]
            where gutter_x_pts is in PDF points,
            shape_metrics is dict with gradient, valley_width, curvature, etc.,
            is_valid indicates if shape analysis passed
        """
        if density_threshold is None:
            density_threshold = self.detect_text_density_threshold(pdf_path, is_two_up=True)
        
        try:
            import fitz  # PyMuPDF
            doc = fitz.open(str(pdf_path))
            page_nums = pages if pages is not None else list(range(len(doc)))
            
            results = []
            
            for page_num in page_nums:
                if page_num >= len(doc):
                    continue
                
                page = doc[page_num]
                page_rect = page.rect
                page_width_pts = page_rect.width
                page_height_pts = page_rect.height
                
                # Render page as image (2x zoom)
                zoom = 2.0
                mat = fitz.Matrix(zoom, zoom)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                
                # Convert to numpy array
                img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
                
                # Convert to grayscale
                if len(img.shape) == 3:
                    gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                else:
                    gray = img
                
                img_height, img_width = gray.shape
                
                # Extract middle 35-65% region vertically (avoid edge artifacts)
                middle_top = int(img_height * 0.35)
                middle_bottom = int(img_height * 0.65)
                content_region = gray[middle_top:middle_bottom, :]
                
                # Calculate horizontal projection: sum of inverted pixels (non-white pixels)
                inverted = 255 - content_region
                content_projection = np.sum(inverted, axis=0).astype(np.float32)
                
                # Apply Gaussian smoothing to reduce noise
                kernel_size = max(5, int(img_width * 0.02))
                if kernel_size % 2 == 0:
                    kernel_size += 1
                if kernel_size > 1:
                    content_projection = cv2.GaussianBlur(
                        content_projection.reshape(1, -1), (1, kernel_size), 0
                    ).flatten()
                
                # Find minimum in configured gutter range (gutter_min_percent% to gutter_max_percent%)
                gutter_min_px = int((self.gutter_min_percent / 100.0) * img_width)
                gutter_max_px = int((self.gutter_max_percent / 100.0) * img_width)
                
                search_region = content_projection[gutter_min_px:gutter_max_px]
                if len(search_region) == 0:
                    results.append((page_width_pts / 2, {}, False))
                    continue
                
                # Find minimum using windowed averaging (more robust than single pixel)
                window_size = max(5, int(len(search_region) * 0.05))
                min_window_avg = float('inf')
                min_window_idx = 0
                
                for i in range(len(search_region) - window_size + 1):
                    window = search_region[i:i+window_size]
                    window_avg = np.mean(window)
                    if window_avg < min_window_avg:
                        min_window_avg = window_avg
                        min_window_idx = i + window_size // 2  # Center of window
                
                # Convert back to full image coordinates
                min_idx_px = gutter_min_px + min_window_idx
                min_density = float(min_window_avg)
                
                # Shape analysis: Calculate gradient, curvature, valley width
                shape_metrics = self._analyze_gutter_shape(
                    content_projection, min_idx_px, img_width, min_density
                )
                
                # Validate using shape analysis
                is_valid, validation_errors = self._validate_gutter_shape(
                    shape_metrics, min_idx_px, img_width
                )
                
                # Store validation errors in shape_metrics for access by caller
                shape_metrics['validation_errors'] = validation_errors
                
                # Convert to PDF points
                gutter_x_pts = (min_idx_px / img_width) * page_width_pts if img_width > 0 else page_width_pts / 2
                gutter_pct = (min_idx_px / img_width) * 100 if img_width > 0 else 50
                
                if is_valid:
                    self.logger.debug(
                        f"Page {page_num + 1} density minimum: gutter={min_idx_px}px ({gutter_pct:.1f}%) = {gutter_x_pts:.1f}pts, "
                        f"gradient={shape_metrics.get('avg_gradient', 0):.1f}, valley_width={shape_metrics.get('valley_width_ratio', 0):.2f}"
                    )
                else:
                    self.logger.warning(
                        f"Page {page_num + 1} density minimum validation failed: {'; '.join(validation_errors)}"
                    )
                
                results.append((gutter_x_pts, shape_metrics, is_valid))
            
            doc.close()
            return results
            
        except Exception as e:
            self.logger.error(f"Error detecting gutter by density minimum: {e}")
            return []
    
    def _analyze_gutter_shape(
        self,
        projection: np.ndarray,
        min_idx: int,
        img_width: int,
        min_value: float
    ) -> Dict[str, Any]:
        """Analyze shape around minimum position to distinguish gutters from column edges.
        
        Args:
            projection: Horizontal projection profile
            min_idx: Index of minimum position
            img_width: Image width in pixels
            min_value: Minimum density value
            
        Returns:
            Dict with shape metrics: gradient, valley_width, curvature, etc.
        """
        # Analyze region around minimum (±10% of width)
        analysis_radius = int(img_width * 0.10)
        start_idx = max(0, min_idx - analysis_radius)
        end_idx = min(len(projection), min_idx + analysis_radius)
        
        region = projection[start_idx:end_idx]
        if len(region) < 10:
            return {'avg_gradient': float('inf'), 'valley_width_ratio': 0, 'avg_second_deriv': float('inf')}
        
        # Calculate first derivative (gradient)
        gradient = np.diff(region)
        avg_gradient = float(np.mean(np.abs(gradient)))
        max_gradient = float(np.max(np.abs(gradient)))
        
        # Calculate second derivative (curvature)
        second_deriv = np.diff(gradient)
        avg_second_deriv = float(np.mean(np.abs(second_deriv)))
        max_second_deriv = float(np.max(np.abs(second_deriv)))
        
        # Measure valley width: distance between points where density rises 30% from minimum
        threshold = min_value + 0.3 * (np.max(region) - min_value)
        valley_indices = np.where(region <= threshold)[0]
        
        if len(valley_indices) > 0:
            valley_width = int(valley_indices[-1] - valley_indices[0])
            valley_width_ratio = valley_width / len(region) if len(region) > 0 else 0
        else:
            valley_width_ratio = 0
        
        # Calculate signal strength: content reduction at minimum
        avg_density = float(np.mean(region))
        content_reduction = (avg_density - min_value) / (avg_density + 1e-6) if avg_density > 0 else 0
        content_reduction_pct = content_reduction * 100
        
        return {
            'avg_gradient': avg_gradient,
            'max_gradient': max_gradient,
            'avg_second_deriv': avg_second_deriv,
            'max_second_deriv': max_second_deriv,
            'valley_width_ratio': valley_width_ratio,
            'content_reduction_pct': content_reduction_pct,
            'min_value': float(min_value),
            'avg_value': avg_density
        }
    
    def _validate_gutter_shape(
        self,
        shape_metrics: Dict[str, Any],
        min_idx: int,
        img_width: int
    ) -> Tuple[bool, List[str]]:
        """Validate that minimum position represents a real gutter, not a column edge.
        
        Args:
            shape_metrics: Shape analysis metrics from _analyze_gutter_shape
            min_idx: Index of minimum position
            img_width: Image width in pixels
            
        Returns:
            Tuple of (is_valid, validation_errors)
        """
        validation_errors = []
        is_valid = True
        
        avg_gradient = shape_metrics.get('avg_gradient', float('inf'))
        max_gradient = shape_metrics.get('max_gradient', float('inf'))
        avg_second_deriv = shape_metrics.get('avg_second_deriv', float('inf'))
        max_second_deriv = shape_metrics.get('max_second_deriv', float('inf'))
        valley_width_ratio = shape_metrics.get('valley_width_ratio', 0)
        content_reduction_pct = shape_metrics.get('content_reduction_pct', 0)
        min_idx_pct = (min_idx / img_width) * 100 if img_width > 0 else 0
        
        # Validation 1: Average gradient < 500 (gradual valley, not sharp drop)
        if avg_gradient > 500:
            is_valid = False
            validation_errors.append(f"Average gradient ({avg_gradient:.1f}) too high (sharp transition, not gradual gutter)")
        
        # Validation 2: Valley width ratio > 0.5 (wide valley, not narrow edge)
        if valley_width_ratio < 0.4:
            is_valid = False
            validation_errors.append(f"Valley width ratio ({valley_width_ratio:.2f}) too narrow (column edge, not gutter)")
        
        # Validation 3: Average second derivative < 400 (smooth transition)
        if avg_second_deriv > 400:
            is_valid = False
            validation_errors.append(f"Average curvature ({avg_second_deriv:.1f}) too high (sharp corner, not smooth gutter)")
        
        # Validation 4: Position within configured gutter range (gutter_min_percent% to gutter_max_percent%)
        if min_idx_pct < self.gutter_min_percent or min_idx_pct > self.gutter_max_percent:
            # If outside range, reject if gradient is also high (off-center sharp drop)
            if avg_gradient > 600:
                is_valid = False
                validation_errors.append(
                    f"Position ({min_idx_pct:.1f}%) outside range ({self.gutter_min_percent}-{self.gutter_max_percent}%) "
                    f"with high gradient ({avg_gradient:.1f}) - likely column edge"
                )
        
        # Validation 5: Signal strength - content reduction > 15%
        if content_reduction_pct < 15:
            is_valid = False
            validation_errors.append(f"Signal strength ({content_reduction_pct:.1f}%) too low (no significant gutter detected)")
        
        # Additional reject conditions for column edges
        # Reject if max gradient > 15000 AND second derivative > 1000 (very sharp corner)
        if max_gradient > 15000 and avg_second_deriv > 1000:
            is_valid = False
            validation_errors.append(
                f"Very sharp corner detected (max_gradient={max_gradient:.1f}, curvature={avg_second_deriv:.1f}) - column edge"
            )
        
        # Reject if position outside range AND gradient > 800 (off-center sharp drop)
        if (min_idx_pct < self.gutter_min_percent or min_idx_pct > self.gutter_max_percent) and avg_gradient > 800:
            is_valid = False
            validation_errors.append(
                f"Off-center sharp drop (position={min_idx_pct:.1f}%, gradient={avg_gradient:.1f}) - column edge"
            )
        
        return is_valid, validation_errors
    
    def verify_gutter_position_safety(
        self,
        image: np.ndarray,
        gutter_x_px: int,
        density_threshold: float,
        page_width_pts: float
    ) -> Tuple[bool, str]:
        """Verify gutter position won't cut through text.
        
        Args:
            image: Grayscale image
            gutter_x_px: Gutter X position in pixels
            density_threshold: Text density threshold
            page_width_pts: Page width in PDF points (for conversion)
            
        Returns:
            Tuple of (is_safe, warning_message)
        """
        h, w = image.shape
        
        # Sample ONLY from middle 35-65% of page height (avoid edge artifacts)
        middle_top = int(h * 0.35)
        middle_bottom = int(h * 0.65)
        
        # Sample a narrow strip centered exactly at gutter position
        # Use 20px total (10px on each side) to check exactly where the split will occur
        strip_width_px = 20  # Fixed 20px strip (10px on each side of gutter)
        
        x1 = max(0, gutter_x_px - strip_width_px // 2)
        x2 = min(w, gutter_x_px + strip_width_px // 2)
        
        strip = image[middle_top:middle_bottom, x1:x2]
        
        if strip.size == 0:
            return True, ""  # Empty strip, safe
        
        # Calculate content density
        density = self._calculate_density(strip)
        
        # Debug: Log what we're checking
        gutter_ratio = gutter_x_px / w if w > 0 else 0
        self.logger.debug(
            f"Gutter safety check: position={gutter_x_px}px ({gutter_ratio:.1%} of width), "
            f"strip={x1}-{x2}px (width={x2-x1}px), density={density:.1%}"
        )
        
        # Reject if content density > 30% (would cut through text)
        # Increased from 15% to 30% because:
        # - 16-19% is often valid (text bleed-through, artifacts, shadows)
        # - Real text columns typically have > 50% density
        # - 30% threshold is more conservative while still catching real problems
        if density > 0.30:
            return False, f"Gutter position has {density:.1%} content density (would cut through text)"
        
        # Warn if density is between 20-30% (borderline case)
        if density > 0.20:
            return True, f"Gutter position has {density:.1%} content density (borderline, but acceptable)"
        
        return True, ""
