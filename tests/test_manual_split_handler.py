#!/usr/bin/env python3
"""Tests for manual split handler state updates."""

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


class _DummyEventHandler:
    pass


watchdog_events_mod.FileSystemEventHandler = _DummyEventHandler

sys.modules.setdefault("watchdog", watchdog_mod)
sys.modules.setdefault("watchdog.observers", watchdog_observers_mod)
sys.modules.setdefault("watchdog.observers.polling", watchdog_polling_mod)
sys.modules.setdefault("watchdog.events", watchdog_events_mod)

from handle_item_selected_pages import _handle_manual_split
from scripts.paper_processor_daemon import PaperProcessorDaemon
from shared_tools.ui.navigation import NavigationResult


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


def test_handle_manual_split_sets_split_succeeded(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "EN_scan_double.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n%%EOF\n")

    split_out = tmp_path / "PREPROCESSED_EN_scan_split.pdf"
    split_out.write_bytes(b"%PDF-1.4\n%%EOF\n")

    fake_fitz = types.ModuleType("fitz")
    fake_fitz.open = lambda _path: _FakeDoc([846.8, 846.8])
    monkeypatch.setitem(sys.modules, "fitz", fake_fitz)

    monkeypatch.setattr(
        daemon,
        "_split_with_custom_gutter",
        lambda *_args, **_kwargs: (split_out, None),
    )
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "55")

    ctx = {
        "pdf_path": pdf_path,
        "preprocessing_state": {
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": True,
        },
    }

    result = _handle_manual_split(ctx, daemon)

    assert result.type == NavigationResult.Type.SHOW_PAGE
    assert result.page_id == "pdf_preview"
    assert ctx["processed_pdf"] == split_out
    state = ctx["preprocessing_state"]
    assert state["split_method"] == "manual"
    assert state["split_attempted"] is True
    assert state["split_succeeded"] is True
    assert state["manual_split_ratio"] == 55
