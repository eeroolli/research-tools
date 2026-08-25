#!/usr/bin/env python3
"""
Fix one-field Zotero personal names (e.g. "Brendon Swedlow") into Last, First.

Default is scan-only (no writes). Use --review to approve suggestions interactively,
or --apply-approved after editing the review JSON. Always writes a timestamped
backup before PATCH; --revert restores from that backup when safe.

See docs/fix_zotero_author_name_order.md
"""

from __future__ import annotations

import argparse
import configparser
import json
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_tools.config.io import read_config_files
from shared_tools.utils.author_name_splitter import (
    SplitSuggestion,
    WellFormedAuthor,
    as_name_str,
    build_wellformed_index,
    decide_apply_action,
    decide_revert_action,
    group_suggestions,
    is_malformed_personal_creator,
    replace_malformed_creator,
    suggest_split,
    wellformed_from_sqlite_row,
)
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor

CACHE_DIR = ROOT / "data" / "cache"
BACKUPS_DIR = ROOT / "data" / "backups"
DEFAULT_SUGGESTIONS_PATH = CACHE_DIR / "author_name_fixes.json"
DEFAULT_SKIPPED_PATH = CACHE_DIR / "author_name_fixes_skipped.json"


def _db_path_from_config() -> Path:
    config = configparser.ConfigParser()
    read_config_files(config, [ROOT / "config.conf", ROOT / "config.personal.conf"])
    if not config.has_option("PATHS", "zotero_db_path"):
        raise SystemExit("zotero_db_path not found in config.conf / config.personal.conf")
    path = Path(config.get("PATHS", "zotero_db_path").strip())
    if not path.exists():
        raise SystemExit(f"Zotero database not found: {path}")
    return path


def _connect_readonly(db_path: Path) -> sqlite3.Connection:
    uri = f"file:{db_path}?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    try:
        conn.execute("PRAGMA query_only=ON;")
    except sqlite3.Error:
        pass
    return conn


def _execute_with_lock_retry(
    conn: sqlite3.Connection,
    query: str,
    params: tuple = (),
    *,
    operation_name: str = "query",
    max_retries: int = 3,
) -> List[tuple]:
    last_err: Optional[Exception] = None
    for attempt in range(max_retries + 1):
        try:
            cur = conn.cursor()
            cur.execute(query, params)
            return cur.fetchall()
        except sqlite3.OperationalError as e:
            last_err = e
            if "database is locked" not in str(e).lower():
                raise
            if attempt >= max_retries:
                break
            sleep_s = 0.5 * (2**attempt)
            print(
                f"Zotero DB locked during {operation_name}; "
                f"retrying in {sleep_s:.1f}s ({attempt + 1}/{max_retries})...",
                file=sys.stderr,
            )
            time.sleep(sleep_s)
    raise SystemExit(
        f"Zotero database is locked ({operation_name}). "
        "Close Zotero or wait for sync, then retry. "
        f"Last error: {last_err}"
    )


def _load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")


def _load_skipped(path: Path) -> Set[str]:
    data = _load_json(path, {"skipped": []})
    skipped = data.get("skipped") if isinstance(data, dict) else data
    if not isinstance(skipped, list):
        return set()
    return {str(s).strip() for s in skipped if str(s).strip()}


def _save_skipped(path: Path, names: Set[str]) -> None:
    ordered = sorted(names, key=str.casefold)
    _save_json(
        path,
        {
            "skipped": ordered,
            "updated": datetime.now().isoformat(timespec="seconds"),
        },
    )


def scan_library(
    db_path: Path,
    *,
    include_unmatched: bool = False,
    skipped_names: Optional[Set[str]] = None,
) -> List[SplitSuggestion]:
    """Read creators from SQLite and return grouped split suggestions."""
    conn = _connect_readonly(db_path)
    try:
        # Well-formed two-field authors for the match index
        rows = _execute_with_lock_retry(
            conn,
            """
            SELECT DISTINCT c.lastName, c.firstName
            FROM creators c
            JOIN itemCreators ic ON c.creatorID = ic.creatorID
            WHERE ic.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND TRIM(IFNULL(c.firstName, '')) != ''
              AND TRIM(IFNULL(c.lastName, '')) != ''
            """,
            operation_name="wellformed author index",
        )
        authors: List[WellFormedAuthor] = []
        for last, first in rows:
            wf = wellformed_from_sqlite_row(last, first)
            if wf:
                authors.append(wf)
        index = build_wellformed_index(authors)

        # fieldMode may be missing on very old DBs — detect columns
        col_rows = _execute_with_lock_retry(
            conn,
            "PRAGMA table_info(creators)",
            operation_name="creators schema",
        )
        col_names = {r[1] for r in col_rows}
        has_field_mode = "fieldMode" in col_names
        field_mode_select = "c.fieldMode" if has_field_mode else "NULL AS fieldMode"

        item_rows = _execute_with_lock_retry(
            conn,
            f"""
            SELECT
                i.key,
                IFNULL(title_v.value, '') AS title,
                c.lastName,
                c.firstName,
                {field_mode_select},
                ct.creatorType,
                ic.orderIndex
            FROM items i
            JOIN itemCreators ic ON i.itemID = ic.itemID
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            LEFT JOIN itemData id_title
                ON i.itemID = id_title.itemID
               AND id_title.fieldID = (
                    SELECT fieldID FROM fields WHERE fieldName = 'title' LIMIT 1
               )
            LEFT JOIN itemDataValues title_v
                ON id_title.valueID = title_v.valueID
            WHERE i.itemID NOT IN (SELECT itemID FROM deletedItems)
              AND i.itemTypeID NOT IN (
                    SELECT itemTypeID FROM itemTypes
                    WHERE typeName IN ('attachment', 'note', 'annotation')
              )
            ORDER BY c.lastName, c.firstName, i.key, ic.orderIndex
            """,
            operation_name="creator scan",
        )
    finally:
        conn.close()

    suggestions: List[SplitSuggestion] = []
    for key, title, last, first, field_mode, creator_type, _order in item_rows:
        # Coerce early: lastName may be a digit string or (rarely) a non-str.
        last_s = as_name_str(last)
        first_s = as_name_str(first)
        fm = int(field_mode) if field_mode is not None else None
        if not is_malformed_personal_creator(last_s, first_s, field_mode=fm):
            continue
        raw = last_s  # one-field persons live in lastName in SQLite
        sug = suggest_split(raw, index)
        if sug is None:
            continue
        sug.item_keys = [str(key)]
        sug.creator_types = [str(creator_type or "author")]
        if title:
            sug.sample_titles = [str(title)[:120]]
        suggestions.append(sug)

    return group_suggestions(
        suggestions,
        include_unmatched=include_unmatched,
        skipped_names=skipped_names,
    )


def suggestions_to_dict(suggestions: List[SplitSuggestion]) -> Dict[str, Any]:
    groups = []
    for s in suggestions:
        groups.append(
            {
                "original": s.original,
                "suggested_last_name": s.last_name,
                "suggested_first_name": s.first_name,
                "confidence": s.confidence,
                "match_reason": s.match_reason,
                "item_keys": list(s.item_keys),
                "item_count": len(s.item_keys),
                "creator_types": list(s.creator_types),
                "sample_titles": list(s.sample_titles),
                "approved": None,
            }
        )
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "group_count": len(groups),
        "item_count": sum(g["item_count"] for g in groups),
        "groups": groups,
    }


def dict_to_approved_plans(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Return groups with approved True (or approved edits)."""
    plans = []
    for g in data.get("groups") or []:
        if g.get("approved") is not True:
            continue
        plans.append(g)
    return plans


def print_scan_summary(data: Dict[str, Any]) -> None:
    groups = data.get("groups") or []
    print(f"Candidates: {data.get('group_count', 0)} name groups "
          f"across {data.get('item_count', 0)} item(s)")
    if not groups:
        print("0 candidates — library looks clean for this check.")
        return
    for i, g in enumerate(groups, 1):
        conf = g.get("confidence", "?")
        print(
            f"  {i}. [{conf}] {g.get('original')!r} "
            f"-> {g.get('suggested_last_name')}, {g.get('suggested_first_name')} "
            f"({g.get('item_count', 0)} item(s))"
        )
        reason = g.get("match_reason") or ""
        if reason:
            print(f"      {reason}")
        titles = g.get("sample_titles") or []
        for t in titles[:2]:
            print(f"      e.g. {t}")


def interactive_review(
    data: Dict[str, Any],
    skipped_path: Path,
) -> Tuple[Dict[str, Any], Set[str]]:
    """Walk groups; return updated data and newly skipped originals."""
    skipped = _load_skipped(skipped_path)
    groups = data.get("groups") or []
    if not groups:
        return data, skipped

    print("\nReview each suggestion:")
    print("  y = approve  n = skip (remember)  e = edit first/last")
    print("  a = approve all remaining  q = quit review (keep decisions so far)\n")

    approve_rest = False
    for idx, g in enumerate(groups):
        if g.get("approved") is True:
            continue
        if approve_rest:
            g["approved"] = True
            continue

        original = g.get("original", "")
        print(
            f"[{idx + 1}/{len(groups)}] {original!r}\n"
            f"  -> last={g.get('suggested_last_name')!r} "
            f"first={g.get('suggested_first_name')!r}\n"
            f"  confidence={g.get('confidence')}  items={g.get('item_count')}\n"
            f"  {g.get('match_reason', '')}"
        )
        while True:
            choice = input("  [y/n/e/a/q] ").strip().casefold()
            if choice in ("y", "yes"):
                g["approved"] = True
                break
            if choice in ("n", "no"):
                g["approved"] = False
                if original:
                    skipped.add(original)
                break
            if choice == "e":
                new_last = input(
                    f"  lastName [{g.get('suggested_last_name')}]: "
                ).strip()
                new_first = input(
                    f"  firstName [{g.get('suggested_first_name')}]: "
                ).strip()
                if new_last:
                    g["suggested_last_name"] = new_last
                if new_first:
                    g["suggested_first_name"] = new_first
                g["approved"] = True
                g["match_reason"] = "manually edited during review"
                break
            if choice == "a":
                g["approved"] = True
                approve_rest = True
                break
            if choice == "q":
                return data, skipped
            print("  Enter y, n, e, a, or q.")

    return data, skipped


def _fetch_item(
    processor: ZoteroPaperProcessor, item_key: str
) -> Optional[Dict[str, Any]]:
    import requests

    r = requests.get(
        f"{processor.base_url}/items/{item_key}",
        headers=processor.headers,
        timeout=30,
    )
    if r.status_code != 200:
        print(f"  WARN GET {item_key}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        return None
    return r.json()


def build_item_change_plans(
    processor: ZoteroPaperProcessor,
    approved_groups: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    For each approved group, GET items and build before/after creators payloads.
    """
    # Map item_key -> list of (original, last, first)
    by_item: Dict[str, List[Tuple[str, str, str]]] = {}
    for g in approved_groups:
        original = str(g.get("original") or "").strip()
        last = str(g.get("suggested_last_name") or "").strip()
        first = str(g.get("suggested_first_name") or "").strip()
        if not original or not last or not first:
            continue
        for key in g.get("item_keys") or []:
            by_item.setdefault(str(key), []).append((original, last, first))

    plans: List[Dict[str, Any]] = []
    for item_key, fixes in by_item.items():
        item = _fetch_item(processor, item_key)
        if not item:
            plans.append(
                {
                    "key": item_key,
                    "error": "get_failed",
                    "title": "",
                    "version": None,
                    "creators_before": None,
                    "creators_after": None,
                    "status": "get_failed",
                }
            )
            continue
        data = item.get("data") or {}
        creators_before = list(data.get("creators") or [])
        creators_after = creators_before
        for original, last, first in fixes:
            creators_after = replace_malformed_creator(
                creators_after, original, last, first
            )
        plans.append(
            {
                "key": item_key,
                "title": (data.get("title") or "")[:200],
                "version": item.get("version"),
                "creators_before": creators_before,
                "creators_after": creators_after,
                "status": "planned",
            }
        )
        time.sleep(0.05)
    return plans


def apply_plans(
    processor: ZoteroPaperProcessor,
    plans: List[Dict[str, Any]],
    *,
    dry_run: bool = False,
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Apply planned creator changes; return updated plans and stats."""
    stats = {
        "applied": 0,
        "skip_already_applied": 0,
        "skip_changed": 0,
        "skip_noop": 0,
        "failed": 0,
        "get_failed": 0,
    }
    results: List[Dict[str, Any]] = []

    for plan in plans:
        if plan.get("status") == "get_failed" or plan.get("creators_before") is None:
            stats["get_failed"] += 1
            results.append(plan)
            continue

        # Fresh GET for safety
        item = _fetch_item(processor, plan["key"])
        if not item:
            plan = {**plan, "status": "get_failed"}
            stats["get_failed"] += 1
            results.append(plan)
            continue

        data = item.get("data") or {}
        current = data.get("creators") or []
        before = plan["creators_before"]
        after = plan["creators_after"]

        if before == after:
            plan = {**plan, "status": "skip_noop", "version": item.get("version")}
            stats["skip_noop"] += 1
            results.append(plan)
            continue

        action = decide_apply_action(current, before, after)
        if action == "skip_already_applied":
            plan = {
                **plan,
                "status": "skip_already_applied",
                "version": item.get("version"),
            }
            stats["skip_already_applied"] += 1
            results.append(plan)
            continue
        if action == "skip_changed":
            plan = {
                **plan,
                "status": "skip_changed",
                "version": item.get("version"),
                "creators_current": current,
            }
            stats["skip_changed"] += 1
            results.append(plan)
            print(
                f"  skip_changed {plan['key']}: creators edited since scan",
                file=sys.stderr,
            )
            continue

        if dry_run:
            plan = {**plan, "status": "would_apply", "version": item.get("version")}
            stats["applied"] += 1
            results.append(plan)
            continue

        ok = processor.update_item_field(plan["key"], "creators", after)
        if ok:
            plan = {**plan, "status": "applied", "version": item.get("version")}
            stats["applied"] += 1
        else:
            plan = {**plan, "status": "failed", "version": item.get("version")}
            stats["failed"] += 1
            print(f"  FAILED PATCH {plan['key']}", file=sys.stderr)
        results.append(plan)
        time.sleep(0.1)

    return results, stats


def revert_backup(
    processor: ZoteroPaperProcessor,
    backup: Dict[str, Any],
) -> Dict[str, int]:
    stats = {
        "reverted": 0,
        "skip_already_reverted": 0,
        "skip_changed": 0,
        "failed": 0,
        "get_failed": 0,
        "skipped_not_applied": 0,
    }
    for entry in backup.get("items") or []:
        # Only revert entries that were applied (or legacy backups without status)
        status = entry.get("status")
        if status not in (None, "applied", "would_apply"):
            if status and status.startswith("skip"):
                stats["skipped_not_applied"] += 1
                continue

        key = entry.get("key")
        before = entry.get("creators_before")
        after = entry.get("creators_after")
        if not key or before is None or after is None:
            stats["get_failed"] += 1
            continue

        item = _fetch_item(processor, key)
        if not item:
            stats["get_failed"] += 1
            continue
        current = (item.get("data") or {}).get("creators") or []
        action = decide_revert_action(current, before, after)
        if action == "skip_already_reverted":
            stats["skip_already_reverted"] += 1
            continue
        if action == "skip_changed":
            stats["skip_changed"] += 1
            print(f"  skip_changed {key}: not reverting (edited since apply)", file=sys.stderr)
            continue
        ok = processor.update_item_field(key, "creators", before)
        if ok:
            stats["reverted"] += 1
        else:
            stats["failed"] += 1
            print(f"  FAILED revert PATCH {key}", file=sys.stderr)
        time.sleep(0.1)
    return stats


def _write_backup(plans: List[Dict[str, Any]], *, note: str) -> Path:
    BACKUPS_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = BACKUPS_DIR / f"creators-{ts}.json"
    # Never overwrite
    if path.exists():
        path = BACKUPS_DIR / f"creators-{ts}-{int(time.time())}.json"
    payload = {
        "created": datetime.now().isoformat(timespec="seconds"),
        "note": note,
        "item_count": len(plans),
        "items": plans,
    }
    _save_json(path, payload)
    return path


def _confirm(prompt: str) -> bool:
    ans = input(f"{prompt} [y/N] ").strip().casefold()
    return ans in ("y", "yes")


def main() -> None:
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument(
        "--review",
        action="store_true",
        help="Interactive approve/skip/edit, then optional apply",
    )
    p.add_argument(
        "--apply-approved",
        metavar="FILE",
        help="Apply groups marked approved=true in a review JSON (writes backup first)",
    )
    p.add_argument(
        "--revert",
        metavar="BACKUP",
        help="Revert from a creators-*.json backup (only if still matches after)",
    )
    p.add_argument(
        "--include-unmatched",
        action="store_true",
        help="Also show medium-confidence heuristic splits (no library twin)",
    )
    p.add_argument(
        "--include-skipped",
        action="store_true",
        help="Include names previously skipped with 'n'",
    )
    p.add_argument(
        "--suggestions-out",
        type=Path,
        default=DEFAULT_SUGGESTIONS_PATH,
        help=f"Where to write scan/review JSON (default: {DEFAULT_SUGGESTIONS_PATH})",
    )
    p.add_argument(
        "--skipped-file",
        type=Path,
        default=DEFAULT_SKIPPED_PATH,
        help=f"Skip-memory JSON (default: {DEFAULT_SKIPPED_PATH})",
    )
    args = p.parse_args()

    if args.revert:
        backup_path = Path(args.revert)
        if not backup_path.is_file():
            raise SystemExit(f"Backup not found: {backup_path}")
        backup = _load_json(backup_path, {})
        if not _confirm(f"Revert creators from {backup_path}?"):
            print("Aborted.")
            return
        processor = ZoteroPaperProcessor()
        stats = revert_backup(processor, backup)
        print("Revert summary:", stats)
        return

    if args.apply_approved:
        path = Path(args.apply_approved)
        if not path.is_file():
            raise SystemExit(f"Review file not found: {path}")
        data = _load_json(path, {})
        approved = dict_to_approved_plans(data)
        if not approved:
            print("No groups with approved=true in", path)
            return
        print(f"Approved groups: {len(approved)}")
        if not _confirm("Apply these creator fixes to Zotero via Web API?"):
            print("Aborted.")
            return
        processor = ZoteroPaperProcessor()
        plans = build_item_change_plans(processor, approved)
        # Backup planned state before writes
        backup_path = _write_backup(plans, note=f"apply-approved from {path}")
        print(f"Backup written: {backup_path}")
        results, stats = apply_plans(processor, plans, dry_run=False)
        # Refresh backup with final statuses
        _save_json(
            backup_path,
            {
                "created": datetime.now().isoformat(timespec="seconds"),
                "note": f"apply-approved from {path}",
                "item_count": len(results),
                "items": results,
                "stats": stats,
            },
        )
        print("Apply summary:", stats)
        print(f"Backup updated: {backup_path}")
        return

    # Scan (and optional review)
    db_path = _db_path_from_config()
    print(f"Scanning Zotero DB (read-only): {db_path}")
    skipped: Set[str] = set()
    if not args.include_skipped:
        skipped = _load_skipped(args.skipped_file)
        if skipped:
            print(f"Hiding {len(skipped)} previously skipped name(s) "
                  f"(use --include-skipped to show)")

    suggestions = scan_library(
        db_path,
        include_unmatched=args.include_unmatched,
        skipped_names=skipped if not args.include_skipped else None,
    )
    data = suggestions_to_dict(suggestions)
    print_scan_summary(data)
    _save_json(args.suggestions_out, data)
    print(f"Suggestions written: {args.suggestions_out}")

    if not args.review:
        if data.get("group_count"):
            print("\nNext: python scripts/fix_zotero_author_name_order.py --review")
        return

    data, skipped = interactive_review(data, args.skipped_file)
    _save_skipped(args.skipped_file, skipped)
    _save_json(args.suggestions_out, data)
    print(f"Review saved: {args.suggestions_out}")
    print(f"Skip memory: {args.skipped_file} ({len(skipped)} name(s))")

    approved = dict_to_approved_plans(data)
    if not approved:
        print("No approvals — nothing to apply.")
        return

    print(f"\nApproved: {len(approved)} name group(s)")
    if not _confirm("Apply approved fixes to Zotero via Web API now?"):
        print("Skipped apply. Later:")
        print(
            f"  python scripts/fix_zotero_author_name_order.py "
            f"--apply-approved {args.suggestions_out}"
        )
        return

    processor = ZoteroPaperProcessor()
    plans = build_item_change_plans(processor, approved)
    backup_path = _write_backup(plans, note="review apply")
    print(f"Backup written: {backup_path}")
    results, stats = apply_plans(processor, plans, dry_run=False)
    _save_json(
        backup_path,
        {
            "created": datetime.now().isoformat(timespec="seconds"),
            "note": "review apply",
            "item_count": len(results),
            "items": results,
            "stats": stats,
        },
    )
    print("Apply summary:", stats)
    print(f"Backup: {backup_path}")
    print(
        f"Revert later if needed:\n"
        f"  python scripts/fix_zotero_author_name_order.py --revert {backup_path}"
    )


if __name__ == "__main__":
    main()
