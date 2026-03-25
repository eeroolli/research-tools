#!/usr/bin/env python3
"""
Tests for PDF preprocessing split behavior in PaperProcessorDaemon.

Focuses on:
- `_double` filenames: must always trigger a split when split_method='auto'
- Non-`_double` filenames: must *not* split unless two-up detection says so
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from scripts.paper_processor_daemon import PaperProcessorDaemon


def _make_dummy_pdf(path: Path) -> None:
    """Create a minimal single-page PDF at the given path using PyMuPDF if available.

    If PyMuPDF is not installed, create a tiny static PDF bytes sequence instead.
    The exact content does not matter for these tests; we only care that the file exists.
    """
    try:
        import fitz  # type: ignore[import]

        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Test PDF")
        doc.save(path)
        doc.close()
    except Exception:
        # Fallback: very small static PDF header/body sufficient for most parsers
        path.write_bytes(
            b"%PDF-1.4\n"
            b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
            b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
            b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
            b"xref\n0 4\n0000000000 65535 f \n"
            b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
        )


@pytest.fixture
def daemon(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> PaperProcessorDaemon:
    """Create a PaperProcessorDaemon with a temporary watch directory and minimal config.

    We avoid loading the real config.conf by monkeypatching methods that depend on it
    where necessary.
    """
    # Ensure working directory does not matter for these tests
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()

    # Instantiate daemon; this may still read config.conf, so we rely on the
    # existing test environment. If that becomes an issue, we can monkeypatch
    # _load_config or related helpers to use a synthetic config.
    d = PaperProcessorDaemon(watch_dir, debug=False)

    # For safety, point publications_dir to a temp location to avoid touching real files
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(exist_ok=True)

    return d


def test_double_filename_always_triggers_split_auto(daemon: PaperProcessorDaemon, tmp_path: Path) -> None:
    """Files with `_double` in the name must always trigger a split with method 'auto'."""
    pdf_path = tmp_path / "EN_20260101-120000_001_double.pdf"
    _make_dummy_pdf(pdf_path)

    processed, state = daemon._preprocess_pdf_with_options(
        pdf_path,
        border_removal=False,
        split_method="auto",
        trim_leading=False,
    )

    # With `_double` in the name, split must be attempted and succeed
    assert state.get("split_attempted") is True
    assert state.get("split_succeeded") is True
    assert state.get("split_method") == "auto"
    assert state.get("split_reason") == "filename_double"
    assert processed is not None
    assert processed != pdf_path


def test_non_double_filename_does_not_split_without_two_up(daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-`_double` filenames should not split when two-up detection says 'not two-up'."""
    pdf_path = tmp_path / "EN_20260101-120000_001.pdf"
    _make_dummy_pdf(pdf_path)

    # Force two-up detector to say "not two-up" regardless of content
    monkeypatch.setattr(
        daemon,
        "_detect_two_up_page",
        lambda path: (False, 0.0, "none"),
    )

    processed, state = daemon._preprocess_pdf_with_options(
        pdf_path,
        border_removal=False,
        split_method="auto",
        trim_leading=False,
    )

    # No `_double` and two-up detector says False -> no split attempted
    assert state.get("split_attempted") is False
    assert state.get("split_succeeded") is not True
    assert state.get("split_method") in ("none", "auto")
    assert processed == pdf_path

