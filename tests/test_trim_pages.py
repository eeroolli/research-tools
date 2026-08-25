"""Tests for trim page-spec parsing and mapping."""

from __future__ import annotations

import pytest

from shared_tools.pdf.trim_pages import (
    TrimPageSpecError,
    filter_trim_pages_to_count,
    format_page_list,
    map_current_view_to_source,
    parse_page_spec,
    union_trim_pages,
)


def test_parse_single_page():
    assert parse_page_spec("1", 10) == [1]
    assert parse_page_spec("3", 10) == [3]


def test_parse_ranges_and_list():
    assert parse_page_spec("1, 4-5, 11, 13", 20) == [1, 4, 5, 11, 13]
    assert parse_page_spec("1-3", 10) == [1, 2, 3]


def test_parse_end_and_minus_one():
    assert parse_page_spec("end", 6) == [6]
    assert parse_page_spec("-1", 6) == [6]
    assert parse_page_spec("1, end", 6) == [1, 6]


def test_parse_rejects_out_of_range():
    with pytest.raises(TrimPageSpecError, match="out of range"):
        parse_page_spec("11", 10)


def test_parse_rejects_zero():
    with pytest.raises(TrimPageSpecError, match="out of range"):
        parse_page_spec("0", 10)


def test_parse_rejects_drop_all():
    with pytest.raises(TrimPageSpecError, match="cannot drop all"):
        parse_page_spec("1-5", 5)


def test_parse_rejects_junk():
    with pytest.raises(TrimPageSpecError, match="invalid"):
        parse_page_spec("abc", 10)


def test_parse_empty():
    assert parse_page_spec("", 10) == []
    assert parse_page_spec("  ", 10) == []


def test_format_page_list():
    assert format_page_list([1, 4, 5, 11, 13]) == "1, 4-5, 11, 13"
    assert format_page_list([1, 2, 3]) == "1-3"
    assert format_page_list([]) == ""


def test_filter_trim_pages_to_count():
    assert filter_trim_pages_to_count([1, 5, 99], 10) == [1, 5]
    assert filter_trim_pages_to_count([20], 5) == []


def test_map_current_view_to_source_end():
    # Source 6 pages, already dropped page 1 → current view has 5 pages
    # current-view "end" (5) → source page 6
    mapped = map_current_view_to_source([5], [1], 6)
    assert mapped == [6]
    assert union_trim_pages([1], mapped) == [1, 6]


def test_map_current_view_middle_pages():
    # Dropped [1, 3]; remaining source = [2, 4, 5, 6]
    # current-view page 2 → source 4
    assert map_current_view_to_source([2], [1, 3], 6) == [4]
