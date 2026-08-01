#!/usr/bin/env python3
"""
Tests for PDF preprocessing split behavior in PaperProcessorDaemon.

Focuses on:
- `*_double.pdf` and `*_double_<digits>.pdf` (Document Capture Pro counter):
  must trigger filename-based split when split_method='auto'
- Names containing `_double` but not that pattern (e.g. `..._double__part1.pdf`):
  must *not* use the filename rule — same rule as `_preprocess_split_if_needed`
- Other filenames: must *not* split unless two-up detection says so
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import sys
import types

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Import-time dependency stubs (tests should run without optional packages installed)
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
    from scripts.paper_processor_daemon import PaperProcessorDaemon
except ModuleNotFoundError as exc:
    pytest.skip(f"Optional dependency missing for daemon import: {exc}", allow_module_level=True)


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


@pytest.mark.parametrize(
    "filename",
    [
        "EN_20260101-120000_001_double.pdf",
        "EN_20260101-120000_001_double_001.pdf",
        "NO_20260723_0001_double_002.pdf",
    ],
)
def test_double_filename_always_triggers_split_auto(
    daemon: PaperProcessorDaemon,
    tmp_path: Path,
    filename: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`*_double.pdf` and Document Capture Pro `*_double_<n>.pdf` trigger filename split."""
    pdf_path = tmp_path / filename
    _make_dummy_pdf(pdf_path)
    split_out = tmp_path / f"PREPROCESSED_{pdf_path.stem}_split.pdf"
    _make_dummy_pdf(split_out)

    monkeypatch.setattr(
        daemon,
        "_split_with_mutool",
        lambda *args, **kwargs: split_out,
    )

    processed, state = daemon._preprocess_pdf_with_options(
        pdf_path,
        border_removal=False,
        split_method="auto",
        trim_leading=False,
    )

    assert state.get("split_attempted") is True
    assert state.get("split_succeeded") is True
    assert state.get("split_method") == "auto"
    assert state.get("split_reason") == "filename_double"
    assert processed == split_out


def test_double_in_name_without_double_pdf_suffix_no_filename_split(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`..._double__part1.pdf` is not the scanner double mark — no filename-forced split."""
    pdf_path = tmp_path / "EN_20260101-120000_001_double__part1.pdf"
    _make_dummy_pdf(pdf_path)

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

    assert state.get("split_attempted") is False
    assert state.get("split_succeeded") is not True
    assert processed == pdf_path


def test_substring_double_not_suffix_does_not_trigger_filename_split(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`_double` in the middle of the name is not the scanner `*_double.pdf` convention."""
    pdf_path = tmp_path / "EN_20260101-120000_001_double_scan.pdf"
    _make_dummy_pdf(pdf_path)

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

    assert state.get("split_reason") != "filename_double"
    assert state.get("split_attempted") is False
    assert processed == pdf_path


def test_filename_requests_double_split_helper() -> None:
    assert PaperProcessorDaemon._filename_requests_double_split("EN_x_double.pdf")
    assert PaperProcessorDaemon._filename_requests_double_split("EN_x_double_001.pdf")
    assert not PaperProcessorDaemon._filename_requests_double_split("EN_x_double__part1.pdf")
    assert not PaperProcessorDaemon._filename_requests_double_split("EN_x_double_scan.pdf")
    assert not PaperProcessorDaemon._filename_requests_double_split("EN_x.pdf")


def test_stem_for_preprocessed_artifacts_strips_trailing_double() -> None:
    p = Path("/tmp/EN_x_004_double.pdf")
    assert PaperProcessorDaemon._stem_for_preprocessed_artifacts(p) == "EN_x_004"
    # Keep Document Capture Pro counter; only strip the `_double` token.
    p_counter = Path("/tmp/EN_x_004_double_001.pdf")
    assert PaperProcessorDaemon._stem_for_preprocessed_artifacts(p_counter) == "EN_x_004_001"
    p2 = Path("/tmp/EN_x_004_double__part1.pdf")
    assert PaperProcessorDaemon._stem_for_preprocessed_artifacts(p2) == "EN_x_004_double__part1"


def test_enqueue_paper_dedupes_duplicate_paths(daemon: PaperProcessorDaemon, tmp_path: Path) -> None:
    """Watcher + separator must not queue the same resolved path twice."""
    pdf_path = tmp_path / "watch" / "EN_x__part1.pdf"
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    _make_dummy_pdf(pdf_path)

    assert daemon._enqueue_paper(pdf_path, notice=False) is True
    assert daemon._enqueue_paper(pdf_path, notice=False) is False
    assert daemon._paper_queue.qsize() == 1

    got = daemon._paper_queue.get_nowait()
    assert got == pdf_path
    daemon._release_enqueued_path(pdf_path)
    assert daemon._enqueue_paper(pdf_path, notice=False) is True


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
