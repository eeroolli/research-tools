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


def test_stem_for_preprocessed_artifacts_strips_existing_preprocessed_prefix() -> None:
    """Border→split must not yield PREPROCESSED_PREPROCESSED_* names."""
    chained = Path("/tmp/pdf_splits/PREPROCESSED_EN_x_004_no_borders.pdf")
    assert (
        PaperProcessorDaemon._stem_for_preprocessed_artifacts(chained)
        == "EN_x_004_no_borders"
    )
    double = Path("/tmp/PREPROCESSED_PREPROCESSED_EN_x_no_borders_split.pdf")
    assert (
        PaperProcessorDaemon._stem_for_preprocessed_artifacts(double)
        == "EN_x_no_borders_split"
    )
    plain = Path("/tmp/EN_x_004.pdf")
    assert PaperProcessorDaemon._stem_for_preprocessed_artifacts(plain) == "EN_x_004"


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


def test_process_paper_runs_preprocessing_before_metadata_extraction(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Extraction must receive the early-preprocessed PDF path, not the raw scan."""
    pdf_path = tmp_path / "EN_20260801_0001_double.pdf"
    _make_dummy_pdf(pdf_path)
    working_pdf = tmp_path / "PREPROCESSED_early.pdf"
    _make_dummy_pdf(working_pdf)

    call_order: list[str] = []
    extract_paths: list[Path] = []

    daemon._close_sumatra_all_tabs = lambda: True
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True
    daemon._return_focus_to_terminal = lambda: None
    daemon._close_pdf_viewer = lambda: None
    daemon.move_to_failed = lambda *_args, **_kwargs: None
    daemon.display_metadata = lambda *_args, **_kwargs: None
    daemon._handle_isbn_lookup_result = lambda result: result
    daemon.prompt_for_document_type = lambda metadata: metadata
    daemon._maybe_auto_document_separator_early = lambda *_args, **_kwargs: False

    def _preprocess(pdf, **_kwargs):
        call_order.append("preprocess")
        return working_pdf, {"split_method": "50-50", "split_attempted": True, "split_succeeded": True}

    def _preview(*_args, **_kwargs):
        call_order.append("preview")
        return working_pdf, {
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "border_removal": False,
            "trim_leading": True,
        }

    daemon._preprocess_pdf_with_options = _preprocess
    daemon._preview_and_modify_preprocessing = _preview

    def _process_pdf(pdf, **_kwargs):
        call_order.append("extract")
        extract_paths.append(Path(pdf))
        return {
            "success": True,
            "metadata": {
                "title": "Right-hand page title",
                "authors": ["Author, A"],
                "year": "1999",
                "document_type": "journal_article",
            },
            "method": "grep",
            "identifiers_found": {},
        }

    daemon.metadata_processor = SimpleNamespace(process_pdf=_process_pdf)
    daemon.service_manager = SimpleNamespace(
        ensure_grobid_ready=lambda: False, grobid_ready=False, grobid_client=None
    )
    daemon.local_zotero = object()
    daemon.search_and_display_local_zotero = lambda metadata, force_prompt_year=False, skip_author_select=False: (
        "manual",
        None,
        metadata,
    )
    daemon.move_to_manual_review = lambda *_args, **_kwargs: None
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")

    daemon.process_paper(pdf_path)

    assert call_order[:3] == ["preprocess", "preview", "extract"]
    assert extract_paths == [working_pdf]
    assert daemon._working_pdf == working_pdf
    assert daemon._preprocessing_state.get("split_succeeded") is True


def test_is_landscape_page_helper() -> None:
    assert PaperProcessorDaemon._is_landscape_page(842, 595) is True
    assert PaperProcessorDaemon._is_landscape_page(595, 842) is False
    assert PaperProcessorDaemon._is_landscape_page(600, 600) is False


def _make_sized_pdf(path: Path, page_sizes: list[tuple[float, float]]) -> None:
    """Create a multi-page PDF with given (width, height) per page."""
    fitz = pytest.importorskip("fitz")
    doc = fitz.open()
    for width, height in page_sizes:
        page = doc.new_page(width=width, height=height)
        page.insert_text((36, 72), f"{width:.0f}x{height:.0f}")
    doc.save(path)
    doc.close()


def test_split_keeps_portrait_pages_in_mixed_pdf(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Portrait, landscape, portrait → 4 output pages; ends keep source size."""
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "mixed_orient.pdf"
    portrait = (595.0, 842.0)
    landscape = (842.0, 595.0)
    _make_sized_pdf(pdf_path, [portrait, landscape, portrait])

    # Avoid writing under system temp; save into tmp_path
    monkeypatch.setattr(
        daemon,
        "_save_preprocessed_pdf",
        lambda doc, out_path: doc.save(str(out_path)),
    )
    monkeypatch.setattr(
        "tempfile.gettempdir",
        lambda: str(tmp_path),
    )

    out_path, err = daemon._split_with_custom_gutter(pdf_path, landscape[0] / 2)
    assert err is None
    assert out_path is not None
    assert out_path.exists()

    out = fitz.open(str(out_path))
    try:
        assert len(out) == 4
        assert abs(out[0].rect.width - portrait[0]) < 1.0
        assert abs(out[0].rect.height - portrait[1]) < 1.0
        assert abs(out[1].rect.width - landscape[0] / 2) < 1.0
        assert abs(out[1].rect.height - landscape[1]) < 1.0
        assert abs(out[2].rect.width - landscape[0] / 2) < 1.0
        assert abs(out[2].rect.height - landscape[1]) < 1.0
        assert abs(out[3].rect.width - portrait[0]) < 1.0
        assert abs(out[3].rect.height - portrait[1]) < 1.0
    finally:
        out.close()


def test_split_all_landscape_doubles_page_count(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "all_landscape.pdf"
    landscape = (842.0, 595.0)
    _make_sized_pdf(pdf_path, [landscape, landscape])

    monkeypatch.setattr(
        daemon,
        "_save_preprocessed_pdf",
        lambda doc, out_path: doc.save(str(out_path)),
    )
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    out_path, err = daemon._split_with_custom_gutter(pdf_path, landscape[0] / 2)
    assert err is None
    assert out_path is not None

    out = fitz.open(str(out_path))
    try:
        assert len(out) == 4
    finally:
        out.close()


def test_split_all_portrait_copies_through(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fitz = pytest.importorskip("fitz")
    pdf_path = tmp_path / "all_portrait.pdf"
    portrait = (595.0, 842.0)
    _make_sized_pdf(pdf_path, [portrait, portrait, portrait])

    monkeypatch.setattr(
        daemon,
        "_save_preprocessed_pdf",
        lambda doc, out_path: doc.save(str(out_path)),
    )
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path))

    # Gutter value is unused for portrait-only; any value is fine
    out_path, err = daemon._split_with_custom_gutter(pdf_path, 300.0)
    assert err is None
    assert out_path is not None

    out = fitz.open(str(out_path))
    try:
        assert len(out) == 3
        for i in range(3):
            assert abs(out[i].rect.width - portrait[0]) < 1.0
            assert abs(out[i].rect.height - portrait[1]) < 1.0
    finally:
        out.close()
