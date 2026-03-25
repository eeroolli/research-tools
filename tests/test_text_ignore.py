"""Tests for shared_tools.utils.text_ignore."""

import re

import pytest

from shared_tools.utils import text_ignore as ti


def test_sanitize_text_removes_matching_lines(monkeypatch):
    monkeypatch.setattr(ti, "get_ignore_patterns", lambda force_reload=False: [
        re.compile(r"^ignore\s+me\s*$", re.IGNORECASE | re.MULTILINE),
    ])
    raw = "Title line\nignore me\nkeep this\n"
    assert ti.sanitize_text(raw) == "Title line\nkeep this"


def test_filter_candidates_drops_matches(monkeypatch):
    monkeypatch.setattr(ti, "get_ignore_patterns", lambda force_reload=False: [
        re.compile(r"bad\.com", re.IGNORECASE),
    ])
    assert ti.filter_candidates(["https://good.com/x", "https://bad.com/y"]) == ["https://good.com/x"]
