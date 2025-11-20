#!/usr/bin/env python3
"""
Helper script to perform English OCR on PDFs with rotation checking.

This script:
1. Checks and corrects PDF rotation if needed
2. Performs OCR on the PDF (using ocrmypdf if available, or manual tesseract)
3. Outputs an OCR'd PDF with searchable text

Usage:
    python scripts/ocr_pdf.py <input_pdf> [output_pdf]
    
If output_pdf is not specified, creates a new file with "_ocr" suffix.
"""

import sys
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Optional, Tuple

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from shared_tools.pdf.pdf_rotation_handler import PDFRotationHandler

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)


def check_ocrmypdf_available() -> bool:
    """Check if ocrmypdf is available."""
    try:
        result = subprocess.run(['ocrmypdf', '--version'], 
                              capture_output=True, 
                              timeout=5)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def ocr_with_ocrmypdf(input_pdf: Path, output_pdf: Path, language: str = 'eng') -> bool:
    """Perform OCR using ocrmypdf (preferred method).
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path
        language: Tesseract language code (default: 'eng')
        
    Returns:
        True if successful, False otherwise
    """
    try:
        logger.info(f"Using ocrmypdf for OCR (language: {language})...")
        
        # Try with PDF/A first (best quality)
        cmd = [
            'ocrmypdf',
            '--language', language,
            '--deskew',  # Auto-deskew pages
            '--clean',   # Clean pages before OCR
            '--optimize', '1',  # Light optimization
            str(input_pdf),
            str(output_pdf)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        
        if result.returncode == 0:
            logger.info(f"✅ OCR completed successfully: {output_pdf}")
            return True
        
        # If PDF/A conversion failed (Ghostscript error), try without PDF/A
        if 'Ghostscript' in result.stderr or 'PDF/A' in result.stderr or 'rangecheck' in result.stderr:
            logger.warning("⚠️  PDF/A conversion failed (Ghostscript error), retrying without PDF/A...")
            cmd_no_pdfa = [
                'ocrmypdf',
                '--language', language,
                '--deskew',
                '--clean',
                '--skip-text',  # Skip if text layer already exists
                '--output-type', 'pdf',  # Regular PDF, not PDF/A
                str(input_pdf),
                str(output_pdf)
            ]
            
            result = subprocess.run(cmd_no_pdfa, capture_output=True, text=True, timeout=600)
            
            if result.returncode == 0:
                logger.info(f"✅ OCR completed successfully (without PDF/A): {output_pdf}")
                return True
            else:
                logger.error(f"❌ ocrmypdf failed even without PDF/A: {result.stderr[:500]}")
                return False
        else:
            logger.error(f"❌ ocrmypdf failed: {result.stderr[:500]}")
            return False
            
    except subprocess.TimeoutExpired:
        logger.error("❌ OCR timed out after 10 minutes")
        return False
    except Exception as e:
        logger.error(f"❌ Error running ocrmypdf: {e}")
        return False


def ocr_with_tesseract_manual(input_pdf: Path, output_pdf: Path, language: str = 'eng') -> bool:
    """Perform OCR manually using tesseract (fallback method).
    
    Note: This method creates a basic searchable PDF but ocrmypdf produces better results.
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path
        language: Tesseract language code (default: 'eng')
        
    Returns:
        True if successful, False otherwise
    """
    try:
        import pytesseract
        import fitz  # PyMuPDF
        from PIL import Image
        import io
        
        logger.warning("⚠️  Manual OCR method is a fallback - install ocrmypdf for best results")
        logger.info(f"Using manual tesseract OCR (language: {language})...")
        
        # Open PDF
        doc = fitz.open(input_pdf)
        new_doc = fitz.open()
        
        total_pages = len(doc)
        logger.info(f"Processing {total_pages} pages...")
        
        for page_num in range(total_pages):
            page = doc[page_num]
            
            # Render page as image at 300 DPI for good OCR quality
            mat = fitz.Matrix(300/72, 300/72)  # 300 DPI
            pix = page.get_pixmap(matrix=mat)
            img_data = pix.tobytes("png")
            
            # Convert to PIL Image
            img = Image.open(io.BytesIO(img_data))
            
            # Get OCR data with bounding boxes for proper text positioning
            ocr_data = pytesseract.image_to_data(img, lang=language, output_type=pytesseract.Output.DICT)
            
            # Create new page with same dimensions
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            
            # Insert original image
            new_page.insert_image(page.rect, stream=img_data)
            
            # Add OCR text with proper positioning (invisible but searchable)
            # Process OCR data to add text at correct positions
            text_blocks = []
            for i, text in enumerate(ocr_data.get('text', [])):
                if text.strip():
                    conf = int(ocr_data.get('conf', [0])[i] or 0)
                    if conf > 30:  # Only add text with reasonable confidence
                        x = ocr_data.get('left', [0])[i]
                        y = ocr_data.get('top', [0])[i]
                        w = ocr_data.get('width', [0])[i]
                        h = ocr_data.get('height', [0])[i]
                        
                        # Scale coordinates from image DPI to PDF points
                        scale_x = page.rect.width / pix.width
                        scale_y = page.rect.height / pix.height
                        
                        pdf_x = x * scale_x
                        pdf_y = (pix.height - y - h) * scale_y  # Flip Y coordinate
                        
                        # Add text as invisible layer (render_mode=3 = invisible)
                        try:
                            new_page.insert_text(
                                (pdf_x, pdf_y),
                                text,
                                fontsize=max(1, h * scale_y * 0.8),  # Scale font size
                                render_mode=3  # Invisible text for searchability
                            )
                        except:
                            pass  # Skip if text insertion fails
            
            if (page_num + 1) % 10 == 0:
                logger.info(f"  Processed {page_num + 1}/{total_pages} pages...")
        
        # Save OCR'd PDF
        new_doc.save(str(output_pdf))
        new_doc.close()
        doc.close()
        
        logger.info(f"✅ Manual OCR completed: {output_pdf}")
        logger.info("   Note: For best results, install ocrmypdf: conda install ocrmypdf -c conda-forge")
        return True
        
    except ImportError as e:
        logger.error(f"❌ Missing dependency: {e}")
        logger.error("Install with: conda install pytesseract pillow pymupdf -c conda-forge")
        return False
    except Exception as e:
        logger.error(f"❌ Error during manual OCR: {e}")
        import traceback
        traceback.print_exc()
        return False


def check_mutool_available() -> bool:
    """Check if mutool is available for page splitting.
    
    Tries multiple methods:
    1. Direct 'mutool' command
    2. 'mutool' in common system locations
    """
    # Try direct command first
    try:
        result = subprocess.run(['mutool', '--version'], 
                              capture_output=True, 
                              timeout=5,
                              stderr=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL)
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    
    # Try to find mutool in common locations (system-wide install)
    common_paths = [
        '/usr/bin/mutool',
        '/usr/local/bin/mutool',
        '/opt/homebrew/bin/mutool',  # macOS Homebrew
    ]
    
    for path in common_paths:
        if Path(path).exists():
            try:
                result = subprocess.run([path, '--version'],
                                      capture_output=True,
                                      timeout=5,
                                      stderr=subprocess.DEVNULL,
                                      stdout=subprocess.DEVNULL)
                if result.returncode == 0:
                    return True
            except:
                pass
    
    return False


def split_two_up_pdf(input_pdf: Path, auto_split: bool = False) -> Tuple[Optional[Path], bool]:
    """Split a two-up PDF (two pages on one sheet) into single pages.
    
    Args:
        input_pdf: Input PDF path
        auto_split: If True, auto-split files with '_double.pdf' suffix or detect two-up
        
    Returns:
        Tuple of (Path to split PDF if split was performed, None otherwise, mutool_available)
        The second value indicates if mutool is available (True) or not (False)
    """
    mutool_available = check_mutool_available()
    
    if not mutool_available:
        name = input_pdf.name.lower()
        if name.endswith('_double.pdf') or auto_split:
            logger.warning("⚠️  mutool not found - cannot split pages")
            logger.info("   Install mutool with one of these options:")
            logger.info("   - System-wide: sudo apt install mupdf-tools")
            logger.info("   - Conda: conda install mupdf-tools -c conda-forge")
            logger.warning("   Continuing without splitting - OCR may be less accurate on two-up pages")
        return None, False
    
    name = input_pdf.name.lower()
    
    # Auto-split if filename ends with _double.pdf
    if name.endswith('_double.pdf'):
        logger.info("📄 Detected _double.pdf suffix - auto-splitting...")
        result = _split_with_mutool(input_pdf)
        return result, True
    
    if not auto_split:
        return None, True
    
    # Detect two-up layout
    try:
        import pdfplumber
        with pdfplumber.open(str(input_pdf)) as pdf:
            if len(pdf.pages) == 0:
                return None, True
            first = pdf.pages[0]
            width, height = first.width, first.height
            
            # Check aspect ratio (wide pages might be two-up)
            if width and height and width / max(1.0, height) > 1.3:
                logger.info(f"📄 Detected wide page (aspect ratio: {width/height:.2f})")
                logger.info("   This might be two pages on one sheet")
                choice = input("   Split into single pages? [y/N]: ").strip().lower()
                if choice == 'y':
                    result = _split_with_mutool(input_pdf, width=width, height=height)
                    return result, True
    except ImportError:
        logger.debug("pdfplumber not available for two-up detection")
    except Exception as e:
        logger.debug(f"Two-up detection failed: {e}")
    
    return None, True


def _split_with_mutool(pdf_path: Path, width: Optional[float] = None, height: Optional[float] = None) -> Optional[Path]:
    """Split a two-up PDF using mutool poster.
    
    Args:
        pdf_path: Input PDF path
        width: Page width (optional, will detect if not provided)
        height: Page height (optional, will detect if not provided)
        
    Returns:
        Path to split PDF or None if failed
    """
    try:
        if width is None or height is None:
            try:
                import pdfplumber
                with pdfplumber.open(str(pdf_path)) as pdf:
                    if len(pdf.pages) > 0:
                        width, height = pdf.pages[0].width, pdf.pages[0].height
            except Exception:
                width = height = 0
        
        # Determine split direction: landscape (2x1) or portrait (1x2)
        x, y = (2, 1) if (width and height and width > height) else (1, 2)
        
        # Create split in temp directory
        temp_dir = Path(tempfile.gettempdir()) / 'pdf_ocr_splits'
        temp_dir.mkdir(parents=True, exist_ok=True)
        out_path = temp_dir / f"{pdf_path.stem}_split.pdf"
        
        # Try to find mutool (might be system-wide install)
        mutool_cmd = 'mutool'
        if not check_mutool_available():
            # Try common system locations
            for path in ['/usr/bin/mutool', '/usr/local/bin/mutool', '/opt/homebrew/bin/mutool']:
                if Path(path).exists():
                    mutool_cmd = path
                    break
            else:
                # mutool not found anywhere
                raise FileNotFoundError("mutool not found in PATH or common locations")
        
        cmd = [
            mutool_cmd, 'poster', '-x', str(x), '-y', str(y),
            str(pdf_path), str(out_path)
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        
        if result.returncode == 0 and out_path.exists():
            logger.info(f"✅ Split PDF created: {out_path.name}")
            return out_path
        else:
            logger.error(f"❌ mutool split failed: {result.stderr.strip()}")
            return None
            
    except FileNotFoundError:
        logger.warning("⚠️  mutool not found; cannot split pages")
        return None
    except Exception as e:
        logger.error(f"❌ Split failed: {e}")
        return None


def ocr_pdf(input_pdf: Path, output_pdf: Optional[Path] = None, check_rotation: bool = True, auto_split: bool = True) -> bool:
    """Perform OCR on a PDF with optional rotation checking and page splitting.
    
    Args:
        input_pdf: Input PDF path
        output_pdf: Output PDF path (if None, creates input_pdf with "_ocr" suffix)
        check_rotation: Whether to check and correct rotation first
        auto_split: Whether to auto-split two-up pages (two pages on one sheet)
        
    Returns:
        True if successful, False otherwise
    """
    if not input_pdf.exists():
        logger.error(f"❌ Input PDF not found: {input_pdf}")
        return False
    
    # Determine output path
    if output_pdf is None:
        output_pdf = input_pdf.parent / f"{input_pdf.stem}_ocr{input_pdf.suffix}"
    
    logger.info(f"Input PDF: {input_pdf}")
    logger.info(f"Output PDF: {output_pdf}")
    
    # Step 1: Split two-up pages if needed (BEFORE rotation and OCR)
    pdf_to_process = input_pdf
    temp_split_pdf = None
    
    if auto_split:
        logger.info("\n📄 Checking for two-up pages (two pages on one sheet)...")
        split_result, mutool_available = split_two_up_pdf(input_pdf, auto_split=True)
        if split_result:
            pdf_to_process = split_result
            temp_split_pdf = split_result
            logger.info(f"✅ Using split version: {pdf_to_process.name}")
        elif mutool_available:
            logger.info("✅ No splitting needed")
        # If mutool not available, warning already shown in split_two_up_pdf()
    
    # Step 2: Check and correct rotation if needed
    pdf_to_ocr = pdf_to_process
    temp_rotated_pdf = None
    rotated_pdf_saved = None  # Path to saved rotated PDF (for user inspection)
    
    if check_rotation:
        logger.info("\n📐 Checking PDF rotation...")
        rotation_handler = PDFRotationHandler()
        rotation = rotation_handler.detect_pdf_rotation(pdf_to_process, max_pages=2)
        
        if rotation:
            logger.info(f"⚠️  Detected rotation: {rotation}")
            logger.info("Correcting rotation...")
            
            # Save rotated PDF next to output for user inspection
            rotated_pdf_saved = output_pdf.parent / f"{output_pdf.stem}_rotated{output_pdf.suffix}"
            corrected = rotation_handler.create_corrected_pdf(pdf_to_process, rotation, rotated_pdf_saved)
            
            if corrected:
                pdf_to_ocr = corrected
                logger.info(f"✅ Rotation corrected, using: {pdf_to_ocr}")
                logger.info(f"   Rotated PDF saved for inspection: {rotated_pdf_saved.name}")
            else:
                logger.warning("⚠️  Failed to correct rotation, using original PDF")
        else:
            logger.info("✅ PDF orientation is correct")
    
    # Step 2: Perform OCR
    logger.info("\n🔍 Performing OCR...")
    
    # Try ocrmypdf first (preferred)
    success = False
    if check_ocrmypdf_available():
        success = ocr_with_ocrmypdf(pdf_to_ocr, output_pdf, language='eng')
        
        # If ocrmypdf failed, fall back to manual method
        if not success:
            logger.warning("⚠️  ocrmypdf failed, falling back to manual tesseract method...")
            success = ocr_with_tesseract_manual(pdf_to_ocr, output_pdf, language='eng')
    else:
        logger.info("ocrmypdf not available, using manual tesseract method...")
        logger.info("(Install ocrmypdf for better results: conda install ocrmypdf -c conda-forge)")
        success = ocr_with_tesseract_manual(pdf_to_ocr, output_pdf, language='eng')
    
    # Cleanup temp files if created (but keep saved rotated PDF for inspection)
    for temp_file in [temp_split_pdf]:
        if temp_file and temp_file.exists():
            try:
                temp_file.unlink()
                # Try to remove parent directory if empty
                try:
                    temp_file.parent.rmdir()
                except:
                    pass  # Directory not empty or other error
                logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                logger.warning(f"Could not clean up temp file {temp_file}: {e}")
    
    # Note: rotated_pdf_saved is kept for user inspection (not cleaned up)
    
    if success:
        logger.info(f"\n✅ OCR completed successfully!")
        logger.info(f"   Output: {output_pdf}")
        return True
    else:
        logger.error(f"\n❌ OCR failed")
        return False


def main():
    """Main function."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    input_pdf = Path(sys.argv[1])
    output_pdf = Path(sys.argv[2]) if len(sys.argv) > 2 else None
    
    # Check for flags
    auto_split = True  # Default: auto-split two-up pages
    check_rotation = True  # Default: check rotation
    
    if len(sys.argv) > 2:
        # Check if output_pdf is actually a flag
        if output_pdf and output_pdf.name.startswith('-'):
            output_pdf = None
            # Parse flags if needed
    
    success = ocr_pdf(input_pdf, output_pdf, check_rotation=check_rotation, auto_split=auto_split)
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()

