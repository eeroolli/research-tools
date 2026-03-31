#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Minimal import-time stubs (same rationale as other daemon tests)
watchdog_mod = types.ModuleType("watchdog")
watchdog_observers_mod = types.ModuleType("watchdog.observers")
watchdog_polling_mod = types.ModuleType("watchdog.observers.polling")
watchdog_events_mod = types.ModuleType("watchdog.events")


class _DummyPollingObserver:
    def __init__(self, *args, **kwargs) -> None:
        pass

    def schedule(self, *args, **kwargs) -> None:
        pass

    def start(self, *args, **kwargs) -> None:
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
requests_mod.Session = lambda: SimpleNamespace(headers={}, get=lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {}))
sys.modules.setdefault("requests", requests_mod)

sys.modules.setdefault("cv2", types.ModuleType("cv2"))
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

from scripts.paper_processor_daemon import PaperProcessorDaemon


def _write_dummy_pdf(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        b"%PDF-1.4\n"
        b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
        b"2 0 obj<</Type/Pages/Count 1/Kids[3 0 R]>>endobj\n"
        b"3 0 obj<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]>>endobj\n"
        b"xref\n0 4\n0000000000 65535 f \n"
        b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n0\n%%EOF\n"
    )


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(parents=True, exist_ok=True)
    d = PaperProcessorDaemon(watch_dir, debug=False)
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(parents=True, exist_ok=True)
    return d


def test_handle_item_selected_returns_back_status(daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch) -> None:
    from shared_tools.ui import navigation as nav

    monkeypatch.setattr(daemon, "_display_zotero_item_details", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(daemon, "_auto_enrich_selected_item", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        nav.NavigationEngine,
        "run_page_flow",
        lambda *_args, **_kwargs: nav.NavigationResult.return_to_caller(),
    )

    status = daemon.handle_item_selected(
        pdf_path=Path("scan.pdf"),
        metadata={"title": "x", "authors": ["A"], "_year_confirmed": True},
        selected_item={"key": "K1", "title": "T", "authors": ["A"]},
    )

    assert status == "back_to_item_selection"


def test_handle_item_selected_resolved_no_attach_navigation_result(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keeping existing PDF must not map to back_to_item_selection (scan already moved)."""
    from shared_tools.ui import navigation as nav

    monkeypatch.setattr(daemon, "_display_zotero_item_details", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(daemon, "_auto_enrich_selected_item", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        nav.NavigationEngine,
        "run_page_flow",
        lambda *_args, **_kwargs: nav.NavigationResult.resolved_no_attach(),
    )

    status = daemon.handle_item_selected(
        pdf_path=Path("scan.pdf"),
        metadata={"title": "x", "authors": ["A"], "_year_confirmed": True},
        selected_item={"key": "K1", "title": "T", "authors": ["A"]},
    )

    assert status == "resolved_no_attach"


def test_process_paper_reenters_selection_after_item_back(
    daemon: PaperProcessorDaemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "EN_20260324_0001_double.pdf"
    _write_dummy_pdf(pdf_path)

    # Keep process_paper focused on control flow under test.
    daemon._close_sumatra_all_tabs = lambda: True
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True
    daemon._return_focus_to_terminal = lambda: None
    daemon._close_pdf_viewer = lambda: None
    daemon.move_to_failed = lambda *_args, **_kwargs: None
    daemon.display_metadata = lambda *_args, **_kwargs: None
    daemon._handle_isbn_lookup_result = lambda result: result
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")

    daemon.metadata_processor = SimpleNamespace(
        process_pdf=lambda *_args, **_kwargs: {
            "success": True,
            "metadata": {
                "title": "A title",
                "authors": ["Bean", "Papadakis"],
                "year": "1994",
                "document_type": "journal_article",
            },
            "method": "grep",
            "identifiers_found": {},
        }
    )

    daemon.prompt_for_year = lambda metadata, force_prompt=False: {**metadata, "_year_confirmed": True}
    daemon.prompt_for_document_type = lambda metadata: metadata
    daemon.service_manager = SimpleNamespace(ensure_grobid_ready=lambda: False, grobid_ready=False, grobid_client=None)
    daemon.local_zotero = object()

    search_calls = {"count": 0}

    def _search_stub(*_args, **_kwargs):
        search_calls["count"] += 1
        return (
            "select",
            {"key": f"K{search_calls['count']}", "title": "Item", "authors": ["Bean", "Papadakis"]},
            {"title": "A title", "authors": ["Bean", "Papadakis"], "year": "1994", "_year_confirmed": True},
        )

    daemon.search_and_display_local_zotero = _search_stub

    selected_outcomes = iter(["back_to_item_selection", "processed"])
    daemon.handle_item_selected = lambda *_args, **_kwargs: next(selected_outcomes)

    moved_manual = {"count": 0}
    daemon.move_to_manual_review = lambda *_args, **_kwargs: moved_manual.__setitem__("count", moved_manual["count"] + 1)

    result = daemon.process_paper(pdf_path)

    assert result is None
    assert search_calls["count"] == 2
    assert moved_manual["count"] == 0


def test_process_paper_back_from_match_list_does_not_move_pdf_to_manual(
    daemon: PaperProcessorDaemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: 'z' (back) in Zotero match list must not move PDF to manual review."""
    pdf_path = tmp_path / "EN_20260331_0001_double.pdf"
    _write_dummy_pdf(pdf_path)

    daemon._close_sumatra_all_tabs = lambda: True
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True
    daemon._return_focus_to_terminal = lambda: None
    daemon._close_pdf_viewer = lambda: None
    daemon.move_to_failed = lambda *_args, **_kwargs: None
    daemon.display_metadata = lambda *_args, **_kwargs: None
    daemon._handle_isbn_lookup_result = lambda result: result
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")

    daemon.metadata_processor = SimpleNamespace(
        process_pdf=lambda *_args, **_kwargs: {
            "success": True,
            "metadata": {
                "title": "A title",
                "authors": ["Bean", "Papadakis"],
                "year": "1994",
                "document_type": "journal_article",
            },
            "method": "grep",
            "identifiers_found": {},
        }
    )
    daemon.prompt_for_year = lambda metadata, force_prompt=False: {**metadata, "_year_confirmed": True}
    daemon.prompt_for_document_type = lambda metadata: metadata
    daemon.service_manager = SimpleNamespace(ensure_grobid_ready=lambda: False, grobid_ready=False, grobid_client=None)
    daemon.local_zotero = object()

    # Simulate: select item -> item flow returns back_to_item_selection -> user hits 'z' in match list -> then selects item again.
    search_results = iter(
        [
            (
                "select",
                {"key": "K1", "title": "Item", "authors": ["Bean", "Papadakis"]},
                {"title": "A title", "authors": ["Bean", "Papadakis"], "year": "1994", "_year_confirmed": True},
            ),
            ("back", None, {"title": "A title", "authors": ["Bean", "Papadakis"], "year": "1994", "_year_confirmed": True}),
            (
                "select",
                {"key": "K2", "title": "Item2", "authors": ["Bean", "Papadakis"]},
                {"title": "A title", "authors": ["Bean", "Papadakis"], "year": "1994", "_year_confirmed": True},
            ),
        ]
    )
    daemon.search_and_display_local_zotero = lambda *_args, **_kwargs: next(search_results)

    selected_outcomes = iter(["back_to_item_selection", "processed"])
    daemon.handle_item_selected = lambda *_args, **_kwargs: next(selected_outcomes)

    moved_manual = {"count": 0}
    moved_skipped = {"count": 0}
    moved_done = {"count": 0}
    daemon.move_to_manual_review = lambda *_args, **_kwargs: moved_manual.__setitem__("count", moved_manual["count"] + 1)
    daemon.move_to_skipped = lambda *_args, **_kwargs: moved_skipped.__setitem__("count", moved_skipped["count"] + 1)
    daemon.move_to_done = lambda *_args, **_kwargs: moved_done.__setitem__("count", moved_done["count"] + 1)

    result = daemon.process_paper(pdf_path)

    assert result is None
    assert moved_manual["count"] == 0
    assert moved_skipped["count"] == 0
    assert moved_done["count"] == 0


def test_process_paper_quit_from_zotero_selection_moves_to_manual_review(
    daemon: PaperProcessorDaemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "EN_20260331_0002_double.pdf"
    _write_dummy_pdf(pdf_path)

    daemon._close_sumatra_all_tabs = lambda: True
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True
    daemon._return_focus_to_terminal = lambda: None
    daemon._close_pdf_viewer = lambda: None
    daemon.move_to_failed = lambda *_args, **_kwargs: None
    daemon.display_metadata = lambda *_args, **_kwargs: None
    daemon._handle_isbn_lookup_result = lambda result: result
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")

    daemon.metadata_processor = SimpleNamespace(
        process_pdf=lambda *_args, **_kwargs: {
            "success": True,
            "metadata": {
                "title": "A title",
                "authors": ["Bean", "Papadakis"],
                "year": "1994",
                "document_type": "journal_article",
            },
            "method": "grep",
            "identifiers_found": {},
        }
    )
    daemon.prompt_for_year = lambda metadata, force_prompt=False: {**metadata, "_year_confirmed": True}
    daemon.prompt_for_document_type = lambda metadata: metadata
    daemon.service_manager = SimpleNamespace(ensure_grobid_ready=lambda: False, grobid_ready=False, grobid_client=None)
    daemon.local_zotero = object()

    daemon.search_and_display_local_zotero = lambda *_args, **_kwargs: ("quit", None, {"title": "A title"})

    moved_manual = {"count": 0}
    daemon.move_to_manual_review = lambda *_args, **_kwargs: moved_manual.__setitem__("count", moved_manual["count"] + 1)

    result = daemon.process_paper(pdf_path)

    assert result is None
    assert moved_manual["count"] == 1


def test_process_paper_restart_from_zotero_selection_returns_restart(
    daemon: PaperProcessorDaemon,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pdf_path = tmp_path / "EN_20260331_0003_double.pdf"
    _write_dummy_pdf(pdf_path)

    daemon._close_sumatra_all_tabs = lambda: True
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True
    daemon._return_focus_to_terminal = lambda: None
    daemon._close_pdf_viewer = lambda: None
    daemon.move_to_failed = lambda *_args, **_kwargs: None
    daemon.display_metadata = lambda *_args, **_kwargs: None
    daemon._handle_isbn_lookup_result = lambda result: result
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: "")

    daemon.metadata_processor = SimpleNamespace(
        process_pdf=lambda *_args, **_kwargs: {
            "success": True,
            "metadata": {
                "title": "A title",
                "authors": ["Bean", "Papadakis"],
                "year": "1994",
                "document_type": "journal_article",
            },
            "method": "grep",
            "identifiers_found": {},
        }
    )
    daemon.prompt_for_year = lambda metadata, force_prompt=False: {**metadata, "_year_confirmed": True}
    daemon.prompt_for_document_type = lambda metadata: metadata
    daemon.service_manager = SimpleNamespace(ensure_grobid_ready=lambda: False, grobid_ready=False, grobid_client=None)
    daemon.local_zotero = object()

    daemon.search_and_display_local_zotero = lambda *_args, **_kwargs: ("restart", None, {"title": "A title"})

    result = daemon.process_paper(pdf_path)

    assert result == "RESTART"


def test_close_pdf_viewer_calls_close_sumatra_all_tabs_on_windows(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def _close_all() -> bool:
        calls.append(True)
        return True

    monkeypatch.setattr(daemon, "_close_sumatra_all_tabs", _close_all)
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    daemon._close_pdf_viewer()
    assert calls == [True]


def test_close_pdf_viewer_attempts_sumatra_on_non_windows(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[bool] = []

    def _close_all() -> bool:
        calls.append(True)
        return True

    monkeypatch.setattr(daemon, "_close_sumatra_all_tabs", _close_all)
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "linux")
    daemon._close_pdf_viewer()
    assert calls == [True]


def test_close_sumatra_all_tabs_sends_cmd_close_all_tabs(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, object]] = []

    def _send(cmd: str, path) -> bool:
        sent.append((cmd, path))
        return True

    monkeypatch.setattr(daemon, "_send_sumatra_command", _send)
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    assert daemon._close_sumatra_all_tabs() is True
    assert sent == [("CmdCloseAllTabs", None)]


def test_close_sumatra_all_tabs_attempts_off_windows(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[tuple[str, object]] = []

    def _send(cmd: str, path) -> bool:
        sent.append((cmd, path))
        return False

    monkeypatch.setattr(daemon, "_send_sumatra_command", _send)
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "darwin")
    assert daemon._close_sumatra_all_tabs() is False
    assert sent == [("CmdCloseAllTabs", None)]


def test_preview_loop_dedupes_same_processed_pdf_open(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_pdf = tmp_path / "orig.pdf"
    processed_pdf = tmp_path / "processed.pdf"
    _write_dummy_pdf(original_pdf)
    _write_dummy_pdf(processed_pdf)

    open_calls: list[Path] = []
    daemon._open_pdf_in_viewer = lambda p: (open_calls.append(Path(p)) or True)
    daemon._preprocess_pdf_with_options = lambda *_args, **_kwargs: (
        processed_pdf,
        {
            "border_removal": False,
            "split_method": "none",
            "split_attempted": False,
            "split_succeeded": False,
            "trim_leading": True,
        },
    )

    answers = iter(["2", "1"])
    monkeypatch.setattr("builtins.input", lambda *_args, **_kwargs: next(answers))

    final_pdf, _state = daemon._preview_and_modify_preprocessing(
        original_pdf,
        processed_pdf,
        {
            "border_removal": False,
            "split_method": "none",
            "split_attempted": False,
            "split_succeeded": False,
            "trim_leading": False,
        },
    )

    assert final_pdf == processed_pdf
    assert open_calls == [processed_pdf]

