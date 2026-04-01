#!/usr/bin/env python3
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace

import pytest
import builtins

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))
sys.path.insert(0, str(project_root / "scripts"))

# Import-time dependency stubs
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
try:
    import importlib.util as _importlib_util

    if _importlib_util.find_spec("fitz") is None:
        sys.modules.setdefault("fitz", types.ModuleType("fitz"))
except ImportError:
    # Extremely minimal Python env; fall back to stubbing.
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

from shared_tools.ui.user_feedback import UNACCEPTABLE_INPUT_MESSAGE

from scripts.paper_processor_daemon import PaperProcessorDaemon
from scripts.paper_processor_daemon import PaperFileHandler


@pytest.fixture
def daemon(tmp_path: Path) -> PaperProcessorDaemon:
    watch_dir = tmp_path / "watch"
    watch_dir.mkdir(parents=True, exist_ok=True)
    d = PaperProcessorDaemon(watch_dir, debug=False)
    d.publications_dir = tmp_path / "publications"
    d.publications_dir.mkdir(parents=True, exist_ok=True)
    return d


def test_run_processing_loop_restarts_current_file_before_next(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    path1 = Path("EN_20260324_0001_double.pdf")
    path2 = Path("EN_20260324_0002_double.pdf")

    queue_items = iter([path1, path2])

    class _StopLoop(Exception):
        pass

    def _queue_get():
        try:
            return next(queue_items)
        except StopIteration:
            raise _StopLoop()

    calls: list[Path] = []
    state = {"path1_count": 0}

    def _process_paper(path: Path):
        calls.append(path)
        if path == path1:
            state["path1_count"] += 1
            if state["path1_count"] == 1:
                return "RESTART"
        return None

    monkeypatch.setattr(daemon._paper_queue, "get", _queue_get)
    monkeypatch.setattr(daemon, "process_paper", _process_paper)

    with pytest.raises(_StopLoop):
        daemon._run_processing_loop()

    assert calls == [path1, path1, path2]


def test_review_search_params_supports_z_back(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(daemon, "_input_with_timeout", lambda *_args, **_kwargs: "z")
    title, authors, year_str, journal, skip_search, go_back = daemon.review_search_params(
        "Some Title",
        ["Alice Author"],
        "1994",
        "Some Journal",
    )

    assert title == "Some Title"
    assert authors == ["Alice Author"]
    assert year_str == "1994"
    assert journal == "Some Journal"
    assert skip_search is False
    assert go_back is True


def test_review_search_params_unknown_field_choice_shows_feedback_and_keeps_year(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Typing a year at the field menu (e.g. 2004) is not a field key; year must stay unchanged."""
    answers = iter(["e", "2004", "", ""])

    def _fake_input(*_args, **_kwargs):
        return next(answers)

    monkeypatch.setattr(daemon, "_input_with_timeout", _fake_input)
    title, authors, year_str, journal, skip_search, go_back = daemon.review_search_params(
        "Some Title",
        ["Alice Author"],
        "1954",
        None,
    )

    assert year_str == "1954"
    assert skip_search is False
    assert go_back is False
    out = capsys.readouterr().out
    assert UNACCEPTABLE_INPUT_MESSAGE in out
    assert "Tip: To change the year" in out


def test_review_search_params_field_2_updates_year(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch
) -> None:
    answers = iter(["e", "2", "", ""])

    def _fake_input(*_args, **_kwargs):
        return next(answers)

    monkeypatch.setattr(daemon, "_input_with_timeout", _fake_input)
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


def test_file_handler_defers_queue_notice_during_active_processing(
    daemon: PaperProcessorDaemon, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    queued: list[Path] = []
    logged: list[str] = []

    event_pdf = tmp_path / "EN_20260324_0009_double.pdf"
    event_pdf.write_text("placeholder")

    monkeypatch.setattr("scripts.paper_processor_daemon.time.sleep", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(daemon, "should_process", lambda _name: True)
    monkeypatch.setattr(daemon._paper_queue, "put", lambda path: queued.append(path))
    monkeypatch.setattr(daemon.logger, "info", lambda msg: logged.append(str(msg)))

    daemon._set_processing_active(True)
    handler = PaperFileHandler(daemon)
    handler.on_created(SimpleNamespace(is_directory=False, src_path=str(event_pdf)))

    assert queued == [event_pdf]
    assert all("New scan queued:" not in msg for msg in logged)
    assert daemon._consume_deferred_scan_notice() == "1 new scan queued while finishing the current interaction"

