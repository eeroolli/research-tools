"""
Identifier extraction stubs for academic papers.
This module provides a minimal interface that future implementations (Ollama, Claude)
can plug into without changing callers.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import List, Optional, Dict, Any


@dataclass
class PaperIdentifiers:
    doi: Optional[str] = None
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    journal: Optional[str] = None
    year: Optional[str] = None
    language: Optional[str] = None
    confidence: float = 0.0
    extras: Dict[str, Any] | None = None


def extract_from_first_page_text(ocr_text: str) -> PaperIdentifiers:
    """Very lightweight heuristic extractor placeholder.
    - Returns structured identifiers with low confidence.
    - To be replaced by Ollama-backed extractor.
    """
    if not ocr_text or not isinstance(ocr_text, str):
        return PaperIdentifiers(confidence=0.0)

    text = ocr_text.strip()
    # Minimal DOI regex (placeholder)
    import re
    doi_match = re.search(r"10\.\d{4,9}/\S+", text)
    doi = doi_match.group(0) if doi_match else None

    # Placeholder title heuristic: first non-empty line up to 180 chars
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    title = first_line[:180] if first_line else None

    return PaperIdentifiers(
        doi=doi,
        title=title,
        authors=None,
        journal=None,
        year=None,
        language=None,
        confidence=30.0 if doi or title else 0.0,
        extras={"method": "heuristic_stub"},
    )


def extract_with_ollama(ocr_text: str, model: str = "llama2:7b") -> PaperIdentifiers:
    """Stub for future Ollama-backed extraction.
    Currently returns heuristic result and marks source as ollama_stub.
    """
    base = extract_from_first_page_text(ocr_text)
    base.extras = {**(base.extras or {}), "ollama_model": model, "source": "ollama_stub"}
    return base

{
  "cells": [],
  "metadata": {
    "language_info": {
      "name": "python"
    }
  },
  "nbformat": 4,
  "nbformat_minor": 2
}