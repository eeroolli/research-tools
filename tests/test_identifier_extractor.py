"""Tests for identifier extraction, including OCR-damaged DOI URLs."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.utils.identifier_extractor import IdentifierExtractor
from shared_tools.utils.identifier_validator import IdentifierValidator


class TestExtractOcrDois:
    """OCR-damaged doi.org URLs should be extracted and validate after correction."""

    def test_extract_ocr_dx_doi_url_from_text(self):
        text = "DOI: http://dx.doi.org/l0.l080/l4742837.20l2.703831"
        dois = IdentifierExtractor.extract_dois(text)
        assert "l0.l080/l4742837.20l2.703831" in dois

    def test_extracted_ocr_doi_validates(self):
        text = "http://dx.doi.org/l0.l080/l4742837.20l2.703831"
        dois = IdentifierExtractor.extract_dois(text)
        assert len(dois) >= 1
        is_valid, cleaned, reason = IdentifierValidator.validate_doi(dois[0])
        assert is_valid is True
        assert cleaned == "10.1080/14742837.2012.703831"
        assert "OCR corrected" in reason
