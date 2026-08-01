"""
Config-driven document type aliases → Zotero itemType.

Reads document_types.conf (repo root by default). Used by enrichment
comparison/scoring and by Zotero item create/update paths.
"""
from __future__ import annotations

import configparser
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, Optional, Set, Tuple

from shared_tools.config.io import read_config_file

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_CONF = _REPO_ROOT / "document_types.conf"

# Fallback if conf is missing — keep in sync with historical determine_item_type map.
_FALLBACK_ALIASES: Dict[str, str] = {
    "journal_article": "journalArticle",
    "conference_paper": "conferencePaper",
    "book_chapter": "bookSection",
    "preprint": "preprint",
    "working_paper": "preprint",
    "manuscript": "manuscript",
    "report": "report",
    "thesis": "thesis",
    "news_article": "newspaperArticle",
    "web_article": "webpage",
    "book": "book",
    "journalarticle": "journalArticle",
    "booksection": "bookSection",
    "conferencepaper": "conferencePaper",
}


def normalize_type_key(value: Optional[str]) -> str:
    """Fold a type label for alias lookup (case, spaces, hyphens, punctuation)."""
    if not value:
        return ""
    s = str(value).strip().lower()
    s = s.replace("-", "_").replace(" ", "_")
    s = re.sub(r"[^a-z0-9_]", "", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _default_conf_path() -> Path:
    return _DEFAULT_CONF


@lru_cache(maxsize=4)
def _load_maps(conf_path: str) -> Tuple[Dict[str, str], Set[Tuple[str, str]]]:
    """Load alias map and partial-match pairs from conf.

    Returns:
        aliases: normalized_key → Zotero itemType
        partial: frozenset of frozenset pairs as sorted 2-tuples of Zotero types
    """
    aliases: Dict[str, str] = {}
    partial: Set[Tuple[str, str]] = set()

    path = Path(conf_path)
    if not path.is_file():
        for k, v in _FALLBACK_ALIASES.items():
            aliases[normalize_type_key(k)] = v
            aliases[normalize_type_key(v)] = v
        return aliases, partial

    parser = configparser.ConfigParser()
    # Preserve option name casing for values; keys still normalized by us.
    parser.optionxform = str  # type: ignore[assignment]
    read_config_file(parser, str(path))

    if parser.has_section("aliases"):
        for raw_key, raw_val in parser.items("aliases"):
            key = normalize_type_key(raw_key)
            val = (raw_val or "").strip()
            if not key or not val or val.startswith("#"):
                continue
            aliases[key] = val
            # Also index the Zotero value so passthrough works after normalize.
            aliases[normalize_type_key(val)] = val

    if parser.has_section("partial_matches"):
        for raw_left, raw_right in parser.items("partial_matches"):
            left = to_zotero_item_type_from_map(raw_left, aliases)
            right = to_zotero_item_type_from_map(raw_right, aliases)
            if left and right and left != right:
                pair = tuple(sorted((left, right)))
                partial.add(pair)  # type: ignore[arg-type]

    return aliases, partial


def to_zotero_item_type_from_map(
    value: Optional[str], aliases: Dict[str, str]
) -> Optional[str]:
    if not value:
        return None
    key = normalize_type_key(value)
    if not key:
        return None
    return aliases.get(key)


def get_alias_maps(conf_path: Optional[str] = None) -> Tuple[Dict[str, str], Set[Tuple[str, str]]]:
    path = str(Path(conf_path) if conf_path else _default_conf_path())
    return _load_maps(path)


def to_zotero_item_type(
    value: Optional[str], conf_path: Optional[str] = None
) -> Optional[str]:
    """Map any known source/internal/CSL/COAR label to a Zotero itemType.

    Returns None if the value is empty or unmapped (do not default during compare).
    """
    aliases, _ = get_alias_maps(conf_path)
    return to_zotero_item_type_from_map(value, aliases)


def document_types_equivalent(
    a: Optional[str], b: Optional[str], conf_path: Optional[str] = None
) -> bool:
    """True when both sides map to the same non-None Zotero itemType."""
    za = to_zotero_item_type(a, conf_path)
    zb = to_zotero_item_type(b, conf_path)
    return bool(za and zb and za == zb)


def type_match_score(
    a: Optional[str], b: Optional[str], conf_path: Optional[str] = None
) -> float:
    """Score for MatchPolicy: 1.0 equivalent, 0.3 configured partial, else 0.0."""
    za = to_zotero_item_type(a, conf_path)
    zb = to_zotero_item_type(b, conf_path)
    if not za or not zb:
        return 0.0
    if za == zb:
        return 1.0
    _, partial = get_alias_maps(conf_path)
    if tuple(sorted((za, zb))) in partial:
        return 0.3
    return 0.0


def clear_document_type_cache() -> None:
    """Clear cached conf (for tests)."""
    _load_maps.cache_clear()
