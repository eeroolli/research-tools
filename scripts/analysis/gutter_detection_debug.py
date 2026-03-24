#!/usr/bin/env python3
"""
Manual diagnostic script for gutter detection on a specific PDF.

This was originally `tests/test_gutter_detection.py` but has been moved out of
the automated test suite. Use it as:

    python scripts/analysis/gutter_detection_debug.py "<path-to-pdf>"
"""

import sys
from pathlib import Path

import fitz
import numpy as np
import cv2

from shared_tools.pdf.border_remover import BorderRemover


def normalize_path_for_wsl(path_str: str) -> str:
    """Normalize a path string to WSL format.

    Handles both WSL paths (/mnt/c/...) and Windows paths (C:\\...):
    - Windows paths like "I:\\path\\to\\file" -> "/mnt/i/path/to/file"
    - WSL paths already in correct format are returned as-is.
    """
    if path_str is None:
        return path_str
    path_str = path_str.strip().strip('"\'')
    path_str = path_str.replace('"', "").replace("'", "")

    # If already a WSL path (starts with /), normalize duplicate slashes and return
    if path_str.startswith("/"):
        while "//" in path_str:
            path_str = path_str.replace("//", "/")
        return path_str

    # If Windows path (contains :), convert to WSL
    if ":" in path_str:
        path_str = path_str.replace("\\", "/")

        # Extract drive letter (first character before :)
        drive_letter = path_str[0].lower()
        remainder = path_str.split(":", 1)[1].lstrip("/")
        wsl_path = f"/mnt/{drive_letter}/{remainder}"
        while "//" in wsl_path:
            wsl_path = wsl_path.replace("//", "/")
        return wsl_path

    return path_str


def run_gutter_detection(pdf_path_str: str) -> None:
    """Test gutter detection on a specific PDF."""
    normalized_path = normalize_path_for_wsl(pdf_path_str)
    pdf_path = Path(normalized_path)

    if not pdf_path.exists():
        print(f"❌ PDF not found: {pdf_path}")
        return

    print(f"\n📄 Testing gutter detection on: {pdf_path.name}")
    print("=" * 70)

    # Initialize border remover
    border_remover = BorderRemover({"max_border_width": 300})

    try:
        doc = fitz.open(str(pdf_path))
        page = doc[0]
        page_rect = page.rect
        page_width = page_rect.width

        # Render page as image
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)

        # Convert to grayscale
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        img_height, img_width = gray.shape

        # Detect borders
        borders = border_remover.detect_borders(img)
        print(f"   Borders detected: {borders}")

        # Calculate content area
        border_left_px = borders.get("left", 0)
        border_right_px = borders.get("right", 0)
        content_left_px = border_left_px
        content_right_px = img_width - border_right_px
        content_width_px = content_right_px - content_left_px

        # Extract content region (middle 80% vertically)
        vertical_margin = int(img_height * 0.1)
        content_region = gray[vertical_margin : img_height - vertical_margin, content_left_px:content_right_px]

        # Calculate projections
        spine_projection = np.mean(content_region, axis=0)  # Average brightness
        inverted = 255 - content_region
        content_projection = np.sum(inverted, axis=0)  # Content density

        # Smooth
        kernel_size = max(5, int(content_width_px * 0.02))
        if kernel_size % 2 == 0:
            kernel_size += 1
        if kernel_size > 1:
            spine_projection = cv2.GaussianBlur(spine_projection.reshape(1, -1), (1, kernel_size), 0).flatten()
            content_projection = cv2.GaussianBlur(content_projection.reshape(1, -1), (1, kernel_size), 0).flatten()

        # Find minima
        search_start = int(len(spine_projection) * 0.2)
        search_end = int(len(spine_projection) * 0.8)
        search_region_spine = spine_projection[search_start:search_end]
        search_region_content = content_projection[search_start:search_end]

        window_size = max(5, int(len(search_region_spine) * 0.05))

        # Spine method
        min_spine_val = float("inf")
        min_spine_idx = search_start
        for i in range(len(search_region_spine) - window_size):
            window = search_region_spine[i : i + window_size]
            window_avg = np.mean(window)
            if window_avg < min_spine_val:
                min_spine_val = window_avg
                min_spine_idx = i + search_start

        # Content method
        min_content_val = float("inf")
        min_content_idx = search_start
        for i in range(len(search_region_content) - window_size):
            window = search_region_content[i : i + window_size]
            window_avg = np.mean(window)
            if window_avg < min_content_val:
                min_content_val = window_avg
                min_content_idx = i + search_start

        # Analyze signals
        avg_brightness = np.mean(search_region_spine)
        spine_darkness = avg_brightness - min_spine_val
        spine_signal = spine_darkness / (avg_brightness + 1e-6)

        avg_content = np.mean(search_region_content)
        content_reduction = avg_content - min_content_val
        content_signal = content_reduction / (avg_content + 1e-6)

        print("\n   Spine detection:")
        print(f"     Darkest area at column: {min_spine_idx}")
        print(f"     Average brightness: {avg_brightness:.1f}")
        print(f"     Darkest brightness: {min_spine_val:.1f}")
        print(f"     Darkness difference: {spine_darkness:.1f}")
        print(f"     Signal strength: {spine_signal:.3f} ({spine_signal*100:.1f}%)")

        print("\n   Content detection:")
        print(f"     Minimum content at column: {min_content_idx}")
        print(f"     Average content: {avg_content:.1f}")
        print(f"     Minimum content: {min_content_val:.1f}")
        print(f"     Content reduction: {content_reduction:.1f}")
        print(f"     Signal strength: {content_signal:.3f} ({content_signal*100:.1f}%)")

        # Convert to PDF coordinates
        spine_px = content_left_px + min_spine_idx
        spine_pdf = (spine_px / img_width) * page_width
        spine_pct = (spine_pdf / page_width) * 100

        content_px = content_left_px + min_content_idx
        content_pdf = (content_px / img_width) * page_width
        content_pct = (content_pdf / page_width) * 100

        print("\n   Results:")
        print(f"     Spine method: {spine_pdf:.1f} points ({spine_pct:.1f}%)")
        print(f"     Content method: {content_pdf:.1f} points ({content_pct:.1f}%)")

        if spine_signal > 0.15:
            print("     → Using SPINE method (physical book)")
            final_pdf = spine_pdf
            final_pct = spine_pct
        else:
            print("     → Using CONTENT method (printed article)")
            final_pdf = content_pdf
            final_pct = content_pct

        print("\n   Final gutter: {:.1f} points ({:.1f}%)".format(final_pdf, final_pct))
        print("\n📊 Summary:")
        print(f"   Page width: {page_width:.1f} points")
        print(f"   Left page would be: {final_pdf:.1f} points ({final_pct:.1f}%)")
        print(f"   Right page would be: {page_width - final_pdf:.1f} points ({100 - final_pct:.1f}%)")

        doc.close()

    except Exception as e:  # pragma: no cover - diagnostic script
        print(f"⚠️  Error in visualization: {e}")
        import traceback

        traceback.print_exc()


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python gutter_detection_debug.py \"<path-to-pdf>\"")
        sys.exit(1)

    run_gutter_detection(sys.argv[1])


if __name__ == "__main__":
    main()

