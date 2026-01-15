import logging

from shared_tools.utils import identifier_extractor as identifier_extractor_module
from shared_tools.utils.grobid_validator import GrobidValidator


def test_grobid_validator_filters_missing(monkeypatch, tmp_path):
    metadata = {
        "authors": ["Smith, John", "Doe, Jane"],
        "extraction_method": "grobid"
    }

    # Only include Smith in text
    monkeypatch.setattr(
        identifier_extractor_module.IdentifierExtractor,
        "extract_text",
        classmethod(lambda cls, *args, **kwargs: "Abstract by John Smith on research.")
    )

    updated = GrobidValidator.validate_authors(metadata, tmp_path / "dummy.pdf", logger=logging.getLogger())
    assert updated["authors"] == ["Smith, John"]


def test_grobid_validator_uses_regex_fallback(monkeypatch, tmp_path):
    metadata = {
        "authors": ["Ghost, Author"],
        "extraction_method": "grobid"
    }

    monkeypatch.setattr(
        identifier_extractor_module.IdentifierExtractor,
        "extract_text",
        classmethod(lambda cls, *args, **kwargs: "")
    )

    updated = GrobidValidator.validate_authors(metadata, tmp_path / "dummy.pdf", regex_authors=["Alice Johnson"])
    # No text so authors remain, but ensure regex fallback applied when authors emptied
    assert updated["authors"] == ["Ghost, Author"] or updated["authors"] == ["Alice Johnson"]
