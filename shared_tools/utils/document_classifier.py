#!/usr/bin/env python3
"""
Document classification helpers (e.g., handwritten note detection).
"""

import configparser
from pathlib import Path
from typing import Optional

from .identifier_extractor import IdentifierExtractor


class DocumentClassifier:
    """Classify document characteristics such as handwritten notes."""

    @staticmethod
    def _read_handwritten_threshold_from_config() -> int:
        """Read handwritten note text threshold from config files."""
        try:
            config = configparser.ConfigParser()
            root_dir = Path(__file__).parent.parent.parent
            config.read([
                root_dir / 'config.conf',
                root_dir / 'config.personal.conf'
            ])

            if config.has_option('METADATA', 'handwritten_note_text_threshold'):
                threshold = config.getint('METADATA', 'handwritten_note_text_threshold')
                return max(0, threshold)

            return 50  # Default threshold
        except Exception:
            return 50

    @classmethod
    def get_handwritten_threshold(cls) -> int:
        """Public accessor for handwritten note threshold."""
        return cls._read_handwritten_threshold_from_config()

    @classmethod
    def is_handwritten_note(cls, pdf_path: Path, page_offset: int = 0, max_pages_to_check: int = 2) -> bool:
        """Check if PDF appears to be a handwritten note (very little OCR text)."""
        threshold = cls.get_handwritten_threshold()

        try:
            total_text_length = 0
            pages_checked = 0

            for i in range(page_offset, page_offset + max_pages_to_check):
                page_text = IdentifierExtractor.extract_text(pdf_path, page_offset=i, max_pages=1)
                if page_text:
                    total_text_length += len(page_text.strip())
                pages_checked += 1

            if pages_checked > 0:
                avg_text_per_page = total_text_length / pages_checked
                return avg_text_per_page < threshold

            return False
        except Exception:
            return False
