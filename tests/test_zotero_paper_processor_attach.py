"""Tests for Zotero linked PDF attachment titles."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


@pytest.fixture
def processor() -> ZoteroPaperProcessor:
    """Minimal processor without reading real zotero config."""
    p = object.__new__(ZoteroPaperProcessor)
    p.api_key = "test-key"
    p.library_id = "12345"
    p.library_type = "user"
    p.base_url = "https://api.zotero.org/users/12345"
    p.headers = {"Zotero-API-Key": "test-key", "Content-Type": "application/json"}
    return p


def test_attach_pdf_to_existing_title_includes_pdf_suffix(processor: ZoteroPaperProcessor) -> None:
    """Linked attachment title must be full basename (incl. .pdf) like attach_pdf()."""
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        r = MagicMock()
        r.status_code = 200
        return r

    with patch.object(
        processor,
        "_convert_wsl_to_windows_path",
        return_value=r"I:\publications\Nosek_et_al_2007_Pervasiveness_scan.pdf",
    ), patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
        ok = processor.attach_pdf_to_existing("PARENTKEY1", Path("/fake/path.pdf"))
    assert ok is True
    assert captured["json"] is not None
    attachment = captured["json"][0]
    assert attachment["title"] == "Nosek_et_al_2007_Pervasiveness_scan.pdf"
    assert attachment["title"].endswith(".pdf")
    assert attachment["linkMode"] == "linked_file"
    assert attachment["parentItem"] == "PARENTKEY1"


def test_attach_pdf_uses_full_basename_for_comparison(processor: ZoteroPaperProcessor) -> None:
    """attach_pdf should still send basename with extension in title."""
    captured: dict = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        r = MagicMock()
        r.status_code = 200
        return r

    with patch.object(
        processor,
        "_convert_wsl_to_windows_path",
        return_value=r"C:\pub\Author_2020_Title_scan.pdf",
    ), patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
        ok = processor.attach_pdf("ITEMKEY", Path("x.pdf"), "ignored title for basename")

    assert ok is True
    att = captured["json"][0]
    assert att["title"] == "Author_2020_Title_scan.pdf"
