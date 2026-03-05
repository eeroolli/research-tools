"""
Metadata match policy for deciding whether to auto-enrich, require manual review,
or reject an online metadata candidate.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Tuple
import os
import json
import time
import re


@dataclass
class MatchPolicyConfig:
    auto_accept_threshold: float = 0.85
    manual_review_threshold: float = 0.75
    language_confidence_min: float = 0.90
    weight_title: float = 0.45
    weight_authors: float = 0.30
    weight_year: float = 0.15
    weight_type: float = 0.10
    weight_language: float = 0.05


class MatchPolicy:
    def __init__(self, config: Optional[MatchPolicyConfig] = None):
        self.config = config or MatchPolicyConfig()

    def evaluate(
        self,
        zotero_metadata: Dict,
        candidate_metadata: Dict,
    ) -> Dict:
        """Evaluate a candidate against Zotero metadata and produce a decision object."""
        identifier_info = self._identifier_info(zotero_metadata, candidate_metadata)
        composite_score, components = self._composite_score(
            zotero_metadata, candidate_metadata
        )

        status, reason = self._decision(identifier_info, composite_score)

        decision = {
            "status": status,
            "reason": reason,
            "confidence": composite_score,
            "evidence": {
                "identifier": identifier_info,
                "title_similarity": components["title"],
                "author_overlap": components["authors"],
                "year_match": components["year"] >= 1.0,
                "type_match": components["type"] >= 1.0,
                "language": components["language_detail"],
            },
        }
        return decision

    # --- scoring helpers -------------------------------------------------

    def _identifier_info(self, zotero: Dict, candidate: Dict) -> Dict:
        doi_z = (zotero.get("doi") or "").strip().lower()
        doi_c = (candidate.get("doi") or "").strip().lower()

        isbn_z = (zotero.get("isbn") or "").strip().lower()
        isbn_c = (candidate.get("isbn") or "").strip().lower()

        issn_z = (zotero.get("issn") or "").strip().lower()
        issn_c = (candidate.get("issn") or "").strip().lower()

        def check_pair(z, c):
            if z and c:
                return z == c, z != c
            return False, False

        doi_match, doi_conflict = check_pair(doi_z, doi_c)
        isbn_match, isbn_conflict = check_pair(isbn_z, isbn_c)
        issn_match, issn_conflict = check_pair(issn_z, issn_c)

        match = doi_match or isbn_match or issn_match
        conflict = doi_conflict or isbn_conflict or issn_conflict

        return {
            "type": "doi/isbn/issn",
            "zotero": {"doi": doi_z, "isbn": isbn_z, "issn": issn_z},
            "candidate": {"doi": doi_c, "isbn": isbn_c, "issn": issn_c},
            "match": match,
            "conflict": conflict,
        }

    def _composite_score(
        self, zotero: Dict, candidate: Dict
    ) -> Tuple[float, Dict]:
        c = self.config

        title_score = self._title_similarity(
            zotero.get("title", ""), candidate.get("title", "")
        )
        authors_score, authors_detail = self._author_overlap(
            zotero.get("authors", []), candidate.get("authors", [])
        )
        year_score = self._year_match(zotero.get("year"), candidate.get("year"))
        type_score = self._type_match(
            zotero.get("document_type"), candidate.get("document_type")
        )
        lang_score, lang_detail = self._language_match(
            zotero.get("language"), candidate.get("language"), candidate.get("language_confidence")
        )

        weight_sum = (
            c.weight_title
            + c.weight_authors
            + c.weight_year
            + c.weight_type
            + (c.weight_language if lang_score is not None else 0)
        )

        composite = 0.0
        composite += c.weight_title * title_score
        composite += c.weight_authors * authors_score
        composite += c.weight_year * year_score
        composite += c.weight_type * type_score
        if lang_score is not None:
            composite += c.weight_language * lang_score

        if weight_sum > 0:
            composite = composite / weight_sum

        components = {
            "title": title_score,
            "authors": authors_detail,
            "year": year_score,
            "type": type_score,
            "language_detail": lang_detail,
        }
        return composite, components

    def _title_similarity(self, a: str, b: str) -> float:
        a_clean = self._clean(a)
        b_clean = self._clean(b)
        if not a_clean or not b_clean:
            return 0.0
        return SequenceMatcher(None, a_clean, b_clean).ratio()

    def _author_overlap(self, a_list: List[str], b_list: List[str]) -> Tuple[float, Dict]:
        # #region agent log
        try:
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ENR_A1",
                    "location": "enrichment_policy.py:_author_overlap",
                    "message": "Author overlap input",
                    "data": {
                        "z_types": [type(x).__name__ for x in (a_list or [])][:5],
                        "c_types": [type(x).__name__ for x in (b_list or [])][:5],
                        "z_preview": (a_list or [])[:3],
                        "c_preview": (b_list or [])[:3],
                    },
                    "timestamp": int(time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion

        a_norm = {self._clean_author(a) for a in a_list if self._clean_author(a)}
        b_norm = {self._clean_author(b) for b in b_list if self._clean_author(b)}

        if not a_norm or not b_norm:
            return 0.0, {
                "matches": 0,
                "total_zotero": len(a_norm),
                "total_candidate": len(b_norm),
            }

        matches = len(a_norm.intersection(b_norm))
        denom = max(len(a_norm), len(b_norm))
        score = matches / denom if denom else 0.0
        # #region agent log
        try:
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ENR_A2",
                    "location": "enrichment_policy.py:_author_overlap",
                    "message": "Author overlap normalized",
                    "data": {
                        "z_norm_preview": list(a_norm)[:5],
                        "c_norm_preview": list(b_norm)[:5],
                        "matches": matches,
                        "score": score,
                    },
                    "timestamp": int(time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion
        return score, {
            "matches": matches,
            "total_zotero": len(a_norm),
            "total_candidate": len(b_norm),
        }

    def _year_match(self, y1, y2) -> float:
        try:
            y1i, y2i = int(y1), int(y2)
        except Exception:
            return 0.0
        if y1i == y2i:
            return 1.0
        if abs(y1i - y2i) == 1:
            return 0.5
        return 0.0

    def _type_match(self, t1: Optional[str], t2: Optional[str]) -> float:
        if not t1 or not t2:
            return 0.0
        # Normalize to a comparable form across Zotero (camelCase) and online sources (snake/kebab).
        t1n = re.sub(r"[^a-z0-9]", "", t1.lower().strip())
        t2n = re.sub(r"[^a-z0-9]", "", t2.lower().strip())
        # #region agent log
        try:
            log_path = r"f:\prog\research-tools\.cursor\debug.log" if os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "sessionId": "debug-session",
                    "runId": "run1",
                    "hypothesisId": "ENR_T1",
                    "location": "enrichment_policy.py:_type_match",
                    "message": "Type match compare",
                    "data": {"t1": t1, "t2": t2, "t1n": t1n, "t2n": t2n},
                    "timestamp": int(time.time() * 1000),
                }) + "\n")
        except Exception:
            pass
        # #endregion
        if t1n == t2n:
            return 1.0
        # partial match for journal vs conference
        if {t1n, t2n} <= {"journalarticle", "conferencepaper"}:
            return 0.3
        return 0.0

    def _language_match(
        self,
        lang_z: Optional[str],
        lang_c: Optional[str],
        confidence: Optional[float],
    ) -> Tuple[Optional[float], Dict]:
        lang_z = (lang_z or "").strip().lower()
        lang_c = (lang_c or "").strip().lower()

        if not lang_c:
            return None, {
                "zotero": lang_z,
                "candidate": lang_c,
                "match": False,
                "confidence": confidence,
                "source": None,
            }

        if confidence is not None and confidence < self.config.language_confidence_min:
            return None, {
                "zotero": lang_z,
                "candidate": lang_c,
                "match": False,
                "confidence": confidence,
                "source": None,
            }

        match = bool(lang_z) and lang_z == lang_c
        return (1.0 if match else 0.0), {
            "zotero": lang_z,
            "candidate": lang_c,
            "match": match,
            "confidence": confidence,
            "source": None,
        }

    def _decision(self, identifier_info: Dict, composite: float) -> Tuple[str, str]:
        c = self.config
        if identifier_info["match"]:
            return "auto_accept", "identifier_match"

        if identifier_info["conflict"]:
            if composite >= c.auto_accept_threshold:
                return "manual_review", "identifier_conflict"
            return "reject", "identifier_conflict"

        if composite >= c.auto_accept_threshold:
            return "auto_accept", "strong_composite"

        if composite >= c.manual_review_threshold:
            return "manual_review", "weak_composite"

        return "reject", "weak_match"

    # --- utilities -------------------------------------------------------
    @staticmethod
    def _clean(text: str) -> str:
        return " ".join(text.lower().split()) if isinstance(text, str) else ""

    @staticmethod
    def _clean_author(text: str) -> str:
        if not isinstance(text, str):
            return ""
        raw = " ".join(text.lower().split())
        if not raw:
            return ""

        # Normalize "Last, First" into "First Last" before token handling.
        if "," in text:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if len(parts) >= 2:
                raw = " ".join([parts[1], parts[0]] + parts[2:])
            else:
                raw = raw.replace(",", " ")
        else:
            raw = raw.replace(",", " ")

        # Remove punctuation, keep spaces/alphanumerics.
        raw = re.sub(r"[^a-z0-9\s]", "", raw)
        tokens = raw.split()
        if not tokens:
            return ""

        # Order-invariant comparison: "Louis Wirth" == "Wirth Louis"
        tokens = sorted(tokens)
        return " ".join(tokens)
