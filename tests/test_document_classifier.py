import types

from shared_tools.utils.document_classifier import DocumentClassifier
from shared_tools.utils import identifier_extractor as identifier_extractor_module


def test_is_handwritten_note_uses_threshold(monkeypatch, tmp_path):
    # Monkeypatch extract_text to return small text for two pages
    calls = {"count": 0}

    def fake_extract_text(pdf_path, page_offset=0, max_pages=1, document_type=None):
        calls["count"] += 1
        return "hi"  # very short

    monkeypatch.setattr(identifier_extractor_module.IdentifierExtractor, "extract_text", classmethod(lambda cls, *args, **kwargs: fake_extract_text(*args, **kwargs)))
    monkeypatch.setattr(DocumentClassifier, "get_handwritten_threshold", classmethod(lambda cls: 50))

    assert DocumentClassifier.is_handwritten_note(tmp_path / "dummy.pdf") is True
    # ensure we checked requested pages
    assert calls["count"] >= 1


def test_is_handwritten_note_returns_false_with_text(monkeypatch, tmp_path):
    monkeypatch.setattr(identifier_extractor_module.IdentifierExtractor, "extract_text", classmethod(lambda cls, *args, **kwargs: "long text " * 20))
    monkeypatch.setattr(DocumentClassifier, "get_handwritten_threshold", classmethod(lambda cls: 10))

    assert DocumentClassifier.is_handwritten_note(tmp_path / "dummy.pdf") is False
