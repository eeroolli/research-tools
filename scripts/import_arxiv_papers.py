#!/usr/bin/env python3
"""
Batch import arXiv papers: download PDF to publications_dir, create/link Zotero items.

Modes
-----
--dry-run   (default) Report planned actions; write manifest CSV.
--apply     Download PDFs and create/attach Zotero linked files.

Input
-----
Positional arXiv URLs/IDs and/or --file path (markdown/text; extracts arxiv.org links).

Output
------
data/logs/arxiv_import_manifest.csv
data/logs/arxiv_import_links.txt

Run in PowerShell (not WSL) so P:\\ NAS paths are reliable.
"""

from __future__ import annotations

import argparse
import configparser
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from shared_tools.api.arxiv_client import ArxivClient
from shared_tools.config.io import read_config_files
from shared_tools.utils.filename_generator import FilenameGenerator
from shared_tools.utils.identifier_validator import IdentifierValidator
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor

ARXIV_URL_RE = re.compile(
    r"https?://(?:www\.)?arxiv\.org/(?:abs|pdf)/([^\s\])>\"']+)",
    re.IGNORECASE,
)
ARXIV_ID_RE = re.compile(
    r"(?:arxiv:\s*)?"
    r"(\d{4}\.\d{4,5}(?:v\d+)?|[a-z\-]+(?:\.[A-Z]{2})?/\d{7}(?:v\d+)?)",
    re.IGNORECASE,
)

MANIFEST_FIELDS = [
    "arxiv_id",
    "doi",
    "filename",
    "windows_path",
    "zotero_item_key",
    "action",
    "timestamp",
    "detail",
]

ARXIV_REQUEST_DELAY_SECONDS = 3.0


def _load_config() -> configparser.ConfigParser:
    cfg = configparser.ConfigParser()
    read_config_files(cfg, [ROOT / "config.conf", ROOT / "config.personal.conf"])
    return cfg


def _log_folder(cfg: configparser.ConfigParser) -> Path:
    raw = cfg.get("PATHS", "log_folder", fallback="./data/logs").strip()
    p = Path(raw)
    if not p.is_absolute():
        p = (ROOT / p).resolve()
    return p.resolve()


def _publications_dir(cfg: configparser.ConfigParser, processor: ZoteroPaperProcessor) -> Path:
    raw = cfg.get("PATHS", "publications_dir", fallback="").strip()
    if not raw:
        sys.exit("PATHS.publications_dir is not configured.")
    win_path = processor._convert_wsl_to_windows_path(raw)
    return Path(win_path)


def _publications_windows_path(cfg: configparser.ConfigParser, processor: ZoteroPaperProcessor) -> str:
    return str(_publications_dir(cfg, processor))


def parse_arxiv_id(value: str) -> Optional[str]:
    """Extract and validate a single arXiv ID from URL or bare ID string."""
    value = value.strip()
    if not value:
        return None

    url_match = ARXIV_URL_RE.search(value)
    if url_match:
        candidate = url_match.group(1).replace(".pdf", "").split("?")[0].strip("/")
        valid, clean, _ = IdentifierValidator.validate_arxiv_id(candidate)
        return clean if valid else None

    bare = value.replace("arxiv:", "").replace("arXiv:", "").strip()
    valid, clean, _ = IdentifierValidator.validate_arxiv_id(bare)
    return clean if valid else None


def collect_arxiv_ids(args: argparse.Namespace) -> List[str]:
    """Collect unique arXiv IDs from CLI args and optional file."""
    seen: set = set()
    ordered: List[str] = []

    def _add(raw: str) -> None:
        arxiv_id = parse_arxiv_id(raw)
        if arxiv_id and arxiv_id not in seen:
            seen.add(arxiv_id)
            ordered.append(arxiv_id)

    for token in args.arxiv_refs:
        _add(token)

    if args.file:
        file_path = Path(args.file)
        if not file_path.is_file():
            sys.exit(f"Input file not found: {file_path}")
        text = file_path.read_text(encoding="utf-8")
        for match in ARXIV_URL_RE.finditer(text):
            _add(match.group(0))
        for line in text.splitlines():
            for match in ARXIV_ID_RE.finditer(line):
                if "arxiv.org" not in line.lower():
                    _add(match.group(1))

    if not ordered:
        sys.exit("No valid arXiv IDs found. Pass URLs/IDs or --file with arxiv.org links.")

    return ordered


def find_zotero_item(
    processor: ZoteroPaperProcessor,
    metadata: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Find existing Zotero item by DOI, arXiv ID, then title."""
    doi = (metadata.get("doi") or "").strip()
    if doi:
        item = processor.search_by_doi(doi)
        if item:
            return item

    arxiv_id = metadata.get("arxiv_id")
    if arxiv_id:
        item = processor.search_by_arxiv_id(arxiv_id)
        if item:
            return item

    title = metadata.get("title")
    if title:
        item = processor.search_by_title(title)
        if item:
            return item

    return None


def linked_pdf_already_attached(
    processor: ZoteroPaperProcessor,
    item_key: str,
    windows_path: str,
) -> bool:
    children = processor.fetch_item_children(item_key)
    return processor.linked_pdf_exists(children, windows_path)


def download_pdf(pdf_url: str, dest: Path, apply: bool) -> Tuple[bool, str]:
    if dest.exists():
        return True, "exists"

    if not apply:
        return True, "would_download"

    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        response = requests.get(pdf_url, timeout=120, stream=True)
        response.raise_for_status()
        with open(dest, "wb") as fh:
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    fh.write(chunk)
        return True, "downloaded"
    except requests.RequestException as exc:
        return False, str(exc)


def process_paper(
    arxiv_id: str,
    *,
    arxiv_client: ArxivClient,
    processor: ZoteroPaperProcessor,
    filename_gen: FilenameGenerator,
    publications_dir: Path,
    publications_win: str,
    apply: bool,
    skip_existing: bool,
    tag: Optional[str],
) -> Dict[str, str]:
    """Process one arXiv paper; return manifest row dict."""
    timestamp = datetime.now().isoformat(timespec="seconds")
    row: Dict[str, str] = {
        "arxiv_id": arxiv_id,
        "doi": "",
        "filename": "",
        "windows_path": "",
        "zotero_item_key": "",
        "action": "error",
        "timestamp": timestamp,
        "detail": "",
    }

    metadata = arxiv_client.get_metadata(arxiv_id)
    if not metadata:
        row["detail"] = "Failed to fetch metadata from arXiv API"
        return row

    row["doi"] = metadata.get("doi") or ""
    filename = filename_gen.generate(metadata) + ".pdf"
    row["filename"] = filename
    dest = publications_dir / filename
    windows_path = str(publications_dir / filename).replace("/", "\\")
    row["windows_path"] = windows_path

    pdf_url = metadata.get("pdf_url") or f"https://arxiv.org/pdf/{arxiv_id}.pdf"

    if skip_existing and dest.exists():
        dl_ok, dl_detail = True, "skipped_existing_file"
    else:
        dl_ok, dl_detail = download_pdf(pdf_url, dest, apply=apply)

    if not dl_ok:
        row["action"] = "download_failed"
        row["detail"] = dl_detail
        return row

    if not apply:
        existing = find_zotero_item(processor, metadata)
        if existing:
            item_key = existing["key"]
            row["zotero_item_key"] = item_key
            if linked_pdf_already_attached(processor, item_key, windows_path):
                row["action"] = "would_skip_already_linked"
            else:
                row["action"] = "would_attach"
            row["detail"] = dl_detail
        else:
            row["action"] = "would_create"
            row["detail"] = dl_detail
        return row

    if not dest.exists():
        row["action"] = "download_failed"
        row["detail"] = "PDF missing after download attempt"
        return row

    existing = find_zotero_item(processor, metadata)
    if existing:
        item_key = existing["key"]
        row["zotero_item_key"] = item_key
        if linked_pdf_already_attached(processor, item_key, windows_path):
            row["action"] = "already_linked"
            row["detail"] = dl_detail
            return row

        attach_result = processor.attach_pdf_to_existing(item_key, windows_path)
        if attach_result.get("ok"):
            row["action"] = "attached"
            row["detail"] = dl_detail
        else:
            row["action"] = "attach_failed"
            row["detail"] = attach_result.get("error", "attach failed")
        return row

    result = processor.add_paper(metadata, dest)
    item_key = result.get("item_key") or ""
    row["zotero_item_key"] = item_key

    if result.get("action") == "duplicate_skipped" and item_key:
        if linked_pdf_already_attached(processor, item_key, windows_path):
            row["action"] = "already_linked"
            row["detail"] = "duplicate item, pdf already linked"
        else:
            attach_result = processor.attach_pdf_to_existing(item_key, windows_path)
            if attach_result.get("ok"):
                row["action"] = "attached_to_duplicate"
                row["detail"] = dl_detail
            else:
                row["action"] = "attach_failed"
                row["detail"] = attach_result.get("error", "attach to duplicate failed")
        return row

    if result.get("success") and item_key:
        if tag:
            processor.update_item_tags(item_key, add_tags=[tag])
        row["action"] = result.get("action") or "created"
        row["detail"] = dl_detail
    else:
        row["action"] = "create_failed"
        row["detail"] = result.get("error") or "unknown error"

    return row


def write_manifest(rows: List[Dict[str, str]], manifest_path: Path, links_path: Path) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    write_header = not manifest_path.exists()

    with open(manifest_path, "a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MANIFEST_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(rows)

    with open(links_path, "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(
                f"arxiv:{row['arxiv_id']} -> {row['windows_path']} "
                f"[{row['action']}] key={row['zotero_item_key']}\n"
            )


def print_summary(rows: List[Dict[str, str]], apply: bool) -> None:
    mode = "APPLY" if apply else "DRY-RUN"
    print(f"\n=== arXiv import summary ({mode}) ===")
    for row in rows:
        print(
            f"  {row['arxiv_id']:>14}  {row['action']:<24}  "
            f"{row['filename'][:50]}"
        )
        if row.get("detail"):
            print(f"    detail: {row['detail']}")
    actions = {}
    for row in rows:
        actions[row["action"]] = actions.get(row["action"], 0) + 1
    print("\nCounts:", ", ".join(f"{k}={v}" for k, v in sorted(actions.items())))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Download arXiv PDFs to publications_dir and link/create Zotero items.",
    )
    parser.add_argument(
        "arxiv_refs",
        nargs="*",
        help="arXiv URLs or IDs",
    )
    parser.add_argument(
        "--file",
        help="Markdown/text file containing arxiv.org links",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Download PDFs and write to Zotero (default is dry-run)",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip PDF download when file already exists on NAS",
    )
    parser.add_argument(
        "--tag",
        help="Zotero tag to add when creating new items",
    )
    parser.add_argument(
        "--manifest",
        help="Manifest CSV path (default: data/logs/arxiv_import_manifest.csv)",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    apply = args.apply

    arxiv_ids = collect_arxiv_ids(args)
    cfg = _load_config()
    processor = ZoteroPaperProcessor()
    publications_dir = _publications_dir(cfg, processor)
    publications_win = _publications_windows_path(cfg, processor)

    if not publications_dir.exists() and apply:
        print(f"Publications directory not found: {publications_dir}")
        print("Ensure NAS is mounted (P:\\academic\\publications).")
        return 1

    log_dir = _log_folder(cfg)
    manifest_path = Path(args.manifest) if args.manifest else log_dir / "arxiv_import_manifest.csv"
    links_path = log_dir / "arxiv_import_links.txt"

    arxiv_client = ArxivClient()
    filename_gen = FilenameGenerator()

    print(f"Mode: {'APPLY' if apply else 'DRY-RUN'}")
    print(f"Papers: {len(arxiv_ids)}")
    print(f"Publications: {publications_win}")
    print(f"Manifest: {manifest_path}")

    rows: List[Dict[str, str]] = []
    for index, arxiv_id in enumerate(arxiv_ids):
        if index > 0:
            time.sleep(ARXIV_REQUEST_DELAY_SECONDS)

        print(f"\n[{index + 1}/{len(arxiv_ids)}] {arxiv_id}")
        row = process_paper(
            arxiv_id,
            arxiv_client=arxiv_client,
            processor=processor,
            filename_gen=filename_gen,
            publications_dir=publications_dir,
            publications_win=publications_win,
            apply=apply,
            skip_existing=args.skip_existing,
            tag=args.tag,
        )
        rows.append(row)
        print(f"  -> {row['action']}: {row.get('detail') or row['filename']}")

    write_manifest(rows, manifest_path, links_path)
    print_summary(rows, apply=apply)
    print(f"\nManifest written: {manifest_path}")
    print(f"Links file written: {links_path}")

    failed = [r for r in rows if r["action"] in ("error", "download_failed", "create_failed", "attach_failed")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
