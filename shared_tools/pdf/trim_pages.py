"""Parse and format page lists for PDF trim (drop) preprocessing.

Page numbers are 1-based indices of the post-split, pre-trim PDF.
Lone integers are page indices (3 = page 3), not "drop first N".
"""

from __future__ import annotations

from typing import List, Sequence


class TrimPageSpecError(ValueError):
    """Invalid trim page specification."""


def parse_page_spec(spec: str, page_count: int) -> List[int]:
    """Parse a page drop spec into sorted unique 1-based page indices.

    Accepted tokens (comma-separated):
      - ``1`` / ``3`` — single page
      - ``1-3`` / ``4-5`` — inclusive range
      - ``-1`` / ``end`` — last page

    Raises:
        TrimPageSpecError: on empty leftover, junk, or out-of-range pages.
    """
    if page_count < 1:
        raise TrimPageSpecError("PDF has no pages")

    raw = (spec or "").strip().lower()
    if not raw:
        return []

    pages: set[int] = set()
    for part in raw.split(","):
        tok = part.strip()
        if not tok:
            continue
        pages.update(_expand_token(tok, page_count))

    if not pages:
        return []

    sorted_pages = sorted(pages)
    for p in sorted_pages:
        if p < 1 or p > page_count:
            raise TrimPageSpecError(f"page {p} out of range 1..{page_count}")

    if len(sorted_pages) >= page_count:
        raise TrimPageSpecError(
            f"cannot drop all {page_count} page(s); leave at least one page"
        )

    return sorted_pages


def _expand_token(tok: str, page_count: int) -> List[int]:
    if tok in ("end", "-1"):
        return [page_count]

    if "-" in tok:
        # Range like 1-3; reject lone leading-minus that isn't -1 (handled above)
        a_str, b_str = tok.split("-", 1)
        a_str = a_str.strip()
        b_str = b_str.strip()
        if not a_str or not b_str:
            raise TrimPageSpecError(f"invalid range token: {tok!r}")
        if not a_str.isdigit() or not b_str.isdigit():
            raise TrimPageSpecError(f"invalid range token: {tok!r}")
        a = int(a_str)
        b = int(b_str)
        if a > b:
            raise TrimPageSpecError(f"descending range not allowed: {tok!r}")
        return list(range(a, b + 1))

    if tok.isdigit():
        return [int(tok)]

    raise TrimPageSpecError(f"invalid page token: {tok!r}")


def format_page_list(pages: Sequence[int]) -> str:
    """Format sorted page numbers as compact ranges: [1,4,5,11,13] -> '1, 4-5, 11, 13'."""
    if not pages:
        return ""
    sorted_pages = sorted(set(int(p) for p in pages))
    ranges: List[str] = []
    start = prev = sorted_pages[0]
    for p in sorted_pages[1:]:
        if p == prev + 1:
            prev = p
            continue
        ranges.append(_format_range(start, prev))
        start = prev = p
    ranges.append(_format_range(start, prev))
    return ", ".join(ranges)


def _format_range(start: int, end: int) -> str:
    if start == end:
        return str(start)
    return f"{start}-{end}"


def filter_trim_pages_to_count(pages: Sequence[int], page_count: int) -> List[int]:
    """Keep only indices in 1..page_count (sorted unique)."""
    return sorted({int(p) for p in pages if 1 <= int(p) <= page_count})


def map_current_view_to_source(
    current_view_pages: Sequence[int],
    existing_trim_pages: Sequence[int],
    source_count: int,
) -> List[int]:
    """Map page numbers from the already-trimmed preview back to source indices.

    ``source_count`` is the post-split page count before any trim.
    Remaining source pages (not in ``existing_trim_pages``) are ordered 1..N
    as the current view; current-view page k maps to the k-th remaining source page.
    """
    dropped = set(int(p) for p in existing_trim_pages)
    remaining = [p for p in range(1, source_count + 1) if p not in dropped]
    mapped: List[int] = []
    for k in current_view_pages:
        k = int(k)
        if k < 1 or k > len(remaining):
            raise TrimPageSpecError(
                f"current-view page {k} out of range 1..{len(remaining)}"
            )
        mapped.append(remaining[k - 1])
    return sorted(set(mapped))


def union_trim_pages(*page_lists: Sequence[int]) -> List[int]:
    """Sorted unique union of page lists."""
    out: set[int] = set()
    for lst in page_lists:
        out.update(int(p) for p in lst)
    return sorted(out)
