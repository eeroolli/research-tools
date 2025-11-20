#!/usr/bin/env python3
"""
Interactive PDF fixer that reuses PaperProcessorDaemon helpers.

Features:
- Optional two-up splitting (mutool poster)
- Optional trimming of leading and trailing pages
- Optional dark border removal

The script copies the input PDF to a temporary workspace and guides the user
through each step. When finished, the result can overwrite the original file
or be saved to a new location.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

try:
    import fitz  # PyMuPDF
except ImportError:
    fitz = None

from paper_processor_daemon import PaperProcessorDaemon


class LightweightPaperTools(PaperProcessorDaemon):
    """Minimal toolbox that exposes PDF helpers without heavy services."""

    def __init__(self, working_dir: Path, debug: bool = False):
        self.watch_dir = Path(working_dir)
        self.pid_file = self.watch_dir / ".pdf_self_fixer.pid"
        self.debug = debug

        # Reuse existing helper implementations without starting services
        PaperProcessorDaemon.load_config(self)
        PaperProcessorDaemon.setup_logging(self)
        from shared_tools.pdf.border_remover import BorderRemover

        self.border_remover = BorderRemover({"max_border_width": self.border_max_width})

        # Ensure logger present even if setup_logging was overridden elsewhere
        if not hasattr(self, "logger"):
            import logging

            self.logger = logging.getLogger(__name__)

    # Override heavy initializers with no-ops
    def _initialize_services(self):
        self.logger.debug("Skipping service initialization for PDF fixer.")


@dataclass
class FixerState:
    source_pdf: Path
    working_pdf: Path
    modified_paths: List[Path]


class PDFInteractiveFixer:
    """Interactive workflow for repairing a single PDF."""

    def __init__(self, pdf_path: Path, debug: bool = False):
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError("Input file must have .pdf extension")

        self.source_pdf = pdf_path
        self.toolbox = LightweightPaperTools(pdf_path.parent, debug=debug)
        self.temp_dir = Path(tempfile.mkdtemp(prefix="pdf_fix_"))
        self.state = self._create_initial_state()
        self.toolbox.logger.info(f"🛠️  Working copy created at {self.state.working_pdf}")

    def _create_initial_state(self) -> FixerState:
        working_copy = self.temp_dir / self.source_pdf.name
        shutil.copy2(self.source_pdf, working_copy)
        return FixerState(
            source_pdf=self.source_pdf,
            working_pdf=working_copy,
            modified_paths=[working_copy],
        )

    # ---------------------------
    # Interactive workflow steps
    # ---------------------------

    def run(self):
        try:
            self._maybe_split_two_up()
            self._maybe_trim_leading()
            self._maybe_trim_trailing()
            self._maybe_remove_borders()
            self._finalize()
        finally:
            self._cleanup()

    def _update_working_pdf(self, new_path: Optional[Path]):
        if new_path and new_path != self.state.working_pdf:
            self.state.modified_paths.append(new_path)
            self.state.working_pdf = new_path
            self.toolbox.logger.info(f"➡️  Using updated PDF: {new_path.name}")

    def _maybe_split_two_up(self):
        self.toolbox.logger.info("\n=== Step 1/4: Two-up splitting (optional) ===")
        split_path = self.toolbox._preprocess_split_if_needed(self.state.working_pdf)
        if split_path:
            print(f"✅ Split complete: {split_path.name}")
            self._update_working_pdf(split_path)
        else:
            print("ℹ️  No splitting performed.")

    def _maybe_trim_leading(self):
        self.toolbox.logger.info("\n=== Step 2/4: Trim leading pages (optional) ===")
        trimmed = self._prompt_trim_leading_pages()
        if trimmed:
            print(f"✅ Leading pages trimmed: {trimmed.name}")
            self._update_working_pdf(trimmed)
        else:
            print("ℹ️  Keeping leading pages unchanged.")

    def _maybe_trim_trailing(self):
        self.toolbox.logger.info("\n=== Step 3/4: Trim trailing pages (optional) ===")
        trimmed = self._prompt_trim_trailing_pages()
        if trimmed:
            print(f"✅ Trailing pages trimmed: {trimmed.name}")
            self._update_working_pdf(trimmed)
        else:
            print("ℹ️  Keeping trailing pages unchanged.")

    def _maybe_remove_borders(self):
        self.toolbox.logger.info("\n=== Step 4/4: Dark border removal (optional) ===")
        cleaned = self.toolbox._check_and_remove_dark_borders(self.state.working_pdf)
        if cleaned:
            print(f"✅ Borders removed: {cleaned.name}")
            self._update_working_pdf(cleaned)
        else:
            print("ℹ️  Skipping border removal.")

    # ---------------------------
    # Trimming helpers
    # ---------------------------

    def _prompt_trim_leading_pages(self) -> Optional[Path]:
        if fitz is None:
            print("⚠️  PyMuPDF not available; cannot trim.")
            return None

        toolbox = self.toolbox
        while True:
            response = input("Drop leading pages? [Enter=keep / number=pages to drop]: ").strip().lower()
            if response in ("", "0", "n", "no"):
                return None

            if not response.isdigit():
                print("⚠️  Please enter a whole number or press Enter to skip.")
                continue

            pages_to_drop = int(response)
            if pages_to_drop <= 0:
                return None

            preview, total_pages = toolbox._extract_page_preview_text(self.state.working_pdf, pages_to_drop)
            if total_pages is not None and pages_to_drop >= total_pages:
                print(f"⚠️  PDF has only {total_pages} page(s); cannot drop {pages_to_drop}.")
                continue

            print("\nThe first page after trimming would start with:")
            print(f'  "{preview}"' if preview else "  [No text detected on that page]")

            confirm = input(f"Type 'trim' to drop the first {pages_to_drop} page(s), or press Enter to cancel: ").strip().lower()
            if confirm != "trim":
                print("ℹ️  Keeping leading pages.")
                return None

            trimmed = toolbox._create_pdf_from_page_offset(self.state.working_pdf, pages_to_drop)
            if not trimmed:
                print("⚠️  Failed to create trimmed PDF. Keeping original pages.")
                return None
            toolbox.logger.info(f"Trimmed {pages_to_drop} leading page(s): {trimmed.name}")
            return trimmed

    def _prompt_trim_trailing_pages(self) -> Optional[Path]:
        if fitz is None:
            print("⚠️  PyMuPDF not available; cannot trim.")
            return None

        while True:
            response = input("Drop trailing pages? [Enter=keep / number=pages to drop]: ").strip().lower()
            if response in ("", "0", "n", "no"):
                return None

            if not response.isdigit():
                print("⚠️  Please enter a whole number or press Enter to skip.")
                continue

            pages_to_drop = int(response)
            if pages_to_drop <= 0:
                return None

            trimmed = self._create_pdf_without_last_pages(self.state.working_pdf, pages_to_drop)
            if trimmed is None:
                continue

            preview = self._extract_trailing_preview(trimmed)
            print("\nThe last page after trimming would contain:")
            print(f'  "{preview}"' if preview else "  [No text detected on last page]")

            confirm = input(f"Type 'trim' to drop the last {pages_to_drop} page(s), or press Enter to cancel: ").strip().lower()
            if confirm != "trim":
                print("ℹ️  Keeping trailing pages.")
                return None

            self.toolbox.logger.info(f"Trimmed {pages_to_drop} trailing page(s): {trimmed.name}")
            return trimmed

    def _create_pdf_without_last_pages(self, pdf_path: Path, pages_to_drop: int) -> Optional[Path]:
        if fitz is None:
            print("⚠️  PyMuPDF not available; cannot trim.")
            return None

        try:
            doc = fitz.open(pdf_path)
        except Exception as exc:
            print(f"⚠️  Could not open PDF: {exc}")
            return None

        total_pages = len(doc)
        if pages_to_drop >= total_pages:
            print(f"⚠️  Cannot drop {pages_to_drop} page(s); PDF has only {total_pages}.")
            doc.close()
            return None

        new_doc = fitz.open()
        for page_num in range(total_pages - pages_to_drop):
            page = doc[page_num]
            new_page = new_doc.new_page(width=page.rect.width, height=page.rect.height)
            new_page.show_pdf_page(new_page.rect, doc, page_num)

        temp_target = self.temp_dir / f"{pdf_path.stem}_trimmed_end.pdf"
        new_doc.save(temp_target)
        new_doc.close()
        doc.close()

        self.state.modified_paths.append(temp_target)
        return temp_target

    def _extract_trailing_preview(self, pdf_path: Path, max_chars: int = 180) -> Optional[str]:
        if fitz is None:
            return None
        try:
            doc = fitz.open(pdf_path)
            if len(doc) == 0:
                doc.close()
                return None
            page = doc[-1]
            raw_text = page.get_text("text") or ""
            doc.close()
            preview = " ".join(raw_text.split())
            if preview and len(preview) > max_chars:
                preview = preview[: max_chars - 3].rstrip() + "..."
            return preview or None
        except Exception:
            return None

    # ---------------------------
    # Finalization & cleanup
    # ---------------------------

    def _finalize(self):
        current = self.state.working_pdf
        print("\n=== Summary ===")
        self._show_pdf_summary(current)
        choice = input("\nSave result? [1] Overwrite original [2] Save as new file [3] Cancel changes: ").strip()

        if choice == "1":
            shutil.copy2(current, self.source_pdf)
            print(f"✅ Overwritten original: {self.source_pdf}")
        elif choice == "2":
            target_path = self._prompt_for_output_path()
            if target_path:
                shutil.copy2(current, target_path)
                print(f"✅ Saved new file: {target_path}")
        else:
            print("ℹ️  No changes saved.")

    def _show_pdf_summary(self, pdf_path: Path):
        if fitz is None:
            size_mb = pdf_path.stat().st_size / (1024 * 1024)
            print(f"File: {pdf_path.name} — {size_mb:.2f} MB")
            return

        try:
            doc = fitz.open(pdf_path)
            page_count = len(doc)
            first_page = doc[0] if page_count else None
            doc.close()
        except Exception:
            page_count = "?"
            first_page = None

        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        print(f"File: {pdf_path.name}")
        print(f"Pages: {page_count}")
        if first_page:
            print(f"Dimensions: {first_page.rect.width:.0f} x {first_page.rect.height:.0f}")
        print(f"Size: {size_mb:.2f} MB")

    def _prompt_for_output_path(self) -> Optional[Path]:
        while True:
            target = input("Enter output filename (.pdf) or press Enter to cancel: ").strip()
            if not target:
                print("ℹ️  Skipping save.")
                return None

            target_path = Path(target).expanduser()
            if target_path.exists():
                overwrite = input(f"{target_path} exists. Overwrite? [y/N]: ").strip().lower()
                if overwrite != "y":
                    continue
            elif target_path.suffix.lower() != ".pdf":
                print("⚠️  Please provide a .pdf filename.")
                continue

            target_path.parent.mkdir(parents=True, exist_ok=True)
            return target_path

    def _cleanup(self):
        try:
            shutil.rmtree(self.temp_dir, ignore_errors=True)
        except Exception:
            pass


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive PDF fixer using PaperProcessorDaemon helpers.")
    parser.add_argument("pdf", type=Path, help="Path to the PDF file to fix")
    parser.add_argument("--debug", action="store_true", help="Enable verbose logging")
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None):
    args = parse_args(argv)
    fixer = PDFInteractiveFixer(args.pdf, debug=args.debug)
    fixer.run()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n❌ Operation cancelled by user.")

