#!/usr/bin/env python3
"""Tests for manual split handler — routes through full preprocess pipeline."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

watchdog_mod = types.ModuleType("watchdog")
watchdog_observers_mod = types.ModuleType("watchdog.observers")
watchdog_polling_mod = types.ModuleType("watchdog.observers.polling")
watchdog_events_mod = types.ModuleType("watchdog.events")


class _DummyPollingObserver:
    def __init__(self, *args, **kwargs) -> None:
        pass


watchdog_polling_mod.PollingObserver = _DummyPollingObserver
watchdog_events_mod.FileSystemEventHandler = object
sys.modules.setdefault("watchdog", watchdog_mod)
sys.modules.setdefault("watchdog.observers", watchdog_observers_mod)
sys.modules.setdefault("watchdog.observers.polling", watchdog_polling_mod)
sys.modules.setdefault("watchdog.events", watchdog_events_mod)

requests_mod = types.ModuleType("requests")
requests_mod.get = lambda *args, **kwargs: SimpleNamespace(status_code=404, json=lambda: {})
requests_mod.ConnectionError = Exception
requests_mod.Timeout = TimeoutError
requests_mod.RequestException = Exception
requests_mod.Session = lambda: SimpleNamespace(
    headers={}, get=lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {})
)
sys.modules.setdefault("requests", requests_mod)
sys.modules.setdefault("cv2", types.ModuleType("cv2"))
try:
    import importlib.util as _importlib_util

    if _importlib_util.find_spec("fitz") is None:
        sys.modules.setdefault("fitz", types.ModuleType("fitz"))
except ImportError:
    sys.modules.setdefault("fitz", types.ModuleType("fitz"))
bs4_mod = types.ModuleType("bs4")
bs4_mod.BeautifulSoup = object
sys.modules.setdefault("bs4", bs4_mod)
pyzbar_mod = types.ModuleType("pyzbar")
pyzbar_mod.pyzbar = SimpleNamespace(decode=lambda *args, **kwargs: [])
sys.modules.setdefault("pyzbar", pyzbar_mod)
yaml_mod = types.ModuleType("yaml")
yaml_mod.safe_load = lambda *_args, **_kwargs: {}
sys.modules.setdefault("yaml", yaml_mod)

try:
    from handle_item_selected_pages import (
        _handle_add_trimming,
        _handle_drop_border_removal,
        _handle_drop_trimming,
        _handle_manual_split,
        _preprocess_restart_source,
    )
    from scripts.paper_processor_daemon import PaperProcessorDaemon
    from shared_tools.ui.navigation import NavigationResult
except ModuleNotFoundError as exc:
    pytest.skip(f"Optional dependency missing for daemon import: {exc}", allow_module_level=True)


class _FakePage:
    def __init__(self, width: float) -> None:
        self.rect = SimpleNamespace(width=width)


class _FakeDoc:
    def __init__(self, widths: list[float]) -> None:
        self._widths = widths

    def __len__(self) -> int:
        return len(self._widths)

    def __getitem__(self, index: int) -> _FakePage:
        return _FakePage(self._widths[index])

    def close(self) -> None:
        pass


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    d = PaperProcessorDaemon(watch_dir, debug=False)
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(exist_ok=True)
    return d


def test_handle_manual_split_restarts_pipeline_with_prior_trim(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Manual split must restart preprocess with trim_leading preserved (not split-only)."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    final_out = tmp_path / "PREPROCESSED_EN_scan_split_trimmed.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured: dict = {}

    def fake_preprocess(pdf_path_arg, border_removal=True, split_method="auto",
                        trim_leading=True, manual_split_ratio=None):
        captured["args"] = {
            "pdf_path": pdf_path_arg,
            "border_removal": border_removal,
            "split_method": split_method,
            "trim_leading": trim_leading,
            "manual_split_ratio": manual_split_ratio,
        }
        return final_out, {
            "border_removal": False,
            "split_method": "manual",
            "split_attempted": True,
            "split_succeeded": True,
            "manual_split_ratio": manual_split_ratio,
            "trim_leading": True,
        }

    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "55")

    ctx = {
        "pdf_path": pdf_path,
        "preprocessing_state": {
            "split_method": "auto",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": True,
            "border_removal": False,
        },
    }

    result = _handle_manual_split(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert result.page_id == "pdf_preview"
    assert captured["args"]["pdf_path"] == pdf_path
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["trim_leading"] is True
    assert captured["args"]["manual_split_ratio"] == 55
    assert captured["args"]["border_removal"] is False
    assert ctx["processed_pdf"] == final_out
    state = ctx["preprocessing_state"]
    assert state["split_method"] == "manual"
    assert state["split_succeeded"] is True
    assert state["manual_split_ratio"] == 55
    assert state["trim_leading"] is True


def test_preprocess_manual_split_reapplies_trim(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pipeline: manual split then trim when trim_leading=True — not silent drop."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    split_out = tmp_path / "PREPROCESSED_EN_scan_split.pdf"
    split_out.write_bytes(b"%PDF-1.4\n%%EOF\n")
    trimmed_out = tmp_path / "PREPROCESSED_EN_scan_split_from_page2.pdf"
    trimmed_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda _path: _FakeDoc([846.8, 846.8])
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    monkeypatch.setattr(
        daemon,
        "_split_with_custom_gutter",
        lambda *_args, **_kwargs: (split_out, None),
    )
    trim_calls: list = []

    def fake_trim(pdf_arg):
        trim_calls.append(pdf_arg)
        return trimmed_out, True

    monkeypatch.setattr(daemon, "_prompt_trim_leading_pages_for_attachment", fake_trim)

    result_pdf, state = daemon._preprocess_pdf_with_options(
        pdf_path,
        border_removal=False,
        split_method="manual",
        trim_leading=True,
        manual_split_ratio=45,
    )

    assert result_pdf == trimmed_out
    assert len(trim_calls) == 1
    assert trim_calls[0] == split_out
    assert state["split_method"] == "manual"
    assert state["split_succeeded"] is True
    assert state["manual_split_ratio"] == 45
    assert state["trim_leading"] is True


def test_preprocess_manual_split_skips_trim_when_not_requested(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When trim was never applied, manual split must not invent a trim prompt."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    split_out = tmp_path / "PREPROCESSED_EN_scan_split.pdf"
    split_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda _path: _FakeDoc([846.8])
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    monkeypatch.setattr(
        daemon,
        "_split_with_custom_gutter",
        lambda *_args, **_kwargs: (split_out, None),
    )

    def fail_if_trim(_pdf):
        raise AssertionError("trim should not be prompted when trim_leading=False")

    monkeypatch.setattr(daemon, "_prompt_trim_leading_pages_for_attachment", fail_if_trim)

    result_pdf, state = daemon._preprocess_pdf_with_options(
        pdf_path,
        border_removal=False,
        split_method="manual",
        trim_leading=False,
        manual_split_ratio=50,
    )

    assert result_pdf == split_out
    assert state["split_method"] == "manual"
    assert state["split_succeeded"] is True
    assert state["trim_leading"] is False


def _manual_split_state() -> dict:
    return {
        "border_removal": False,
        "split_method": "manual",
        "split_attempted": True,
        "split_succeeded": True,
        "manual_split_ratio": 52.0,
        "trim_leading": False,
    }


def _capture_preprocess(final_out: Path):
    captured: dict = {}

    def fake_preprocess(
        pdf_path_arg,
        border_removal=True,
        split_method="auto",
        trim_leading=True,
        manual_split_ratio=None,
    ):
        captured["args"] = {
            "pdf_path": pdf_path_arg,
            "border_removal": border_removal,
            "split_method": split_method,
            "trim_leading": trim_leading,
            "manual_split_ratio": manual_split_ratio,
        }
        return final_out, {
            "border_removal": border_removal,
            "split_method": split_method,
            "split_attempted": True,
            "split_succeeded": True,
            "manual_split_ratio": manual_split_ratio,
            "trim_leading": trim_leading,
        }

    return captured, fake_preprocess


def test_handle_add_trimming_preserves_manual_split_ratio(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add trimming after manual split must forward manual_split_ratio."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    final_out = tmp_path / "PREPROCESSED_EN_scan_split_trimmed.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured, fake_preprocess = _capture_preprocess(final_out)
    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)

    ctx = {
        "pdf_path": pdf_path,
        "preprocessing_state": _manual_split_state(),
    }

    result = _handle_add_trimming(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert result.page_id == "pdf_preview"
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["manual_split_ratio"] == 52.0
    assert captured["args"]["trim_leading"] is True
    assert captured["args"]["border_removal"] is False
    assert ctx["preprocessing_state"]["manual_split_ratio"] == 52.0


def test_handle_drop_trimming_preserves_manual_split_ratio(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop trimming after manual split must forward manual_split_ratio."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    final_out = tmp_path / "PREPROCESSED_EN_scan_split.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured, fake_preprocess = _capture_preprocess(final_out)
    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)

    state = _manual_split_state()
    state["trim_leading"] = True
    ctx = {
        "pdf_path": pdf_path,
        "preprocessing_state": state,
    }

    result = _handle_drop_trimming(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert result.page_id == "pdf_preview"
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["manual_split_ratio"] == 52.0
    assert captured["args"]["trim_leading"] is False
    assert ctx["preprocessing_state"]["manual_split_ratio"] == 52.0


def test_handle_drop_border_preserves_manual_split_ratio(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Drop border after manual split must forward manual_split_ratio."""
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")
    final_out = tmp_path / "PREPROCESSED_EN_scan_split.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    captured, fake_preprocess = _capture_preprocess(final_out)
    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)

    state = _manual_split_state()
    state["border_removal"] = True
    ctx = {
        "pdf_path": pdf_path,
        "preprocessing_state": state,
    }

    result = _handle_drop_border_removal(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert result.page_id == "pdf_preview"
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["manual_split_ratio"] == 52.0
    assert captured["args"]["border_removal"] is False
    assert captured["args"]["trim_leading"] is False
    assert ctx["preprocessing_state"]["manual_split_ratio"] == 52.0


def test_restart_uses_original_scan_not_working_pdf_for_manual_split(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Attachment preview must restart from the two-up original, not the split working PDF."""
    original = tmp_path / "NO_20260801_0002.pdf"
    original.write_bytes(b"%PDF-1.4\n%%EOF\n")
    working = tmp_path / "PREPROCESSED_NO_20260801_0002_split.pdf"
    working.write_bytes(b"%PDF-1.4\n%%EOF\n")
    final_out = tmp_path / "PREPROCESSED_NO_20260801_0002_split_manual.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    daemon._original_scan_path = original

    captured, fake_preprocess = _capture_preprocess(final_out)
    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "48")

    ctx = {
        "pdf_path": working,  # what handle_item_selected receives after early preprocess
        "original_pdf": working,  # stale / wrong if set from pdf_path
        "preprocessing_state": {
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": False,
            "border_removal": False,
        },
    }

    result = _handle_manual_split(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert captured["args"]["pdf_path"] == original
    assert captured["args"]["pdf_path"] != working
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["manual_split_ratio"] == 48
    assert captured["args"]["trim_leading"] is False
    assert ctx["original_pdf"] == original
    assert daemon._working_pdf == final_out
    assert daemon._preprocessing_state["manual_split_ratio"] == 48


def test_add_trimming_restarts_from_original_with_manual_ratio(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Add trim after manual split: original source + ratio + trim (split then trim)."""
    original = tmp_path / "NO_20260801_0002.pdf"
    original.write_bytes(b"%PDF-1.4\n%%EOF\n")
    working = tmp_path / "PREPROCESSED_NO_20260801_0002_split.pdf"
    working.write_bytes(b"%PDF-1.4\n%%EOF\n")
    final_out = tmp_path / "PREPROCESSED_NO_20260801_0002_split_trimmed.pdf"
    final_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    daemon._original_scan_path = original

    captured, fake_preprocess = _capture_preprocess(final_out)
    monkeypatch.setattr(daemon, "_preprocess_pdf_with_options", fake_preprocess)

    ctx = {
        "pdf_path": working,
        "original_pdf": working,
        "preprocessing_state": _manual_split_state(),
    }

    result = _handle_add_trimming(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert captured["args"]["pdf_path"] == original
    assert captured["args"]["split_method"] == "manual"
    assert captured["args"]["manual_split_ratio"] == 52.0
    assert captured["args"]["trim_leading"] is True
    assert daemon._working_pdf == final_out
    assert daemon._preprocessing_state["trim_leading"] is True


def test_preprocess_restart_source_prefers_original_scan_path(
    daemon: PaperProcessorDaemon, tmp_path: Path
) -> None:
    original = tmp_path / "scan.pdf"
    original.write_bytes(b"%PDF-1.4\n%%EOF\n")
    working = tmp_path / "PREPROCESSED_scan_split.pdf"
    working.write_bytes(b"%PDF-1.4\n%%EOF\n")
    daemon._original_scan_path = original

    src = _preprocess_restart_source(
        {"pdf_path": working, "original_pdf": working},
        daemon,
    )
    assert src == original


def test_preprocess_restart_source_falls_back_without_original_scan(
    daemon: PaperProcessorDaemon, tmp_path: Path
) -> None:
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n%%EOF\n")
    if hasattr(daemon, "_original_scan_path"):
        delattr(daemon, "_original_scan_path")

    src = _preprocess_restart_source({"pdf_path": pdf}, daemon)
    assert src == pdf