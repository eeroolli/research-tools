"""Unit tests for fix_zotero_linked_pdf_attachment_titles helpers."""

from __future__ import annotations

import importlib.util
import sys
import csv
from pathlib import Path

import pytest

project_root = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def fixmod():
    path = project_root / "scripts" / "fix_zotero_linked_pdf_attachment_titles.py"
    spec = importlib.util.spec_from_file_location("fix_zotero_linked_pdf_attachment_titles", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_basename_from_zotero_path_windows(fixmod) -> None:
    assert fixmod._basename_from_zotero_path(r"I:\pub\Nosek_et_al_2007_scan.pdf") == "Nosek_et_al_2007_scan.pdf"
    assert fixmod._basename_from_zotero_path("I:/pub/file.pdf") == "file.pdf"


def test_is_eligible_pdf_linked(fixmod) -> None:
    assert fixmod._is_eligible_pdf_linked(
        {"itemType": "attachment", "linkMode": "linked_file", "path": r"C:\a\b\c.pdf"}
    )
    assert not fixmod._is_eligible_pdf_linked(
        {"itemType": "attachment", "linkMode": "linked_file", "path": r"C:\a\b\notes.txt"}
    )
    assert not fixmod._is_eligible_pdf_linked({"itemType": "note", "linkMode": "", "path": ""})


def test_needs_title_fix(fixmod) -> None:
    data = {
        "path": r"X:\pub\Paper_scan.pdf",
        "contentType": None,
    }
    assert fixmod._needs_content_type_fix(data) is True

    data_ok = {"path": r"X:\pub\Paper_scan.pdf", "contentType": "application/pdf"}
    assert fixmod._needs_content_type_fix(data_ok) is False


def test_extract_year_and_author_summary_helpers(fixmod) -> None:
    assert fixmod._extract_year("2004-01-01") == "2004"
    assert fixmod._extract_year("Spring 1998 issue") == "1998"
    assert fixmod._extract_year("") == ""

    creators = [{"firstName": "Anthony", "lastName": "Greenwald"}]
    assert fixmod._author_summary(creators) == "Anthony Greenwald"
    assert fixmod._author_summary([{"name": "Consortium Author"}]) == "Consortium Author"
    assert fixmod._author_summary([]) == ""


def test_missing_csv_roundtrip_and_dedupe_key_loading(fixmod, tmp_path: Path) -> None:
    csv_path = tmp_path / "missing_linked_files.csv"
    rows = [
        {
            "author": "A B",
            "year": "2004",
            "title": "Sample",
            "type": "journalArticle",
            "linked_file_path_in_zotero": r"I:\publications\Sample.pdf",
            "parent_key": "PARENT1",
            "attachment_key": "ATT1",
            "run_mode": "logs-only",
            "reason": "file_not_found",
            "timestamp": "2026-03-26T17:00:00",
        }
    ]
    written = fixmod._write_missing_rows(csv_path, rows)
    assert written == 1
    assert csv_path.exists()

    with open(csv_path, newline="", encoding="utf-8") as f:
        got = list(csv.DictReader(f))
    assert len(got) == 1
    assert got[0]["attachment_key"] == "ATT1"
    assert got[0]["linked_file_path_in_zotero"].endswith("Sample.pdf")

    keys = fixmod._load_existing_missing_keys(csv_path)
    assert ("ATT1", r"I:\publications\Sample.pdf") in keys
