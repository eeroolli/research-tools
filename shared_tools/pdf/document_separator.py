from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence, Set, Tuple


# -----------------------------------------------------------------------------
# Document separation plan model (distinct from landscape/two-up page splitting)
# -----------------------------------------------------------------------------


@dataclass(frozen=True)
class SeparationPlan:
    """A fully-interpreted separation plan for a PDF with N scan pages (1-based).

    - kept_outputs: each inner list is the ordered list of scan page numbers
      that will be written into one output PDF.
    - dropped_pages: scan pages that will be omitted from all outputs.
    - keep_only: when True, any page not explicitly kept is implicitly dropped.
    """

    total_pages: int
    kept_outputs: List[List[int]]
    dropped_pages: Set[int]
    keep_only: bool = False

    def kept_pages_set(self) -> Set[int]:
        s: Set[int] = set()
        for group in self.kept_outputs:
            s.update(group)
        return s


class SeparationPlanError(ValueError):
    pass


# -----------------------------------------------------------------------------
# Separation plan parser
# -----------------------------------------------------------------------------


def _normalize_ws(s: str) -> str:
    return " ".join((s or "").strip().split())


def _expand_range_token(tok: str) -> List[int]:
    tok = tok.strip()
    if not tok:
        return []
    if "-" in tok:
        a_str, b_str = tok.split("-", 1)
        a_str = a_str.strip()
        b_str = b_str.strip()
        if not a_str.isdigit() or not b_str.isdigit():
            raise SeparationPlanError(f"Invalid range token: {tok!r}")
        a = int(a_str)
        b = int(b_str)
        if a <= b:
            return list(range(a, b + 1))
        # allow descending? prefer to reject to avoid surprises
        raise SeparationPlanError(f"Descending range not allowed: {tok!r}")
    if not tok.isdigit():
        raise SeparationPlanError(f"Invalid page token: {tok!r}")
    return [int(tok)]


def _parse_page_list(expr: str) -> List[int]:
    """Parse '1-3,8-10' -> [1,2,3,8,9,10] preserving token order."""
    expr = (expr or "").strip()
    if not expr:
        return []
    pages: List[int] = []
    for part in expr.split(","):
        part = part.strip()
        if not part:
            continue
        pages.extend(_expand_range_token(part))
    return pages


def _validate_pages_in_range(pages: Iterable[int], total_pages: int, *, label: str) -> None:
    for p in pages:
        if p < 1 or p > total_pages:
            raise SeparationPlanError(f"{label}: page {p} out of range 1..{total_pages}")


def parse_separation_plan(plan: str, total_pages: int) -> SeparationPlan:
    """Parse manual document-separation plan syntax.

    Syntax:
      - groups separated by ';'
      - keep group: 1-12 or 1-3,8-10
      - drop group: -13 or -(13-14)
      - keep-only mode marker: ';;' anywhere in the string

    Special shorthand:
      - If there are NO explicit keep groups, drop-only plans like ';-13;' imply
        keeping the remaining pages grouped around the dropped pages.
    """
    if total_pages < 1:
        raise SeparationPlanError("total_pages must be >= 1")

    raw = (plan or "").strip()
    if not raw:
        raise SeparationPlanError("Empty separation plan")

    keep_only = ";;" in raw
    tokens = [t.strip() for t in raw.split(";")]

    # In keep-only mode, empty tokens are just separators/formatting noise.
    if keep_only:
        tokens = [t for t in tokens if t]

    drop_pages: Set[int] = set()
    keep_groups: List[List[int]] = []

    def parse_drop(tok: str) -> List[int]:
        inner = tok[1:].strip()  # after leading '-'
        if inner.startswith("(") and inner.endswith(")"):
            inner = inner[1:-1].strip()
        pages = _parse_page_list(inner)
        if not pages:
            raise SeparationPlanError(f"Empty drop group: {tok!r}")
        _validate_pages_in_range(pages, total_pages, label="drop")
        return pages

    explicit_keep_present = any(t and not t.lstrip().startswith("-") for t in tokens)

    if keep_only or explicit_keep_present:
        for tok in tokens:
            if not tok:
                continue
            if tok.startswith("-"):
                pages = parse_drop(tok)
                drop_pages.update(pages)
                continue

            pages = _parse_page_list(tok)
            if not pages:
                raise SeparationPlanError(f"Empty keep group: {tok!r}")
            _validate_pages_in_range(pages, total_pages, label="keep")
            keep_groups.append(pages)

        kept_set = set().union(*(set(g) for g in keep_groups)) if keep_groups else set()
        if kept_set & drop_pages:
            overlap = sorted(kept_set & drop_pages)
            raise SeparationPlanError(f"Pages appear in both keep and drop: {overlap}")

        if keep_only:
            # Implicitly drop everything not kept.
            implicit_drop = set(range(1, total_pages + 1)) - kept_set
            drop_pages |= implicit_drop
        else:
            # In explicit mode, require full coverage (keep+drop = all pages).
            covered = kept_set | drop_pages
            if covered != set(range(1, total_pages + 1)):
                missing = sorted(set(range(1, total_pages + 1)) - covered)
                raise SeparationPlanError(
                    "Plan does not cover all pages (use keep-only mode ';;' to allow omissions). "
                    f"Missing: {missing}"
                )

        return SeparationPlan(total_pages=total_pages, kept_outputs=keep_groups, dropped_pages=drop_pages, keep_only=keep_only)

    # Drop-only shorthand: build keep groups as complement segments in ascending order.
    for tok in tokens:
        if not tok:
            continue
        if not tok.startswith("-"):
            raise SeparationPlanError(f"Drop-only plan cannot contain keep group: {tok!r}")
        pages = parse_drop(tok)
        drop_pages.update(pages)

    all_pages = list(range(1, total_pages + 1))
    keep_pages = [p for p in all_pages if p not in drop_pages]

    if not keep_pages:
        raise SeparationPlanError("Plan drops all pages; no outputs would be created")

    # Divide kept pages into contiguous output segments.
    segments: List[List[int]] = []
    cur: List[int] = []
    last: Optional[int] = None
    for p in keep_pages:
        if last is None or p == last + 1:
            cur.append(p)
        else:
            segments.append(cur)
            cur = [p]
        last = p
    if cur:
        segments.append(cur)

    return SeparationPlan(total_pages=total_pages, kept_outputs=segments, dropped_pages=drop_pages, keep_only=False)


def _format_output_line(i: int, group: List[int]) -> str:
    """One summary line for a kept group; always uses *scan* page numbering (source PDF)."""
    if len(group) == 1:
        return f"Output {i}: scan page {group[0]} only (single page in this output PDF)"
    if _is_contiguous(group):
        a, b = group[0], group[-1]
        n = len(group)
        return f"Output {i}: scan pages {a}–{b} ({n} pages in this output PDF)"
    return f"Output {i}: scan pages {group}"


def format_separation_plan(plan: SeparationPlan) -> str:
    """Return a human-readable multi-line plan summary (1-based scan pages in the source PDF)."""
    lines: List[str] = []
    lines.append(f"Total pages in this scan: {plan.total_pages}")
    lines.append(
        "(Numbers below are positions in this scan PDF before writing separate outputs, "
        "not page counts inside each output file.)"
    )
    for i, group in enumerate(plan.kept_outputs, 1):
        if not group:
            continue
        lines.append(_format_output_line(i, group))
    if plan.dropped_pages:
        dropped = sorted(plan.dropped_pages)
        lines.append(f"Drop from scan (page numbers): {dropped}")
    if plan.keep_only:
        lines.append("Mode: keep-only (implicit drop of all other pages)")
    return "\n".join(lines)


def _is_contiguous(pages: Sequence[int]) -> bool:
    return bool(pages) and all(pages[i] == pages[i - 1] + 1 for i in range(1, len(pages)))


# -----------------------------------------------------------------------------
# Separator detection (text + vivid background + vivid blank neighbors)
# -----------------------------------------------------------------------------


def _normalized_page_text(page_text: str) -> str:
    # Normalize to simplify quick length + token checks.
    return " ".join((page_text or "").split()).strip()


def _has_separator_token(normalized_text_upper: str) -> bool:
    return ("SEPARATOR" in normalized_text_upper) or ("DOCUMENT SEPARATOR" in normalized_text_upper)


def _text_is_short(normalized_text: str, *, max_chars: int = 200, max_words: int = 50) -> bool:
    if len(normalized_text) > max_chars:
        return False
    if normalized_text and len(normalized_text.split()) > max_words:
        return False
    return True


def _page_vivid_background(page, *, target_width_px: int = 260) -> Optional[bool]:
    """Return True/False if vividness can be computed; None if not available."""
    try:
        import fitz  # type: ignore
    except ImportError:
        return None

    try:
        rect = page.rect
        if rect.width <= 0 or rect.height <= 0:
            return None
        scale = float(target_width_px) / float(rect.width)
        if scale <= 0:
            return None
        pix = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
        if not pix.samples:
            return None
        try:
            import numpy as np  # type: ignore
        except ImportError:
            # Fallback: very rough heuristic without numpy (sample first bytes only)
            # If the first ~1KB has lots of non-240-ish bytes, call it vivid.
            s = pix.samples
            sample = s[: min(len(s), 1024)]
            non_white = sum(1 for b in sample if b < 235)
            return non_white > (len(sample) * 0.10)

        img = np.frombuffer(pix.samples, dtype=np.uint8)
        # Pixmap is RGB packed
        if img.size < 3:
            return None
        img = img.reshape(pix.height, pix.width, 3)

        maxc = img.max(axis=2).astype("float32")
        minc = img.min(axis=2).astype("float32")
        sat = (maxc - minc) / (maxc + 1e-6)
        mean_sat = float(sat.mean())

        near_white = (img[:, :, 0] > 240) & (img[:, :, 1] > 240) & (img[:, :, 2] > 240)
        frac_near_white = float(near_white.mean())

        # Heuristic tuned for bright colored separator sheets vs white paper.
        return (mean_sat >= 0.18) and (frac_near_white <= 0.85)
    except (ValueError, RuntimeError, AttributeError):
        return None


def is_vivid_blank_page(page, *, max_text_chars: int = 10) -> bool:
    text = _normalized_page_text(page.get_text("text") or "")
    if len(text) > max_text_chars:
        return False
    vivid = _page_vivid_background(page)
    return bool(vivid)


def is_separator_page(page) -> bool:
    page_text = page.get_text("text") or ""
    norm = _normalized_page_text(page_text)
    if not _text_is_short(norm):
        return False
    upper = norm.upper()
    if not _has_separator_token(upper):
        return False
    vivid = _page_vivid_background(page)
    if vivid is None:
        # Color sampling unavailable; accept text-only match (still gated by short-text).
        return True
    return bool(vivid)


def detect_separator_pages(pdf_path: Path) -> Tuple[List[int], Set[int]]:
    """Return (separator_page_indices_0based, pages_to_drop_0based).

    Drop set includes the separator pages plus any adjacent vivid-blank pages.
    """
    try:
        import fitz  # type: ignore
    except ImportError as exc:
        raise RuntimeError("PyMuPDF (fitz) is required for separator detection") from exc

    sep_pages: List[int] = []
    drop_pages: Set[int] = set()
    doc = fitz.open(str(pdf_path))
    try:
        total = len(doc)
        for i in range(total):
            page = doc.load_page(i)
            if is_separator_page(page):
                sep_pages.append(i)
        for s in sep_pages:
            drop_pages.add(s)
            for n in (s - 1, s + 1):
                if 0 <= n < total:
                    try:
                        neighbor_page = doc.load_page(n)
                    except (RuntimeError, ValueError):
                        continue
                    if is_vivid_blank_page(neighbor_page):
                        drop_pages.add(n)
        return sep_pages, drop_pages
    finally:
        doc.close()


def build_plan_from_drop_pages(*, total_pages: int, drop_pages_1based: Sequence[int]) -> SeparationPlan:
    """Build a plan that keeps all pages except the dropped ones, as separate output PDFs."""
    drop_set = set(int(p) for p in drop_pages_1based)
    _validate_pages_in_range(drop_set, total_pages, label="drop")
    keep_pages = [p for p in range(1, total_pages + 1) if p not in drop_set]
    if not keep_pages:
        raise SeparationPlanError("Dropping all pages would create no outputs")
    # contiguous segments
    segments: List[List[int]] = []
    cur: List[int] = []
    last: Optional[int] = None
    for p in keep_pages:
        if last is None or p == last + 1:
            cur.append(p)
        else:
            segments.append(cur)
            cur = [p]
        last = p
    if cur:
        segments.append(cur)
    return SeparationPlan(total_pages=total_pages, kept_outputs=segments, dropped_pages=drop_set, keep_only=False)


def build_plan_from_separators(*, total_pages: int, separator_pages_1based: Sequence[int]) -> SeparationPlan:
    """Canonical plan: keep around separators; drop separators (and nothing else)."""
    return build_plan_from_drop_pages(total_pages=total_pages, drop_pages_1based=list(separator_pages_1based))


# -----------------------------------------------------------------------------
# Writer
# -----------------------------------------------------------------------------


def save_as_documents(
    pdf_path: Path,
    separation_plan: SeparationPlan,
    *,
    out_dir: Path,
    output_paths: Sequence[Path],
) -> List[Path]:
    """Write outputs according to separation_plan into the provided output_paths.

    output_paths length must equal len(separation_plan.kept_outputs).
    """
    try:
        import fitz  # type: ignore
    except Exception as exc:
        raise RuntimeError("PyMuPDF (fitz) is required for PDF slicing") from exc

    if len(output_paths) != len(separation_plan.kept_outputs):
        raise SeparationPlanError("output_paths count must match number of output groups")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    src = fitz.open(str(pdf_path))
    try:
        if len(src) != separation_plan.total_pages:
            # Allow mismatch only if caller derived plan from a different view; treat as hard error for safety.
            raise SeparationPlanError(
                f"PDF page count changed: plan={separation_plan.total_pages} actual={len(src)}"
            )

        written: List[Path] = []
        for group_idx, (pages_1based, out_path) in enumerate(
            zip(separation_plan.kept_outputs, output_paths), 1
        ):
            if not pages_1based:
                raise SeparationPlanError(f"Output group {group_idx} is empty")
            out_path = Path(out_path)
            new_doc = fitz.open()
            try:
                for p in pages_1based:
                    new_doc.insert_pdf(src, from_page=p - 1, to_page=p - 1)
                new_doc.save(str(out_path))
            finally:
                new_doc.close()

            if not out_path.exists():
                raise SeparationPlanError(f"Failed to write output PDF: {out_path}")
            written.append(out_path)
        return written
    finally:
        src.close()

