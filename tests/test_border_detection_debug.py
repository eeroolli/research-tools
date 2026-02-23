#!/usr/bin/env python3
"""
Test script to debug border detection on example PDF.

Analyzes EN_20260102_0001_double.pdf to understand why borders aren't detected.
"""

import sys
import logging
from pathlib import Path

# Check for required dependencies first
try:
    import cv2
except ImportError:
    print("ERROR: cv2 (OpenCV) not found!")
    print("\nPlease activate the conda environment first:")
    print("  conda activate research-tools")
    print("\nOr if using WSL:")
    print("  source ~/miniconda3/etc/profile.d/conda.sh")
    print("  conda activate research-tools")
    sys.exit(1)

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF (fitz) not found!")
    print("\nPlease activate the conda environment first:")
    print("  conda activate research-tools")
    sys.exit(1)

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Try to import BorderRemover - will fail if cv2 not available
try:
    from shared_tools.pdf.border_remover import BorderRemover
except (ImportError, ModuleNotFoundError) as e:
    error_msg = str(e).lower()
    if 'cv2' in error_msg or 'opencv' in error_msg:
        print("=" * 60)
        print("ERROR: cv2 (OpenCV) module not found!")
        print("=" * 60)
        print("\nThis script requires the 'research-tools' conda environment.")
        print("\nTo fix this, activate the conda environment first:")
        print("\n  For Windows PowerShell:")
        print("    conda activate research-tools")
        print("\n  For WSL/Linux:")
        print("    source ~/miniconda3/etc/profile.d/conda.sh")
        print("    conda activate research-tools")
        print("\n  Or if conda is in a different location:")
        print("    source ~/anaconda3/etc/profile.d/conda.sh  # or anaconda3")
        print("    conda activate research-tools")
        print("\nThen run this script again.")
    else:
        print(f"ERROR: Failed to import BorderRemover: {e}")
        import traceback
        traceback.print_exc()
    sys.exit(1)

import numpy as np
from PIL import Image
import io

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)
logger = logging.getLogger(__name__)


def analyze_pdf(pdf_path: Path, page_num: int = 0):
    """Analyze border detection on a specific PDF page.
    
    Args:
        pdf_path: Path to PDF file
        page_num: Page number to analyze (0-indexed)
    """
    logger.info(f"=" * 60)
    logger.info(f"Analyzing: {pdf_path.name}")
    logger.info(f"Page: {page_num + 1}")
    logger.info(f"=" * 60)
    
    # Initialize border remover with debug
    border_remover = BorderRemover({'max_border_width': 600})
    border_remover.logger = logger
    
    # Open PDF and extract page
    doc = fitz.open(str(pdf_path))
    try:
        if page_num >= len(doc):
            logger.error(f"Page {page_num} not found (PDF has {len(doc)} pages)")
            return
        
        page = doc[page_num]
        logger.info(f"Page dimensions: {page.rect.width:.1f} x {page.rect.height:.1f} points")
        
        # Render at 2x zoom for analysis
        zoom = 2.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        
        # Convert to numpy array
        img = Image.open(io.BytesIO(img_data))
        image_array = np.array(img)
        
        logger.info(f"\nRendered image: {image_array.shape}")
        logger.info(f"Image pixel range: min={image_array.min()}, max={image_array.max()}")
        
        # Analyze edge regions directly
        logger.info("\n" + "=" * 60)
        logger.info("DIRECT EDGE ANALYSIS")
        logger.info("=" * 60)
        
        h, w = image_array.shape[:2]
        # Convert to grayscale if needed (same as BorderRemover does)
        if len(image_array.shape) == 3:
            gray = cv2.cvtColor(image_array, cv2.COLOR_RGB2GRAY)
        else:
            gray = image_array
        
        # Analyze top edge (first 100 pixels)
        top_region = gray[:100, :] if h > 100 else gray
        logger.info(f"\nTop edge (first 100px):")
        logger.info(f"  Shape: {top_region.shape}")
        logger.info(f"  Pixel range: min={top_region.min()}, max={top_region.max()}, mean={top_region.mean():.1f}")
        logger.info(f"  Pixels <= 60 (dark): {np.sum(top_region <= 60)} / {top_region.size} "
                   f"({100 * np.sum(top_region <= 60) / top_region.size:.1f}%)")
        logger.info(f"  Pixels <= 40 (very dark): {np.sum(top_region <= 40)} / {top_region.size} "
                   f"({100 * np.sum(top_region <= 40) / top_region.size:.1f}%)")
        
        # Analyze bottom edge
        bottom_region = gray[-100:, :] if h > 100 else gray
        logger.info(f"\nBottom edge (last 100px):")
        logger.info(f"  Shape: {bottom_region.shape}")
        logger.info(f"  Pixel range: min={bottom_region.min()}, max={bottom_region.max()}, mean={bottom_region.mean():.1f}")
        logger.info(f"  Pixels <= 60 (dark): {np.sum(bottom_region <= 60)} / {bottom_region.size} "
                   f"({100 * np.sum(bottom_region <= 60) / bottom_region.size:.1f}%)")
        logger.info(f"  Pixels <= 40 (very dark): {np.sum(bottom_region <= 40)} / {bottom_region.size} "
                   f"({100 * np.sum(bottom_region <= 40) / bottom_region.size:.1f}%)")
        
        # Analyze left edge
        left_region = gray[:, :100] if w > 100 else gray
        logger.info(f"\nLeft edge (first 100px):")
        logger.info(f"  Shape: {left_region.shape}")
        logger.info(f"  Pixel range: min={left_region.min()}, max={left_region.max()}, mean={left_region.mean():.1f}")
        logger.info(f"  Pixels <= 60 (dark): {np.sum(left_region <= 60)} / {left_region.size} "
                   f"({100 * np.sum(left_region <= 60) / left_region.size:.1f}%)")
        logger.info(f"  Pixels <= 40 (very dark): {np.sum(left_region <= 40)} / {left_region.size} "
                   f"({100 * np.sum(left_region <= 40) / left_region.size:.1f}%)")
        
        # Analyze right edge
        right_region = gray[:, -100:] if w > 100 else gray
        logger.info(f"\nRight edge (last 100px):")
        logger.info(f"  Shape: {right_region.shape}")
        logger.info(f"  Pixel range: min={right_region.min()}, max={right_region.max()}, mean={right_region.mean():.1f}")
        logger.info(f"  Pixels <= 60 (dark): {np.sum(right_region <= 60)} / {right_region.size} "
                   f"({100 * np.sum(right_region <= 60) / right_region.size:.1f}%)")
        logger.info(f"  Pixels <= 40 (very dark): {np.sum(right_region <= 40)} / {right_region.size} "
                   f"({100 * np.sum(right_region <= 40) / right_region.size:.1f}%)")
        
        # Now run the actual detection with debug
        logger.info("\n" + "=" * 60)
        logger.info("BORDER DETECTION (with debug)")
        logger.info("=" * 60)
        
        borders = border_remover.detect_borders(image_array, debug=True)
        
        logger.info("\n" + "=" * 60)
        logger.info("RESULTS")
        logger.info("=" * 60)
        logger.info(f"Detected borders: {borders}")
        
        if all(v == 0 for v in borders.values()):
            logger.warning("\n⚠️  NO BORDERS DETECTED!")
            logger.info("\nThis suggests:")
            logger.info("  1. Candidate detection may have failed (no borders found)")
            logger.info("  2. Or verification failed (borders found but rejected)")
            logger.info("  Check the debug output above to see which step failed.")
        else:
            logger.info(f"\n✅ Borders detected: {sum(1 for v in borders.values() if v > 0)} sides")
        
    finally:
        doc.close()


def main():
    """Main entry point."""
    import configparser
    
    # Look for the example PDF
    # Try common locations
    possible_paths = [
        Path("EN_20260102_0001_double.pdf"),
        Path("../EN_20260102_0001_double.pdf"),
        Path("../../EN_20260102_0001_double.pdf"),
        Path.home() / "EN_20260102_0001_double.pdf",
    ]
    
    # Also check scanner directory from config
    try:
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        scanner_path = config.get('PATHS', 'scanner_papers_dir', 
                                  fallback='/mnt/i/FraScanner/papers')
        scanner_dir = Path(scanner_path)
        if scanner_dir.exists():
            possible_paths.append(scanner_dir / "EN_20260102_0001_double.pdf")
            possible_paths.append(scanner_dir / "done" / "EN_20260102_0001_double.pdf")
    except Exception:
        pass
    
    pdf_path = None
    for path in possible_paths:
        if path.exists():
            pdf_path = path
            break
    
    if pdf_path is None:
        logger.error("Could not find EN_20260102_0001_double.pdf")
        logger.info("Please provide the path to the PDF as an argument:")
        logger.info("  python test_border_detection_debug.py <path_to_pdf>")
        if len(sys.argv) > 1:
            pdf_path = Path(sys.argv[1])
            if not pdf_path.exists():
                logger.error(f"File not found: {pdf_path}")
                return
        else:
            return
    
    # Analyze first page
    analyze_pdf(pdf_path, page_num=0)


if __name__ == "__main__":
    main()

