#!/usr/bin/env python3
from __future__ import annotations

import builtins
import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Import-time dependency stubs (match other daemon tests)
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


def test_review_search_params_free_text_does_not_use_timeout_input(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Free-text editing must not route through _input_with_timeout()."""

    def _guarded_timeout(prompt: str, *args, **kwargs):
        if prompt.startswith("Author(s) (comma-separated)") or prompt.startswith("Year [") or prompt.startswith("Title [") or prompt.startswith("Journal ["):
            raise AssertionError(f"Free-text prompt unexpectedly used _input_with_timeout: {prompt}")
        # Menu navigation inputs: enter edit, choose field 2, done, accept search.
        return next(menu_answers)

    menu_answers = iter(["e", "2", "", ""])
    monkeypatch.setattr(daemon, "_input_with_timeout", _guarded_timeout)

    # Free-text typed entry for year prompt.
    input_answers = iter(["2004"])
    monkeypatch.setattr(builtins, "input", lambda *_args, **_kwargs: next(input_answers))

    title, authors, year_str, journal, skip_search, go_back = daemon.review_search_params(
        "Some Title",
        ["Alice Author"],
        "1954",
        None,
    )

    assert year_str == "2004"
    assert skip_search is False
    assert go_back is False

