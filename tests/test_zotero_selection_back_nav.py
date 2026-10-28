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

    def fake_search(metadata, force_prompt_year=False, skip_author_select=False):
        calls.append(
            {
                "force_prompt_year": force_prompt_year,
                "skip_author_select": skip_author_select,
                "authors": list(metadata.get("authors") or []),
            }
        )
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

    def fake_search(metadata, force_prompt_year=False, skip_author_select=False):
        calls.append(
            {
                "force_prompt_year": force_prompt_year,
                "skip_author_select": skip_author_select,
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

    def fake_search(metadata, force_prompt_year=False, skip_author_select=False):
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


def test_skip_author_select_only_on_first_entry(daemon: PaperProcessorDaemon) -> None:
    """skip_author_select applies once; back_to_authors opens the author picker again."""
    calls = []

    def fake_search(metadata, force_prompt_year=False, skip_author_select=False):
        calls.append(
            {
                "force_prompt_year": force_prompt_year,
                "skip_author_select": skip_author_select,
                "authors": list(metadata.get("authors") or []),
                "title": metadata.get("title"),
            }
        )
        if len(calls) == 1:
            return ("back_to_authors", None, metadata)
        return ("create", None, metadata)

    daemon.search_and_display_local_zotero = fake_search

    start = {
        "authors": ["John Stuart Mill"],
        "year": "1974",
        "title": "A System of Logic",
        "_year_confirmed": True,
        "_all_authors": ["Grade Working Group for The", "Sir James", "John Stuart Mill"],
    }
    action, _, meta = daemon._run_zotero_selection_loop(
        start,
        Path("scan.pdf"),
        skip_author_select=True,
    )

    assert action == "create"
    assert calls[0]["skip_author_select"] is True
    assert calls[0]["authors"] == ["John Stuart Mill"]
    assert calls[0]["title"] == "A System of Logic"
    assert calls[1]["skip_author_select"] is False
    assert calls[1]["authors"] == [
        "Grade Working Group for The",
        "Sir James",
        "John Stuart Mill",
    ]
    assert meta["title"] == "A System of Logic"


def test_search_action_keeps_selected_authors_not_all_authors(
    daemon: PaperProcessorDaemon,
) -> None:
    """Match-menu [a] must not restore OCR junk from _all_authors."""
    pdf_path = Path("scan.pdf")
    selected = {
        "authors": ["John Stuart Mill"],
        "year": "1974",
        "_year_confirmed": True,
        "_all_authors": ["Grade Working Group for The", "Sir James", "John Stuart Mill"],
        "document_type": "book",
        "title": "",
    }
    search_calls = []

    def fake_search(metadata, force_prompt_year=False, skip_author_select=False):
        search_calls.append(
            {
                "force_prompt_year": force_prompt_year,
                "skip_author_select": skip_author_select,
                "authors": list(metadata.get("authors") or []),
            }
        )
        if len(search_calls) == 1:
            return ("search", None, metadata)
        return ("create", None, metadata)

    daemon.search_and_display_local_zotero = fake_search

    updated = dict(selected)
    action, item, updated = daemon._run_zotero_selection_loop(updated, pdf_path)
    assert action == "search"
    assert updated["authors"] == ["John Stuart Mill"]

    # Mimic flattened [a] handler: keep authors, force year on next loop
    if updated.get("_year_confirmed"):
        updated.pop("_year_confirmed", None)
    action2, _, updated = daemon._run_zotero_selection_loop(
        updated, pdf_path, force_prompt_year=True
    )
    assert action2 == "create"
    assert search_calls[1]["force_prompt_year"] is True
    assert search_calls[1]["authors"] == ["John Stuart Mill"]
    assert "Grade Working Group for The" not in search_calls[1]["authors"]


def test_skip_author_select_runs_title_metadata_search(
    daemon: PaperProcessorDaemon,
) -> None:
    """After [b], skip author picker and prepend search_by_metadata title hits."""
    select_calls = []
    metadata_search_calls = []
    ordered_search_calls = []

    title_hit = {
        "item_key": "TITLE1",
        "title": "A System of Logic",
        "authors": ["John Stuart Mill"],
        "year": "1973",
        "similarity": 95.0,
    }
    author_hit = {
        "key": "AUTH1",
        "title": "On liberty",
        "creators": [{"creatorType": "author", "firstName": "John Stuart", "lastName": "Mill"}],
        "year": "1974",
        "hasAttachment": False,
        "order_score": 100,
    }

    class FakeZotero:
        def search_by_metadata(self, metadata, max_matches=10):
            metadata_search_calls.append(dict(metadata))
            return [title_hit]

        def search_by_authors_ordered(self, *args, **kwargs):
            ordered_search_calls.append({"args": args, "kwargs": kwargs})
            return [author_hit]

        def search_by_author(self, *args, **kwargs):
            return []

    daemon.local_zotero = FakeZotero()
    daemon.author_validator = None
    daemon.select_authors_for_search = lambda authors: select_calls.append(list(authors)) or authors
    daemon.prompt_for_year = lambda metadata, force_prompt=False, allow_back=False: metadata
    displayed = []

    def fake_display(matches, search_info=""):
        displayed.append({"matches": matches, "search_info": search_info})
        return ("select", matches[0])

    daemon.display_and_select_zotero_matches = fake_display

    meta = {
        "authors": ["John Stuart Mill"],
        "year": "1974",
        "title": "A System of Logic",
        "document_type": "book",
        "_year_confirmed": True,
        "_all_authors": ["John Stuart Mill"],
    }
    action, item, updated = daemon.search_and_display_local_zotero(
        meta, skip_author_select=True
    )

    assert select_calls == []  # author picker skipped
    assert len(metadata_search_calls) == 1
    assert metadata_search_calls[0]["title"] == "A System of Logic"
    assert len(ordered_search_calls) == 1
    assert action == "select"
    assert item.get("key") == "TITLE1" or item.get("item_key") == "TITLE1"
    assert displayed[0]["matches"][0].get("title") == "A System of Logic"
    assert 'title: "A System of Logic"' in displayed[0]["search_info"] or "A System of Logic" in displayed[0]["search_info"]
    assert updated["title"] == "A System of Logic"


def test_pdf_preview_back_page_is_proposed_actions() -> None:
    from handle_item_selected_pages import create_pdf_preview_page

    daemon = SimpleNamespace(prompt_timeout=5)
    page = create_pdf_preview_page(daemon)
    assert page.back_page == "proposed_actions"
