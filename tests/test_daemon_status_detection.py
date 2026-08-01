"""Tests for daemon worker command-line classification used by --status / --stop."""

import pytest

from shared_tools.daemon.process_detection import is_daemon_worker_command_line


@pytest.mark.parametrize(
    "cmdline,expected",
    [
        (None, False),
        ("", False),
        ("python other_script.py", False),
        (
            r"cmd /K ... python scripts\paper_processor_daemon.py",
            True,
        ),
        (
            r"C:\Users\x\miniconda3\envs\research-tools-win\python.exe "
            r"F:\prog\research-tools\scripts\paper_processor_daemon.py",
            True,
        ),
        (
            "python scripts/paper_processor_daemon.py --status",
            False,
        ),
        (
            "python scripts/paper_processor_daemon.py --stop",
            False,
        ),
        (
            "python scripts/paper_processor_daemon.py --force-stop",
            False,
        ),
        (
            "python scripts/paper_processor_daemon.py --restart",
            False,
        ),
        (
            "wsl ... python scripts/paper_processor_daemon.py --debug",
            True,
        ),
    ],
)
def test_is_daemon_worker_command_line(cmdline, expected):
    assert is_daemon_worker_command_line(cmdline) is expected
