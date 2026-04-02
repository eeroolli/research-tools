"""Tests for Zotero linked PDF attachment helpers."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

import pytest

from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def processor() -> ZoteroPaperProcessor:
    """Minimal processor without reading real Zotero config."""
    p = object.__new__(ZoteroPaperProcessor)
    p.api_key = "test-key"
    p.library_id = "12345"
    p.library_type = "user"
    p.base_url = "https://api.zotero.org/users/12345"
    p.headers = {"Zotero-API-Key": "test-key", "Content-Type": "application/json"}
    return p


def _make_post_mock(status: int = 200, body: Any = None):
    """Return a fake requests.post callable that records its arguments."""
    captured: Dict = {}
    body = body if body is not None else {"successful": {"0": {"key": "ATTACHKEY"}}, "failed": {}}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["json"] = json
        r = MagicMock()
        r.status_code = status
        r.content = b"{}"
        r.json.return_value = body
        return r

    return fake_post, captured


def _make_child(path: str, link_mode: str = "linked_file") -> Dict[str, Any]:
    return {
        "data": {
            "itemType": "attachment",
            "linkMode": link_mode,
            "path": path,
        }
    }


# ---------------------------------------------------------------------------
# attach_pdf: structured result
# ---------------------------------------------------------------------------

class TestAttachPdfStructuredResult:
    def test_success_returns_ok_true(self, processor):
        fake_post, captured = _make_post_mock(body={
            "successful": {"0": {"key": "K1"}},
            "failed": {},
        })
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"I:\publications\Foo.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            result = processor.attach_pdf("ITEM", Path("x.pdf"), "Foo")

        assert result["ok"] is True
        assert "K1" in result["attachment_keys"]
        assert result["sent_path"] == r"I:\publications\Foo.pdf"
        assert result["http_status"] == 200
        assert result["error"] is None

    def test_failed_array_returns_ok_false(self, processor):
        fake_post, _ = _make_post_mock(body={
            "successful": {},
            "failed": {"0": {"message": "file not found"}},
        })
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"I:\publications\Foo.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            result = processor.attach_pdf("ITEM", Path("x.pdf"), "Foo")

        assert result["ok"] is False
        assert result["error"] is not None

    def test_http_error_returns_ok_false(self, processor):
        fake_post, _ = _make_post_mock(status=403, body={"error": "forbidden"})
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"I:\publications\Foo.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            result = processor.attach_pdf("ITEM", Path("x.pdf"), "Foo")

        assert result["ok"] is False
        assert result["http_status"] == 403

    def test_title_and_content_type_payload(self, processor):
        """Attachment payload must include full basename and application/pdf."""
        fake_post, captured = _make_post_mock()
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"C:\pub\Author_2020_scan.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            processor.attach_pdf("ITEM", Path("x.pdf"), "ignored")

        att = captured["json"][0]
        assert att["title"] == "Author_2020_scan.pdf"
        assert att["contentType"] == "application/pdf"
        assert "filename" not in att, "'filename' must NOT be sent for linked_file attachments"
        assert att["linkMode"] == "linked_file"


# ---------------------------------------------------------------------------
# attach_pdf_to_existing: structured result
# ---------------------------------------------------------------------------

class TestAttachPdfToExistingStructuredResult:
    def test_success_returns_ok_true(self, processor):
        fake_post, captured = _make_post_mock()
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"I:\publications\Nosek_scan.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            result = processor.attach_pdf_to_existing("PARENT", Path("x.pdf"))

        assert result["ok"] is True
        assert result["sent_path"] == r"I:\publications\Nosek_scan.pdf"
        assert result["error"] is None
        att = captured["json"][0]
        assert att["title"] == "Nosek_scan.pdf"
        assert att["contentType"] == "application/pdf"
        assert att["parentItem"] == "PARENT"

    def test_failed_array_returns_ok_false(self, processor):
        fake_post, _ = _make_post_mock(body={
            "successful": {},
            "failed": {"0": {"message": "missing file"}},
        })
        with patch.object(processor, "_convert_wsl_to_windows_path",
                          return_value=r"I:\publications\Sample.pdf"), \
             patch("shared_tools.zotero.paper_processor.requests.post", side_effect=fake_post):
            result = processor.attach_pdf_to_existing("PARENT", Path("x.pdf"))

        assert result["ok"] is False


# ---------------------------------------------------------------------------
# linked_pdf_exists: exact and suffix matching
# ---------------------------------------------------------------------------

class TestLinkedPdfExists:
    def test_exact_match(self):
        children = [_make_child(r"I:\publications\Foo.pdf")]
        assert ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_exact_match_case_insensitive(self):
        children = [_make_child(r"I:\PUBLICATIONS\foo.pdf")]
        assert ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_suffix_match(self):
        """Zotero may store a relative path; match by basename suffix."""
        children = [_make_child(r"publications\Foo.pdf")]
        assert ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_basename_only_match(self):
        children = [_make_child(r"Foo.pdf")]
        assert ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_no_match_different_file(self):
        children = [_make_child(r"I:\publications\Bar.pdf")]
        assert not ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_no_match_not_linked_file(self):
        children = [_make_child(r"I:\publications\Foo.pdf", link_mode="imported_file")]
        assert not ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")

    def test_empty_children(self):
        assert not ZoteroPaperProcessor.linked_pdf_exists([], r"I:\publications\Foo.pdf")

    def test_non_attachment_children_ignored(self):
        note = {"data": {"itemType": "note", "linkMode": "linked_file", "path": r"I:\publications\Foo.pdf"}}
        assert not ZoteroPaperProcessor.linked_pdf_exists([note], r"I:\publications\Foo.pdf")

    def test_forward_slash_paths_normalized(self):
        """Paths stored with forward slashes should still match."""
        children = [_make_child("I:/publications/Foo.pdf")]
        assert ZoteroPaperProcessor.linked_pdf_exists(children, r"I:\publications\Foo.pdf")


# ---------------------------------------------------------------------------
# _parse_attach_response: handles both dict and list forms
# ---------------------------------------------------------------------------

class TestParseAttachResponse:
    def test_dict_successful(self):
        body = {"successful": {"0": {"key": "K1"}}, "failed": {}}
        keys, failed = ZoteroPaperProcessor._parse_attach_response(body)
        assert "K1" in keys
        assert failed == []

    def test_list_successful(self):
        body = {"successful": [{"key": "K2"}], "failed": []}
        keys, failed = ZoteroPaperProcessor._parse_attach_response(body)
        assert "K2" in keys

    def test_failed_items_returned(self):
        body = {"successful": {}, "failed": {"0": {"message": "err"}}}
        keys, failed = ZoteroPaperProcessor._parse_attach_response(body)
        assert keys == []
        assert len(failed) == 1

    def test_non_dict_body_returns_empty(self):
        keys, failed = ZoteroPaperProcessor._parse_attach_response("not a dict")
        assert keys == []
        assert failed == []


# ---------------------------------------------------------------------------
# Daemon _verify_pdf_linkage decision logic (inline, no daemon import)
#
# We test the logic directly here rather than importing PaperProcessorDaemon
# because that module requires optional heavy deps (watchdog, cv2, etc.).
# The implementation is identical to the real daemon method.
# ---------------------------------------------------------------------------

def _verify_pdf_linkage_impl(self, parent_key, sent_path, scan_path):
    """Replicate _verify_pdf_linkage from the daemon, minus the daemon import."""
    try:
        children = self.zotero_processor.fetch_item_children(parent_key)
    except Exception as exc:
        print(f"⚠️  Could not fetch Zotero children for {parent_key}: {exc}")
        self.move_to_manual_review(scan_path)
        return False

    if self.zotero_processor.linked_pdf_exists(children, sent_path):
        return True

    linked_paths = [
        c.get("data", {}).get("path", "")
        for c in children
        if c.get("data", {}).get("itemType") == "attachment"
    ]
    print(f"\n⚠️  Zotero linkage verification FAILED  parent={parent_key} expected={sent_path}")
    print(f"   Zotero has: {linked_paths or 'no attachment children'}")
    self.move_to_manual_review(scan_path)
    return False


class TestDaemonVerifyPdfLinkage:
    """Test the daemon's _verify_pdf_linkage logic without importing the daemon module."""

    def _make_fake_daemon(self, processor):
        class FakeDaemon:
            def __init__(self_):
                self_.zotero_processor = processor
                self_.manual_review_calls: list = []

            def move_to_manual_review(self_, path):
                self_.manual_review_calls.append(path)
                return True

            _verify_pdf_linkage = _verify_pdf_linkage_impl

        return FakeDaemon()

    def test_verify_succeeds_when_child_present(self, processor, tmp_path):
        scan = tmp_path / "scan.pdf"
        scan.touch()
        sent = r"I:\publications\Foo.pdf"

        with patch.object(processor, "fetch_item_children", return_value=[_make_child(sent)]):
            fd = self._make_fake_daemon(processor)
            result = fd._verify_pdf_linkage("PKEY", sent, scan)

        assert result is True
        assert fd.manual_review_calls == []

    def test_verify_fails_and_calls_manual_review(self, processor, tmp_path):
        scan = tmp_path / "scan.pdf"
        scan.touch()
        sent = r"I:\publications\Foo.pdf"

        with patch.object(processor, "fetch_item_children", return_value=[]):
            fd = self._make_fake_daemon(processor)
            result = fd._verify_pdf_linkage("PKEY", sent, scan)

        assert result is False
        assert fd.manual_review_calls == [scan]

    def test_verify_fails_via_suffix_match(self, processor, tmp_path):
        """Relative path in Zotero should still satisfy the verification."""
        scan = tmp_path / "scan.pdf"
        scan.touch()
        sent = r"I:\publications\Foo.pdf"

        with patch.object(processor, "fetch_item_children",
                          return_value=[_make_child(r"publications\Foo.pdf")]):
            fd = self._make_fake_daemon(processor)
            result = fd._verify_pdf_linkage("PKEY", sent, scan)

        assert result is True

    def test_verify_fetch_error_calls_manual_review(self, processor, tmp_path):
        scan = tmp_path / "scan.pdf"
        scan.touch()

        with patch.object(processor, "fetch_item_children", side_effect=RuntimeError("network")):
            fd = self._make_fake_daemon(processor)
            result = fd._verify_pdf_linkage("PKEY", r"I:\publications\Foo.pdf", scan)

        assert result is False
        assert fd.manual_review_calls == [scan]
