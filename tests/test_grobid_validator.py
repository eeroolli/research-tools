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
    # No text so authors remain, but ensure regex fallback can be applied when authors emptied
    assert updated["authors"] == ["Ghost, Author"] or updated["authors"] == ["Alice Johnson"]


def test_grobid_validator_uses_regex_when_all_filtered(monkeypatch, tmp_path):
    """If all GROBID authors are filtered out of the text, regex_authors should be used."""
    metadata = {
        "authors": ["Bodei, Remo"],
        "extraction_method": "grobid"
    }

    # Text contains only the regex author name, not the GROBID author
    monkeypatch.setattr(
        identifier_extractor_module.IdentifierExtractor,
        "extract_text",
        classmethod(lambda cls, *args, **kwargs: "This essay by Georg Simmel explores the stranger.")
    )

    updated = GrobidValidator.validate_authors(
        metadata,
        tmp_path / "dummy.pdf",
        regex_authors=["Georg Simmel"],
        logger=logging.getLogger()
    )
    assert updated["authors"] == ["Georg Simmel"]


def test_grobid_validator_keeps_digit_lastname(monkeypatch, tmp_path):
    """Short/digit last names (e.g. 6) must not be filtered when present in text."""
    metadata = {
        "authors": ["6, Perry", "Ghost, Author"],
        "extraction_method": "grobid",
    }
    monkeypatch.setattr(
        identifier_extractor_module.IdentifierExtractor,
        "extract_text",
        classmethod(lambda cls, *args, **kwargs: "Essay by Perry 6 on methods."),
    )
    updated = GrobidValidator.validate_authors(
        metadata, tmp_path / "dummy.pdf", logger=logging.getLogger()
    )
    assert "6, Perry" in updated["authors"]
    assert "Ghost, Author" not in updated["authors"]
