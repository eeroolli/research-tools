#!/usr/bin/env python3
"""
Retroactively fix Zotero linked-file PDF attachment icons by ensuring
`contentType=application/pdf` on linked_file PDF attachments.

Default is dry-run. Use --apply after reviewing output.

Modes:
  --logs-only   Use scanned_papers_log.csv from PATHS log_folder in config (same as daemon).
  --library-wide   All linked_file PDF attachments in the library (paginated).

PATCHes existing Zotero attachment items via Web API.

This script works in PowerShell. Not WSL.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

# Project root (parent of scripts/)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import requests

from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


def _scanned_papers_log_path() -> Path:
    """Resolve data/logs/scanned_papers_log.csv from PATHS log_folder (config.conf + config.personal.conf)."""
    cfg = configparser.ConfigParser()
    cfg.read([ROOT / "config.conf", ROOT / "config.personal.conf"])
    raw = cfg.get("PATHS", "log_folder", fallback="./data/logs").strip()
    log_folder = Path(raw)
    if not log_folder.is_absolute():
        log_folder = (ROOT / log_folder).resolve()
    else:
        log_folder = log_folder.resolve()
    return log_folder / "scanned_papers_log.csv"


def _logs_dir_path() -> Path:
    """Resolve log folder from PATHS.log_folder in config."""
    cfg = configparser.ConfigParser()
    cfg.read([ROOT / "config.conf", ROOT / "config.personal.conf"])
    raw = cfg.get("PATHS", "log_folder", fallback="./data/logs").strip()
    log_folder = Path(raw)
    if not log_folder.is_absolute():
        return (ROOT / log_folder).resolve()
    return log_folder.resolve()


def _missing_csv_path() -> Path:
    return _logs_dir_path() / "missing_linked_files.csv"


def _basename_from_zotero_path(path_str: str) -> str:
    """Basename of a Zotero linked path (handles / and \\)."""
    if not path_str or not str(path_str).strip():
        return ""
    s = str(path_str).strip()
    # Zotero may use attachment:path form on some builds
    if s.lower().startswith("attachment:"):
        s = s.split(":", 1)[1].strip()
    s = s.replace("/", os.sep).replace("\\", os.sep)
    return Path(s).name


def _is_eligible_pdf_linked(data: Dict[str, Any]) -> bool:
    if (data.get("itemType") or "") != "attachment":
        return False
    if (data.get("linkMode") or "") != "linked_file":
        return False
    path_str = data.get("path") or ""
    base = _basename_from_zotero_path(path_str)
    if not base:
        return False
    return base.lower().endswith(".pdf")


def _linked_file_exists(path_str: str) -> bool:
    if not path_str:
        return False
    s = str(path_str).strip()
    if s.lower().startswith("attachment:"):
        s = s.split(":", 1)[1].strip()
    # Zotero-internal pseudo-schemes aren't directly checkable on disk here.
    # Treat as \"exists\" so we don't incorrectly skip valid attachments.
    if s.lower().startswith(("attachments:", "storage:")):
        return True
    try:
        return Path(s).is_file()
    except OSError:
        return False


def _needs_content_type_fix(data: Dict[str, Any]) -> bool:
    """True if eligible linked PDF attachment is missing application/pdf contentType."""
    current = data.get("contentType")
    return (current or "").strip().lower() != "application/pdf"


def _extract_year(date_value: str) -> str:
    text = (date_value or "").strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]
    for i in range(0, max(0, len(text) - 3)):
        chunk = text[i : i + 4]
        if chunk.isdigit():
            return chunk
    return ""


def _author_summary(creators: List[Dict[str, Any]]) -> str:
    if not creators:
        return ""
    first = creators[0] or {}
    last = (first.get("lastName") or "").strip()
    first_name = (first.get("firstName") or "").strip()
    name = " ".join([x for x in [first_name, last] if x]).strip()
    if name:
        return name
    return (first.get("name") or "").strip()


def _fetch_parent_metadata(
    processor: ZoteroPaperProcessor,
    parent_key: str,
    cache: Dict[str, Dict[str, str]],
) -> Dict[str, str]:
    if not parent_key:
        return {"author": "", "year": "", "title": "", "type": ""}
    if parent_key in cache:
        return cache[parent_key]

    fallback = {"author": "", "year": "", "title": "", "type": ""}
    try:
        r = requests.get(f"{processor.base_url}/items/{parent_key}", headers=processor.headers, timeout=60)
        if r.status_code != 200:
            cache[parent_key] = fallback
            return fallback
        item = r.json() or {}
        data = item.get("data") or {}
        meta = {
            "author": _author_summary(data.get("creators") or []),
            "year": _extract_year(data.get("date") or ""),
            "title": (data.get("title") or "").strip(),
            "type": (data.get("itemType") or "").strip(),
        }
        cache[parent_key] = meta
        return meta
    except Exception:
        cache[parent_key] = fallback
        return fallback


def _load_existing_missing_keys(csv_path: Path) -> set[Tuple[str, str]]:
    keys: set[Tuple[str, str]] = set()
    if not csv_path.exists():
        return keys
    try:
        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                keys.add(
                    (
                        (row.get("attachment_key") or "").strip(),
                        (row.get("linked_file_path_in_zotero") or "").strip(),
                    )
                )
    except Exception:
        return keys
    return keys


def _write_missing_rows(csv_path: Path, rows: List[Dict[str, str]]) -> int:
    if not rows:
        return 0
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "author",
        "year",
        "title",
        "type",
        "linked_file_path_in_zotero",
        "parent_key",
        "attachment_key",
        "run_mode",
        "reason",
        "timestamp",
    ]
    write_header = not csv_path.exists()
    with open(csv_path, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        if write_header:
            writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return len(rows)


def _read_parent_keys_from_csv(csv_path: Path) -> List[str]:
    keys: List[str] = []
    seen: set[str] = set()
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.reader(f, delimiter=";", quotechar='"')
        rows = list(reader)
    if not rows:
        return []
    header = [h.strip() for h in rows[0]]
    try:
        idx = header.index("zotero_item_code")
    except ValueError:
        raise SystemExit(f"CSV missing zotero_item_code column: {csv_path}")
    for row in rows[1:]:
        if len(row) <= idx:
            continue
        k = (row[idx] or "").strip()
        if k and k not in seen:
            seen.add(k)
            keys.append(k)
    return keys


def _fetch_children(processor: ZoteroPaperProcessor, parent_key: str) -> List[Dict[str, Any]]:
    url = f"{processor.base_url}/items/{parent_key}/children"
    r = requests.get(url, headers=processor.headers, timeout=60)
    if r.status_code != 200:
        print(f"  WARN GET children {parent_key}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        return []
    return r.json()


def _iter_library_attachments(processor: ZoteroPaperProcessor) -> Iterable[Dict[str, Any]]:
    start = 0
    limit = 100
    while True:
        params = {"itemType": "attachment", "limit": limit, "start": start}
        r = requests.get(f"{processor.base_url}/items", headers=processor.headers, params=params, timeout=60)
        if r.status_code != 200:
            print(f"WARN GET items: {r.status_code} {r.text[:300]}", file=sys.stderr)
            break
        batch = r.json()
        if not batch:
            break
        for item in batch:
            yield item
        if len(batch) < limit:
            break
        start += limit
        time.sleep(0.1)


def _process_attachment_item(
    processor: ZoteroPaperProcessor,
    item: Dict[str, Any],
    *,
    apply: bool,
    allow_missing_file: bool,
    stats: Dict[str, int],
    run_mode: str,
    missing_rows: List[Dict[str, str]],
    seen_missing_keys: set[Tuple[str, str]],
    existing_missing_keys: set[Tuple[str, str]],
    parent_cache: Dict[str, Dict[str, str]],
) -> None:
    key = item.get("key")
    data = item.get("data") or {}
    parent = data.get("parentItem")

    if not _is_eligible_pdf_linked(data):
        return

    if not allow_missing_file and not _linked_file_exists(data.get("path") or ""):
        stats["skipped_missing_file"] = stats.get("skipped_missing_file", 0) + 1
        print(f"  skip (file not on disk): {key} path={data.get('path')!r}")
        dedupe_key = (str(key or ""), str(data.get("path") or ""))
        if dedupe_key not in seen_missing_keys and dedupe_key not in existing_missing_keys:
            seen_missing_keys.add(dedupe_key)
            meta = _fetch_parent_metadata(processor, str(parent or ""), parent_cache)
            missing_rows.append(
                {
                    "author": meta.get("author", ""),
                    "year": meta.get("year", ""),
                    "title": meta.get("title", ""),
                    "type": meta.get("type", ""),
                    "linked_file_path_in_zotero": str(data.get("path") or ""),
                    "parent_key": str(parent or ""),
                    "attachment_key": str(key or ""),
                    "run_mode": run_mode,
                    "reason": "file_not_found",
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
            )
        return

    if not _needs_content_type_fix(data):
        stats["already_ok"] = stats.get("already_ok", 0) + 1
        return

    stats["would_fix"] = stats.get("would_fix", 0) + 1
    content_type_old = data.get("contentType")
    print(f"  {'PATCH' if apply else 'DRY '}: key={key} parent={parent} contentType={content_type_old!r} -> 'application/pdf'")
    if apply:
        ok = processor.update_item_field(key, "contentType", "application/pdf")
        if ok:
            stats["patched"] = stats.get("patched", 0) + 1
        else:
            stats["patch_failed"] = stats.get("patch_failed", 0) + 1
            print(f"    FAILED PATCH key={key}", file=sys.stderr)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument(
        "--logs-only",
        action="store_true",
        help="Only parents from scanned_papers_log.csv (path from PATHS log_folder in config)",
    )
    p.add_argument(
        "--library-wide",
        action="store_true",
        help="Scan all attachment items in the library (linked PDFs only)",
    )
    p.add_argument(
        "--apply",
        action="store_true",
        help="Apply PATCH (default: dry-run only)",
    )
    p.add_argument(
        "--allow-missing-file",
        action="store_true",
        help="Allow title fix even when linked path is not found on disk",
    )
    args = p.parse_args()

    if not args.logs_only and not args.library_wide:
        p.error("Specify --logs-only or --library-wide")
    if args.logs_only and args.library_wide:
        p.error("Use either --logs-only or --library-wide, not both")

    processor = ZoteroPaperProcessor()

    stats: Dict[str, int] = {}
    missing_rows: List[Dict[str, str]] = []
    seen_missing_keys: set[Tuple[str, str]] = set()
    missing_csv = _missing_csv_path()
    existing_missing_keys = _load_existing_missing_keys(missing_csv)
    parent_cache: Dict[str, Dict[str, str]] = {}

    if args.logs_only:
        csv_path = _scanned_papers_log_path()
        print(f"Using log CSV: {csv_path}")
        if not csv_path.is_file():
            raise SystemExit(f"CSV not found: {csv_path}")
        parents = _read_parent_keys_from_csv(csv_path)
        print(f"Parents from CSV: {len(parents)}")
        for parent_key in parents:
            print(f"Parent {parent_key}:")
            children = _fetch_children(processor, parent_key)
            for item in children:
                _process_attachment_item(
                    processor,
                    item,
                    apply=args.apply,
                    allow_missing_file=args.allow_missing_file,
                    stats=stats,
                    run_mode="logs-only",
                    missing_rows=missing_rows,
                    seen_missing_keys=seen_missing_keys,
                    existing_missing_keys=existing_missing_keys,
                    parent_cache=parent_cache,
                )
            time.sleep(0.05)
    else:
        print("Library-wide scan (linked_file PDF attachments only)...")
        for item in _iter_library_attachments(processor):
            data = item.get("data") or {}
            if not _is_eligible_pdf_linked(data):
                continue
            _process_attachment_item(
                processor,
                item,
                apply=args.apply,
                allow_missing_file=args.allow_missing_file,
                stats=stats,
                run_mode="library-wide",
                missing_rows=missing_rows,
                seen_missing_keys=seen_missing_keys,
                existing_missing_keys=existing_missing_keys,
                parent_cache=parent_cache,
            )
            time.sleep(0.02)

    written = _write_missing_rows(missing_csv, missing_rows)
    print(f"Missing-file rows captured this run: {written}")
    print(f"Missing-file CSV: {missing_csv}")
    print("Summary:", stats)


if __name__ == "__main__":
    main()
