#!/usr/bin/env python3
"""
Detect and suggest Last/First splits for one-field Zotero personal names.

Typical old-import bug: "Brendon Swedlow" stored as a single lastName (or API
``name``) instead of lastName="Swedlow", firstName="Brendon".

Pure logic only — no SQLite or API I/O.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# Lowercased tokens that often start a multi-word surname (longest-match prefers
# including these in lastName when matching the library index).
NAME_PARTICLES: Set[str] = {
    "van",
    "von",
    "de",
    "der",
    "den",
    "da",
    "di",
    "du",
    "la",
    "le",
    "del",
    "della",
    "des",
    "dos",
    "das",
    "ten",
    "ter",
    "te",
    "af",
    "zu",
    "zur",
    "st",
    "st.",
    "saint",
    "mac",
    "mc",
}

# If any token matches (case-insensitive), treat as institution / one-field org.
ORG_TOKENS: Set[str] = {
    "university",
    "universitet",
    "universität",
    "institute",
    "institution",
    "foundation",
    "inc",
    "inc.",
    "ltd",
    "ltd.",
    "gmbh",
    "press",
    "society",
    "association",
    "consortium",
    "committee",
    "laboratory",
    "laboratories",
    "lab",
    "center",
    "centre",
    "college",
    "school",
    "department",
    "ministry",
    "agency",
    "council",
    "organization",
    "organisation",
    "corp",
    "corp.",
    "corporation",
    "llc",
    "plc",
    "group",
    "editors",
    "editorial",
}


@dataclass(frozen=True)
class WellFormedAuthor:
    """A two-field person already in the library."""

    last_name: str
    first_name: str

    @property
    def key(self) -> Tuple[str, str]:
        return (self.last_name.casefold(), self.first_name.casefold())


@dataclass
class SplitSuggestion:
    """Suggested fix for one malformed creator string."""

    original: str
    last_name: str
    first_name: str
    confidence: str  # "high" | "medium"
    match_reason: str
    item_keys: List[str] = field(default_factory=list)
    creator_types: List[str] = field(default_factory=list)
    sample_titles: List[str] = field(default_factory=list)

    def as_two_field_creator(self, creator_type: str = "author") -> Dict[str, str]:
        return {
            "creatorType": creator_type,
            "firstName": self.first_name,
            "lastName": self.last_name,
        }


def as_name_str(value: Any) -> str:
    """Coerce a name field to a stripped string.

    Handles None, ints (e.g. lastName ``6``), and other non-strings without
    raising. Empty after strip → ``\"\"``.
    """
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    # Avoid bool (subclass of int) looking like a name.
    if isinstance(value, bool):
        return ""
    return str(value).strip()


def lastname_in_text(
    last_name: Any,
    text: str,
    *,
    allow_substring_if_long: bool = True,
) -> bool:
    """
    True if ``last_name`` appears in ``text`` under short-name-safe rules.

    - Always tries word-boundary match (``\\b``), so ``\"6\"`` matches
      ``\"perry 6 et al\"`` but not inside ``\"16\"`` / ``\"60\"``.
    - If ``allow_substring_if_long`` and ``len(last_name) > 2``, also accepts
      a plain substring hit (legacy loose path for normal surnames).
    """
    import re

    last = as_name_str(last_name)
    if not last or not text:
        return False
    pattern = r"\b" + re.escape(last) + r"\b"
    # Case: callers often pass already-lowercased text and last_name; use
    # IGNORECASE so mixed case still works.
    if re.search(pattern, text, flags=re.IGNORECASE):
        return True
    if allow_substring_if_long and len(last) > 2 and last.casefold() in text.casefold():
        return True
    return False


def tokenize_name(name: Any) -> List[str]:
    """Split a display name into whitespace tokens (commas stripped from edges)."""
    cleaned = as_name_str(name).replace(",", " ")
    if not cleaned:
        return []
    return [t for t in cleaned.split() if t]


def is_likely_organization(name: Any) -> bool:
    """True if the single-field name looks like an institution, not a person."""
    tokens = tokenize_name(name)
    if not tokens:
        return False
    for tok in tokens:
        bare = tok.strip(".,;:()[]{}\"'").casefold()
        if bare in ORG_TOKENS:
            return True
    return False


def _has_letter(text: str) -> bool:
    """True if text contains at least one Unicode letter."""
    return any(ch.isalpha() for ch in text)


def is_malformed_personal_creator(
    last_name: Any,
    first_name: Any,
    *,
    name: Any = None,
    field_mode: Optional[int] = None,
) -> bool:
    """
    True if this creator looks like a person stuffed into one field.

    Candidates:
    - API ``name`` set (one-field), or
    - empty firstName and multi-token lastName, or
    - fieldMode == 1 with multi-token lastName/name

    Not candidates: well-formed two-field people (including odd last names like
    ``\"6\"`` with a real first name), single-token last names, names that
    already contain a comma (already Last, First style), orgs.
    """
    last = as_name_str(last_name)
    first = as_name_str(first_name)
    single = as_name_str(name)

    if first and last and not single:
        return False

    raw = single or last
    if not raw:
        return False
    if "," in raw:
        return False
    if is_likely_organization(raw):
        return False

    tokens = tokenize_name(raw)
    if len(tokens) < 2:
        return False

    # Explicit one-field mode, or empty first with multi-word last/name.
    if field_mode == 1:
        return True
    if single:
        return True
    if not first and len(tokens) >= 2:
        return True
    return False


def build_wellformed_index(
    authors: Iterable[WellFormedAuthor],
) -> Dict[str, List[WellFormedAuthor]]:
    """
    Map casefolded lastName -> list of well-formed authors with that last name.

    Only authors with both first and last non-empty are indexed. Digit-only
    last names (e.g. ``\"6\"``) are included so indexing never crashes and
    high-confidence can still match ``\"Perry 6\"``.
    """
    index: Dict[str, List[WellFormedAuthor]] = {}
    seen: Set[Tuple[str, str]] = set()
    for author in authors:
        last = as_name_str(author.last_name)
        first = as_name_str(author.first_name)
        if not last or not first:
            continue
        key = (last.casefold(), first.casefold())
        if key in seen:
            continue
        seen.add(key)
        bucket = index.setdefault(last.casefold(), [])
        bucket.append(WellFormedAuthor(last_name=last, first_name=first))
    return index


def _particle_aware_split_points(tokens: Sequence[str]) -> List[int]:
    """
    Return start indices into ``tokens`` for candidate last-name suffixes.

    Prefer longer suffixes. Always include last-token-only (len-1). Also include
    splits that start at a particle so ``van der Waals`` is tried before ``Waals``.
    """
    n = len(tokens)
    if n < 2:
        return []
    starts: List[int] = []
    # Longest last-name first: start index from 1 .. n-1
    for start in range(1, n):
        starts.append(start)
    # Prefer particle-led suffixes by sorting: longer suffix first, then
    # particle-led before bare.
    def sort_key(start: int) -> Tuple[int, int]:
        suffix_len = n - start
        particle_bonus = 1 if tokens[start].casefold().rstrip(".") in NAME_PARTICLES else 0
        return (-suffix_len, -particle_bonus)

    starts.sort(key=sort_key)
    # Deduplicate while preserving order
    out: List[int] = []
    seen: Set[int] = set()
    for s in starts:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def suggest_split(
    raw_name: Any,
    wellformed_index: Dict[str, List[WellFormedAuthor]],
) -> Optional[SplitSuggestion]:
    """
    Suggest lastName/firstName for a malformed personal name.

    High confidence: some suffix matches an indexed lastName and the remaining
    prefix matches that author's firstName (case-insensitive). Longest matching
    last-name suffix wins. Digit-only last names in the index are allowed.

    Medium confidence: heuristic last-token (or particle-aware) surname with no
    library twin. Medium suggestions require at least one letter in the proposed
    last name (so a bare ``\"6\"`` suffix is not guessed without a library twin).
    """
    original = as_name_str(raw_name)
    tokens = tokenize_name(original)
    if len(tokens) < 2:
        return None
    if is_likely_organization(original):
        return None

    # High confidence: try longest last-name suffixes first
    for start in _particle_aware_split_points(tokens):
        last_tokens = tokens[start:]
        first_tokens = tokens[:start]
        last_candidate = " ".join(last_tokens)
        first_candidate = " ".join(first_tokens)
        matches = wellformed_index.get(last_candidate.casefold(), [])
        for author in matches:
            if as_name_str(author.first_name).casefold() == first_candidate.casefold():
                return SplitSuggestion(
                    original=original,
                    last_name=as_name_str(author.last_name),
                    first_name=as_name_str(author.first_name),
                    confidence="high",
                    match_reason=(
                        f"matches existing author "
                        f"{author.last_name}, {author.first_name}"
                    ),
                )

    # Medium: particle-aware heuristic — take longest particle-led suffix if
    # the first token of the suffix is a particle and at least one name token
    # follows; else last token only.
    last_start = len(tokens) - 1
    for i in range(1, len(tokens)):
        if tokens[i].casefold().rstrip(".") in NAME_PARTICLES:
            # Prefer the leftmost particle that still leaves >=1 first-name token
            # and >=1 surname token after particles.
            rest = tokens[i:]
            if len(rest) >= 2:
                last_start = i
                break
    last_name = " ".join(tokens[last_start:])
    first_name = " ".join(tokens[:last_start])
    if not last_name or not first_name:
        return None
    # Do not invent digit-only surnames without a library match.
    if not _has_letter(last_name):
        return None
    return SplitSuggestion(
        original=original,
        last_name=last_name,
        first_name=first_name,
        confidence="medium",
        match_reason="heuristic split (no matching two-field author in library)",
    )


def group_suggestions(
    suggestions: Iterable[SplitSuggestion],
    *,
    include_unmatched: bool = False,
    skipped_names: Optional[Set[str]] = None,
) -> List[SplitSuggestion]:
    """
    Deduplicate by original string (casefold), keep first high over medium,
    filter medium unless include_unmatched, drop skipped names.
    """
    skipped = {s.casefold() for s in (skipped_names or set())}
    by_key: Dict[str, SplitSuggestion] = {}
    for sug in suggestions:
        key = sug.original.casefold()
        if key in skipped:
            continue
        if sug.confidence == "medium" and not include_unmatched:
            continue
        existing = by_key.get(key)
        if existing is None:
            by_key[key] = sug
            continue
        # Prefer high over medium; merge item metadata
        if existing.confidence != "high" and sug.confidence == "high":
            sug.item_keys = list(dict.fromkeys(existing.item_keys + sug.item_keys))
            sug.creator_types = list(
                dict.fromkeys(existing.creator_types + sug.creator_types)
            )
            sug.sample_titles = list(
                dict.fromkeys(existing.sample_titles + sug.sample_titles)
            )[:5]
            by_key[key] = sug
        else:
            existing.item_keys = list(
                dict.fromkeys(existing.item_keys + sug.item_keys)
            )
            existing.creator_types = list(
                dict.fromkeys(existing.creator_types + sug.creator_types)
            )
            for title in sug.sample_titles:
                if title not in existing.sample_titles and len(existing.sample_titles) < 5:
                    existing.sample_titles.append(title)
    # Stable order: high first, then original name
    result = list(by_key.values())
    result.sort(key=lambda s: (0 if s.confidence == "high" else 1, s.original.casefold()))
    return result


def normalize_creators_for_compare(creators: Any) -> List[Dict[str, str]]:
    """Normalize a creators list for equality checks (apply/revert safety)."""
    if not creators or not isinstance(creators, list):
        return []
    out: List[Dict[str, str]] = []
    for c in creators:
        if not isinstance(c, dict):
            continue
        entry: Dict[str, str] = {
            "creatorType": str(c.get("creatorType") or "author"),
        }
        name = as_name_str(c.get("name"))
        last = as_name_str(c.get("lastName"))
        first = as_name_str(c.get("firstName"))
        if name and not last and not first:
            entry["name"] = name
        else:
            entry["lastName"] = last
            entry["firstName"] = first
        out.append(entry)
    return out


def creators_equal(a: Any, b: Any) -> bool:
    """True if two creators lists are equivalent after normalization."""
    return normalize_creators_for_compare(a) == normalize_creators_for_compare(b)


def decide_apply_action(
    current_creators: Any,
    creators_before: Any,
    creators_after: Any,
) -> str:
    """
    Decide whether to apply a planned change.

    Returns:
        ``apply`` — current matches before; safe to write after
        ``skip_already_applied`` — current already equals after
        ``skip_changed`` — current matches neither (user edited in Zotero)
    """
    if creators_equal(current_creators, creators_after):
        return "skip_already_applied"
    if creators_equal(current_creators, creators_before):
        return "apply"
    return "skip_changed"


def decide_revert_action(
    current_creators: Any,
    creators_before: Any,
    creators_after: Any,
) -> str:
    """
    Decide whether to revert a backup entry.

    Returns:
        ``revert`` — current still equals what we wrote (after)
        ``skip_already_reverted`` — current already equals before
        ``skip_changed`` — user edited further; do not overwrite
    """
    if creators_equal(current_creators, creators_before):
        return "skip_already_reverted"
    if creators_equal(current_creators, creators_after):
        return "revert"
    return "skip_changed"


def replace_malformed_creator(
    creators: Sequence[Dict[str, Any]],
    original_raw: Any,
    new_last: Any,
    new_first: Any,
) -> List[Dict[str, Any]]:
    """
    Return a copy of creators with matching one-field/malformed entries replaced.

    Matches when a creator's ``name`` or (empty first + lastName) equals
    ``original_raw`` (case-insensitive, whitespace-normalized).
    """
    target = " ".join(tokenize_name(original_raw)).casefold()
    new_last_s = as_name_str(new_last)
    new_first_s = as_name_str(new_first)
    result: List[Dict[str, Any]] = []
    for c in creators:
        if not isinstance(c, dict):
            continue
        cloned = dict(c)
        name = as_name_str(cloned.get("name"))
        last = as_name_str(cloned.get("lastName"))
        first = as_name_str(cloned.get("firstName"))
        candidate_raw = name or (last if not first else "")
        candidate_key = (
            " ".join(tokenize_name(candidate_raw)).casefold() if candidate_raw else ""
        )
        if candidate_key and candidate_key == target:
            creator_type = str(cloned.get("creatorType") or "author")
            result.append(
                {
                    "creatorType": creator_type,
                    "firstName": new_first_s,
                    "lastName": new_last_s,
                }
            )
        else:
            # Keep odd last names (e.g. digit ``\"6\"``) as strings after clone.
            if "lastName" in cloned:
                cloned["lastName"] = as_name_str(cloned.get("lastName"))
            if "firstName" in cloned:
                cloned["firstName"] = as_name_str(cloned.get("firstName"))
            result.append(cloned)
    return result


def wellformed_from_sqlite_row(
    last_name: Any,
    first_name: Any,
) -> Optional[WellFormedAuthor]:
    """Build a WellFormedAuthor if both fields are non-empty (incl. digit last names)."""
    last = as_name_str(last_name)
    first = as_name_str(first_name)
    if last and first:
        return WellFormedAuthor(last_name=last, first_name=first)
    return None
