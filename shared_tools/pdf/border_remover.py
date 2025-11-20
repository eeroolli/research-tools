#!/usr/bin/env python3
"""
Border removal utility for scanned documents.

Detects and removes dark borders from scanned pages using projection profile
analysis. Designed for scanned book chapters with irregular borders from 
physical book edges.

Algorithm:
1. Calculate projection profiles (sum of pixels) for every row and column
2. Find significant transitions in the projection (border → content)
3. Whitening detected border regions to clean paper color
"""

import logging
from pathlib import Path
from typing import Optional, Tuple, Dict, Any
import cv2
import numpy as np
from PIL import Image
import fitz  # PyMuPDF
import io


class BorderRemover:
    """Removes dark borders from scanned document pages."""
    
    def __init__(self, config: Dict[str, Any] = None):
        """Initialize border remover.
        
        Args:
            config: Configuration dictionary with optional keys:
                - max_border_width: Maximum border width to detect in pixels (default: 300)
                - variance_threshold: Maximum std dev for whitening uniform regions (default: 30)
        """
        self.config = config or {}
        self.logger = logging.getLogger(__name__)
        
        # Configuration parameters
        self.max_border_width = self.config.get('max_border_width', 300)
        # Page-edge specific configuration
        self.page_white_delta = self.config.get('page_white_delta', 8)   # tolerance below page white (tighter)
        self.dark_threshold = self.config.get('dark_threshold', 60)       # scanner bed / dark area (stricter)
        self.sustained_run = self.config.get('sustained_run', 24)         # min consecutive white pixels (stricter)
        self.sustained_text = self.config.get('sustained_text', 20)      # min consecutive text-like pixels (stricter)
        self.max_check_percentage = self.config.get('max_check_percentage', 0.25)  # scan up to 25% of side (reduced)
        self.edge_inset = self.config.get('edge_inset', 10)              # pixels from edge to start checking for dark borders
        self.smoothing_window = self.config.get('smoothing_window', 5)   # smoothing window (reduced, less aggressive)
        self.min_valid_ratio = self.config.get('min_valid_ratio', 0.7)    # require 70% of scanlines to find TW
        self.whiten_gray = self.config.get('whiten_gray', 240)           # default gray value for whitening
        # Per-side diagnostic grays (so we can see provenance)
        self.top_gray = self.config.get('top_gray', 240)
        self.bottom_gray = self.config.get('bottom_gray', 230)
        self.left_gray = self.config.get('left_gray', 220)
        self.right_gray = self.config.get('right_gray', 210)
        # Overwrite policy when masks overlap: first_wins or last_wins
        self.first_wins = self.config.get('first_wins', True)
        # Hardened detection parameters
        self.min_white_after_tw = self.config.get('min_white_after_tw', 80)  # required white run after TW
        self.min_text_before_tw = self.config.get('min_text_before_tw', 20)  # required text run before TW
        # Per-side minimum margins (pixels) to avoid picking inner gaps
        self.min_margin_top = self.config.get('min_margin_top', 60)
        self.min_margin_bottom = self.config.get('min_margin_bottom', 100)
        self.min_margin_left = self.config.get('min_margin_left', 60)
        self.min_margin_right = self.config.get('min_margin_right', 60)
        # Neighbor consensus/outlier filtering for TW curves
        self.neighbor_window = self.config.get('neighbor_window', 17)
        self.neighbor_min = self.config.get('neighbor_min', 10)
        self.neighbor_delta = self.config.get('neighbor_delta', 20)
        # Erode masks to remove tendrils; and limit to outer bands
        self.mask_erode_px = self.config.get('mask_erode_px', 3)
        self.edge_process_pct = self.config.get('edge_process_pct', 0.2)
        # WDW edge-in detection parameters
        self.band_bright_percentile = self.config.get('band_bright_percentile', 80)
        self.band_dark_percentile = self.config.get('band_dark_percentile', 20)
        self.max_outer_white_px = self.config.get('max_outer_white_px', 20)
        self.min_dark_px = self.config.get('min_dark_px', 20)
        self.min_page_margin_px = self.config.get('min_page_margin_px', 80)
        self.close_gaps_k = self.config.get('close_gaps_k', 2)
        # WDW (edge-in) specific
        self.bright_percentile = self.config.get('bright_percentile', 80.0)
        self.dark_percentile = self.config.get('dark_percentile', 20.0)
        self.max_outer_white_px = self.config.get('max_outer_white_px', 20)
        self.min_dark_px_wdw = self.config.get('min_dark_px_wdw', 20)
        self.min_page_margin_px = self.config.get('min_page_margin_px', 80)
        self.close_gaps_k = self.config.get('close_gaps_k', 2)
        
    def detect_borders(self, image: np.ndarray) -> Dict[str, int]:
        """Detect border widths on all sides of an image.
        
        Only reports borders if they actually contain dark pixels (scanner bed).
        This prevents false positives on printouts which have wide white margins.
        
        Args:
            image: Grayscale or color image as numpy array
            
        Returns:
            Dictionary with keys: 'top', 'bottom', 'left', 'right'
            Values are pixel widths of detected borders (0 if no dark border found)
        """
        # Convert to grayscale if color
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image
        
        h, w = gray.shape
        
        # Get candidate borders (where content starts)
        candidate_borders = self._detect_borders_projection(gray, h, w)
        
        # Verify borders actually contain dark pixels (scanner bed)
        # Skip outer portion of borders to avoid white strips at edges (copier masks)
        dark_threshold = float(self.dark_threshold)
        verified_borders = {'top': 0, 'bottom': 0, 'left': 0, 'right': 0}
        
        # Sample pixels in inner portion of border regions - require at least some dark pixels
        min_dark_fraction = 0.15  # At least 15% of checked region should be dark
        skip_outer_percent = 0.20  # Skip outer 20% of detected border
        min_skip_pixels = 50  # Minimum pixels to skip (handles small borders)
        
        # Top border
        if candidate_borders['top'] > 0:
            border_width = candidate_borders['top']
            # Skip outer portion, check inner part
            skip_pixels = max(int(border_width * skip_outer_percent), min_skip_pixels)
            inner_start = skip_pixels
            inner_end = border_width
            if inner_end > inner_start:
                inner_region = gray[inner_start:inner_end, :]
                if inner_region.size > 0:
                    dark_pixels = np.sum(inner_region <= dark_threshold)
                    dark_fraction = dark_pixels / inner_region.size
                    if dark_fraction >= min_dark_fraction:
                        verified_borders['top'] = candidate_borders['top']
        
        # Bottom border
        if candidate_borders['bottom'] > 0:
            border_width = candidate_borders['bottom']
            # Skip outer portion (from edge), check inner part
            skip_pixels = max(int(border_width * skip_outer_percent), min_skip_pixels)
            inner_start = h - border_width + skip_pixels
            inner_end = h
            if inner_end > inner_start:
                inner_region = gray[inner_start:inner_end, :]
                if inner_region.size > 0:
                    dark_pixels = np.sum(inner_region <= dark_threshold)
                    dark_fraction = dark_pixels / inner_region.size
                    if dark_fraction >= min_dark_fraction:
                        verified_borders['bottom'] = candidate_borders['bottom']
        
        # Left border
        if candidate_borders['left'] > 0:
            border_width = candidate_borders['left']
            # Skip outer portion, check inner part
            skip_pixels = max(int(border_width * skip_outer_percent), min_skip_pixels)
            inner_start = skip_pixels
            inner_end = border_width
            if inner_end > inner_start:
                inner_region = gray[:, inner_start:inner_end]
                if inner_region.size > 0:
                    dark_pixels = np.sum(inner_region <= dark_threshold)
                    dark_fraction = dark_pixels / inner_region.size
                    if dark_fraction >= min_dark_fraction:
                        verified_borders['left'] = candidate_borders['left']
        
        # Right border
        if candidate_borders['right'] > 0:
            border_width = candidate_borders['right']
            # Skip outer portion (from edge), check inner part
            skip_pixels = max(int(border_width * skip_outer_percent), min_skip_pixels)
            inner_start = w - border_width + skip_pixels
            inner_end = w
            if inner_end > inner_start:
                inner_region = gray[:, inner_start:inner_end]
                if inner_region.size > 0:
                    dark_pixels = np.sum(inner_region <= dark_threshold)
                    dark_fraction = dark_pixels / inner_region.size
                    if dark_fraction >= min_dark_fraction:
                        verified_borders['right'] = candidate_borders['right']
        
        return verified_borders
    
    def _detect_borders_projection(self, gray: np.ndarray, height: int, width: int) -> Dict[str, int]:
        """Detect white margins around text content.
        
        Strategy: Find white margins around the text (these define the content area).
        Everything outside these margins with low variance (uniform regions like
        scanner bed, hands, etc.) will be whitened in remove_borders.
        
        Args:
            gray: Grayscale image
            height: Image height
            width: Image width
            
        Returns:
            Dictionary with white margin positions: 'top', 'bottom', 'left', 'right'
            These define where content starts (not border widths)
        """
        # Detect white margin boundaries - these define where content starts
        left_margin = self._find_white_margin_edge(gray, 'left', width, height)
        right_margin = self._find_white_margin_edge(gray, 'right', width, height)
        top_margin = self._find_white_margin_edge(gray.T, 'top', height, width)
        bottom_margin = self._find_white_margin_edge(gray.T, 'bottom', height, width)
        
        return {
            'top': top_margin,
            'bottom': bottom_margin,
            'left': left_margin,
            'right': right_margin
        }
    
    def _find_white_margin_edge(self, gray_or_transposed: np.ndarray, side: str, 
                                primary_dim: int, secondary_dim: int) -> int:
        """Find where content starts by detecting transition from uniform edge to content.
        
        Scans from edge inward looking for transition from uniform border region
        (narrow white band, scanner bed, etc.) to actual content area.
        
        Strategy:
        1. Edge regions are uniform (low variance) - narrow white bands, scanner bed, hands, etc.
        2. Content area has higher variance (text, shadows, page content)
        3. Find where variance increases significantly = content boundary
        
        Args:
            gray_or_transposed: Grayscale image (possibly transposed)
            side: Which edge ('left', 'right', 'top', 'bottom')
            primary_dim: Size of dimension we're scanning
            secondary_dim: Size of other dimension (for averaging)
            
        Returns:
            Position where content starts (border width)
        """
        max_check = min(self.max_border_width, primary_dim)
        window_size = 20  # Look at 20px windows for robustness
        
        # Determine scan direction - scan from edge inward
        if side in ['left', 'top']:
            scan_range = range(0, max_check)
        else:  # right, bottom
            scan_range = range(primary_dim - 1, max(0, primary_dim - max_check - 1), -1)
        
        # Sample edge region to establish baseline (uniform border)
        edge_sample_size = min(50, max_check // 3)  # Sample first ~50px or 1/3 of check region
        edge_samples_mean = []
        edge_samples_std = []
        
        for i, pos in enumerate(list(scan_range)[:edge_sample_size]):
            if side in ['left', 'top']:
                window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
            else:
                window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
            
            if window is not None and window.size > 0:
                edge_samples_mean.append(np.mean(window))
                edge_samples_std.append(np.std(window))
        
        if not edge_samples_mean:
            return 0
        
        # Baseline characteristics of edge region
        edge_mean = np.mean(edge_samples_mean)
        edge_std = np.mean(edge_samples_std)
        
        # Find transition to content
        # Content shows up as: higher variance (text/shadows) OR significant brightness change
        variance_threshold = max(edge_std * 2, 25)  # Variance should double, or at least 25
        brightness_change_threshold = 30  # Significant brightness change
        
        content_start = None
        consecutive_content = 0
        required_consecutive = 2  # Need 2 consecutive windows showing content characteristics
        
        for pos in scan_range:
            if side in ['left', 'top']:
                window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
            else:
                window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
            
            if window is None or window.size == 0:
                continue
            
            mean_val = np.mean(window)
            std_val = np.std(window)
            
            # Check if this looks like content (not uniform border)
            # Content indicators:
            # 1. Higher variance (text/shadows) OR
            # 2. Significant brightness change from edge
            is_content = (std_val > variance_threshold) or \
                        (abs(mean_val - edge_mean) > brightness_change_threshold)
            
            if is_content:
                consecutive_content += 1
                if content_start is None:
                    content_start = pos
            else:
                # Reset if we find uniform region again (might be multiple uniform bands)
                consecutive_content = 0
                content_start = None
            
            # Found enough consecutive content windows - this is likely the content boundary
            if consecutive_content >= required_consecutive:
                break
        
        # Return border width (everything before content)
        if content_start is None:
            return 0
        
        # Convert position to border width
        if side in ['left', 'top']:
            return content_start
        else:
            return primary_dim - content_start
    
    def _find_dark_border_edge(self, gray_or_transposed: np.ndarray, side: str,
                               primary_dim: int, secondary_dim: int) -> int:
        """Find dark border by detecting transition from dark edge to content.
        
        Fallback method when white margin detection fails. Scans from edge inward
        looking for transition from dark border region to lighter content.
        
        Strategy:
        1. Calculate average brightness of edge region (first 100px)
        2. Scan inward looking for significant brightness increase
        3. Return position where transition occurs
        
        Args:
            gray_or_transposed: Grayscale image (possibly transposed)
            side: Which edge ('left', 'right', 'top', 'bottom')
            primary_dim: Size of dimension we're scanning
            secondary_dim: Size of other dimension
            
        Returns:
            Width/height of detected border
        """
        max_check = min(self.max_border_width, primary_dim)
        window_size = 20
        
        # Determine scan direction
        if side in ['left', 'top']:
            scan_range = range(0, max_check)
        else:  # right, bottom
            scan_range = range(primary_dim - 1, max(0, primary_dim - max_check - 1), -1)
        
        # Sample edge region to determine if there's a dark border
        edge_sample_size = min(100, max_check)
        edge_samples = []
        
        for pos in list(scan_range)[:edge_sample_size]:
            if side in ['left', 'top']:
                window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
            else:
                window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
            
            if window is not None and window.size > 0:
                edge_samples.append(np.mean(window))
        
        if not edge_samples:
            return 0
        
        edge_mean = np.mean(edge_samples)
        edge_std = np.std(edge_samples)
        
        # Calculate content brightness (sample from middle region)
        middle_start = primary_dim // 4
        middle_end = primary_dim * 3 // 4
        content_samples = []
        
        for pos in range(middle_start, middle_end, 50):
            if side in ['left', 'top']:
                window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
            else:
                window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
            
            if window is not None and window.size > 0:
                content_samples.append(np.mean(window))
        
        if not content_samples:
            return 0
        
        content_mean = np.mean(content_samples)
        
        # Only detect border if edge is significantly darker than content
        # Threshold: edge should be at least 30 brightness units darker
        if edge_mean >= content_mean - 30:
            return 0  # No significant dark border
        
        # Find transition point: where brightness increases significantly
        transition_threshold = edge_mean + (content_mean - edge_mean) * 0.5  # Midpoint
        min_brightness_jump = 20  # Minimum increase to consider it content
        
        last_mean = None
        transition_pos = None
        
        for pos in scan_range:
            if side in ['left', 'top']:
                window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
            else:
                window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
            
            if window is None or window.size == 0:
                continue
            
            mean_val = np.mean(window)
            
            # Check for significant brightness increase
            if last_mean is not None:
                brightness_jump = mean_val - last_mean
                if brightness_jump > min_brightness_jump and mean_val > transition_threshold:
                    transition_pos = pos
                    break
            
            last_mean = mean_val
        
        # If no clear transition, use adaptive threshold based on edge vs content
        if transition_pos is None:
            # Find where we cross the midpoint threshold
            for pos in scan_range:
                if side in ['left', 'top']:
                    window = gray_or_transposed[:, pos:pos+window_size] if pos + window_size <= primary_dim else None
                else:
                    window = gray_or_transposed[:, pos-window_size:pos] if pos - window_size >= 0 else None
                
                if window is None or window.size == 0:
                    continue
                
                mean_val = np.mean(window)
                if mean_val > transition_threshold:
                    transition_pos = pos
                    break
        
        # Convert position to border width
        if transition_pos is None:
            return 0
        
        if side in ['left', 'top']:
            return transition_pos
        else:
            return primary_dim - transition_pos
    
    def remove_borders(self, image: np.ndarray, borders: Optional[Dict[str, int]] = None) -> np.ndarray:
        """Remove borders by whitening uniform regions outside content margins.
        
        Strategy:
        1. White margins define the content area
        2. Everything outside those margins that has low variance (uniform) 
           is whitened (scanner bed, hands, etc.)
        3. High-variance regions are left alone (might be text shadows, binding, etc.)
        
        Args:
            image: Input image (color or grayscale)
            borders: White margin positions dict (detected if None)
            
        Returns:
            Image with uniform border regions whitened
        """
        if borders is None:
            borders = self.detect_borders(image)
        
        result = image.copy()
        h, w = result.shape[:2] if len(result.shape) == 2 else result.shape[:2]
        
        # Convert to grayscale for variance analysis
        if len(result.shape) == 3:
            gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
            white_value = np.array([255, 255, 255], dtype=result.dtype)
        else:
            gray = result
            white_value = 255
        
        # Variance threshold: regions with std < this are considered uniform and can be whitened
        variance_threshold = self.config.get('variance_threshold', 30)
        
        # Define content area from white margins
        content_left = borders['left']
        content_right = w - borders['right']
        content_top = borders['top']
        content_bottom = h - borders['bottom']
        
        # Process top border region
        # Always check significant edge region, not just detected border
        # For slanted borders, check up to half the image height
        check_size = max(borders['top'], min(self.max_border_width, h // 2))
        # Make sure we check at least a reasonable amount
        if borders['top'] < 50:
            check_size = min(self.max_border_width, h // 2)
        
        top_region = gray[:check_size, :]
        self._whiten_uniform_regions(result, top_region, 0, check_size, 0, w,
                                    variance_threshold, white_value, 'top')
        
        # Process bottom border region
        # Always check significant edge region, not just detected border
        # For slanted borders, check up to half the image height
        check_size = max(borders['bottom'], min(self.max_border_width, h // 2))
        # Make sure we check at least a reasonable amount
        if borders['bottom'] < 50:
            check_size = min(self.max_border_width, h // 2)
        
        bottom_region = gray[h-check_size:, :]
        self._whiten_uniform_regions(result, bottom_region, h-check_size, h, 0, w,
                                    variance_threshold, white_value, 'bottom')
        
        # Process left border region
        # Always check significant edge region
        check_size = max(borders['left'], min(self.max_border_width, w // 3))
        if borders['left'] < 50:
            check_size = min(self.max_border_width, w // 3)
        
        left_region = gray[:, :check_size]
        self._whiten_uniform_regions(result, left_region, 0, h, 0, check_size,
                                    variance_threshold, white_value, 'left')
        
        # Process right border region
        check_size = max(borders['right'], min(self.max_border_width, w // 3))
        if borders['right'] < 50:
            check_size = min(self.max_border_width, w // 3)
        
        right_start = w - check_size
        right_region = gray[:, right_start:]
        self._whiten_uniform_regions(result, right_region, 0, h, right_start, w,
                                    variance_threshold, white_value, 'right')
        
        # Also process corners (regions outside content area)
        # Top-left corner
        if borders['top'] > 0 and borders['left'] > 0:
            corner = gray[:borders['top'], :borders['left']]
            if np.std(corner) < variance_threshold:
                if len(result.shape) == 3:
                    result[:borders['top'], :borders['left'], :] = white_value
                else:
                    result[:borders['top'], :borders['left']] = white_value
        
        # Top-right corner
        if borders['top'] > 0 and borders['right'] > 0:
            corner = gray[:borders['top'], w-borders['right']:]
            if np.std(corner) < variance_threshold:
                if len(result.shape) == 3:
                    result[:borders['top'], w-borders['right']:, :] = white_value
                else:
                    result[:borders['top'], w-borders['right']:] = white_value
        
        # Bottom-left corner
        if borders['bottom'] > 0 and borders['left'] > 0:
            corner = gray[h-borders['bottom']:, :borders['left']]
            if np.std(corner) < variance_threshold:
                if len(result.shape) == 3:
                    result[h-borders['bottom']:, :borders['left'], :] = white_value
                else:
                    result[h-borders['bottom']:, :borders['left']] = white_value
        
        # Bottom-right corner
        if borders['bottom'] > 0 and borders['right'] > 0:
            corner = gray[h-borders['bottom']:, w-borders['right']:]
            if np.std(corner) < variance_threshold:
                if len(result.shape) == 3:
                    result[h-borders['bottom']:, w-borders['right']:, :] = white_value
                else:
                    result[h-borders['bottom']:, w-borders['right']:] = white_value
        
        return result
    
    def _whiten_uniform_regions(self, result: np.ndarray, region: np.ndarray,
                                row_start: int, row_end: int, col_start: int, col_end: int,
                                variance_threshold: float, white_value: Any, direction: str):
        """Whiten uniform (low-variance) regions in a border area.
        
        Args:
            result: Full image array to modify
            region: Grayscale region to analyze
            row_start, row_end: Row range in full image
            col_start, col_end: Column range in full image
            variance_threshold: Maximum std dev for whitening
            white_value: White pixel value to use
            direction: 'top', 'bottom', 'left', or 'right'
        """
        if region.size == 0:
            return
        
        if direction in ['top', 'bottom']:
            # For horizontal borders, handle potential slanting (book not perfectly horizontal)
            # Check each row AND each column independently to handle slanted borders
            
            # First pass: whiten entire rows that are uniform/dark
            for i in range(region.shape[0]):
                row_data = region[i, :]
                
                if row_data.size == 0:
                    continue
                
                row_std = np.std(row_data)
                row_mean = np.mean(row_data)
                
                # Whitening criteria: low variance (uniform) OR very dark (scanner bed)
                # More aggressive: whiten if dark, even if not perfectly uniform
                is_uniform = row_std < variance_threshold
                is_very_dark = row_mean < 120  # Increased threshold for dark regions
                is_darkish = row_mean < 150 and row_std < variance_threshold * 1.5  # Medium-dark with low variance
                
                if is_uniform or is_very_dark or is_darkish:
                    # This row is uniform or dark, whiten entire row
                    actual_row = row_start + i
                    if len(result.shape) == 3:
                        result[actual_row, col_start:col_end, :] = white_value
                    else:
                        result[actual_row, col_start:col_end] = white_value
            
            # Second pass: handle slanted borders - check each column independently
            # For tilted books, the border height varies across the width
            # Check ALL columns to ensure complete coverage
            for col_idx in range(region.shape[1]):
                col_data = region[:, col_idx]
                
                if col_data.size == 0:
                    continue
                
                # Find where this column transitions from border to content
                # Scan from edge (direction-dependent)
                content_start_in_col = None
                
                if direction == 'top':
                    # Scan from top (index 0) downward
                    for i in range(len(col_data)):
                        # Check window around this position
                        win_start = max(0, i - 2)
                        win_end = min(len(col_data), i + 3)
                        window = col_data[win_start:win_end]
                        
                        if len(window) == 0:
                            continue
                        
                        win_std = np.std(window)
                        win_mean = np.mean(window)
                        
                        # Content starts when variance increases significantly OR brightness increases
                        # (transition from dark border to lighter content)
                        # Lower thresholds to catch more border regions
                        if win_std > variance_threshold * 1.2 or win_mean > 120:
                            content_start_in_col = i
                            break
                    
                    # Whiten everything before content start in this column
                    if content_start_in_col is not None:
                        actual_col = col_start + col_idx
                        for i in range(content_start_in_col):
                            actual_row = row_start + i
                            if len(result.shape) == 3:
                                result[actual_row, actual_col, :] = white_value
                            else:
                                result[actual_row, actual_col] = white_value
                
                else:  # bottom
                    # Scan from bottom (last index) upward
                    for i in range(len(col_data) - 1, -1, -1):
                        # Check window around this position
                        win_start = max(0, i - 2)
                        win_end = min(len(col_data), i + 3)
                        window = col_data[win_start:win_end]
                        
                        if len(window) == 0:
                            continue
                        
                        win_std = np.std(window)
                        win_mean = np.mean(window)
                        
                        # Content starts when variance increases OR brightness increases
                        # Lower thresholds to catch more border regions
                        if win_std > variance_threshold * 1.2 or win_mean > 120:
                            content_start_in_col = i
                            break
                    
                    # Whiten everything after content start in this column
                    if content_start_in_col is not None:
                        actual_col = col_start + col_idx
                        for i in range(content_start_in_col + 1, len(col_data)):
                            actual_row = row_start + i
                            if len(result.shape) == 3:
                                result[actual_row, actual_col, :] = white_value
                            else:
                                result[actual_row, actual_col] = white_value
        else:  # left, right
            # For vertical borders, check each column
            window_width = min(5, region.shape[1] // 10)
            if window_width < 1:
                window_width = 1
            
            for j in range(region.shape[1]):
                # Get window around this column
                win_start = max(0, j - window_width // 2)
                win_end = min(region.shape[1], j + window_width // 2 + 1)
                window_data = region[:, win_start:win_end]
                
                if window_data.size == 0:
                    continue
                
                col_std = np.std(window_data)
                col_mean = np.mean(window_data)
                
                # Whitening criteria: low variance OR very dark
                is_uniform = col_std < variance_threshold
                is_very_dark = col_mean < 80
                
                if is_uniform or is_very_dark:
                    # This column is uniform or very dark, whiten it
                    actual_col = col_start + j
                    if len(result.shape) == 3:
                        result[row_start:row_end, actual_col, :] = white_value
                    else:
                        result[row_start:row_end, actual_col] = white_value
    
    def detect_borders_grid(self, image: np.ndarray, square_size: int = 100,
                            brightness_threshold: float = 220,
                            variance_threshold: float = 25,
                            margin_percentage: float = 0.7,
                            edge_check_percentage: float = 0.2) -> Dict[str, int]:
        """Alternative grid-based border detection.
        
        Divides image into squares and analyzes variance/brightness to find
        white margins around text content.
        
        Args:
            image: Grayscale or color image as numpy array
            square_size: Size of grid squares in pixels (default: 100)
            brightness_threshold: Minimum brightness for white margin squares (default: 220)
            variance_threshold: Maximum variance for white margin squares (default: 25)
            margin_percentage: Percentage of row/column that must be white margin (default: 0.7)
            edge_check_percentage: Percentage of image dimension to check from each edge (default: 0.2 = 20%)
            
        Returns:
            Dictionary with keys: 'top', 'bottom', 'left', 'right'
            Values are pixel positions where white margins end (content starts)
        """
        # Convert to grayscale if color
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image
        
        h, w = gray.shape
        
        # Limit checking to edge_check_percentage from each edge
        max_top_check = int(h * edge_check_percentage)
        max_bottom_check = int(h * edge_check_percentage)
        max_left_check = int(w * edge_check_percentage)
        max_right_check = int(w * edge_check_percentage)
        
        # Create grid (only need rows/cols in the edge regions we're checking)
        rows = (h + square_size - 1) // square_size  # Ceiling division
        cols = (w + square_size - 1) // square_size
        
        # Calculate mean and std for each square
        grid_mean = np.zeros((rows, cols))
        grid_std = np.zeros((rows, cols))
        
        for i in range(rows):
            for j in range(cols):
                row_start = i * square_size
                row_end = min((i + 1) * square_size, h)
                col_start = j * square_size
                col_end = min((j + 1) * square_size, w)
                
                square = gray[row_start:row_end, col_start:col_end]
                grid_mean[i, j] = np.mean(square)
                grid_std[i, j] = np.std(square)
        
        # Find white margin squares: high brightness, low variance
        white_margin_mask = (grid_mean > brightness_threshold) & (grid_std < variance_threshold)
        
        # Find content boundaries by looking for continuous white margin regions
        # Scan from each edge inward to find where white margins end
        
        # Top: find first row with non-white-margin squares (check up to max_top_check)
        top_margin_rows = 0
        max_top_rows = (max_top_check + square_size - 1) // square_size
        for i in range(min(max_top_rows, rows)):
            if np.sum(white_margin_mask[i, :]) >= cols * margin_percentage:
                top_margin_rows = i + 1
            else:
                break
        
        # Bottom: find last row with non-white-margin squares (check from bottom up to max_bottom_check)
        bottom_margin_rows = 0
        max_bottom_rows = (max_bottom_check + square_size - 1) // square_size
        for i in range(rows - 1, max(rows - max_bottom_rows - 1, -1), -1):
            if np.sum(white_margin_mask[i, :]) >= cols * margin_percentage:
                bottom_margin_rows = rows - i
            else:
                break
        
        # Left: find first column with non-white-margin squares (check up to max_left_check)
        left_margin_cols = 0
        max_left_cols = (max_left_check + square_size - 1) // square_size
        for j in range(min(max_left_cols, cols)):
            if np.sum(white_margin_mask[:, j]) >= rows * margin_percentage:
                left_margin_cols = j + 1
            else:
                break
        
        # Right: find last column with non-white-margin squares (check from right up to max_right_check)
        right_margin_cols = 0
        max_right_cols = (max_right_check + square_size - 1) // square_size
        for j in range(cols - 1, max(cols - max_right_cols - 1, -1), -1):
            if np.sum(white_margin_mask[:, j]) >= rows * margin_percentage:
                right_margin_cols = cols - j
            else:
                break
        
        # Convert grid positions to pixel positions
        return {
            'top': top_margin_rows * square_size,
            'bottom': bottom_margin_rows * square_size,
            'left': left_margin_cols * square_size,
            'right': right_margin_cols * square_size
        }
    
    def remove_borders_grid(self, image: np.ndarray, square_size: int = 100,
                           borders: Optional[Dict[str, int]] = None) -> np.ndarray:
        """Remove borders using grid-based approach.
        
        Identifies white margins around content, then whitens all uniform
        regions outside those margins.
        
        Args:
            image: Input image (color or grayscale)
            square_size: Size of grid squares in pixels
            borders: Content boundary positions (detected if None)
            
        Returns:
            Image with borders whitened
        """
        if borders is None:
            borders = self.detect_borders_grid(image, square_size)
        
        result = image.copy()
        h, w = result.shape[:2] if len(result.shape) == 2 else result.shape[:2]
        
        # Convert to grayscale for analysis
        if len(result.shape) == 3:
            gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
            white_value = np.array([255, 255, 255], dtype=result.dtype)
        else:
            gray = result
            white_value = 255
        
        variance_threshold = self.config.get('variance_threshold', 30)
        
        # Create grid for analyzing regions outside content
        rows = (h + square_size - 1) // square_size
        cols = (w + square_size - 1) // square_size
        
        # Calculate mean and std for each square
        grid_mean = np.zeros((rows, cols))
        grid_std = np.zeros((rows, cols))
        
        for i in range(rows):
            for j in range(cols):
                row_start = i * square_size
                row_end = min((i + 1) * square_size, h)
                col_start = j * square_size
                col_end = min((j + 1) * square_size, w)
                
                square = gray[row_start:row_end, col_start:col_end]
                grid_mean[i, j] = np.mean(square)
                grid_std[i, j] = np.std(square)
        
        # Define content area
        content_top = borders['top']
        content_bottom = h - borders['bottom']
        content_left = borders['left']
        content_right = w - borders['right']
        
        # Whitening criteria: low variance (uniform) OR very dark (scanner bed)
        dark_threshold = 100
        
        # Process each square outside content area
        for i in range(rows):
            for j in range(cols):
                row_start = i * square_size
                row_end = min((i + 1) * square_size, h)
                col_start = j * square_size
                col_end = min((j + 1) * square_size, w)
                
                # Check if square is outside content area
                square_center_row = (row_start + row_end) // 2
                square_center_col = (col_start + col_end) // 2
                
                is_outside = (square_center_row < content_top or 
                             square_center_row >= content_bottom or
                             square_center_col < content_left or
                             square_center_col >= content_right)
                
                if is_outside:
                    # Check if square is uniform or dark
                    mean_val = grid_mean[i, j]
                    std_val = grid_std[i, j]
                    
                    is_uniform = std_val < variance_threshold
                    is_dark = mean_val < dark_threshold
                    
                    if is_uniform or is_dark:
                        # Whiten this square
                        if len(result.shape) == 3:
                            result[row_start:row_end, col_start:col_end, :] = white_value
                        else:
                            result[row_start:row_end, col_start:col_end] = white_value
        
        return result
    
    def remove_borders_grid_hierarchical(self, image: np.ndarray, 
                                        coarse_size: int = 100,
                                        fine_size: int = 25,
                                        brightness_threshold: float = 200,
                                        variance_threshold: float = 30,
                                        margin_percentage: float = 0.5,
                                        edge_check_percentage: float = 0.2,
                                        borders: Optional[Dict[str, int]] = None) -> np.ndarray:
        """Remove borders using hierarchical multi-scale approach.
        
        Phase 1: Coarse detection with large squares (fast)
        Phase 2: Fine-grained removal with small squares only where needed
        
        Args:
            image: Input image (color or grayscale)
            coarse_size: Size of coarse grid squares (default: 100)
            fine_size: Size of fine grid squares for patchy regions (default: 25)
            brightness_threshold: For white margin detection
            variance_threshold: For uniform region detection
            margin_percentage: Percentage requirement for margin detection
            borders: Content boundary positions (detected if None)
            
        Returns:
            Image with borders whitened
        """
        if borders is None:
            borders = self.detect_borders_grid(
                image, 
                square_size=coarse_size,
                brightness_threshold=brightness_threshold,
                variance_threshold=variance_threshold,
                margin_percentage=margin_percentage,
                edge_check_percentage=edge_check_percentage
            )
        
        result = image.copy()
        h, w = result.shape[:2] if len(result.shape) == 2 else result.shape[:2]
        
        # Convert to grayscale
        if len(result.shape) == 3:
            gray = cv2.cvtColor(result, cv2.COLOR_RGB2GRAY)
            white_value = np.array([255, 255, 255], dtype=result.dtype)
        else:
            gray = result
            white_value = 255
        
        variance_threshold_removal = self.config.get('variance_threshold', 30)
        dark_threshold = 100
        
        # Define content area
        content_top = borders['top']
        content_bottom = h - borders['bottom']
        content_left = borders['left']
        content_right = w - borders['right']
        
        # PHASE 1: Coarse processing with large squares
        # Only process edge regions (20% from each edge)
        max_top_process = int(h * edge_check_percentage)
        max_bottom_process = int(h * edge_check_percentage)
        max_left_process = int(w * edge_check_percentage)
        max_right_process = int(w * edge_check_percentage)
        
        coarse_rows = (h + coarse_size - 1) // coarse_size
        coarse_cols = (w + coarse_size - 1) // coarse_size
        
        # Calculate statistics for coarse squares
        coarse_mean = np.zeros((coarse_rows, coarse_cols))
        coarse_std = np.zeros((coarse_rows, coarse_cols))
        patchy_squares = []  # Track squares that need fine-grained processing
        
        for i in range(coarse_rows):
            for j in range(coarse_cols):
                row_start = i * coarse_size
                row_end = min((i + 1) * coarse_size, h)
                col_start = j * coarse_size
                col_end = min((j + 1) * coarse_size, w)
                
                square = gray[row_start:row_end, col_start:col_end]
                coarse_mean[i, j] = np.mean(square)
                coarse_std[i, j] = np.std(square)
        
        # Process coarse squares - only in edge regions
        for i in range(coarse_rows):
            for j in range(coarse_cols):
                row_start = i * coarse_size
                row_end = min((i + 1) * coarse_size, h)
                col_start = j * coarse_size
                col_end = min((j + 1) * coarse_size, w)
                
                # Only process if square is in edge regions (20% from edges)
                is_in_top_edge = row_end <= max_top_process
                is_in_bottom_edge = row_start >= (h - max_bottom_process)
                is_in_left_edge = col_end <= max_left_process
                is_in_right_edge = col_start >= (w - max_right_process)
                is_in_edge_region = is_in_top_edge or is_in_bottom_edge or is_in_left_edge or is_in_right_edge
                
                if not is_in_edge_region:
                    continue  # Skip squares in center region
                
                # Check if square is outside content area
                square_center_row = (row_start + row_end) // 2
                square_center_col = (col_start + col_end) // 2
                
                is_outside = (square_center_row < content_top or 
                             square_center_row >= content_bottom or
                             square_center_col < content_left or
                             square_center_col >= content_right)
                
                if is_outside:
                    mean_val = coarse_mean[i, j]
                    std_val = coarse_std[i, j]
                    
                    is_uniform = std_val < variance_threshold_removal
                    is_dark = mean_val < dark_threshold
                    
                    if is_uniform or is_dark:
                        # Uniform or very dark: whiten entire coarse square
                        if len(result.shape) == 3:
                            result[row_start:row_end, col_start:col_end, :] = white_value
                        else:
                            result[row_start:row_end, col_start:col_end] = white_value
                    elif mean_val < 150:  # Patchy dark region (medium-dark, high variance)
                        # Mark for fine-grained processing
                        patchy_squares.append((i, j, row_start, row_end, col_start, col_end))
        
        # PHASE 2: Fine-grained processing for patchy squares
        for i, j, row_start, row_end, col_start, col_end in patchy_squares:
            # Subdivide this coarse square into fine squares
            fine_rows = (row_end - row_start + fine_size - 1) // fine_size
            fine_cols = (col_end - col_start + fine_size - 1) // fine_size
            
            for fi in range(fine_rows):
                for fj in range(fine_cols):
                    fine_row_start = row_start + fi * fine_size
                    fine_row_end = min(row_start + (fi + 1) * fine_size, row_end)
                    fine_col_start = col_start + fj * fine_size
                    fine_col_end = min(col_start + (fj + 1) * fine_size, col_end)
                    
                    fine_square = gray[fine_row_start:fine_row_end, fine_col_start:fine_col_end]
                    
                    if fine_square.size == 0:
                        continue
                    
                    fine_mean = np.mean(fine_square)
                    fine_std = np.std(fine_square)
                    
                    # For sub-squares: whiten if uniform OR dark
                    fine_is_uniform = fine_std < variance_threshold_removal
                    fine_is_dark = fine_mean < dark_threshold
                    
                    if fine_is_uniform or fine_is_dark:
                        # Whiten this sub-square
                        if len(result.shape) == 3:
                            result[fine_row_start:fine_row_end, fine_col_start:fine_col_end, :] = white_value
                        else:
                            result[fine_row_start:fine_row_end, fine_col_start:fine_col_end] = white_value
        
        return result
    
    def process_pdf_page(self, pdf_path: Path, page_num: int, 
                        zoom: float = 2.0) -> Tuple[np.ndarray, Dict[str, int]]:
        """Process a single PDF page.
        
        Args:
            pdf_path: Path to PDF file
            page_num: Zero-indexed page number
            zoom: Render zoom level for image quality
            
        Returns:
            Tuple of (processed image, detected borders dict)
        """
        doc = fitz.open(str(pdf_path))
        try:
            if page_num >= len(doc):
                raise ValueError(f"Page {page_num} not found (PDF has {len(doc)} pages)")
            
            page = doc[page_num]
            
            # Render page as image
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Convert to numpy array
            img = Image.open(io.BytesIO(img_data))
            image_array = np.array(img)
            
            # Detect and remove borders
            borders = self.detect_borders(image_array)
            result = self.remove_borders(image_array, borders)
            
            return result, borders
            
        finally:
            doc.close()
    
    def process_entire_pdf(self, pdf_path: Path, output_path: Path,
                          zoom: float = 2.0, pages: Optional[list] = None) -> Dict[str, Any]:
        """Process entire PDF and save with borders removed.
        
        Args:
            pdf_path: Input PDF path
            output_path: Output PDF path
            zoom: Render zoom for quality
            pages: Optional list of page numbers to process (None = all pages)
            
        Returns:
            Processing statistics dictionary
        """
        doc = fitz.open(str(pdf_path))
        stats = {
            'pages_processed': 0,
            'total_border_pixels': 0,
            'border_widths': []
        }
        
        try:
            output_doc = fitz.open()  # New PDF
            
            process_pages = pages if pages is not None else range(len(doc))
            
            for page_num in process_pages:
                try:
                    # Process page - get processed high-res image
                    processed_image, borders = self.process_pdf_page(
                        pdf_path, page_num, zoom
                    )
                    
                    # Create new page in output PDF with original dimensions
                    original_page = doc[page_num]
                    rect = original_page.rect
                    new_page = output_doc.new_page(width=rect.width, height=rect.height)
                    
                    # Convert numpy array to PIL Image
                    img = Image.fromarray(processed_image)
                    
                    # Create pixmap from image for insertion
                    img_bytes = io.BytesIO()
                    img.save(img_bytes, format='PNG')
                    img_bytes.seek(0)
                    
                    # Insert as image - rect will scale automatically
                    img_rect = fitz.Rect(0, 0, rect.width, rect.height)
                    new_page.insert_image(img_rect, stream=img_bytes.read())
                    
                    # Track statistics
                    stats['pages_processed'] += 1
                    border_pixels = (borders['top'] + borders['bottom']) * processed_image.shape[1] + \
                                   (borders['left'] + borders['right']) * processed_image.shape[0]
                    stats['total_border_pixels'] += border_pixels
                    stats['border_widths'].append(borders)
                    
                    self.logger.debug(f"Page {page_num + 1}: removed borders {borders}")
                    
                except Exception as e:
                    self.logger.error(f"Error processing page {page_num + 1}: {e}")
                    continue
            
            # Save output PDF
            output_doc.save(str(output_path))
            output_doc.close()
            
            self.logger.debug(f"Processed {stats['pages_processed']} pages, "
                             f"removed {stats['total_border_pixels']} border pixels")
            
        finally:
            doc.close()
        
        return stats

    # -------------------- Page-edge based detection (no cropping) --------------------
    def detect_page_edges(self, image: np.ndarray) -> Dict[str, int]:
        """Detect physical page edges (paper vs scanner bed) using brightness.

        Returns median distances from each side to the page edge: keys 'top','bottom','left','right'.
        """
        # Convert to grayscale
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        h, w = gray.shape

        # Estimate page white from central patch (20% x 20%)
        row0 = h // 2 - h // 10
        row1 = h // 2 + h // 10
        col0 = w // 2 - w // 10
        col1 = w // 2 + w // 10
        center_patch = gray[max(0, row0):min(h, row1), max(0, col0):min(w, col1)]
        center_mean = float(np.mean(center_patch)) if center_patch.size > 0 else 230.0
        page_white_threshold = max(150.0, center_mean - float(self.page_white_delta))

        # Scan limits
        max_top = int(h * self.max_check_percentage)
        max_bottom = int(h * self.max_check_percentage)
        max_left = int(w * self.max_check_percentage)
        max_right = int(w * self.max_check_percentage)

        # Per-line boundaries
        top_boundary = self._scan_edge(gray, 'top', page_white_threshold, self.sustained_run, max_top)
        bottom_boundary = self._scan_edge(gray, 'bottom', page_white_threshold, self.sustained_run, max_bottom)
        left_boundary = self._scan_edge(gray, 'left', page_white_threshold, self.sustained_run, max_left)
        right_boundary = self._scan_edge(gray, 'right', page_white_threshold, self.sustained_run, max_right)

        # Summaries (median distances)
        top_med = int(np.median(top_boundary)) if len(top_boundary) else 0
        bottom_med = int(np.median(bottom_boundary)) if len(bottom_boundary) else 0
        left_med = int(np.median(left_boundary)) if len(left_boundary) else 0
        right_med = int(np.median(right_boundary)) if len(right_boundary) else 0

        return {'top': top_med, 'bottom': bottom_med, 'left': left_med, 'right': right_med}

    def remove_borders_page_edge(self, image: np.ndarray) -> np.ndarray:
        """Whiten regions outside detected page edges while preserving image size."""
        # Convert to grayscale
        color = len(image.shape) == 3
        if color:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            result = image.copy()
            white_value = np.array([255, 255, 255], dtype=image.dtype)
        else:
            gray = image
            result = image.copy()
            white_value = 255

        h, w = gray.shape

        # Estimate page white
        row0 = h // 2 - h // 10
        row1 = h // 2 + h // 10
        col0 = w // 2 - w // 10
        col1 = w // 2 + w // 10
        center_patch = gray[max(0, row0):min(h, row1), max(0, col0):min(w, col1)]
        center_mean = float(np.mean(center_patch)) if center_patch.size > 0 else 230.0
        page_white_threshold = max(150.0, center_mean - float(self.page_white_delta))

        # Scan limits
        max_top = int(h * self.max_check_percentage)
        max_bottom = int(h * self.max_check_percentage)
        max_left = int(w * self.max_check_percentage)
        max_right = int(w * self.max_check_percentage)

        # Per-line boundaries (arrays)
        top_boundary = self._scan_edge(gray, 'top', page_white_threshold, self.sustained_run, max_top)
        bottom_boundary = self._scan_edge(gray, 'bottom', page_white_threshold, self.sustained_run, max_bottom)
        left_boundary = self._scan_edge(gray, 'left', page_white_threshold, self.sustained_run, max_left)
        right_boundary = self._scan_edge(gray, 'right', page_white_threshold, self.sustained_run, max_right)

        # Whitening per edge using per-line boundaries
        # Top: for each column, whiten rows [0, boundary)
        for x in range(w):
            b = top_boundary[x] if x < len(top_boundary) else 0
            if b > 0:
                if color:
                    result[0:b, x, :] = white_value
                else:
                    result[0:b, x] = white_value

        # Bottom: boundary is distance from bottom; compute row index
        for x in range(w):
            d = bottom_boundary[x] if x < len(bottom_boundary) else 0
            if d > 0:
                row_idx = h - d
                if row_idx < 0:
                    row_idx = 0
                if color:
                    result[row_idx:h, x, :] = white_value
                else:
                    result[row_idx:h, x] = white_value

        # Left: for each row, whiten cols [0, boundary)
        for y in range(h):
            b = left_boundary[y] if y < len(left_boundary) else 0
            if b > 0:
                if color:
                    result[y, 0:b, :] = white_value
                else:
                    result[y, 0:b] = white_value

        # Right: distance from right; compute col index
        for y in range(h):
            d = right_boundary[y] if y < len(right_boundary) else 0
            if d > 0:
                col_idx = w - d
                if col_idx < 0:
                    col_idx = 0
                if color:
                    result[y, col_idx:w, :] = white_value
                else:
                    result[y, col_idx:w] = white_value

        return result

    # -------------------- Center-out WT/TW-driven detection --------------------
    def detect_page_edges_center_out(self, image: np.ndarray) -> Dict[str, int]:
        """Detect page edges by scanning from center toward each side focusing on TW.

        Returns median distances (in pixels) from each side to TW: 'top','bottom','left','right'.
        If no TW found on a side, returns 0 for that side.
        """
        if len(image.shape) == 3:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
        else:
            gray = image

        h, w = gray.shape

        # Estimate white threshold from center patch
        row0 = h // 2 - h // 10
        row1 = h // 2 + h // 10
        col0 = w // 2 - w // 10
        col1 = w // 2 + w // 10
        center_patch = gray[max(0, row0):min(h, row1), max(0, col0):min(w, col1)]
        center_mean = float(np.mean(center_patch)) if center_patch.size > 0 else 230.0
        white_thr = max(150.0, center_mean - float(self.page_white_delta))
        dark_thr = float(self.dark_threshold)

        top_tw = self._scan_center_out_tw(gray, 'top', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        bottom_tw = self._scan_center_out_tw(gray, 'bottom', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        left_tw = self._scan_center_out_tw(gray, 'left', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        right_tw = self._scan_center_out_tw(gray, 'right', white_thr, dark_thr, self.sustained_text, self.sustained_run)

        # Reduce to medians and convert to distances from edges
        def med(arr: np.ndarray) -> int:
            vals = arr[arr >= 0]
            return int(np.median(vals)) if vals.size > 0 else -1

        top_idx = med(top_tw)
        bottom_idx = med(bottom_tw)
        left_idx = med(left_tw)
        right_idx = med(right_tw)

        top = max(0, top_idx) if top_idx >= 0 else 0
        bottom = max(0, h - 1 - bottom_idx) if bottom_idx >= 0 else 0
        left = max(0, left_idx) if left_idx >= 0 else 0
        right = max(0, w - 1 - right_idx) if right_idx >= 0 else 0

        # Verify actual dark borders: only report if we find dark pixels within edge inset band
        # This prevents false positives on laser-printed PDFs with wide white margins
        inset = self.edge_inset
        
        def has_dark_at_edge(side: str, distance: int) -> bool:
            """Check if there are dark pixels within edge inset band."""
            if distance == 0:
                return False  # No border detected
            
            # Sample pixels in the edge band (from edge to edge+inset)
            dark_count = 0
            total_samples = 0
            sample_step = max(1, inset // 5)  # Sample ~5 points across inset
            
            if side == 'top' and distance > 0:
                y_range = range(0, min(inset, distance))
                for y in y_range[::sample_step]:
                    x_samples = range(0, w, max(1, w // 20))  # Sample across width
                    for x in x_samples:
                        if gray[y, x] <= dark_thr:
                            dark_count += 1
                        total_samples += 1
            elif side == 'bottom' and distance > 0:
                y_range = range(max(0, h - inset), h)
                for y in y_range[::sample_step]:
                    x_samples = range(0, w, max(1, w // 20))
                    for x in x_samples:
                        if gray[y, x] <= dark_thr:
                            dark_count += 1
                        total_samples += 1
            elif side == 'left' and distance > 0:
                x_range = range(0, min(inset, distance))
                for x in x_range[::sample_step]:
                    y_samples = range(0, h, max(1, h // 20))
                    for y in y_samples:
                        if gray[y, x] <= dark_thr:
                            dark_count += 1
                        total_samples += 1
            elif side == 'right' and distance > 0:
                x_range = range(max(0, w - inset), w)
                for x in x_range[::sample_step]:
                    y_samples = range(0, h, max(1, h // 20))
                    for y in y_samples:
                        if gray[y, x] <= dark_thr:
                            dark_count += 1
                        total_samples += 1
            
            # Require at least 10% of samples to be dark (scanner bed is consistently dark)
            return total_samples > 0 and (dark_count / total_samples) >= 0.10
        
        # Only report borders where we find actual dark pixels
        if not has_dark_at_edge('top', top):
            top = 0
        if not has_dark_at_edge('bottom', bottom):
            bottom = 0
        if not has_dark_at_edge('left', left):
            left = 0
        if not has_dark_at_edge('right', right):
            right = 0

        return {'top': top, 'bottom': bottom, 'left': left, 'right': right}

    def remove_borders_page_edge_center_out(self, image: np.ndarray) -> np.ndarray:
        """Whiten beyond TW per side using center-out detection; preserve size.
        
        Uses light gray (240) for whitening so dark areas remain visible for diagnostics.
        Only whitens a side if >= min_valid_ratio of scanlines found valid TW transitions.
        """
        color = len(image.shape) == 3
        if color:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            result = image.copy()
            whiten_value = np.array([self.whiten_gray, self.whiten_gray, self.whiten_gray], dtype=image.dtype)
        else:
            gray = image
            result = image.copy()
            whiten_value = self.whiten_gray

        h, w = gray.shape

        # thresholds
        row0 = h // 2 - h // 10
        row1 = h // 2 + h // 10
        col0 = w // 2 - w // 10
        col1 = w // 2 + w // 10
        center_patch = gray[max(0, row0):min(h, row1), max(0, col0):min(w, col1)]
        center_mean = float(np.mean(center_patch)) if center_patch.size > 0 else 230.0
        white_thr = max(150.0, center_mean - float(self.page_white_delta))
        dark_thr = float(self.dark_threshold)

        top_tw = self._scan_center_out_tw(gray, 'top', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        bottom_tw = self._scan_center_out_tw(gray, 'bottom', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        left_tw = self._scan_center_out_tw(gray, 'left', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        right_tw = self._scan_center_out_tw(gray, 'right', white_thr, dark_thr, self.sustained_text, self.sustained_run)

        # Safety check: only whiten if enough scanlines found TW
        def should_whiten(arr):
            valid_count = np.sum(arr >= 0)
            return valid_count >= (len(arr) * self.min_valid_ratio)

        # Define edge bands (only process outer bands)
        top_band = int(h * self.edge_process_pct)
        bottom_band = h - int(h * self.edge_process_pct)
        left_band = int(w * self.edge_process_pct)
        right_band = w - int(w * self.edge_process_pct)

        # Top: whiten rows [0, min(tw, top_band))
        if should_whiten(top_tw):
            for x in range(w):
                idx = top_tw[x] if x < len(top_tw) else -1
                if idx > 0:
                    y0, y1 = 0, min(idx, top_band)
                    if y1 > y0:
                        if color:
                            result[y0:y1, x, :] = whiten_value
                        else:
                            result[y0:y1, x] = whiten_value

        # Bottom: whiten rows [max(tw, bottom_band), h)
        if should_whiten(bottom_tw):
            for x in range(w):
                idx = bottom_tw[x] if x < len(bottom_tw) else -1
                if idx >= 0 and idx < h:
                    y0, y1 = max(idx, bottom_band), h
                    if y1 > y0:
                        if color:
                            result[y0:y1, x, :] = whiten_value
                        else:
                            result[y0:y1, x] = whiten_value

        # Left: whiten cols [0, min(tw, left_band))
        if should_whiten(left_tw):
            for y in range(h):
                idx = left_tw[y] if y < len(left_tw) else -1
                if idx > 0:
                    x0, x1 = 0, min(idx, left_band)
                    if x1 > x0:
                        if color:
                            result[y, x0:x1, :] = whiten_value
                        else:
                            result[y, x0:x1] = whiten_value

        # Right: whiten cols [max(tw, right_band), w)
        if should_whiten(right_tw):
            for y in range(h):
                idx = right_tw[y] if y < len(right_tw) else -1
                if idx >= 0 and idx < w:
                    x0, x1 = max(idx, right_band), w
                    if x1 > x0:
                        if color:
                            result[y, x0:x1, :] = whiten_value
                        else:
                            result[y, x0:x1] = whiten_value

        return result

    def remove_borders_page_edge_center_out_diagnostics(self, image: np.ndarray):
        """Return (result, masks, tw_dict) using per-side diagnostic grays and masks.

        masks: { 'top': bool[h,w], 'bottom': bool[h,w], 'left': bool[h,w], 'right': bool[h,w] }
        tw_dict: { 'top': np.ndarray[w], 'bottom': np.ndarray[w], 'left': np.ndarray[h], 'right': np.ndarray[h] }
        """
        color = len(image.shape) == 3
        if color:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            result = image.copy()
        else:
            gray = image
            result = image.copy()

        h, w = gray.shape

        # thresholds
        row0 = h // 2 - h // 10
        row1 = h // 2 + h // 10
        col0 = w // 2 - w // 10
        col1 = w // 2 + w // 10
        center_patch = gray[max(0, row0):min(h, row1), max(0, col0):min(w, col1)]
        center_mean = float(np.mean(center_patch)) if center_patch.size > 0 else 230.0
        white_thr = max(150.0, center_mean - float(self.page_white_delta))
        dark_thr = float(self.dark_threshold)

        top_tw = self._scan_center_out_tw(gray, 'top', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        bottom_tw = self._scan_center_out_tw(gray, 'bottom', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        left_tw = self._scan_center_out_tw(gray, 'left', white_thr, dark_thr, self.sustained_text, self.sustained_run)
        right_tw = self._scan_center_out_tw(gray, 'right', white_thr, dark_thr, self.sustained_text, self.sustained_run)

        def should_whiten(arr):
            valid_count = np.sum(arr >= 0)
            return valid_count >= (len(arr) * self.min_valid_ratio)

        # Build per-side masks
        masks = {
            'top': np.zeros((h, w), dtype=bool),
            'bottom': np.zeros((h, w), dtype=bool),
            'left': np.zeros((h, w), dtype=bool),
            'right': np.zeros((h, w), dtype=bool),
        }

        if should_whiten(top_tw):
            for x in range(w):
                idx = top_tw[x] if x < len(top_tw) else -1
                if idx > 0:
                    masks['top'][0:idx, x] = True

        if should_whiten(bottom_tw):
            for x in range(w):
                idx = bottom_tw[x] if x < len(bottom_tw) else -1
                if idx >= 0 and idx < h:
                    masks['bottom'][idx:h, x] = True

        if should_whiten(left_tw):
            for y in range(h):
                idx = left_tw[y] if y < len(left_tw) else -1
                if idx > 0:
                    masks['left'][y, 0:idx] = True

        if should_whiten(right_tw):
            for y in range(h):
                idx = right_tw[y] if y < len(right_tw) else -1
                if idx >= 0 and idx < w:
                    masks['right'][y, idx:w] = True

        # Apply masks with per-side grays (restrict to outer bands and erode)
        order = ['top', 'bottom', 'left', 'right']
        top_band = int(h * self.edge_process_pct)
        bottom_band = h - int(h * self.edge_process_pct)
        left_band = int(w * self.edge_process_pct)
        right_band = w - int(w * self.edge_process_pct)
        grays = {
            'top': self.top_gray,
            'bottom': self.bottom_gray,
            'left': self.left_gray,
            'right': self.right_gray,
        }

        painted = np.zeros((h, w), dtype=bool)
        for side in order:
            m = masks[side]
            # Restrict to edge bands
            band = np.zeros_like(m)
            if side == 'top':
                band[0:top_band, :] = True
            elif side == 'bottom':
                band[bottom_band:h, :] = True
            elif side == 'left':
                band[:, 0:left_band] = True
            else:
                band[:, right_band:w] = True
            m = np.logical_and(m, band)
            # Erode mask to avoid tendrils
            if self.mask_erode_px and self.mask_erode_px > 0:
                k = int(self.mask_erode_px)
                kernel = np.ones((k, k), dtype=np.uint8)
                m = cv2.erode(m.astype(np.uint8), kernel, iterations=1).astype(bool)
            if not m.any():
                continue
            if self.first_wins:
                m = np.logical_and(m, np.logical_not(painted))
            if color:
                val = np.array([grays[side], grays[side], grays[side]], dtype=result.dtype)
                result[m] = val
            else:
                result[m] = grays[side]
            painted |= m

        tw_dict = {
            'top': top_tw,
            'bottom': bottom_tw,
            'left': left_tw,
            'right': right_tw,
        }

        return result, masks, tw_dict

    # -------------------- WDW (edge-in) detection: optional W0, then D→W1 --------------------
    def remove_borders_page_edge_wdw_diagnostics(self, image: np.ndarray):
        """Detect borders using edge-in W0(optional)->D->W1 per side and whiten within edge bands.

        Returns (result, masks, w1_dict) for diagnostics.
        """
        color = len(image.shape) == 3
        if color:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            result = image.copy()
        else:
            gray = image
            result = image.copy()

        h, w = gray.shape
        top_band = int(h * self.edge_process_pct)
        bottom_band = h - int(h * self.edge_process_pct)
        left_band = int(w * self.edge_process_pct)
        right_band = w - int(w * self.edge_process_pct)

        # thresholds per side band via percentiles
        def side_percentiles(arr: np.ndarray, axis: int, band_slice) -> tuple[float, float]:
            band = arr[band_slice]
            # Flatten to compute thresholds
            vals = band.reshape(-1)
            if vals.size == 0:
                return 230.0, 60.0
            bright_thr = float(np.percentile(vals, self.band_bright_percentile))
            dark_thr = float(np.percentile(vals, self.band_dark_percentile))
            return bright_thr, dark_thr

        # Sides: compute thresholds
        top_bright, top_dark = side_percentiles(gray, 0, (slice(0, top_band), slice(0, w)))
        bottom_bright, bottom_dark = side_percentiles(gray, 0, (slice(bottom_band, h), slice(0, w)))
        left_bright, left_dark = side_percentiles(gray, 1, (slice(0, h), slice(0, left_band)))
        right_bright, right_dark = side_percentiles(gray, 1, (slice(0, h), slice(right_band, w)))

        # Helper to run-length with small-gap tolerance
        def run_len(seq: np.ndarray, start: int, step: int, pred, max_gap: int, limit: int) -> tuple[int, int]:
            length = 0
            gaps = 0
            i = start
            last = start
            while 0 <= i < limit:
                if pred(float(seq[i])):
                    length += 1
                else:
                    gaps += 1
                    if gaps > max_gap:
                        break
                last = i
                i += step
            return length, last

        # Scanline function: find W1 start index given line and direction
        def scan_wdw_line(line: np.ndarray, direction: str, bright_thr: float, dark_thr: float,
                           max_w0: int, min_d: int, min_w1: int, close_k: int) -> int:
            n = len(line)
            if direction in ('top', 'left'):
                idx = 0; step = 1
            else:
                idx = n - 1; step = -1

            # Try Case A: W0 -> D -> W1
            # W0 (optional, but try first): bright short strip
            w0_len, pos_after_w0 = run_len(line, idx, step, lambda v: v >= bright_thr, close_k, n)
            if w0_len > max_w0:
                # If W0 is very long, cap it for the chain, but still allow chain to proceed
                pass

            d_start = pos_after_w0 + step if w0_len > 0 else idx
            d_len, pos_after_d = run_len(line, d_start, step, lambda v: v <= dark_thr, close_k, n)
            if d_len >= min_d:
                w1_start = pos_after_d + step
                w1_len, _ = run_len(line, w1_start, step, lambda v: v >= bright_thr, close_k, n)
                if w1_len >= min_w1:
                    return w1_start if direction in ('top', 'left') else w1_start

            # Case B: D -> W1
            d_len2, pos_after_d2 = run_len(line, idx, step, lambda v: v <= dark_thr, close_k, n)
            if d_len2 >= min_d:
                w1_start2 = pos_after_d2 + step
                w1_len2, _ = run_len(line, w1_start2, step, lambda v: v >= bright_thr, close_k, n)
                if w1_len2 >= min_w1:
                    return w1_start2

            return -1

        # Build per-side W1 indices
        top_w1 = np.full(w, -1, dtype=np.int32)
        for x in range(w):
            col = gray[:, x]
            top_w1[x] = scan_wdw_line(col[:top_band], 'top', top_bright, top_dark,
                                      self.max_outer_white_px, self.min_dark_px, self.min_page_margin_px, self.close_gaps_k)

        bottom_w1 = np.full(w, -1, dtype=np.int32)
        for x in range(w):
            col = gray[:, x]
            # remap index back to full image coordinates
            local = scan_wdw_line(col[bottom_band:], 'bottom', bottom_bright, bottom_dark,
                                  self.max_outer_white_px, self.min_dark_px, self.min_page_margin_px, self.close_gaps_k)
            if local >= 0:
                bottom_w1[x] = bottom_band + local

        left_w1 = np.full(h, -1, dtype=np.int32)
        for y in range(h):
            row = gray[y, :]
            left_w1[y] = scan_wdw_line(row[:left_band], 'left', left_bright, left_dark,
                                       self.max_outer_white_px, self.min_dark_px, self.min_page_margin_px, self.close_gaps_k)

        right_w1 = np.full(h, -1, dtype=np.int32)
        for y in range(h):
            row = gray[y, :]
            local = scan_wdw_line(row[right_band:], 'right', right_bright, right_dark,
                                  self.max_outer_white_px, self.min_dark_px, self.min_page_margin_px, self.close_gaps_k)
            if local >= 0:
                right_w1[y] = right_band + local

        # Neighbor consensus filtering
        def neighbor_filter(arr: np.ndarray) -> np.ndarray:
            length = len(arr)
            if self.neighbor_window <= 1:
                return arr
            win = self.neighbor_window
            half = win // 2
            out = np.full(length, -1, dtype=np.int32)
            for i in range(length):
                if arr[i] < 0:
                    continue
                s = max(0, i - half)
                e = min(length, i + half + 1)
                seg = arr[s:e]
                vals = seg[seg >= 0]
                if vals.size == 0:
                    continue
                cnt = np.sum(np.abs(vals - arr[i]) <= self.neighbor_delta)
                if cnt >= self.neighbor_min:
                    out[i] = arr[i]
            return out

        top_w1 = neighbor_filter(top_w1)
        bottom_w1 = neighbor_filter(bottom_w1)
        left_w1 = neighbor_filter(left_w1)
        right_w1 = neighbor_filter(right_w1)

        # Build masks and apply with erosion
        masks = {
            'top': np.zeros((h, w), dtype=bool),
            'bottom': np.zeros((h, w), dtype=bool),
            'left': np.zeros((h, w), dtype=bool),
            'right': np.zeros((h, w), dtype=bool),
        }
        for x in range(w):
            y1 = top_w1[x]
            if y1 > 0:
                masks['top'][0:min(y1, top_band), x] = True
            yb = bottom_w1[x]
            if yb >= 0:
                masks['bottom'][max(yb, bottom_band):h, x] = True
        for y in range(h):
            x1 = left_w1[y]
            if x1 > 0:
                masks['left'][y, 0:min(x1, left_band)] = True
            xr = right_w1[y]
            if xr >= 0:
                masks['right'][y, max(xr, right_band):w] = True

        # Erode and apply per side grays
        order = ['top', 'bottom', 'left', 'right']
        grays = {
            'top': self.top_gray,
            'bottom': self.bottom_gray,
            'left': self.left_gray,
            'right': self.right_gray,
        }
        painted = np.zeros((h, w), dtype=bool)
        for side in order:
            m = masks[side]
            if self.mask_erode_px and self.mask_erode_px > 0:
                k = int(self.mask_erode_px)
                kernel = np.ones((k, k), dtype=np.uint8)
                m = cv2.erode(m.astype(np.uint8), kernel, iterations=1).astype(bool)
            if not m.any():
                continue
            if self.first_wins:
                m = np.logical_and(m, np.logical_not(painted))
            if color:
                val = np.array([grays[side], grays[side], grays[side]], dtype=result.dtype)
                result[m] = val
            else:
                result[m] = grays[side]
            painted |= m

        w1_dict = {'top': top_w1, 'bottom': bottom_w1, 'left': left_w1, 'right': right_w1}
        return result, masks, w1_dict

    def _scan_center_out_tw(self, gray: np.ndarray, side: str, white_thr: float, dark_thr: float,
                             sustained_text: int, sustained_white: int) -> np.ndarray:
        """Per scanline, move outward from center to find TW (text->white) position.

        Returns array of absolute indices along the scan axis (row index for top/bottom,
        column index for left/right). -1 if not found on a line.
        """
        h, w = gray.shape
        if side in ('top', 'bottom'):
            length = w
        else:
            length = h

        tw = np.full(length, -1, dtype=np.int32)

        def is_white_val(v: float) -> bool:
            return v >= white_thr

        def is_dark_val(v: float) -> bool:
            return v <= dark_thr

        def is_text_val(v: float) -> bool:
            return (v < white_thr) and (v > dark_thr)

        def sustained(seq, idx, step, pred, k):
            cnt = 0
            i = idx
            while 0 <= i < len(seq) and pred(float(seq[i])):
                cnt += 1
                if cnt >= k:
                    return True
                i += step
            return False

        for s in range(length):
            if side == 'top':
                line = gray[:, s]
                center = h // 2
                rng = range(center, -1, -1)
                step = -1
            elif side == 'bottom':
                line = gray[:, s]
                center = h // 2
                rng = range(center, h)
                step = 1
            elif side == 'left':
                line = gray[s, :]
                center = w // 2
                rng = range(center, -1, -1)
                step = -1
            else:  # right
                line = gray[s, :]
                center = w // 2
                rng = range(center, w)
                step = 1

            # Determine starting state at center
            cval = float(line[center])
            state = 'T' if is_text_val(cval) else ('W' if is_white_val(cval) else 'D')

            if state == 'W':
                # Walk outward until we enter text, then look for TW
                entered_text = False
                text_pos = None
                for idx in rng:
                    v = float(line[idx])
                    if not entered_text and is_text_val(v):
                        if sustained(line, idx, step, lambda x: is_text_val(x), max(sustained_text, self.min_text_before_tw)):
                            entered_text = True
                            text_pos = idx
                            continue
                    if entered_text and is_white_val(v):
                        # Require long white run after TW
                        if sustained(line, idx, step, lambda x: is_white_val(x), max(sustained_white, self.min_white_after_tw)):
                            tw[s] = idx
                            break
            elif state == 'T':
                # Immediately look for TW
                for idx in rng:
                    v = float(line[idx])
                    if is_white_val(v):
                        if sustained(line, idx, step, lambda x: is_white_val(x), max(sustained_white, self.min_white_after_tw)):
                            # also ensure we have enough text behind
                            back_start = idx - (self.min_text_before_tw * (-step))
                            back_ok = True
                            cnt = 0
                            j = idx - step
                            while 0 <= j < len(line) and cnt < self.min_text_before_tw:
                                if not is_text_val(float(line[j])):
                                    back_ok = False
                                    break
                                cnt += 1
                                j -= step
                            if back_ok:
                                tw[s] = idx
                                break
            else:  # state == 'D'
                # Walk until we hit text, then TW
                entered_text = False
                for idx in rng:
                    v = float(line[idx])
                    if not entered_text and is_text_val(v):
                        if sustained(line, idx, step, lambda x: is_text_val(x), max(sustained_text, self.min_text_before_tw)):
                            entered_text = True
                            continue
                    if entered_text and is_white_val(v):
                        if sustained(line, idx, step, lambda x: is_white_val(x), max(sustained_white, self.min_white_after_tw)):
                            tw[s] = idx
                            break

        # Enforce per-side minimum margins from the edge
        if side == 'top':
            for i in range(length):
                if tw[i] >= 0 and tw[i] < self.min_margin_top:
                    tw[i] = -1
        elif side == 'bottom':
            for i in range(length):
                if tw[i] >= 0 and (h - 1 - tw[i]) < self.min_margin_bottom:
                    tw[i] = -1
        elif side == 'left':
            for i in range(length):
                if tw[i] >= 0 and tw[i] < self.min_margin_left:
                    tw[i] = -1
        else:  # right
            for i in range(length):
                if tw[i] >= 0 and (w - 1 - tw[i]) < self.min_margin_right:
                    tw[i] = -1

        # Smooth TW indices to reduce outliers (only smooth valid values, keep -1 as -1)
        if length > 0 and self.smoothing_window > 1:
            k = self.smoothing_window if self.smoothing_window % 2 == 1 else self.smoothing_window + 1
            pad = k // 2
            # Only smooth where we have valid values; keep -1 as -1
            valid_mask = tw >= 0
            if np.sum(valid_mask) > k:  # Only smooth if enough valid values
                smoothed = np.full(length, -1, dtype=np.int32)
                for i in range(length):
                    if tw[i] >= 0:
                        # Get neighbors for smoothing
                        win_start = max(0, i - pad)
                        win_end = min(length, i + pad + 1)
                        neighbors = tw[win_start:win_end]
                        valid_neighbors = neighbors[neighbors >= 0]
                        if len(valid_neighbors) >= (k // 2 + 1):
                            smoothed[i] = int(np.median(valid_neighbors))
                        else:
                            smoothed[i] = tw[i]
                    else:
                        smoothed[i] = -1
                tw = smoothed

        # Neighbor consensus filter
        if self.neighbor_window > 1 and self.neighbor_min > 0:
            win = self.neighbor_window
            half = win // 2
            filtered = np.full(length, -1, dtype=np.int32)
            for i in range(length):
                if tw[i] < 0:
                    continue
                start = max(0, i - half)
                end = min(length, i + half + 1)
                segment = tw[start:end]
                vals = segment[segment >= 0]
                if vals.size == 0:
                    continue
                count = np.sum(np.abs(vals - tw[i]) <= self.neighbor_delta)
                if count >= self.neighbor_min:
                    filtered[i] = tw[i]
            tw = filtered

        return tw

    # -------------------- Edge-in W0? -> D -> W1 detector --------------------
    def _edge_band_thresholds(self, gray: np.ndarray, side: str) -> tuple[float, float]:
        h, w = gray.shape
        top_band = int(h * self.edge_process_pct)
        bottom_band = h - top_band
        left_band = int(w * self.edge_process_pct)
        right_band = w - left_band
        if side == 'top':
            band = gray[0:top_band, :]
        elif side == 'bottom':
            band = gray[bottom_band:h, :]
        elif side == 'left':
            band = gray[:, 0:left_band]
        else:
            band = gray[:, right_band:w]
        vals = band.flatten()
        if vals.size == 0:
            return 230.0, 60.0
        bright_thr = float(np.percentile(vals, self.bright_percentile))
        dark_thr = float(np.percentile(vals, self.dark_percentile))
        return bright_thr, dark_thr

    def _scan_wdw_line(self, line: np.ndarray, from_start: bool, bright_thr: float, dark_thr: float) -> int:
        # returns index of W1 start or -1
        n = len(line)
        idx_range = range(0, n) if from_start else range(n-1, -1, -1)
        # helper to advance run with gap tolerance
        def run_len(pred, max_len=None):
            length = 0
            gaps = 0
            for i in idx_range:
                v = float(line[i])
                if pred(v):
                    length += 1
                    gaps = 0
                else:
                    gaps += 1
                    if gaps > self.close_gaps_k:
                        break
                    length += 1
                if max_len is not None and length >= max_len:
                    break
            return length
        # Implement scan manually using indices for clarity
        i = 0
        step = 1 if from_start else -1
        get = (lambda t: float(line[t]))
        # Optional W0
        w0 = 0
        t = 0 if from_start else n-1
        while 0 <= t < n and get(t) >= bright_thr and w0 < self.max_outer_white_px:
            w0 += 1
            t += step
        # Dark run D
        d = 0
        dark_start_t = t
        gaps = 0
        while 0 <= t < n:
            v = get(t)
            if v <= dark_thr:
                d += 1
                gaps = 0
            else:
                gaps += 1
                if gaps > self.close_gaps_k:
                    break
                d += 1
            t += step
        if d < self.min_dark_px_wdw:
            return -1
        # White run W1
        w1 = 0
        w1_start = t
        gaps = 0
        while 0 <= t < n:
            v = get(t)
            if v >= bright_thr:
                w1 += 1
                gaps = 0
            else:
                gaps += 1
                if gaps > self.close_gaps_k:
                    break
                w1 += 1
            t += step
        if w1 < self.min_page_margin_px:
            return -1
        # W1 start index in forward coordinates
        if from_start:
            return max(0, w1_start)
        else:
            return max(0, w1_start)

    def _scan_wdw_side(self, gray: np.ndarray, side: str) -> np.ndarray:
        h, w = gray.shape
        bright_thr, dark_thr = self._edge_band_thresholds(gray, side)
        if side in ('top', 'bottom'):
            length = w
        else:
            length = h
        boundaries = np.full(length, -1, dtype=np.int32)
        for s in range(length):
            if side == 'top':
                line = gray[:, s]
                idx = self._scan_wdw_line(line[0:h], True, bright_thr, dark_thr)
                boundaries[s] = idx
            elif side == 'bottom':
                line = gray[:, s]
                idx = self._scan_wdw_line(line[0:h], False, bright_thr, dark_thr)
                if idx >= 0:
                    boundaries[s] = idx
            elif side == 'left':
                line = gray[s, :]
                idx = self._scan_wdw_line(line[0:w], True, bright_thr, dark_thr)
                boundaries[s] = idx
            else:
                line = gray[s, :]
                idx = self._scan_wdw_line(line[0:w], False, bright_thr, dark_thr)
                if idx >= 0:
                    boundaries[s] = idx
        # Neighbor consensus filter
        if self.neighbor_window > 1 and self.neighbor_min > 0:
            win = self.neighbor_window
            half = win // 2
            filtered = np.full(length, -1, dtype=np.int32)
            for i in range(length):
                if boundaries[i] < 0:
                    continue
                start = max(0, i - half)
                end = min(length, i + half + 1)
                seg = boundaries[start:end]
                vals = seg[seg >= 0]
                if vals.size == 0:
                    continue
                count = np.sum(np.abs(vals - boundaries[i]) <= self.neighbor_delta)
                if count >= self.neighbor_min:
                    filtered[i] = boundaries[i]
            boundaries = filtered
        return boundaries

    def remove_borders_page_edge_wdw_diagnostics(self, image: np.ndarray):
        color = len(image.shape) == 3
        if color:
            gray = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
            result = image.copy()
        else:
            gray = image
            result = image.copy()
        h, w = gray.shape
        top_band = int(h * self.edge_process_pct)
        bottom_band = h - top_band
        left_band = int(w * self.edge_process_pct)
        right_band = w - left_band
        top_b = self._scan_wdw_side(gray, 'top')
        bottom_b = self._scan_wdw_side(gray, 'bottom')
        left_b = self._scan_wdw_side(gray, 'left')
        right_b = self._scan_wdw_side(gray, 'right')
        masks = {
            'top': np.zeros((h, w), dtype=bool),
            'bottom': np.zeros((h, w), dtype=bool),
            'left': np.zeros((h, w), dtype=bool),
            'right': np.zeros((h, w), dtype=bool),
        }
        # Build masks within bands
        for x in range(w):
            idx = top_b[x] if x < len(top_b) else -1
            if idx > 0:
                y0, y1 = 0, min(idx, top_band)
                masks['top'][y0:y1, x] = True
        for x in range(w):
            idx = bottom_b[x] if x < len(bottom_b) else -1
            if idx >= 0:
                y0, y1 = max(idx, bottom_band), h
                masks['bottom'][y0:y1, x] = True
        for y in range(h):
            idx = left_b[y] if y < len(left_b) else -1
            if idx > 0:
                x0, x1 = 0, min(idx, left_band)
                masks['left'][y, x0:x1] = True
        for y in range(h):
            idx = right_b[y] if y < len(right_b) else -1
            if idx >= 0:
                x0, x1 = max(idx, right_band), w
                masks['right'][y, x0:x1] = True
        # Erode masks
        if self.mask_erode_px and self.mask_erode_px > 0:
            k = int(self.mask_erode_px)
            kernel = np.ones((k, k), dtype=np.uint8)
            for side in masks:
                m = masks[side].astype(np.uint8)
                masks[side] = cv2.erode(m, kernel, iterations=1).astype(bool)
        # Paint with per-side grays
        grays = {'top': self.top_gray, 'bottom': self.bottom_gray, 'left': self.left_gray, 'right': self.right_gray}
        painted = np.zeros((h, w), dtype=bool)
        for side in ['top','bottom','left','right']:
            m = masks[side]
            if not m.any():
                continue
            if self.first_wins:
                m = np.logical_and(m, np.logical_not(painted))
            if color:
                val = np.array([grays[side], grays[side], grays[side]], dtype=result.dtype)
                result[m] = val
            else:
                result[m] = grays[side]
            painted |= m
        tw_dict = {'top': top_b, 'bottom': bottom_b, 'left': left_b, 'right': right_b}
        return result, masks, tw_dict

    def _scan_edge(self, gray: np.ndarray, side: str, white_threshold: float, sustained_run: int, max_check: int) -> np.ndarray:
        """Scan from a given side to find per-line page edge positions.

        Returns an array of length width (for top/bottom) or height (for left/right) containing
        the distance in pixels from the corresponding edge to the detected page.
        For bottom/right, the values are distances from the bottom/right edges.
        """
        h, w = gray.shape

        # Determine iteration axis
        if side in ['top', 'bottom']:
            length = w
        else:
            length = h

        boundaries = np.zeros(length, dtype=np.int32)

        # Smoothing helper: moving average on boundaries after detection
        def smooth(arr: np.ndarray, k: int) -> np.ndarray:
            k = max(1, int(k))
            if k % 2 == 0:
                k += 1
            if k <= 1:
                return arr
            pad = k // 2
            padded = np.pad(arr, (pad, pad), mode='edge')
            kernel = np.ones(k, dtype=np.float32) / float(k)
            sm = np.convolve(padded.astype(np.float32), kernel, mode='valid')
            return sm.astype(np.int32)

        # For each scan line, find dark region first, then transition to bright page
        dark_threshold = float(self.dark_threshold)
        
        for idx in range(length):
            if side == 'top':
                col = gray[:, idx]
                limit = min(max_check, h)
                boundary = 0
                in_dark = False
                dark_start = None
                bright_run = 0
                
                for y in range(limit):
                    val = float(col[y])
                    if val < dark_threshold:
                        # Dark region (scanner bed)
                        in_dark = True
                        dark_start = y if dark_start is None else dark_start
                        bright_run = 0
                    elif in_dark and val >= white_threshold:
                        # Transitioning from dark to bright (page edge)
                        bright_run += 1
                        if bright_run >= sustained_run:
                            boundary = y - sustained_run + 1
                            break
                    else:
                        # Bright from start - no border
                        if not in_dark:
                            break
                        bright_run = 0
                
                boundaries[idx] = max(0, boundary)
            elif side == 'bottom':
                col = gray[:, idx]
                limit = min(max_check, h)
                boundary_from_bottom = 0
                in_dark = False
                dark_start = None
                bright_run = 0
                
                for k in range(limit):
                    y = h - 1 - k
                    val = float(col[y])
                    if val < dark_threshold:
                        # Dark region (scanner bed)
                        in_dark = True
                        dark_start = k if dark_start is None else dark_start
                        bright_run = 0
                    elif in_dark and val >= white_threshold:
                        # Transitioning from dark to bright (page edge)
                        bright_run += 1
                        if bright_run >= sustained_run:
                            boundary_from_bottom = k - sustained_run + 1
                            break
                    else:
                        # Bright from start - no border
                        if not in_dark:
                            break
                        bright_run = 0
                
                boundaries[idx] = max(0, boundary_from_bottom)
            elif side == 'left':
                row = gray[idx, :]
                limit = min(max_check, w)
                boundary = 0
                in_dark = False
                dark_start = None
                bright_run = 0
                
                for x in range(limit):
                    val = float(row[x])
                    if val < dark_threshold:
                        # Dark region (scanner bed)
                        in_dark = True
                        dark_start = x if dark_start is None else dark_start
                        bright_run = 0
                    elif in_dark and val >= white_threshold:
                        # Transitioning from dark to bright (page edge)
                        bright_run += 1
                        if bright_run >= sustained_run:
                            boundary = x - sustained_run + 1
                            break
                    else:
                        # Bright from start - no border
                        if not in_dark:
                            break
                        bright_run = 0
                
                boundaries[idx] = max(0, boundary)
            else:  # right
                row = gray[idx, :]
                limit = min(max_check, w)
                boundary_from_right = 0
                in_dark = False
                dark_start = None
                bright_run = 0
                
                for k in range(limit):
                    x = w - 1 - k
                    val = float(row[x])
                    if val < dark_threshold:
                        # Dark region (scanner bed)
                        in_dark = True
                        dark_start = k if dark_start is None else dark_start
                        bright_run = 0
                    elif in_dark and val >= white_threshold:
                        # Transitioning from dark to bright (page edge)
                        bright_run += 1
                        if bright_run >= sustained_run:
                            boundary_from_right = k - sustained_run + 1
                            break
                    else:
                        # Bright from start - no border
                        if not in_dark:
                            break
                        bright_run = 0
                
                boundaries[idx] = max(0, boundary_from_right)

        # Smooth boundaries to reduce local outliers
        boundaries = smooth(boundaries, self.smoothing_window)
        return boundaries


if __name__ == "__main__":
    # Basic test functionality
    import sys
    
    if len(sys.argv) < 3:
        print("Usage: border_remover.py <input.pdf> <output.pdf>")
        sys.exit(1)
    
    input_path = Path(sys.argv[1])
    output_path = Path(sys.argv[2])
    
    # Setup logging
    logging.basicConfig(level=logging.INFO)
    
    # Process PDF
    remover = BorderRemover()
    stats = remover.process_entire_pdf(input_path, output_path)
    
    print(f"\nCompleted!")
    print(f"Pages processed: {stats['pages_processed']}")
    print(f"Border pixels removed: {stats['total_border_pixels']}")
    print(f"\nAverage border widths:")
    if stats['border_widths']:
        avg_top = np.mean([b['top'] for b in stats['border_widths']])
        avg_bottom = np.mean([b['bottom'] for b in stats['border_widths']])
        avg_left = np.mean([b['left'] for b in stats['border_widths']])
        avg_right = np.mean([b['right'] for b in stats['border_widths']])
        print(f"  Top: {avg_top:.1f}px")
        print(f"  Bottom: {avg_bottom:.1f}px")
        print(f"  Left: {avg_left:.1f}px")
        print(f"  Right: {avg_right:.1f}px")
