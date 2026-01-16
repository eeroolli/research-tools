"""
Enrichment workflow: search online, evaluate candidates, and build update plans.
Supports interactive (daemon) and batch usage.
"""
from typing import Dict, List, Optional, Tuple
import logging

from shared_tools.metadata.enrichment_policy import MatchPolicy, MatchPolicyConfig
from shared_tools.metadata.enrichment_planner import EnrichmentPlanner


class EnrichmentWorkflow:
    def __init__(
        self,
        metadata_processor,
        match_policy: Optional[MatchPolicy] = None,
        planner: Optional[EnrichmentPlanner] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.metadata_processor = metadata_processor
        self.match_policy = match_policy or MatchPolicy(MatchPolicyConfig())
        self.planner = planner or EnrichmentPlanner()
        self.logger = logger or logging.getLogger(__name__)

    def search_online(self, metadata: Dict, max_results: int = 5, additional_candidates: List[Dict] = None) -> List[Dict]:
        """Perform online search using available API clients in metadata_processor.
        
        Args:
            metadata: Base metadata for search queries
            max_results: Maximum results per API source
            additional_candidates: Optional list of pre-fetched candidates (e.g., national-library metadata)
                                  These are included in the candidate pool for evaluation.
        
        Returns:
            List of candidate metadata dicts from all sources
        """
        results = []
        title = metadata.get("title")
        authors = metadata.get("authors", [])
        year = metadata.get("year")
        journal = metadata.get("journal")

        # Include additional candidates first (e.g., national-library metadata)
        if additional_candidates:
            for cand in additional_candidates:
                if cand and isinstance(cand, dict):
                    results.append(cand)

        try:
            if hasattr(self.metadata_processor, "crossref"):
                cr = self.metadata_processor.crossref
                cr_results = cr.search_by_metadata(
                    title=title,
                    authors=authors,
                    year=year,
                    journal=journal,
                    max_results=max_results,
                )
                if cr_results:
                    results.extend(cr_results)
        except Exception as e:
            self.logger.warning(f"CrossRef search failed: {e}")

        try:
            if hasattr(self.metadata_processor, "arxiv"):
                ar = self.metadata_processor.arxiv
                ar_results = ar.search_by_metadata(
                    title=title,
                    authors=authors,
                    max_results=max_results,
                )
                if ar_results:
                    results.extend(ar_results)
        except Exception as e:
            self.logger.warning(f"arXiv search failed: {e}")

        return results[:max_results] if results else []

    def choose_best(
        self, zotero_metadata: Dict, candidates: List[Dict]
    ) -> Tuple[Optional[Dict], Optional[Dict]]:
        """Pick the best candidate and return (candidate, decision)."""
        best = None
        best_decision = None
        best_score = -1.0

        for cand in candidates:
            decision = self.match_policy.evaluate(zotero_metadata, cand)
            score = decision.get("confidence", 0.0)
            if score > best_score:
                best_score = score
                best = cand
                best_decision = decision

        return best, best_decision

    def plan_updates(
        self, zotero_metadata: Dict, candidate: Dict, decision: Dict
    ) -> Dict:
        """Build an update plan using the planner and decision evidence."""
        return self.planner.build_plan(zotero_metadata, candidate, decision)

    def evaluate_and_plan(
        self, zotero_metadata: Dict, candidates: List[Dict]
    ) -> Dict:
        """Evaluate candidates, pick best, and build a plan."""
        best, decision = self.choose_best(zotero_metadata, candidates) if candidates else (None, None)
        if best and decision:
            plan = self.plan_updates(zotero_metadata, best, decision)
        else:
            plan = None
        return {"candidate": best, "decision": decision, "plan": plan}

    def apply_plan(
        self,
        zotero_processor,
        item_key: str,
        plan: Dict,
        *,
        overwrite_fields: Optional[set] = None,
        candidate_metadata: Optional[Dict] = None,
    ) -> Dict:
        """Apply plan updates to Zotero via the provided processor.

        By default, applies only fill-only updates (Zotero empty -> online value).

        Args:
            zotero_processor: Zotero API processor
            item_key: Zotero item key
            plan: Enrichment plan dict (must include 'updates')
            overwrite_fields: Optional set of fields to overwrite regardless of current Zotero value.
                             These are assumed to be explicitly user-approved.
            candidate_metadata: Candidate metadata dict providing values for overwrite_fields.
        """
        updates = plan.get("updates", {}) if plan else {}
        applied = []
        failed = []

        # Apply fill-only updates
        for field, value in updates.items():
            ok = False
            try:
                ok = zotero_processor.update_item_field_if_missing(item_key, field, value)
            except Exception:
                ok = False
            if ok:
                applied.append(field)
            else:
                failed.append(field)

        # Apply explicit overwrites (user-approved conflicts)
        if overwrite_fields:
            cand = candidate_metadata or {}
            for field in overwrite_fields:
                # Skip fields already attempted via fill-only path
                if field in updates:
                    continue
                if field == "tags":
                    # Safe behavior: add candidate tags (do not remove existing tags)
                    try:
                        raw_tags = cand.get("tags") or []
                        # Accept list[str] or list[{'tag':...}]
                        tag_names = []
                        for t in raw_tags:
                            if isinstance(t, dict):
                                name = t.get("tag", "")
                            else:
                                name = str(t)
                            name = (name or "").strip()
                            if name:
                                tag_names.append(name)
                        ok = zotero_processor.update_item_tags(item_key, add_tags=tag_names, remove_tags=None)
                    except Exception:
                        ok = False
                    if ok:
                        applied.append(field)
                    else:
                        failed.append(field)
                    continue

                value = cand.get(field)
                if value is None or value == "":
                    failed.append(field)
                    continue
                ok = False
                try:
                    ok = zotero_processor.update_item_field(item_key, field, value)
                except Exception:
                    ok = False
                if ok:
                    applied.append(field)
                else:
                    failed.append(field)

        if applied or failed:
            self.logger.info(
                "Enrichment apply results",
                extra={
                    "item_key": item_key,
                    "applied": applied,
                    "failed": failed,
                    "overwrite_fields": sorted(list(overwrite_fields)) if overwrite_fields else [],
                },
            )
        return {"applied": applied, "failed": failed}

    # Batch helper
    def process_batch(self, zotero_items: List[Dict]) -> List[Dict]:
        """Process a list of Zotero items; returns a report list per item."""
        reports = []
        for item in zotero_items:
            base = item.get("metadata", {}) if isinstance(item, dict) else {}
            candidates = self.search_online(base)
            best, decision = self.choose_best(base, candidates) if candidates else (None, None)
            if best and decision and decision.get("status") == "auto_accept":
                plan = self.plan_updates(base, best, decision)
            else:
                plan = None
            reports.append(
                {
                    "item": item,
                    "best_candidate": best,
                    "decision": decision,
                    "plan": plan,
                }
            )
        return reports
