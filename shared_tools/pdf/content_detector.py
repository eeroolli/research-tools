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
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Configuration parameters
        self.default_density_threshold = self.config.get('default_density_threshold', 0.15)
        self.safety_margin_pct = self.config.get('safety_margin_pct', 0.10)  # 10% buffer
        self.middle_region_pct = self.config.get('middle_region_pct', 0.3)  # 35-65% region
        
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
    ) -> List[Tuple[Tuple[int, int, int, int], Tuple[int, int, int, int], float]]:
        """Detect two text columns using binary search edge detection.
        
        Returns per-page results: list of (left_box, right_box, gutter_x) for each page.
        
        Args:
            pdf_path: Path to PDF file
            density_threshold: Text density threshold (if None, will detect)
            pages: List of page numbers to process (None = all pages)
            
        Returns:
            List of tuples: [(left_box, right_box, gutter_x), ...] per page
            where boxes are (left, top, right, bottom) in pixels
            and gutter_x is in PDF points
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
                
                # Calculate gutter position (gap between columns) in PDF points
                # Gutter is between left_col_right and right_col_left
                gutter_px = (left_col_right + right_col_left) // 2
                gutter_x_pts = (gutter_px / img_width) * page_width_pts
                
                # Diagnostic logging: Log detected column edges and calculated gutter
                left_col_left_pct = (left_col_left / img_width) * 100 if img_width > 0 else 0
                left_col_right_pct = (left_col_right / img_width) * 100 if img_width > 0 else 0
                right_col_left_pct = (right_col_left / img_width) * 100 if img_width > 0 else 0
                right_col_right_pct = (right_col_right / img_width) * 100 if img_width > 0 else 0
                gutter_pct = (gutter_px / img_width) * 100 if img_width > 0 else 0
                
                self.logger.debug(
                    f"Page {page_num + 1} column detection: "
                    f"left_col=[{left_col_left}px ({left_col_left_pct:.1f}%), {left_col_right}px ({left_col_right_pct:.1f}%)], "
                    f"right_col=[{right_col_left}px ({right_col_left_pct:.1f}%), {right_col_right}px ({right_col_right_pct:.1f}%)], "
                    f"gutter={gutter_px}px ({gutter_pct:.1f}%) = {gutter_x_pts:.1f}pts"
                )
                
                results.append((left_box, right_box, gutter_x_pts))
            
            doc.close()
            return results
            
        except Exception as e:
            self.logger.error(f"Error detecting two-column regions: {e}")
            return []
    
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
