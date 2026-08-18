#!/usr/bin/env python3
from __future__ import annotations

import sqlite3

from shared_tools.zotero.local_search import ZoteroLocalSearch


def _dummy_logger():
    return type(
        "L",
        (),
        {
            "warning": lambda *a, **k: None,
            "debug": lambda *a, **k: None,
            "error": lambda *a, **k: None,
        },
    )()


def _memory_zotero_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    cur = conn.cursor()
    cur.executescript(
        """
        CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
        CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
        CREATE TABLE itemData (
            itemID INTEGER,
            fieldID INTEGER,
            valueID INTEGER
        );

        INSERT INTO fields (fieldID, fieldName) VALUES
            (1, 'volume'),
            (2, 'issue'),
            (3, 'pages'),
            (4, 'ISSN'),
            (5, 'publisher'),
            (6, 'url'),
            (7, 'ISBN'),
            (8, 'language');

        INSERT INTO itemDataValues (valueID, value) VALUES
            (1, '36'),
            (2, '1'),
            (3, '48-72'),
            (4, '1069-3971'),
            (5, 'SAGE Publications'),
            (6, 'https://doi.org/10.1177/example'),
            (7, '978-0-00-000000-0'),
            (8, 'en');

        INSERT INTO itemData (itemID, fieldID, valueID) VALUES
            (10, 1, 1),
            (10, 2, 2),
            (10, 3, 3),
            (10, 4, 4),
            (10, 5, 5),
            (10, 6, 6),
            (10, 7, 7),
            (10, 8, 8);
        """
    )
    conn.commit()
    return conn


def _searcher(conn: sqlite3.Connection) -> ZoteroLocalSearch:
    searcher = object.__new__(ZoteroLocalSearch)
    searcher.logger = _dummy_logger()
    searcher.db_connection = conn
    return searcher


def test_get_item_data_fields_returns_zotero_keys():
    conn = _memory_zotero_db()
    searcher = _searcher(conn)
    fields = searcher._get_item_data_fields(10)
    assert fields["volume"] == "36"
    assert fields["issue"] == "1"
    assert fields["pages"] == "48-72"
    assert fields["ISSN"] == "1069-3971"
    assert fields["publisher"] == "SAGE Publications"
    assert fields["url"] == "https://doi.org/10.1177/example"
    assert fields["ISBN"] == "978-0-00-000000-0"
    assert fields["language"] == "en"
    assert "issn" not in fields


def test_attach_bibliographic_fields_copies_without_overwrite():
    conn = _memory_zotero_db()
    searcher = _searcher(conn)
    item = {"url": "https://already.present"}
    searcher._attach_bibliographic_fields(item, 10)
    assert item["volume"] == "36"
    assert item["issue"] == "1"
    assert item["pages"] == "48-72"
    assert item["ISSN"] == "1069-3971"
    assert item["url"] == "https://already.present"
    assert "issn" not in item
