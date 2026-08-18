"""Tests for convert_zotero_item_to_metadata key mapping."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

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

from scripts.paper_processor_daemon import PaperProcessorDaemon  # noqa: E402


def _convert(item: dict) -> dict:
    daemon = object.__new__(PaperProcessorDaemon)
    return daemon.convert_zotero_item_to_metadata(item)


def test_convert_maps_fuzzy_search_keys_and_volume_issue_pages():
    item = {
        "title": "Grid-Group Analysis, Social Capital and Entrepreneurship among North American Immigrant Groups",
        "year": "2002",
        "item_type": "journalArticle",
        "item_key": "ABC123",
        "doi": "10.1177/1069397102036001003",
        "abstract": "Social Capital = High Group",
        "journal": "Cross-Cultural Research",
        "volume": "36",
        "issue": "1",
        "pages": "48-72",
        "creators": [
            {"creatorType": "author", "firstName": "D. Douglas", "lastName": "Caulkins"},
            {"creatorType": "author", "firstName": "Christina", "lastName": "Peters"},
        ],
    }
    meta = _convert(item)
    assert meta["doi"] == "10.1177/1069397102036001003"
    assert meta["abstract"] == "Social Capital = High Group"
    assert meta["document_type"] == "journalArticle"
    assert meta["zotero_key"] == "ABC123"
    assert meta["volume"] == "36"
    assert meta["issue"] == "1"
    assert meta["pages"] == "48-72"
    assert meta["journal"] == "Cross-Cultural Research"
    assert meta["authors"] == ["Caulkins, D. Douglas", "Peters, Christina"]


def test_convert_maps_zotero_canonical_keys():
    item = {
        "title": "Paper",
        "year": "2002",
        "itemType": "journalArticle",
        "key": "K1",
        "DOI": "10.1/x",
        "abstractNote": "Abs",
        "ISSN": "1069-3971",
        "publicationTitle": "Cross-Cultural Research",
        "ISBN": "978-0-00-000000-0",
        "language": "en",
        "creators": [],
    }
    meta = _convert(item)
    assert meta["doi"] == "10.1/x"
    assert meta["abstract"] == "Abs"
    assert meta["issn"] == "1069-3971"
    assert meta["isbn"] == "978-0-00-000000-0"
    assert meta["language"] == "en"
    assert meta["journal"] == "Cross-Cultural Research"
    assert meta["document_type"] == "journalArticle"
    assert meta["zotero_key"] == "K1"
