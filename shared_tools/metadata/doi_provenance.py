"""DOI provenance for trusted online lookup.

Only DOIs from a prior online API result or from Zotero should drive
DOI-based enrichment searches. GROBID TEI DOIs are often OCR-wrong.
"""
from __future__ import annotations

from typing import Any, Dict, Optional

TRUSTED_DOI_SOURCES = frozenset({"online", "zotero"})


def mark_doi_source(metadata: Optional[Dict[str, Any]], source: str) -> Optional[Dict[str, Any]]:
    """Set doi_source when metadata carries a DOI."""
    if metadata and metadata.get("doi"):
        metadata["doi_source"] = source
    return metadata


def is_trusted_doi(metadata: Optional[Dict[str, Any]]) -> bool:
    """True when metadata has a DOI marked online or zotero."""
    if not metadata or not metadata.get("doi"):
        return False
    return metadata.get("doi_source") in TRUSTED_DOI_SOURCES
