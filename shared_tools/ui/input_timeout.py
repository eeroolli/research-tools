#!/usr/bin/env python3
"""
Cross-platform helpers for line input with optional timeouts and stdin draining.

On Unix/WSL:
- Uses select.select() on sys.stdin for non-blocking checks and timeouts.

On Windows:
- Avoids select() on sys.stdin (which only supports sockets and raises
  OSError [WinError 10038] on console handles).
- Uses msvcrt.kbhit()/getwch() polling to implement simple line editing and
  timeout-aware input without crashing.
"""

from __future__ import annotations

import sys
import time
from typing import Optional


def _drain_stdin_unix(max_lines: int = 5, timeout_per_line: float = 0.05) -> int:
    """Drain buffered stdin lines on Unix/WSL using select."""
    import select  # type: ignore[import]

    drained = 0
    for _ in range(max_lines):
        ready, _, _ = select.select([sys.stdin], [], [], timeout_per_line)
        if not ready:
            break
        _ = sys.stdin.readline()
        drained += 1
    return drained


def _drain_stdin_windows(max_chars: int = 1024, timeout_seconds: float = 0.2) -> int:
    """Best-effort stdin drain on Windows using msvcrt."""
    import msvcrt  # type: ignore[import]

    drained = 0
    end_time = time.time() + timeout_seconds
    while time.time() < end_time and drained < max_chars:
        if not msvcrt.kbhit():
            time.sleep(0.02)
            continue
        _ = msvcrt.getwch()
        drained += 1
    return drained


def drain_stdin(max_lines: int = 5, timeout_per_line: float = 0.05) -> int:
    """Public API: drain any pending input from stdin, best-effort.

    Returns the number of characters/lines drained (approximate).
    """
    if sys.platform == "win32":
        return _drain_stdin_windows(max_chars=max_lines * 256, timeout_seconds=timeout_per_line * max_lines)
    return _drain_stdin_unix(max_lines=max_lines, timeout_per_line=timeout_per_line)


def _read_line_with_timeout_unix(
    prompt: str,
    timeout: Optional[float],
    default: Optional[str],
) -> Optional[str]:
    """Unix/WSL implementation using select on sys.stdin."""
    import select  # type: ignore[import]

    # No timeout: regular blocking input
    if not timeout or timeout <= 0:
        try:
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            return None

    # Timed input using select
    sys.stdout.write(prompt)
    sys.stdout.flush()
    try:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        if ready:
            line = sys.stdin.readline()
            return line.rstrip("\r\n")
        # Timeout
        return default
    except (KeyboardInterrupt, EOFError):
        return None


def _read_line_with_timeout_windows(
    prompt: str,
    timeout: Optional[float],
    default: Optional[str],
) -> Optional[str]:
    """Windows implementation using msvcrt polling on the console."""
    import msvcrt  # type: ignore[import]

    # No timeout: fall back to standard input()
    if not timeout or timeout <= 0:
        try:
            return input(prompt)
        except (KeyboardInterrupt, EOFError):
            return None

    sys.stdout.write(prompt)
    sys.stdout.flush()

    start = time.time()
    chars: list[str] = []

    while True:
        # Timeout check
        if timeout and (time.time() - start) >= timeout:
            # If we've already started typing, treat it as user input
            if chars:
                return "".join(chars)
            # Otherwise, return default (may be None)
            return default

        if msvcrt.kbhit():
            ch = msvcrt.getwch()
            # Enter: end of line
            if ch in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(chars)
            # Handle backspace
            if ch in ("\b", "\x08"):
                if chars:
                    chars.pop()
                    # Erase last character from console
                    sys.stdout.write("\b \b")
                    sys.stdout.flush()
                continue
            # Regular printable char
            chars.append(ch)
            sys.stdout.write(ch)
            sys.stdout.flush()
        else:
            # Avoid busy-waiting
            time.sleep(0.02)


def read_line_with_timeout(
    prompt: str,
    timeout: Optional[float],
    default: Optional[str] = None,
    clear_buffered: bool = False,
) -> Optional[str]:
    """Read a line from stdin with an optional timeout and default.

    Args:
        prompt: Prompt to display.
        timeout: Timeout in seconds (None or <=0 = no timeout).
        default: Default value to return when timeout occurs.
        clear_buffered: If True, drain any pending input before prompting.

    Returns:
        - The line the user typed (without trailing newline), or
        - `default` if timeout occurs and default is not None, or
        - None on timeout when default is None, or on KeyboardInterrupt/EOFError.
    """
    if clear_buffered:
        # Best-effort drain before prompting
        drain_stdin(max_lines=5, timeout_per_line=0.05)

    if sys.platform == "win32":
        return _read_line_with_timeout_windows(prompt, timeout, default)
    return _read_line_with_timeout_unix(prompt, timeout, default)

