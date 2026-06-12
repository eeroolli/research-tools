#!/usr/bin/env python3
"""Tests for safe preprocessed PDF save (viewer lock / overwrite)."""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

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

from scripts.paper_processor_daemon import PaperProcessorDaemon


class _FakeDoc:
    """Minimal PyMuPDF-like document for save-path tests."""

    def __init__(self, payload: bytes = b"fake-pdf-v1") -> None:
        self._payload = payload

    def save(self, path: str) -> None:
        Path(path).write_bytes(self._payload)


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir()
    d = PaperProcessorDaemon(watch_dir, debug=False)
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(exist_ok=True)
    return d


def test_save_preprocessed_pdf_creates_file(daemon: PaperProcessorDaemon, tmp_path: Path) -> None:
    out_path = tmp_path / "PREPROCESSED_test_split.pdf"
    doc = _FakeDoc(b"fake-pdf-created")
    daemon._save_preprocessed_pdf(doc, out_path)

    assert out_path.exists()
    assert not out_path.with_suffix(".tmp.pdf").exists()
    assert out_path.read_bytes() == b"fake-pdf-created"


def test_save_preprocessed_pdf_overwrites_existing(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_path = tmp_path / "PREPROCESSED_test_split.pdf"
    out_path.write_bytes(b"old")

    close_calls: list[str] = []
    monkeypatch.setattr(daemon, "_close_pdf_viewer", lambda: close_calls.append("closed"))

    doc = _FakeDoc(b"new-content")
    daemon._save_preprocessed_pdf(doc, out_path)

    assert close_calls == ["closed"]
    assert out_path.read_bytes() == b"new-content"
    assert not out_path.with_suffix(".tmp.pdf").exists()


def test_save_preprocessed_pdf_releases_lock_before_replace(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    out_path = tmp_path / "PREPROCESSED_test_split.pdf"
    out_path.write_bytes(b"locked")

    lock_file = open(out_path, "r+b")
    try:
        close_calls: list[str] = []

        def release_lock() -> None:
            close_calls.append("closed")
            lock_file.close()

        monkeypatch.setattr(daemon, "_close_pdf_viewer", release_lock)

        doc = _FakeDoc(b"replaced")
        daemon._save_preprocessed_pdf(doc, out_path)

        assert close_calls == ["closed"]
        assert out_path.read_bytes() == b"replaced"
    finally:
        if not lock_file.closed:
            lock_file.close()
