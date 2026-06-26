"""Tests for import_arxiv_papers.py helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.import_arxiv_papers import parse_arxiv_id


class TestParseArxivId:
    def test_abs_url(self):
        assert parse_arxiv_id("https://arxiv.org/abs/2005.11401") == "2005.11401"

    def test_pdf_url(self):
        assert parse_arxiv_id("https://arxiv.org/pdf/2310.11511.pdf") == "2310.11511"

    def test_bare_id(self):
        assert parse_arxiv_id("2212.10496") == "2212.10496"

    def test_arxiv_prefix(self):
        assert parse_arxiv_id("arxiv:2404.16130") == "2404.16130"

    def test_invalid(self):
        assert parse_arxiv_id("not-an-arxiv-id") is None
