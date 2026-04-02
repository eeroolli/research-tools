#!/usr/bin/env python3
"""
Backfill missing Zotero linked-file PDF attachments using scanned_papers_log.csv.

For every log row whose status == 'success', the script checks whether the
expected linked-file PDF attachment already exists in Zotero.  If it is
missing the script can attach it and re-verify.

Modes
-----
--dry-run   (default) Report what would be done; write a recovery CSV.
--apply     Actually attach missing PDFs, then re-verify and update the CSV.

Date filtering
--------------
--since DATETIME   Only consider log rows from this point forward.
                   Format: YYYY-MM-DD  or  YYYY-MM-DDTHH:MM:SS
                   Default: yesterday at 00:00 local time.
--all              Process all 'success' rows regardless of date.

Output
------
data/logs/backfill_recovery.csv – one row per item checked:
  parent_key, final_filename, expected_path, action, detail

Run this script in PowerShell (not WSL) so path conversions are reliable.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


# ---------------------------------------------------------------------------
# Config helpers
# ---------------------------------------------------------------------------

def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    cfg.read([ROOT / "config.conf", ROOT / "config.personal.conf"])
    return cfg


def _log_folder(cfg: configparser.ConfigParser) -> Path:
    raw = cfg.get("PATHS", "log_folder", fallback="./data/logs").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p.resolve()


def _publications_windows_path(cfg: configparser.ConfigParser, processor: ZoteroPaperProcessor) -> str:
    """Return the Windows-format publications directory path."""
    raw = cfg.get("PATHS", "publications_dir", fallback="").strip()
    if not raw:
        sys.exit("❌  PATHS.publications_dir is not configured.")
    return processor._convert_wsl_to_windows_path(raw)


# ---------------------------------------------------------------------------
# Log reading
# ---------------------------------------------------------------------------

def _read_log(log_path: Path) -> List[Dict[str, str]]:
    if not log_path.exists():
        sys.exit(f"❌  Log file not found: {log_path}")
    rows = []
    with open(log_path, newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter=";", quotechar='"')
        for row in reader:
            rows.append(dict(row))
    return rows


def _parse_since(value: str) -> datetime:
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    sys.exit(f"❌  Cannot parse --since value: {value!r}  (use YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS)")


def _filter_rows(rows: List[Dict[str, str]], since: Optional[datetime], process_all: bool) -> List[Dict[str, str]]:
    filtered = [r for r in rows if r.get("status") == "success" and r.get("zotero_item_code") and r.get("final_filename")]
    if process_all or since is None:
        return filtered
    result = []
    for row in filtered:
        ts_raw = row.get("timestamp", "")
        try:
            ts = datetime.fromisoformat(ts_raw)
            # Strip timezone if present for comparison with naive since
            if ts.tzinfo is not None:
                ts = ts.replace(tzinfo=None)
        except ValueError:
            continue
        if ts >= since:
            result.append(row)
    return result


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _expected_windows_path(publications_win: str, final_filename: str) -> str:
    """Build the Windows path Zotero should have for this attachment."""
    pub = publications_win.rstrip("\\").rstrip("/")
    return f"{pub}\\{final_filename}"


# ---------------------------------------------------------------------------
# Recovery CSV
# ---------------------------------------------------------------------------

RECOVERY_FIELDS = [
    "timestamp",
    "parent_key",
    "final_filename",
    "expected_path",
    "existing_linked_pdf_count",
    "action",
    "detail",
]


def _write_recovery_csv(path: Path, rows: List[Dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=RECOVERY_FIELDS, delimiter=";", quotechar='"', quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(rows)
    print(f"\n📄 Recovery CSV written: {path}")


# ---------------------------------------------------------------------------
# Core logic
# ---------------------------------------------------------------------------

def _count_linked_pdfs(children: List[Dict[str, Any]]) -> int:
    count = 0
    for child in children:
        data = child.get("data") or {}
        if data.get("itemType") == "attachment" and data.get("linkMode") == "linked_file":
            count += 1
    return count


def _process_row(
    row: Dict[str, str],
    processor: ZoteroPaperProcessor,
    publications_win: str,
    apply: bool,
    verbose: bool,
) -> Dict[str, str]:
    """Check one log row; attach if apply=True and PDF is missing."""
    parent_key = row["zotero_item_code"].strip()
    final_filename = row["final_filename"].strip()
    expected_path = _expected_windows_path(publications_win, final_filename)
    ts_now = datetime.now().isoformat(timespec="seconds")

    result_row: Dict[str, str] = {
        "timestamp": ts_now,
        "parent_key": parent_key,
        "final_filename": final_filename,
        "expected_path": expected_path,
        "existing_linked_pdf_count": "?",
        "action": "unknown",
        "detail": "",
    }

    # Fetch children
    try:
        children = processor.fetch_item_children(parent_key)
    except Exception as exc:
        result_row["action"] = "error"
        result_row["detail"] = f"fetch_children failed: {exc}"
        if verbose:
            print(f"  ❌ {parent_key}: {exc}")
        return result_row

    existing_count = _count_linked_pdfs(children)
    result_row["existing_linked_pdf_count"] = str(existing_count)

    already_linked = ZoteroPaperProcessor.linked_pdf_exists(children, expected_path)

    if already_linked:
        result_row["action"] = "ok_already_linked"
        if verbose:
            print(f"  ✅ {parent_key}  {final_filename}  (already linked)")
        return result_row

    # PDF is missing
    if not apply:
        result_row["action"] = "dry_run_would_attach"
        result_row["detail"] = f"No child matching {expected_path!r}"
        if verbose:
            print(f"  📋 {parent_key}  {final_filename}  → would attach (dry-run)")
        return result_row

    # Apply: attach and re-verify
    print(f"  📎 {parent_key}  {final_filename}  → attaching…")
    try:
        attach_result = processor.attach_pdf_to_existing(parent_key, expected_path)
    except Exception as exc:
        result_row["action"] = "attach_error"
        result_row["detail"] = f"attach_pdf_to_existing raised: {exc}"
        print(f"     ❌ attach exception: {exc}")
        return result_row

    if not attach_result.get("ok"):
        result_row["action"] = "attach_failed"
        result_row["detail"] = attach_result.get("error") or "Zotero returned failure"
        print(f"     ❌ attach failed: {result_row['detail']}")
        return result_row

    # Re-verify
    try:
        children2 = processor.fetch_item_children(parent_key)
    except Exception as exc:
        result_row["action"] = "attached_verify_error"
        result_row["detail"] = f"Attached OK but re-fetch failed: {exc}"
        print(f"     ⚠️  attached, but re-verify fetch failed: {exc}")
        return result_row

    sent_path = attach_result.get("sent_path", expected_path)
    if ZoteroPaperProcessor.linked_pdf_exists(children2, sent_path):
        result_row["action"] = "attached_verified"
        result_row["detail"] = f"sent_path={sent_path!r}"
        print(f"     ✅ attached and verified")
    else:
        result_row["action"] = "attached_not_verified"
        result_row["detail"] = (
            f"Attached (keys={attach_result.get('attachment_keys')}) "
            f"but child not found for sent_path={sent_path!r}"
        )
        print(f"     ⚠️  attached but linkage not verified")

    return result_row


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--dry-run", dest="apply", action="store_false", default=False,
                            help="Report only (default)")
    mode_group.add_argument("--apply", dest="apply", action="store_true",
                            help="Actually attach missing PDFs")

    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--since", metavar="DATETIME",
                            help="Process rows from this datetime onward (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS). "
                                 "Default: yesterday 00:00 local time.")
    date_group.add_argument("--all", dest="process_all", action="store_true",
                            help="Process all 'success' rows regardless of date")

    parser.add_argument("--verbose", "-v", action="store_true", help="Print one line per item")
    args = parser.parse_args()

    # Default since = yesterday 00:00
    since: Optional[datetime]
    if args.process_all:
        since = None
    elif args.since:
        since = _parse_since(args.since)
    else:
        yesterday = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
        since = yesterday

    # Setup
    cfg = _load_config()
    processor = ZoteroPaperProcessor()
    publications_win = _publications_windows_path(cfg, processor)
    log_path = _log_folder(cfg) / "scanned_papers_log.csv"
    recovery_path = _log_folder(cfg) / "backfill_recovery.csv"

    print(f"📁 Log       : {log_path}")
    print(f"📁 Recovery  : {recovery_path}")
    print(f"📁 Publications (Windows): {publications_win}")
    if since:
        print(f"🗓  Since     : {since}")
    else:
        print(f"🗓  Since     : all rows")
    print(f"{'🚀 Mode: APPLY' if args.apply else '🔍 Mode: DRY-RUN (use --apply to make changes)'}")
    print()

    rows = _read_log(log_path)
    to_process = _filter_rows(rows, since, args.process_all)
    print(f"Rows to check: {len(to_process)}")

    if not to_process:
        print("Nothing to do.")
        return

    recovery_rows: List[Dict[str, str]] = []
    counts = {"ok_already_linked": 0, "would_attach": 0, "attached_verified": 0,
              "attached_not_verified": 0, "attach_failed": 0, "errors": 0}

    for i, row in enumerate(to_process, 1):
        if not args.verbose:
            print(f"\r  {i}/{len(to_process)}", end="", flush=True)
        result = _process_row(row, processor, publications_win, args.apply, args.verbose)
        recovery_rows.append(result)
        action = result.get("action", "")
        if action == "ok_already_linked":
            counts["ok_already_linked"] += 1
        elif action == "dry_run_would_attach":
            counts["would_attach"] += 1
        elif action == "attached_verified":
            counts["attached_verified"] += 1
        elif action == "attached_not_verified":
            counts["attached_not_verified"] += 1
        elif action in ("attach_failed", "attach_error"):
            counts["attach_failed"] += 1
        elif action in ("error", "attached_verify_error"):
            counts["errors"] += 1

    if not args.verbose:
        print()

    _write_recovery_csv(recovery_path, recovery_rows)

    print("\n── Summary ──────────────────────────────────────────────────")
    print(f"  Already linked    : {counts['ok_already_linked']}")
    if args.apply:
        print(f"  Attached+verified : {counts['attached_verified']}")
        print(f"  Attached,unverified: {counts['attached_not_verified']}")
        print(f"  Attach failed     : {counts['attach_failed']}")
    else:
        print(f"  Would attach      : {counts['would_attach']}")
        if counts['would_attach']:
            print(f"\n  ⚠️  Re-run with --apply to attach the missing PDFs.")
    if counts["errors"]:
        print(f"  Errors            : {counts['errors']}")
    print("─────────────────────────────────────────────────────────────")


if __name__ == "__main__":
    main()
