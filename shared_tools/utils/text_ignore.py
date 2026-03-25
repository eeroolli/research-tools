#!/usr/bin/env python3
"""
Config-driven text ignore utility.

Used to remove recurring stamps/headers from extracted PDF text before downstream
metadata extraction (regex, GROBID structured pre-pass, Ollama prompts).
"""

from __future__ import annotations

import configparser
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Pattern


@dataclass(frozen=True)
class _IgnoreConfig:
    patterns: List[Pattern[str]]


_CACHE: Optional[_IgnoreConfig] = None


def _repo_root() -> Path:
    # shared_tools/utils/text_ignore.py -> shared_tools/utils -> shared_tools -> repo root
    return Path(__file__).parent.parent.parent


def _load_ignore_regex_lines(config: configparser.ConfigParser) -> List[str]:
    if not config.has_option("TEXT_IGNORE", "ignore_regex"):
        return []
    raw = config.get("TEXT_IGNORE", "ignore_regex", fallback="") or ""
    lines: List[str] = []
    for ln in raw.splitlines():
        s = ln.strip()
        if not s:
            continue
        if s.startswith("#") or s.startswith(";"):
            continue
        lines.append(s)
    return lines


def _compile_patterns(lines: Iterable[str]) -> List[Pattern[str]]:
    compiled: List[Pattern[str]] = []
    for pattern in lines:
        try:
            compiled.append(re.compile(pattern, flags=re.IGNORECASE))
        except re.error:
            # Invalid regex should not crash the daemon; ignore it.
            continue
    return compiled


def get_ignore_patterns(force_reload: bool = False) -> List[Pattern[str]]:
    """Return compiled ignore regex patterns from config."""
    global _CACHE
    if _CACHE is not None and not force_reload:
        return _CACHE.patterns

    cfg = configparser.ConfigParser()
    root = _repo_root()
    cfg.read([root / "config.conf", root / "config.personal.conf"])

    lines = _load_ignore_regex_lines(cfg)
    patterns = _compile_patterns(lines)
    _CACHE = _IgnoreConfig(patterns=patterns)
    return patterns


def _matches_any(patterns: List[Pattern[str]], text: str) -> bool:
    for p in patterns:
        try:
            if p.search(text):
                return True
        except Exception:
            continue
    return False


def sanitize_text(text: str, *, collapse_blank_lines: bool = True) -> str:
    """Remove ignored stamp/header lines from text.

    Intended to be safe: removes matching LINES, not arbitrary multi-line spans.
    """
    if not isinstance(text, str) or not text:
        return "" if text is None else str(text)

    patterns = get_ignore_patterns()
    if not patterns:
        return text

    out_lines: List[str] = []
    for ln in text.splitlines():
        if _matches_any(patterns, ln):
            continue
        out_lines.append(ln)

    if not collapse_blank_lines:
        return "\n".join(out_lines)

    collapsed: List[str] = []
    last_blank = False
    for ln in out_lines:
        is_blank = not ln.strip()
        if is_blank and last_blank:
            continue
        collapsed.append(ln)
        last_blank = is_blank
    return "\n".join(collapsed).strip()


def filter_candidates(values: Iterable[str]) -> List[str]:
    """Filter extracted candidate values (authors, urls) against ignore patterns."""
    patterns = get_ignore_patterns()
    if not patterns:
        return [v for v in values if v]

    kept: List[str] = []
    for v in values:
        if not v:
            continue
        s = str(v).strip()
        if not s:
            continue
        if _matches_any(patterns, s):
            continue
        kept.append(s)
    return kept

