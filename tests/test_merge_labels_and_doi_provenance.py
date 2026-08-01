"""Tests for merge labels, document_type equivalence, and DOI provenance."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Stub optional deps like other daemon unit tests
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

from shared_tools.metadata.doi_provenance import (  # noqa: E402
    is_trusted_doi,
    mark_doi_source,
)
from scripts.paper_processor_daemon import PaperProcessorDaemon  # noqa: E402


def test_is_trusted_doi_online_and_zotero():
    assert is_trusted_doi({"doi": "10.1/x", "doi_source": "online"})
    assert is_trusted_doi({"doi": "10.1/x", "doi_source": "zotero"})
    assert not is_trusted_doi({"doi": "10.1/x", "doi_source": "grobid"})
    assert not is_trusted_doi({"doi": "10.1/x"})
    assert not is_trusted_doi({"doi_source": "online"})
    assert not is_trusted_doi({})


def test_mark_doi_source():
    meta = {"doi": "10.1/x"}
    mark_doi_source(meta, "online")
    assert meta["doi_source"] == "online"
    empty = {"title": "t"}
    mark_doi_source(empty, "online")
    assert "doi_source" not in empty


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "papers"
    watch_dir.mkdir()
    return PaperProcessorDaemon(watch_dir, debug=False)


def test_merge_equivalent_document_types_no_prompt(
    daemon: PaperProcessorDaemon, capsys: pytest.CaptureFixture[str]
) -> None:
    left = {"document_type": "journal_article", "title": "Paper"}
    right = {"document_type": "journalArticle", "title": "Paper"}
    merged = daemon._merge_metadata_sources(
        left, right, left_label="Manual/Extracted", right_label="Online"
    )
    assert merged["document_type"] == "journalArticle"
    out = capsys.readouterr().out
    assert "sources agree" in out
    assert "Document_Type:" not in out


def test_merge_uses_caller_labels_on_conflict(
    daemon: PaperProcessorDaemon,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    left = {"title": "A", "year": "1997"}
    right = {"title": "B", "year": "1997"}
    monkeypatch.setattr("builtins.input", lambda *a, **k: "o")
    merged = daemon._merge_metadata_sources(
        left, right, left_label="Manual/Extracted", right_label="Online"
    )
    assert merged["title"] == "B"
    out = capsys.readouterr().out
    assert "Manual/Extracted:" in out
    assert "Online:" in out
    assert "Zotero:" not in out


def test_merge_real_document_type_conflict_prompts(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    left = {"document_type": "journal_article"}
    right = {"document_type": "conference_paper"}
    monkeypatch.setattr("builtins.input", lambda *a, **k: "m")
    merged = daemon._merge_metadata_sources(
        left, right, left_label="Manual/Extracted", right_label="Online"
    )
    assert merged["document_type"] == "journal_article"


def test_search_online_uses_trusted_doi_not_grobid(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def fake_search_by_doi(doi: str):
        calls.append(doi)
        return {
            "success": True,
            "metadata": {
                "title": "From DOI",
                "doi": doi,
                "source": "crossref",
                "doi_source": "online",
            },
        }

    daemon.metadata_processor = SimpleNamespace(search_by_doi=fake_search_by_doi)
    monkeypatch.setattr("builtins.input", lambda *a, **k: "1")

    trusted = {
        "title": "T",
        "authors": ["A"],
        "document_type": "journal_article",
        "doi": "10.1/trusted",
        "doi_source": "online",
    }
    result = daemon.search_online_libraries(trusted)
    assert calls == ["10.1/trusted"]
    assert result and result.get("title") == "From DOI"

    calls.clear()
    grobid = {
        "title": "T",
        "authors": ["A"],
        "document_type": "journal_article",
        "doi": "10.1/grobid",
        "doi_source": "grobid",
    }

    # Force CrossRef path to no-op so we only assert DOI lookup was skipped
    class _CR:
        def search_by_metadata(self, **kwargs):
            return []

    daemon.metadata_processor = SimpleNamespace(
        search_by_doi=fake_search_by_doi,
        crossref=_CR(),
        arxiv=SimpleNamespace(search_by_metadata=lambda **k: []),
    )
    daemon.search_online_libraries(grobid)
    assert calls == []
