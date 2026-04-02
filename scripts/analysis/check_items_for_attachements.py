#!/usr/bin/env python3
"""
Inspect specific Zotero parent items and their child attachments in the local Zotero SQLite DB.

This is meant to debug cases where a parent item is shown as "PDF: ❌" in local search
but a publications conflict later suggests a PDF exists somewhere.

It prints:
- matched parent items (itemID, key, itemType, title, DOI)
- all child attachment items for each parent (key, linkMode, contentType, path, title, filename)

Defaults target the two examples from the prompt:
- Greenwald 1998 DOI: 10.1037/0022-3514.74.6.1464
- Höglinger 2016 (no DOI provided): title substring match
"""

from __future__ import annotations

import argparse
import configparser
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


DEFAULT_QUERIES: List[Tuple[str, str]] = [
    ("doi", "10.1037/0022-3514.74.6.1464"),
    ("title", "Sensitive Questions in Online Surveys"),
]


LINK_MODE_MAP = {
    0: "imported_file",
    1: "imported_url",
    2: "linked_file",
    3: "linked_url",
}


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _get_db_path_from_config() -> Path:
    """Resolve PATHS.zotero_db_path from config.conf + config.personal.conf."""
    config = configparser.ConfigParser()
    root_dir = Path(__file__).resolve().parent.parent.parent
    config.read([root_dir / "config.conf", root_dir / "config.personal.conf"])
    if config.has_option("PATHS", "zotero_db_path"):
        raw = config.get("PATHS", "zotero_db_path").strip()
        if not raw:
            raise ValueError("PATHS.zotero_db_path is empty in config")
        return Path(raw)
    raise ValueError("PATHS.zotero_db_path not found in config files")


def _get_field_id(conn: sqlite3.Connection, field_name: str) -> Optional[int]:
    cur = conn.cursor()
    cur.execute("SELECT fieldID FROM fields WHERE fieldName = ?", (field_name,))
    row = cur.fetchone()
    return int(row["fieldID"]) if row else None


def _get_item_data_value(conn: sqlite3.Connection, item_id: int, field_name: str) -> Optional[str]:
    field_id = _get_field_id(conn, field_name)
    if field_id is None:
        return None
    cur = conn.cursor()
    cur.execute(
        """
        SELECT v.value
        FROM itemData d
        JOIN itemDataValues v ON d.valueID = v.valueID
        WHERE d.itemID = ?
          AND d.fieldID = ?
        """,
        (item_id, field_id),
    )
    row = cur.fetchone()
    return str(row["value"]) if row and row["value"] is not None else None


def _find_parent_items_by_doi(conn: sqlite3.Connection, doi: str) -> List[sqlite3.Row]:
    field_id = _get_field_id(conn, "DOI")
    if field_id is None:
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.itemID, i.key, it.typeName AS itemType
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        JOIN itemData d ON d.itemID = i.itemID AND d.fieldID = ?
        JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
          AND LOWER(v.value) = LOWER(?)
        """,
        (field_id, doi.strip()),
    )
    return cur.fetchall()


def _find_parent_items_by_title_substring(conn: sqlite3.Connection, title_sub: str) -> List[sqlite3.Row]:
    field_id = _get_field_id(conn, "title")
    if field_id is None:
        return []
    cur = conn.cursor()
    cur.execute(
        """
        SELECT i.itemID, i.key, it.typeName AS itemType
        FROM items i
        JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
        JOIN itemData d ON d.itemID = i.itemID AND d.fieldID = ?
        JOIN itemDataValues v ON v.valueID = d.valueID
        WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
          AND v.value LIKE ?
        ORDER BY i.itemID DESC
        LIMIT 25
        """,
        (field_id, f"%{title_sub}%"),
    )
    return cur.fetchall()


def _get_child_attachments(conn: sqlite3.Connection, parent_item_id: int) -> List[sqlite3.Row]:
    cur = conn.cursor()
    cur.execute(
        """
        SELECT
            child.itemID,
            child.key,
            ia.parentItemID,
            ia.linkMode,
            ia.contentType,
            ia.path
        FROM itemAttachments ia
        JOIN items child ON ia.itemID = child.itemID
        JOIN itemTypes it ON child.itemTypeID = it.itemTypeID
        WHERE ia.parentItemID = ?
          AND child.itemID NOT IN (SELECT itemID FROM deletedItems)
          AND it.typeName = 'attachment'
        ORDER BY child.itemID ASC
        """,
        (parent_item_id,),
    )
    return cur.fetchall()


def _row_to_dict(row: sqlite3.Row) -> Dict[str, Any]:
    return {k: row[k] for k in row.keys()}


def _print_parent(conn: sqlite3.Connection, parent: sqlite3.Row) -> None:
    item_id = int(parent["itemID"])
    title = _get_item_data_value(conn, item_id, "title") or ""
    doi = _get_item_data_value(conn, item_id, "DOI") or ""
    print(f"- Parent itemID={item_id} key={parent['key']} type={parent['itemType']}")
    if title:
        print(f"  Title: {title}")
    if doi:
        print(f"  DOI:   {doi}")


def _print_attachment(conn: sqlite3.Connection, att: sqlite3.Row) -> None:
    d = _row_to_dict(att)
    item_id = int(d["itemID"])
    link_mode_raw = d.get("linkMode")
    link_mode = LINK_MODE_MAP.get(int(link_mode_raw), str(link_mode_raw)) if link_mode_raw is not None else "?"
    title = _get_item_data_value(conn, item_id, "title") or ""
    filename = _get_item_data_value(conn, item_id, "filename") or ""
    print(f"  * Attachment itemID={item_id} key={d.get('key')}")
    print(f"    linkMode:     {link_mode} ({link_mode_raw})")
    print(f"    contentType:  {d.get('contentType')!r}")
    print(f"    path:         {d.get('path')!r}")
    if title:
        print(f"    title(field): {title!r}")
    if filename:
        print(f"    filename:     {filename!r}")


def _run_queries(conn: sqlite3.Connection, queries: List[Tuple[str, str]]) -> None:
    seen_parents: set[int] = set()
    parents: List[sqlite3.Row] = []

    for kind, value in queries:
        value = (value or "").strip()
        if not value:
            continue
        if kind == "doi":
            matches = _find_parent_items_by_doi(conn, value)
        elif kind == "title":
            matches = _find_parent_items_by_title_substring(conn, value)
        else:
            raise ValueError(f"Unknown query kind: {kind}")

        for m in matches:
            pid = int(m["itemID"])
            if pid in seen_parents:
                continue
            seen_parents.add(pid)
            parents.append(m)

    if not parents:
        print("No parent items matched.")
        return

    print(f"Matched {len(parents)} parent item(s).")
    print("=" * 80)

    for parent in parents:
        _print_parent(conn, parent)
        item_id = int(parent["itemID"])
        attachments = _get_child_attachments(conn, item_id)
        if not attachments:
            print("  (no child attachments)")
        else:
            print(f"  Child attachments: {len(attachments)}")
            for att in attachments:
                _print_attachment(conn, att)
        print("-" * 80)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, default=None, help="Path to Zotero sqlite db (default: PATHS.zotero_db_path from config)")
    ap.add_argument("--doi", action="append", default=[], help="Match parent items by exact DOI (repeatable)")
    ap.add_argument("--title", action="append", default=[], help="Match parent items by title substring (repeatable)")
    args = ap.parse_args()

    db_path = Path(args.db) if args.db else _get_db_path_from_config()
    if not db_path.exists():
        raise SystemExit(
            f"DB not found: {db_path}\n"
            "Tip: set PATHS.zotero_db_path in config.personal.conf or pass --db explicitly."
        )

    queries: List[Tuple[str, str]] = []
    for d in args.doi:
        queries.append(("doi", d))
    for t in args.title:
        queries.append(("title", t))
    if not queries:
        queries = list(DEFAULT_QUERIES)

    conn = _connect(db_path)
    try:
        _run_queries(conn, queries)
    finally:
        conn.close()


if __name__ == "__main__":
    main()

