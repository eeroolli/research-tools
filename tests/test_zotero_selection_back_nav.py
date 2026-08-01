#!/usr/bin/env python3
"""Tests for Zotero selection loop back vs back_to_authors semantics."""
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
requests_mod.Session = lambda: SimpleNamespace(
    headers={}, get=lambda *a, **k: SimpleNamespace(status_code=404, json=lambda: {})
)
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


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(parents=True, exist_ok=True)
    d = PaperProcessorDaemon(watch_dir, debug=False)
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(parents=True, exist_ok=True)
    return d


def test_back_exits_loop_without_retrying_search(daemon: PaperProcessorDaemon) -> None:
    """Author-select back must leave the loop (not re-call search)."""
    calls = []

    def fake_search(metadata, force_prompt_year=False):
        calls.append({"force_prompt_year": force_prompt_year, "authors": list(metadata.get("authors") or [])})
        return ("back", None, metadata)

    daemon.search_and_display_local_zotero = fake_search

    action, item, meta = daemon._run_zotero_selection_loop(
        {"authors": ["Per Selle"], "year": "2001", "_year_confirmed": True},
        Path("scan.pdf"),
    )

    assert action == "back"
    assert item is None
    assert len(calls) == 1


def test_back_to_authors_retries_search_once(daemon: PaperProcessorDaemon) -> None:
    """Matches/no-match z re-enters author selection without leaving the loop."""
    calls = []

    def fake_search(metadata, force_prompt_year=False):
        calls.append(
            {
                "force_prompt_year": force_prompt_year,
                "authors": list(metadata.get("authors") or []),
            }
        )
        if len(calls) == 1:
            # Simulate user narrowing authors then backing from results
            metadata = dict(metadata)
            metadata["authors"] = ["Per Selle"]
            return ("back_to_authors", None, metadata)
        return ("select", {"key": "K1", "title": "T"}, metadata)

    daemon.search_and_display_local_zotero = fake_search

    start = {
        "authors": ["Per Selle"],
        "year": "2001",
        "_year_confirmed": True,
        "_all_authors": ["Per Selle", "Kristin Strømsnes"],
    }
    action, item, meta = daemon._run_zotero_selection_loop(start, Path("scan.pdf"))

    assert action == "select"
    assert item["key"] == "K1"
    assert len(calls) == 2
    # After back_to_authors, authors restored from _all_authors
    assert calls[1]["authors"] == ["Per Selle", "Kristin Strømsnes"]
    assert meta["authors"] == ["Per Selle", "Kristin Strømsnes"]


def test_force_prompt_year_only_on_first_entry(daemon: PaperProcessorDaemon) -> None:
    """force_prompt_year applies once; back_to_authors retry does not keep forcing."""
    calls = []

    def fake_search(metadata, force_prompt_year=False):
        calls.append(force_prompt_year)
        if len(calls) == 1:
            return ("back_to_authors", None, metadata)
        return ("create", None, metadata)

    daemon.search_and_display_local_zotero = fake_search

    action, _, _ = daemon._run_zotero_selection_loop(
        {"authors": ["A"], "_year_confirmed": True, "_all_authors": ["A"]},
        Path("scan.pdf"),
        force_prompt_year=True,
    )

    assert action == "create"
    assert calls == [True, False]


def test_pdf_preview_back_page_is_proposed_actions() -> None:
    from handle_item_selected_pages import create_pdf_preview_page

    daemon = SimpleNamespace(prompt_timeout=5)
    page = create_pdf_preview_page(daemon)
    assert page.back_page == "proposed_actions"
