#!/usr/bin/env python3
"""
PDF processing module for daemon operations.

Provides PDF preprocessing, splitting, border removal, rotation handling,
and page manipulation utilities.
"""

import logging
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple, List

from shared_tools.daemon.exceptions import FileOperationError
from shared_tools.daemon.constants import DaemonConstants


class PDFProcessor:
    """PDF processing utilities for daemon operations."""
    
    def __init__(self, border_remover=None, logger: Optional[logging.Logger] = None):
        """Initialize PDF processor.
        
        Args:
            border_remover: Optional BorderRemover instance for border removal
            logger: Optional logger instance
        """
        self.border_remover = border_remover
        self.logger = logger or logging.getLogger(__name__)
    
    def create_pdf_from_page_offset(self, pdf_path: Path, page_offset: int) -> Optional[Path]:
        """Create a temporary PDF starting from a specific page offset.
        
        Args:
            pdf_path: Path to original PDF file
            page_offset: 0-indexed page offset (0 = page 1, 1 = page 2, etc.)
            
        Returns:
            Path to temporary PDF starting from specified page, or None if failed
            
        Raises:
            FileOperationError: If PDF processing fails
        """
        if page_offset < 1:
            # No offset needed, return None (use original)
            return None
        
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise FileOperationError("PyMuPDF (fitz) not available - cannot create PDF from page offset")
        
        doc = None
        new_doc = None
        try:
            # Open the PDF
            doc = fitz.open(pdf_path)
            
            # Check if PDF has enough pages
            if len(doc) <= page_offset:
                self.logger.warning(f"PDF has only {len(doc)} page(s) - cannot start from page {page_offset + 1}")
                doc.close()
                return None
            
            # Create new PDF starting from page_offset
            new_doc = fitz.open()
            
            # Copy pages starting from page_offset
            for page_num in range(page_offset, len(doc)):
                page = doc[page_num]
                new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.show_pdf_page(new_page.rect, doc, page_num)
            
            # Save to a temporary file
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_splits'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_from_page{page_offset + 1}.pdf"
            
            new_doc.save(str(out_path))
            new_doc.close()
            doc.close()
            
            self.logger.info(f"Created PDF starting from page {page_offset + 1}: {out_path.name}")
            return out_path
            
        except Exception as e:
            # Ensure both documents are closed to prevent resource leaks
            if new_doc is not None:
                try:
                    new_doc.close()
                except Exception:
                    pass
            if doc is not None:
                try:
                    doc.close()
                except Exception:
                    pass
            raise FileOperationError(f"Failed to create PDF from page offset {page_offset + 1}: {e}") from e
    
    def check_and_remove_dark_borders(self, pdf_path: Path, prompt_user: bool = True) -> Optional[Path]:
        """Check for dark borders and optionally remove them.
        
        Checks first 4 pages for borders. If borders detected and prompt_user is True,
        prompts user to confirm removal. Returns path to cleaned PDF or None if no action taken.
        
        Args:
            pdf_path: Path to PDF file
            prompt_user: If True, prompt user before removing borders
            
        Returns:
            Path to cleaned PDF if borders removed, None if skipped or no borders detected
            
        Raises:
            FileOperationError: If border removal fails
        """
        if not self.border_remover:
            self.logger.warning("BorderRemover not available - skipping border removal")
            return None
        
        try:
            import fitz  # PyMuPDF
        except ImportError:
            raise FileOperationError("PyMuPDF (fitz) not available - cannot check borders")
        
        self.logger.info("Checking for dark borders (pages 1-4)...")
        
        # Check first 4 pages for borders
        borders_detected = False
        pages_with_borders = []
        
        try:
            doc = fitz.open(str(pdf_path))
            pages_to_check = min(4, len(doc))
            
            for page_num in range(pages_to_check):
                try:
                    processed_image, borders = self.border_remover.process_pdf_page(
                        pdf_path, page_num, zoom=2.0
                    )
                    
                    # Check if any borders were detected
                    if any(borders.values()):
                        borders_detected = True
                        pages_with_borders.append(page_num + 1)
                except Exception as e:
                    self.logger.debug(f"Error checking page {page_num + 1}: {e}")
                    continue
            
            doc.close()
            
            if not borders_detected:
                self.logger.info("No dark borders detected - skipping removal")
                return None
            
            # Report to user if prompting
            if prompt_user:
                # Check for high border variation
                border_values = {'left': [], 'right': [], 'top': [], 'bottom': []}
                for page_num in range(pages_to_check):
                    try:
                        _, borders = self.border_remover.process_pdf_page(pdf_path, page_num, zoom=2.0)
                        for side in border_values:
                            border_values[side].append(borders.get(side, 0))
                    except:
                        continue
                
                # Check variation
                warnings = []
                import statistics
                for side, values in border_values.items():
                    if len(values) > 1 and any(v > 0 for v in values):
                        cv = statistics.stdev(values) / (statistics.mean(values) + 1e-6)
                        if cv > 0.3:  # > 30% variation
                            warnings.append(f"⚠️  {side.capitalize()} border varies significantly across pages")
                
                # Show warnings if any
                if warnings:
                    print("\n" + "="*60, flush=True)
                    print("⚠️  BORDER DETECTION WARNINGS", flush=True)
                    print("="*60, flush=True)
                    for warning in warnings:
                        print(warning, flush=True)
                    print(flush=True)
                    print("Large images or complex layouts can confuse border detection.", flush=True)
                    print("Options:", flush=True)
                    print("  [1] Proceed with border removal (may remove important content)", flush=True)
                    print("  [2] Skip border removal (keep original borders)", flush=True)
                    print(flush=True)
                    
                    try:
                        choice = input("Your choice [1/2]: ").strip()
                        if choice == '2':
                            print("Skipping border removal", flush=True)
                            return None
                        # else proceed
                    except (KeyboardInterrupt, EOFError):
                        print("\n❌ Cancelled", flush=True)
                        return None
                
                # Original prompt (if no warnings or user chose to proceed)
                pages_str = ", ".join(str(p) for p in pages_with_borders)
                print(f"\n📊 Summary: Dark borders found on {len(pages_with_borders)} of {pages_to_check} pages checked", flush=True)
                choice = input("Remove dark borders from the whole PDF? [Y/n]: ").strip().lower()
                if choice == 'n':
                    print("Skipping border removal", flush=True)
                    return None
            
            # Process entire PDF with border removal
            self.logger.info("Processing all pages for border removal...")
            
            # Create output path
            temp_dir = Path(tempfile.gettempdir()) / 'pdf_borders_removed'
            temp_dir.mkdir(parents=True, exist_ok=True)
            out_path = temp_dir / f"{pdf_path.stem}_no_borders.pdf"
            
            stats = self.border_remover.process_entire_pdf(pdf_path, out_path, zoom=2.0)
            
            if stats is None:
                # Border removal failed validation (page count mismatch)
                self.logger.error("Border removal validation failed - page count mismatch")
                return None
            
            if stats['pages_processed'] > 0:
                self.logger.info(f"Borders removed from {stats['pages_processed']} pages")
                return out_path
            else:
                return None
                
        except Exception as e:
            raise FileOperationError(f"Failed to check/remove borders: {e}") from e
    
    @contextmanager
    def temporary_pdf_from_offset(self, pdf_path: Path, page_offset: int):
        """Context manager for temporary PDF files created from page offset.
        
        Args:
            pdf_path: Path to original PDF file
            page_offset: 0-indexed page offset
            
        Yields:
            Path to temporary PDF starting from specified page, or None if offset < 1
            
        Example:
            with pdf_processor.temporary_pdf_from_offset(pdf_path, 2) as temp_pdf:
                if temp_pdf:
                    process_pdf(temp_pdf)
        """
        temp_path = None
        try:
            temp_path = self.create_pdf_from_page_offset(pdf_path, page_offset)
            yield temp_path
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                    self.logger.debug(f"Cleaned up temporary PDF: {temp_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up temporary PDF {temp_path}: {e}")
    
    @contextmanager
    def temporary_pdf_without_borders(self, pdf_path: Path, prompt_user: bool = True):
        """Context manager for temporary PDF files with borders removed.
        
        Args:
            pdf_path: Path to original PDF file
            prompt_user: If True, prompt user before removing borders
            
        Yields:
            Path to PDF with borders removed, or None if no borders or skipped
            
        Example:
            with pdf_processor.temporary_pdf_without_borders(pdf_path) as cleaned_pdf:
                if cleaned_pdf:
                    process_pdf(cleaned_pdf)
        """
        temp_path = None
        try:
            temp_path = self.check_and_remove_dark_borders(pdf_path, prompt_user=prompt_user)
            yield temp_path
        finally:
            if temp_path and temp_path.exists():
                try:
                    temp_path.unlink()
                    self.logger.debug(f"Cleaned up temporary PDF: {temp_path}")
                except Exception as e:
                    self.logger.warning(f"Failed to clean up temporary PDF {temp_path}: {e}")

