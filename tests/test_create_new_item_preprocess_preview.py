#!/usr/bin/env python3
from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# PaperProcessorDaemon imports watchdog at module import time.
# In minimal test environments, watchdog may be unavailable, so we stub it.
import types

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

# paper_processor_daemon imports multiple API and PDF-processing modules at import time.
# In this sandbox, some optional dependencies may be missing; stub them so the unit
# test can focus on the create-new flow orchestration logic.

requests_mod = types.ModuleType("requests")


class _DummySession:
    def __init__(self) -> None:
        self.headers = {}

    def get(self, *args, **kwargs):
        return SimpleNamespace(status_code=404, json=lambda: {})

requests_mod.get = lambda *args, **kwargs: SimpleNamespace(status_code=404, json=lambda: {})
requests_mod.ConnectionError = Exception
requests_mod.Timeout = TimeoutError
requests_mod.RequestException = Exception


requests_mod.Session = _DummySession
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
    """Write a tiny PDF file so path.exists() checks pass."""
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


def test_create_new_item_uses_preprocessed_pdf_for_attachment(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "EN_20260101-120000_001_double.pdf"
    _write_dummy_pdf(pdf_path)

    processed_pdf = tmp_path / "PREPROCESSED_dummy_split.pdf"
    _write_dummy_pdf(processed_pdf)

    final_pdf = tmp_path / "FINAL_dummy_split.pdf"
    _write_dummy_pdf(final_pdf)

    processed_calls: list[tuple[Path, Path]] = []
    copy_calls: list[tuple[Path, Path]] = []
    find_identical_calls: list[Path] = []
    add_paper_calls: list[tuple[dict, str | None]] = []
    log_calls: list[dict] = []

    # --- Stubs for UI / external systems ---
    daemon.quick_manual_entry = lambda extracted: extracted
    daemon.search_online_libraries = lambda _meta, pdf_path=None: None
    daemon.edit_tags_interactively = lambda current_tags=None, online_tags=None: list(current_tags or [])
    daemon._detect_language_from_filename = lambda _p: None
    daemon._prompt_for_note = lambda _item_key: True
    daemon.move_to_done = lambda _p: None

    # _input_with_timeout is used when online_metadata is None.
    daemon._input_with_timeout = lambda *_args, **_kwargs: "y"

    # builtins.input is used for:
    # 1) "Search online libraries? [Y/n]"
    # 2) "Attach this PDF now? [Y/n]"
    # 3) "Use this filename? [Y/n]"
    input_answers = iter(["n", "y", "y"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(input_answers))

    # Generate a deterministic filename (without extension; code appends ".pdf")
    daemon.generate_filename = lambda _meta: "Test_File"

    # Preprocessing/preview pipeline: we want to verify its return value is used for copy + attach.
    daemon._preprocess_pdf_with_options = lambda *_args, **_kwargs: (
        processed_pdf,
        {
            "border_removal": False,
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": True,
        },
    )

    daemon._preview_and_modify_preprocessing = lambda *_args, **_kwargs: (
        final_pdf,
        {
            "border_removal": False,
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": True,
        },
    )

    daemon._find_identical_in_publications = lambda candidate_pdf: (
        find_identical_calls.append(candidate_pdf) or None
    )

    def _copy_stub(source_path: Path, target_path: Path, replace_existing: bool = False):
        copy_calls.append((source_path, target_path))
        _write_dummy_pdf(target_path)
        return (True, None)

    daemon._copy_file_universal = _copy_stub
    daemon._to_windows_path = lambda p: str(p)

    def _add_paper_stub(final_metadata: dict, attach_target: str | None):
        add_paper_calls.append((final_metadata, attach_target))
        return {"success": True, "item_key": "KEY1", "action": "added_with_pdf"}

    daemon.zotero_processor = SimpleNamespace(add_paper=_add_paper_stub)
    daemon.scanned_papers_logger = SimpleNamespace(
        log_processing=lambda **kwargs: log_calls.append(kwargs)
    )

    extracted_metadata = {
        "title": "A Title",
        "authors": ["Doe, John"],
        "year": "2004",
        "document_type": "journal_article",
        "tags": [],
    }

    ok = daemon.handle_create_new_item(pdf_path, extracted_metadata)
    assert ok is True

    # Reuse check must use the accepted final_pdf.
    assert find_identical_calls == [final_pdf]

    # Copy must use the accepted final_pdf as the source.
    assert copy_calls, "Expected a copy call to happen"
    assert copy_calls[0][0] == final_pdf

    # Zotero attachment should get a target path from the copy step.
    assert add_paper_calls
    _, attach_target = add_paper_calls[0]
    assert attach_target is not None
    assert attach_target.endswith("Test_File.pdf")

    # Logging must reflect preprocessing decisions derived from final_state.
    assert log_calls, "Expected scanned_papers_logger.log_processing to be called"
    logged = log_calls[0]
    assert logged["final_filename"] == "Test_File.pdf"
    assert logged["split"] == "yes"
    assert logged["borders"] == "no"
    assert logged["trim"] == "yes"


def test_create_new_item_shows_preprocessing_preview_menu_on_accept(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    pdf_path = tmp_path / "EN_20260101-120000_002_double.pdf"
    _write_dummy_pdf(pdf_path)

    processed_pdf = tmp_path / "PREPROCESSED_dummy_split.pdf"
    _write_dummy_pdf(processed_pdf)

    daemon.quick_manual_entry = lambda extracted: extracted
    daemon.search_online_libraries = lambda _meta, pdf_path=None: None
    daemon.edit_tags_interactively = lambda current_tags=None, online_tags=None: list(current_tags or [])
    daemon._detect_language_from_filename = lambda _p: None
    daemon._prompt_for_note = lambda _item_key: True
    daemon.move_to_done = lambda _p: None

    daemon._input_with_timeout = lambda *_args, **_kwargs: "y"

    # Answers:
    # 1) Search online libraries? -> 'n'
    # 2) Attach this PDF now? -> 'y'
    # 3) Use this filename? -> 'y'
    # 4) PDF PREVIEW menu choice -> '1' (accept)
    input_answers = iter(["n", "y", "y", "1"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(input_answers))

    daemon.generate_filename = lambda _meta: "Test_File"

    # Let the real `_preview_and_modify_preprocessing` run, but avoid opening a viewer.
    daemon._open_pdf_in_viewer = lambda *_args, **_kwargs: True

    daemon._preprocess_pdf_with_options = lambda *_args, **_kwargs: (
        processed_pdf,
        {
            "border_removal": False,
            "split_method": "50-50",
            "split_attempted": True,
            "split_succeeded": True,
            "trim_leading": True,
        },
    )

    daemon._find_identical_in_publications = lambda _candidate_pdf: None

    def _copy_stub(source_path: Path, target_path: Path, replace_existing: bool = False):
        _write_dummy_pdf(target_path)
        return (True, None)

    daemon._copy_file_universal = _copy_stub
    daemon._to_windows_path = lambda p: str(p)

    daemon.zotero_processor = SimpleNamespace(
        add_paper=lambda _meta, _attach_target: {"success": True, "item_key": "KEY1", "action": "added_with_pdf"}
    )
    daemon.scanned_papers_logger = SimpleNamespace(
        log_processing=lambda **_kwargs: None
    )

    extracted_metadata = {
        "title": "A Title",
        "authors": ["Doe, John"],
        "year": "2004",
        "document_type": "journal_article",
        "tags": [],
    }

    ok = daemon.handle_create_new_item(pdf_path, extracted_metadata)
    assert ok is True

    captured = capsys.readouterr()
    # The actual preview loop prints this header; we assert we reached it.
    assert "PDF PREVIEW" in captured.out


def test_search_skips_broad_surname_fallback_when_author_confirmed(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    broad_search_calls = {"count": 0}

    class _LocalZoteroStub:
        def search_by_authors_ordered(self, *args, **kwargs):
            return []

        def search_by_author(self, *args, **kwargs):
            broad_search_calls["count"] += 1
            return [{"title": "Wrong Christie Match"}]

        def search_by_metadata(self, *args, **kwargs):
            return []

    class _AuthorValidatorStub:
        def get_author_info(self, author_name):
            if author_name == "Nils Christie":
                return {"name": "Nils Christie", "paper_count": 0}
            return None

    daemon.local_zotero = _LocalZoteroStub()
    daemon.author_validator = _AuthorValidatorStub()
    daemon.prompt_for_year = lambda metadata, force_prompt=False: metadata
    daemon.select_authors_for_search = lambda authors: authors

    # Final "no matches" options in search_and_display_local_zotero
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: "2")

    action, item, _updated = daemon.search_and_display_local_zotero(
        {
            "title": "Tolv råd om skriving",
            "authors": ["Nils Christie"],
            "year": "1983",
            "document_type": "journal_article",
        }
    )

    assert action == "create"
    assert item is None
    assert broad_search_calls["count"] == 0


def test_create_new_item_handles_unexpected_add_paper_result(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "EN_20260101-120000_003_double.pdf"
    _write_dummy_pdf(pdf_path)

    daemon.quick_manual_entry = lambda extracted: extracted
    daemon.search_online_libraries = lambda _meta, pdf_path=None: None
    daemon.edit_tags_interactively = lambda current_tags=None, online_tags=None: list(current_tags or [])
    daemon._input_with_timeout = lambda *_args, **_kwargs: "y"
    daemon.move_to_done = lambda _p: None

    # 1) Search online libraries? [Y/n] -> n
    # 2) Attach this PDF now? [Y/n] -> n
    answers = iter(["n", "n"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(answers))

    # Simulate malformed processor contract that previously could crash downstream code.
    daemon.zotero_processor = SimpleNamespace(add_paper=lambda _meta, _attach: None)

    ok = daemon.handle_create_new_item(
        pdf_path,
        {
            "title": "A Title",
            "authors": ["Doe, Jane"],
            "year": "2004",
            "document_type": "journal_article",
            "tags": [],
        },
    )
    assert ok is False


def test_search_online_libraries_all_wrong_returns_none(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _CrossRefStub:
        def search_by_metadata(self, **_kwargs):
            return [
                {
                    "title": "Unrelated result",
                    "authors": ["Wrong, Author"],
                    "year": "2016",
                    "journal": "Wrong Journal",
                    "tags": ["wrong"],
                }
            ]

    daemon.metadata_processor = SimpleNamespace(
        crossref=_CrossRefStub(),
        arxiv=SimpleNamespace(search_by_metadata=lambda **_kwargs: []),
    )
    daemon.enrichment_workflow = SimpleNamespace(
        choose_best=lambda _metadata, candidates: (
            (candidates[0] if candidates else None),
            {"status": "manual_review", "reason": "weak_composite"},
        ),
        plan_updates=lambda *_args, **_kwargs: {},
    )

    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: "w")

    result = daemon.search_online_libraries(
        {
            "title": "Sensitive Questions in Online Surveys",
            "authors": ["Marc Höglinger"],
            "year": "2016",
            "document_type": "journal_article",
        }
    )
    assert result is None


def test_create_new_item_all_wrong_online_results_do_not_leak_online_tags(
    daemon: PaperProcessorDaemon, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pdf_path = tmp_path / "EN_20260101-120000_004_double.pdf"
    _write_dummy_pdf(pdf_path)

    class _CrossRefStub:
        def search_by_metadata(self, **_kwargs):
            return [
                {
                    "title": "Unrelated result",
                    "authors": ["Wrong, Author"],
                    "year": "2016",
                    "journal": "Wrong Journal",
                    "tags": ["should-not-leak"],
                }
            ]

    daemon.metadata_processor = SimpleNamespace(
        crossref=_CrossRefStub(),
        arxiv=SimpleNamespace(search_by_metadata=lambda **_kwargs: []),
    )
    daemon.enrichment_workflow = SimpleNamespace(
        choose_best=lambda _metadata, candidates: (
            (candidates[0] if candidates else None),
            {"status": "manual_review", "reason": "weak_composite"},
        ),
        plan_updates=lambda *_args, **_kwargs: {},
    )

    daemon.quick_manual_entry = lambda extracted: extracted
    daemon._input_with_timeout = lambda *_args, **_kwargs: "y"
    daemon.move_to_done = lambda _p: None
    daemon._prompt_for_note = lambda _item_key: True
    daemon.generate_filename = lambda _meta: "Test_File"

    observed_online_tags: list[list[str]] = []

    def _edit_tags_stub(current_tags=None, online_tags=None):
        observed_online_tags.append(list(online_tags or []))
        return list(current_tags or [])

    daemon.edit_tags_interactively = _edit_tags_stub
    daemon.zotero_processor = SimpleNamespace(
        add_paper=lambda _meta, _attach: {"success": True, "item_key": "KEY1", "action": "added_without_pdf"}
    )
    daemon.scanned_papers_logger = SimpleNamespace(log_processing=lambda **_kwargs: None)

    # Inputs:
    # 1) Search online libraries? [Y/n] -> y
    # 2) online result selection -> w (all wrong)
    # 3) Attach this PDF now? [Y/n] -> n
    answers = iter(["y", "w", "n"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(answers))

    ok = daemon.handle_create_new_item(
        pdf_path,
        {
            "title": "Sensitive Questions in Online Surveys",
            "authors": ["Marc Höglinger"],
            "year": "2016",
            "document_type": "journal_article",
            "tags": [],
        },
    )

    assert ok is True
    assert observed_online_tags, "Tag editor should have been invoked"
    assert observed_online_tags[0] == []


def test_search_online_libraries_all_wrong_does_not_block_future_research(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    class _CrossRefStub:
        def search_by_metadata(self, title=None, **_kwargs):
            if title == "Initial wrong query":
                return [{"title": "Wrong match", "authors": ["Wrong, Author"], "year": "2016"}]
            return [{"title": "Corrected match", "authors": ["Christtie, Noel"], "year": "2017"}]

    daemon.metadata_processor = SimpleNamespace(
        crossref=_CrossRefStub(),
        arxiv=SimpleNamespace(search_by_metadata=lambda **_kwargs: []),
    )
    daemon.enrichment_workflow = SimpleNamespace(
        choose_best=lambda _metadata, candidates: (
            (candidates[0] if candidates else None),
            {"status": "manual_review", "reason": "weak_composite"},
        ),
        plan_updates=lambda *_args, **_kwargs: {},
    )

    answers = iter(["w", "1"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(answers))

    first = daemon.search_online_libraries(
        {
            "title": "Initial wrong query",
            "authors": ["Noel Chrisitie"],
            "year": "2016",
            "document_type": "journal_article",
        }
    )
    second = daemon.search_online_libraries(
        {
            "title": "Corrected query",
            "authors": ["Noel Christtie"],
            "year": "2017",
            "document_type": "journal_article",
        }
    )

    assert first is None
    assert second is not None
    assert second.get("title") == "Corrected match"
