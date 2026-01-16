"""UI helpers for enrichment interactions (selection parsing, etc.)."""

from __future__ import annotations

from typing import List, Set


def parse_index_selection(text: str, max_idx: int) -> List[int]:
    """Parse selections like '1,3-5' into sorted unique indices (1-based).

    - Accepts comma-separated values
    - Accepts ranges like '3-5'
    - Ignores invalid tokens silently
    """
    if not text:
        return []
    parts = [p.strip() for p in text.replace(" ", "").split(",") if p.strip()]
    out: Set[int] = set()
    for p in parts:
        if "-" in p:
            a, b = p.split("-", 1)
            if a.isdigit() and b.isdigit():
                lo, hi = int(a), int(b)
                if lo > hi:
                    lo, hi = hi, lo
                for i in range(lo, hi + 1):
                    if 1 <= i <= max_idx:
                        out.add(i)
        else:
            if p.isdigit():
                i = int(p)
                if 1 <= i <= max_idx:
                    out.add(i)
    return sorted(out)


def clear_enrichment_context(ctx: dict) -> None:
    """Remove enrichment-related keys from a navigation context dict."""
    ctx.pop("enrichment", None)

