#!/usr/bin/env python3
"""Tests for scan filename language prefixes (including SE_ Swedish alias)."""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Lightweight stubs so paper_processor_daemon can import without optional deps.
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
    from scripts.paper_processor_daemon import (
        SCAN_LANGUAGE_MAP,
        SCAN_LANGUAGE_PREFIXES,
        PaperProcessorDaemon,
    )
    from shared_tools.metadata.paper_processor import PaperMetadataProcessor
except ModuleNotFoundError as exc:
    pytest.skip(f"Optional dependency missing for daemon import: {exc}", allow_module_level=True)


@pytest.fixture
def daemon() -> PaperProcessorDaemon:
    """Avoid full PaperProcessorDaemon.__init__ (starts services)."""
    return PaperProcessorDaemon.__new__(PaperProcessorDaemon)


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("NO_20250801_scan.pdf", True),
        ("EN_20250801_scan.pdf", True),
        ("DE_20250801_scan.pdf", True),
        ("FI_20250801_scan.pdf", True),
        ("SV_20250801_scan.pdf", True),
        ("SE_20250801_scan.pdf", True),
        ("DA_20250801_scan.pdf", True),
        ("XX_20250801_scan.pdf", False),
        ("SE_20250801_scan_split.pdf", False),
        ("random.pdf", False),
    ],
)
def test_should_process_language_prefixes(
    daemon: PaperProcessorDaemon, filename: str, expected: bool
) -> None:
    assert daemon.should_process(filename) is expected


@pytest.mark.parametrize(
    "filename,expected_iso",
    [
        ("NO_20250801_scan.pdf", "no"),
        ("EN_20250801_scan.pdf", "en"),
        ("DE_20250801_scan.pdf", "de"),
        ("FI_20250801_scan.pdf", "fi"),
        ("SV_20250801_scan.pdf", "sv"),
        ("SE_20250801_scan.pdf", "sv"),
        ("DA_20250801_scan.pdf", "da"),
        ("XX_20250801_scan.pdf", None),
    ],
)
def test_detect_language_from_filename_iso(
    daemon: PaperProcessorDaemon, filename: str, expected_iso: str | None
) -> None:
    assert daemon._detect_language_from_filename(Path(filename)) == expected_iso


def test_se_and_sv_both_map_to_sv() -> None:
    assert SCAN_LANGUAGE_MAP["SE_"] == "sv"
    assert SCAN_LANGUAGE_MAP["SV_"] == "sv"
    assert "SE_" in SCAN_LANGUAGE_PREFIXES
    assert "SV_" in SCAN_LANGUAGE_PREFIXES


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("SE_scan.pdf", "SV"),
        ("SV_scan.pdf", "SV"),
        ("DA_scan.pdf", "DA"),
        ("NO_scan.pdf", "NO"),
    ],
)
def test_metadata_processor_detects_se_as_sv(filename: str, expected: str) -> None:
    """Metadata extractor returns uppercase codes for Ollama; SE_ → SV."""
    processor = PaperMetadataProcessor.__new__(PaperMetadataProcessor)
    assert processor._detect_language_from_filename(Path(filename)) == expected


def test_split_prefix_preserves_se(daemon: PaperProcessorDaemon) -> None:
    prefix, stem = daemon._split_prefix_and_stem("SE_20250801_scan.pdf")
    assert prefix == "SE_"
    assert stem == "20250801_scan"
