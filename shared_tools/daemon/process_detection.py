"""Detect live paper_processor_daemon worker processes (not status/stop/restart)."""

from __future__ import annotations

import os
import subprocess
import sys
from typing import List, Optional

# Control-plane flags: processes with these are not a live interactive daemon.
DAEMON_CONTROL_FLAGS = ("--status", "--stop", "--force-stop", "--restart")


def is_daemon_worker_command_line(cmd: Optional[str]) -> bool:
    """Return True if command line is a live paper_processor_daemon worker."""
    if not cmd:
        return False
    low = cmd.lower()
    if "paper_processor_daemon.py" not in low:
        return False
    return not any(flag in low for flag in DAEMON_CONTROL_FLAGS)


def find_running_daemon_pids(exclude_pid: Optional[int] = None) -> List[int]:
    """Find PIDs of live daemon workers via process listing (Windows WMI or pgrep)."""
    current = exclude_pid if exclude_pid is not None else os.getpid()
    found: List[int] = []

    if sys.platform == "win32":
        ps_script = (
            "Get-CimInstance Win32_Process | "
            "Where-Object { $_.CommandLine } | "
            "ForEach-Object { '{0}`t{1}' -f $_.ProcessId, $_.CommandLine }"
        )
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps_script,
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
        except Exception:
            return found
        if result.returncode != 0 or not result.stdout:
            return found
        for line in result.stdout.splitlines():
            line = line.strip()
            if not line or "\t" not in line:
                continue
            pid_str, cmdline = line.split("\t", 1)
            try:
                pid = int(pid_str)
            except ValueError:
                continue
            if pid == current:
                continue
            if is_daemon_worker_command_line(cmdline):
                found.append(pid)
        return found

    try:
        out = subprocess.check_output(
            ["pgrep", "-af", "paper_processor_daemon.py"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return found
    for line in out.splitlines():
        parts = line.strip().split(None, 1)
        if not parts:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == current:
            continue
        cmdline = parts[1] if len(parts) > 1 else ""
        if is_daemon_worker_command_line(cmdline):
            found.append(pid)
    return found
