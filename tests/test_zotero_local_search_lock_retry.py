#!/usr/bin/env python3
from __future__ import annotations

import sqlite3

from shared_tools.zotero.local_search import ZoteroLocalSearch


class _CursorAlwaysLocked:
    def execute(self, *_args, **_kwargs):
        raise sqlite3.OperationalError("database is locked")

    def fetchall(self):
        return []


class _ConnectionAlwaysLocked:
    def cursor(self):
        return _CursorAlwaysLocked()


def test_search_by_author_returns_none_after_lock_retries_exhausted():
    searcher = object.__new__(ZoteroLocalSearch)
    searcher.logger = type("L", (), {"warning": lambda *a, **k: None, "debug": lambda *a, **k: None, "error": lambda *a, **k: None})()
    searcher.db_connection = _ConnectionAlwaysLocked()

    result = searcher.search_by_author("Christie", limit=5)
    assert result is None


def test_search_by_authors_ordered_returns_none_after_lock_retries_exhausted():
    searcher = object.__new__(ZoteroLocalSearch)
    searcher.logger = type("L", (), {"warning": lambda *a, **k: None, "debug": lambda *a, **k: None, "error": lambda *a, **k: None})()
    searcher.db_connection = _ConnectionAlwaysLocked()

    result = searcher.search_by_authors_ordered(["Christie"], year="1983", limit=5)
    assert result is None
