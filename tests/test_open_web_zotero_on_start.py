"""Unit tests for Web Zotero open-on-start behavior."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

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


def _make_daemon(*, url: str, is_windows: bool = True) -> PaperProcessorDaemon:
    daemon = object.__new__(PaperProcessorDaemon)
    daemon.logger = MagicMock()
    daemon.zotero_web_library_url = url
    daemon.is_windows = is_windows
    daemon._terminal_window_handle = "42"
    daemon._return_focus_to_terminal = MagicMock()
    daemon._open_url_default_browser = MagicMock()
    daemon._position_browser_on_other_screen = MagicMock()
    return daemon


def test_open_web_zotero_skips_when_url_empty():
    daemon = _make_daemon(url="  ")
    daemon._open_web_zotero_library()
    daemon._open_url_default_browser.assert_not_called()
    daemon._position_browser_on_other_screen.assert_not_called()


def test_open_web_zotero_windows_opens_and_positions(monkeypatch):
    daemon = _make_daemon(url="https://www.zotero.org/eero.olli/library", is_windows=True)
    monkeypatch.setattr("scripts.paper_processor_daemon.time.sleep", lambda *_: None)

    daemon._open_web_zotero_library()

    daemon._return_focus_to_terminal.assert_not_called()
    daemon._open_url_default_browser.assert_called_once_with(
        "https://www.zotero.org/eero.olli/library"
    )
    daemon._position_browser_on_other_screen.assert_called_once()


def test_open_web_zotero_non_windows_opens_without_placement(monkeypatch):
    daemon = _make_daemon(url="https://www.zotero.org/eero.olli/library", is_windows=False)
    open_browser = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.webbrowser.open", open_browser)

    daemon._open_web_zotero_library()

    open_browser.assert_called_once_with("https://www.zotero.org/eero.olli/library", new=2)
    daemon._open_url_default_browser.assert_not_called()
    daemon._position_browser_on_other_screen.assert_not_called()


def test_open_url_default_browser_uses_opera_new_window(monkeypatch, tmp_path):
    daemon = object.__new__(PaperProcessorDaemon)
    daemon.logger = MagicMock()
    opera = tmp_path / "opera.exe"
    opera.write_bytes(b"")

    class FakeKey:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    def fake_open_key(root, path):
        return FakeKey()

    def fake_query(key, name):
        if name == "ProgId":
            return ("OperaStable", 1)
        return (rf'"{opera}" -noautoupdate -- "%1"', 1)

    winreg = types.ModuleType("winreg")
    winreg.HKEY_CURRENT_USER = 1
    winreg.HKEY_CLASSES_ROOT = 2
    winreg.OpenKey = fake_open_key
    winreg.QueryValueEx = fake_query
    monkeypatch.setitem(sys.modules, "winreg", winreg)

    popen = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.Popen", popen)
    startfile = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.os.startfile", startfile, raising=False)

    daemon._open_url_default_browser("https://www.zotero.org/eero.olli/library")

    popen.assert_called_once()
    args = popen.call_args[0][0]
    assert args[0] == str(opera)
    assert args[1] == "--new-window"
    startfile.assert_not_called()


def test_position_browser_single_monitor(monkeypatch):
    daemon = object.__new__(PaperProcessorDaemon)
    daemon.logger = MagicMock()
    daemon._terminal_window_handle = "123"
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr(
        "scripts.paper_processor_daemon.subprocess.run",
        MagicMock(return_value=SimpleNamespace(stdout="SINGLE_MONITOR\n", stderr="", returncode=0)),
    )

    daemon._position_browser_on_other_screen()

    daemon.logger.info.assert_called()
