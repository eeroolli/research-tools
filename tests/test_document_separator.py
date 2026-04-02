from __future__ import annotations

from pathlib import Path

import pytest

from shared_tools.pdf.document_separator import (
    SeparationPlanError,
    build_plan_from_drop_pages,
    detect_separator_pages,
    format_separation_plan,
    parse_separation_plan,
    save_as_documents,
)


def _make_pdf(tmp_path: Path, *, pages: list[dict]) -> Path:
    """Create a synthetic PDF using PyMuPDF.

    pages: list of dicts with optional keys:
      - bg_rgb: (r,g,b) floats 0..1
      - text: str
    """
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:
        pytest.skip(f"PyMuPDF not available: {exc}")

    out = tmp_path / "sample.pdf"
    doc = fitz.open()
    try:
        for p in pages:
            page = doc.new_page(width=595, height=842)  # A4-ish
            bg = p.get("bg_rgb")
            if bg is not None:
                page.draw_rect(page.rect, color=bg, fill=bg)
            txt = p.get("text")
            if txt:
                page.insert_text((72, 100), txt, fontsize=18, color=(0, 0, 0))
        doc.save(str(out))
    finally:
        doc.close()
    return out


class TestParseSeparationPlan:
    def test_explicit_partition(self):
        plan = parse_separation_plan("1-12;-13;14-31", total_pages=31)
        assert len(plan.kept_outputs) == 2
        assert plan.kept_outputs[0][0] == 1 and plan.kept_outputs[0][-1] == 12
        assert 13 in plan.dropped_pages
        assert plan.kept_outputs[1][0] == 14 and plan.kept_outputs[1][-1] == 31

    def test_multiple_outputs_drop_separators(self):
        plan = parse_separation_plan("1-5;-6;7-10;-11;12-31", total_pages=31)
        assert len(plan.kept_outputs) == 3
        assert plan.dropped_pages == {6, 11}

    def test_drop_only_shorthand(self):
        plan = parse_separation_plan(";-13;", total_pages=31)
        assert len(plan.kept_outputs) == 2
        assert plan.dropped_pages == {13}
        assert plan.kept_outputs[0] == list(range(1, 13))
        assert plan.kept_outputs[1] == list(range(14, 32))

    def test_keep_only_mode(self):
        plan = parse_separation_plan("1-12;;14-31", total_pages=31)
        assert plan.keep_only is True
        assert plan.kept_outputs[0] == list(range(1, 13))
        assert plan.kept_outputs[1] == list(range(14, 32))
        assert 13 in plan.dropped_pages

    def test_reject_missing_pages_in_explicit_mode(self):
        with pytest.raises(SeparationPlanError):
            parse_separation_plan("1-3;-4", total_pages=10)


class TestFormatSeparationPlan:
    def test_singleton_output_not_shown_as_duplicate_range(self):
        """Avoid 'pages 12–12', which reads like a length of 12."""
        plan = parse_separation_plan(";-11;", total_pages=12)
        txt = format_separation_plan(plan)
        assert "scan page 12 only" in txt
        assert "12–12" not in txt
        assert "12-12" not in txt
        assert "Total pages in this scan: 12" in txt
        assert "before writing separate outputs" in txt

    def test_range_output_shows_scan_span_and_count(self):
        plan = parse_separation_plan(";-13;", total_pages=31)
        txt = format_separation_plan(plan)
        assert "scan pages 14–31" in txt
        assert "(18 pages in this output PDF)" in txt


class TestDetectSeparatorPages:
    def test_detects_separator_text_and_vivid(self, tmp_path: Path):
        pdf = _make_pdf(
            tmp_path,
            pages=[
                {"bg_rgb": (1, 1, 1), "text": "Normal page content"},
                {"bg_rgb": (0.1, 0.6, 0.9), "text": "SEPARATOR\nDOCUMENT SEPARATOR"},
                {"bg_rgb": (1, 1, 1), "text": "More content"},
            ],
        )
        sep, drop = detect_separator_pages(pdf)
        assert sep == [1]
        assert drop == {1}

    def test_adjacent_vivid_blank_is_dropped(self, tmp_path: Path):
        # Duplex: colored blank back page next to the separator page.
        pdf = _make_pdf(
            tmp_path,
            pages=[
                {"bg_rgb": (1, 1, 1), "text": "Normal"},
                {"bg_rgb": (0.95, 0.8, 0.1), "text": "SEPARATOR"},
                {"bg_rgb": (0.95, 0.8, 0.1), "text": ""},  # vivid blank
                {"bg_rgb": (1, 1, 1), "text": "Normal 2"},
            ],
        )
        sep, drop = detect_separator_pages(pdf)
        assert sep == [1]
        assert drop == {1, 2}


class TestSaveAsDocuments:
    def test_writes_outputs_with_correct_page_counts(self, tmp_path: Path):
        pdf = _make_pdf(
            tmp_path,
            pages=[
                {"bg_rgb": (1, 1, 1), "text": "P1"},
                {"bg_rgb": (1, 1, 1), "text": "P2"},
                {"bg_rgb": (1, 1, 1), "text": "P3"},
                {"bg_rgb": (1, 1, 1), "text": "P4"},
                {"bg_rgb": (1, 1, 1), "text": "P5"},
                {"bg_rgb": (1, 1, 1), "text": "P6"},
            ],
        )
        plan = build_plan_from_drop_pages(total_pages=6, drop_pages_1based=[3])
        out1 = tmp_path / "out__part1.pdf"
        out2 = tmp_path / "out__part2.pdf"
        written = save_as_documents(pdf, plan, out_dir=tmp_path, output_paths=[out1, out2])
        assert written == [out1, out2]

        import fitz

        d1 = fitz.open(str(out1))
        d2 = fitz.open(str(out2))
        try:
            assert len(d1) == 2  # pages 1-2
            assert len(d2) == 3  # pages 4-6
        finally:
            d1.close()
            d2.close()

        # Smoke: formatted plan includes drop page
        txt = format_separation_plan(plan)
        assert "Drop" in txt
