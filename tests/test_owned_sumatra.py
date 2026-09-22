"""Unit tests for daemon-owned SumatraPDF lifecycle (launch once, quiet open, exit on shutdown)."""
from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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

from scripts.paper_processor_daemon import PaperProcessorDaemon


def _make_daemon() -> PaperProcessorDaemon:
    daemon = object.__new__(PaperProcessorDaemon)
    daemon.logger = MagicMock()
    daemon.config = MagicMock()
    daemon.config.get = MagicMock(return_value="")
    daemon.is_windows = True
    daemon._owned_sumatra_pid = None
    daemon._owned_sumatra_positioned = False
    daemon._terminal_window_handle = None
    return daemon


def test_ensure_owned_sumatra_launches_with_appdata(monkeypatch, tmp_path: Path) -> None:
    daemon = _make_daemon()
    exe = tmp_path / "SumatraPDF.exe"
    exe.write_bytes(b"")
    appdata = tmp_path / "sumatra-daemon"
    appdata.mkdir()

    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr(daemon, "_sumatra_exe", lambda: str(exe))
    monkeypatch.setattr(daemon, "_sumatra_appdata_dir", lambda: appdata)
    monkeypatch.setattr(daemon, "_wait_for_owned_sumatra_hwnd", lambda timeout_s=5.0: 99)
    positioned: list[int] = []
    monkeypatch.setattr(
        daemon, "_position_owned_sumatra_window", lambda hwnd: positioned.append(hwnd)
    )

    fake_proc = SimpleNamespace(pid=4242)
    popen = MagicMock(return_value=fake_proc)
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.Popen", popen)

    alive = {"value": False}

    def _alive() -> bool:
        return alive["value"]

    monkeypatch.setattr(daemon, "_owned_sumatra_alive", _alive)

    def _popen_side_effect(*args, **kwargs):
        alive["value"] = True
        return fake_proc

    popen.side_effect = _popen_side_effect

    assert daemon._ensure_owned_sumatra() is True
    popen.assert_called_once()
    args = popen.call_args[0][0]
    assert args[0] == str(exe)
    assert args[1] == "-appdata"
    assert args[2] == str(appdata)
    assert "-reuse-instance" not in args
    assert positioned == [99]
    assert daemon._owned_sumatra_pid == 4242
    assert daemon._owned_sumatra_positioned is True


def test_ensure_owned_sumatra_reuses_running_process(monkeypatch) -> None:
    daemon = _make_daemon()
    daemon._owned_sumatra_pid = 7
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr(daemon, "_owned_sumatra_alive", lambda: True)
    popen = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.Popen", popen)

    assert daemon._ensure_owned_sumatra() is True
    popen.assert_not_called()


def test_open_pdf_in_viewer_uses_quiet_dde_open(monkeypatch, tmp_path: Path) -> None:
    daemon = _make_daemon()
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF")

    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr(daemon, "_ensure_owned_sumatra", lambda: True)
    sent: list[str] = []

    def _dde(cmd: str) -> bool:
        sent.append(cmd)
        return True

    monkeypatch.setattr(daemon, "_send_owned_sumatra_dde", _dde)
    popen = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.Popen", popen)
    startfile = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.os.startfile", startfile, raising=False)

    assert daemon._open_pdf_in_viewer(pdf) is True
    popen.assert_not_called()
    startfile.assert_not_called()
    assert len(sent) == 1
    assert sent[0].startswith('[Open("')
    assert ",0,0,0)]" in sent[0]
    assert "scan.pdf" in sent[0]


def test_open_pdf_in_viewer_dde_keeps_full_path_with_spaces(
    monkeypatch, tmp_path: Path
) -> None:
    """Spaced filenames must stay one Open(...) path, not truncated at the first space."""
    daemon = _make_daemon()
    pdf = tmp_path / "PREPROCESSED_EN_Verweij_2011_Clumsy solutions_split.pdf"
    pdf.write_bytes(b"%PDF")

    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr(daemon, "_ensure_owned_sumatra", lambda: True)
    sent: list[str] = []
    monkeypatch.setattr(
        daemon, "_send_owned_sumatra_dde", lambda cmd: sent.append(cmd) or True
    )

    assert daemon._open_pdf_in_viewer(pdf) is True
    assert len(sent) == 1
    # Open(...) escapes backslashes for Sumatra's DDE protocol.
    escaped = str(pdf).replace("\\", "\\\\").replace('"', '\\"')
    assert escaped in sent[0]
    assert "Clumsy solutions_split.pdf" in sent[0]


def test_open_pdf_in_viewer_missing_file_skips_dde(monkeypatch, tmp_path: Path) -> None:
    daemon = _make_daemon()
    missing = tmp_path / "no such file.pdf"

    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    sent: list[str] = []
    monkeypatch.setattr(
        daemon, "_send_owned_sumatra_dde", lambda cmd: sent.append(cmd) or True
    )
    ensure = MagicMock(return_value=True)
    monkeypatch.setattr(daemon, "_ensure_owned_sumatra", ensure)

    assert daemon._open_pdf_in_viewer(missing) is False
    assert sent == []
    ensure.assert_not_called()


def test_send_owned_sumatra_dde_uses_argv_list_not_powershell(
    monkeypatch, tmp_path: Path
) -> None:
    """Path with spaces must be one -dde argv element; no PowerShell string build."""
    daemon = _make_daemon()
    exe = tmp_path / "SumatraPDF.exe"
    exe.write_bytes(b"")
    appdata = tmp_path / "sumatra-daemon"
    appdata.mkdir()

    monkeypatch.setattr(daemon, "_sumatra_exe", lambda: str(exe))
    monkeypatch.setattr(daemon, "_sumatra_appdata_dir", lambda: appdata)

    run = MagicMock(return_value=SimpleNamespace(returncode=0, stderr=""))
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.run", run)

    dde = '[Open("C:\\\\temp\\\\PREPROCESSED_Clumsy solutions_split.pdf",0,0,0)]'
    assert daemon._send_owned_sumatra_dde(dde) is True

    run.assert_called_once()
    args = run.call_args[0][0]
    assert isinstance(args, list)
    assert args[0] == str(exe)
    assert args[1] == "-appdata"
    assert args[2] == str(appdata)
    assert args[3] == "-dde"
    assert args[4] == dde
    assert "powershell" not in args[0].lower()
    assert "Clumsy solutions_split.pdf" in args[4]


def test_close_pdf_viewer_closes_tabs_not_exit(monkeypatch) -> None:
    daemon = _make_daemon()
    sent: list[str] = []

    def _send(cmd: str, path=None) -> bool:
        sent.append(cmd)
        return True

    monkeypatch.setattr(daemon, "_send_sumatra_command", _send)
    exit_calls: list[str] = []
    monkeypatch.setattr(daemon, "_exit_owned_sumatra", lambda: exit_calls.append("exit"))

    daemon._close_pdf_viewer()
    assert sent == ["CmdCloseAllTabs"]
    assert exit_calls == []


def test_exit_owned_sumatra_sends_cmdexit_and_clears_pid(monkeypatch) -> None:
    daemon = _make_daemon()
    daemon._owned_sumatra_pid = 555
    daemon._owned_sumatra_positioned = True
    monkeypatch.setattr("scripts.paper_processor_daemon.sys.platform", "win32")
    monkeypatch.setattr("scripts.paper_processor_daemon.time.sleep", lambda *_: None)

    sent: list[str] = []
    monkeypatch.setattr(daemon, "_send_owned_sumatra_dde", lambda cmd: sent.append(cmd) or True)

    # CmdExit succeeds; process is already gone so no Stop-Process fallback.
    monkeypatch.setattr(daemon, "_owned_sumatra_alive", lambda: False)
    run = MagicMock()
    monkeypatch.setattr("scripts.paper_processor_daemon.subprocess.run", run)

    daemon._exit_owned_sumatra()
    assert sent == ["[CmdExit]"]
    assert daemon._owned_sumatra_pid is None
    assert daemon._owned_sumatra_positioned is False
    run.assert_not_called()


def test_process_paper_does_not_call_focus_helpers(monkeypatch, tmp_path: Path) -> None:
    daemon = _make_daemon()
    pdf = tmp_path / "paper.pdf"
    pdf.write_bytes(b"%PDF")

    focus_calls: list[str] = []
    close_tabs_at_start: list[str] = []
    open_calls: list[Path] = []

    monkeypatch.setattr(
        daemon, "_return_focus_to_terminal", lambda: focus_calls.append("focus")
    )
    monkeypatch.setattr(
        daemon, "_close_sumatra_all_tabs", lambda: close_tabs_at_start.append("close") or True
    )
    monkeypatch.setattr(
        daemon, "_open_pdf_in_viewer", lambda p: open_calls.append(Path(p)) or True
    )
    monkeypatch.setattr(daemon, "_maybe_auto_document_separator_early", lambda *_: True)

    result = PaperProcessorDaemon.process_paper(daemon, pdf)
    assert result is None
    assert open_calls == [pdf]
    assert focus_calls == []
    assert close_tabs_at_start == []
