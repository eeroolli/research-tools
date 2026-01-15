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

    def search_online(self, metadata: Dict, max_results: int = 5) -> List[Dict]:
        """Perform online search using available API clients in metadata_processor."""
        results = []
        title = metadata.get("title")
        authors = metadata.get("authors", [])
        year = metadata.get("year")
        journal = metadata.get("journal")

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

    def apply_plan(self, zotero_processor, item_key: str, plan: Dict) -> Dict:
        """Apply plan updates to Zotero via the provided processor."""
        updates = plan.get("updates", {}) if plan else {}
        applied = []
        failed = []
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
        if applied or failed:
            self.logger.info(
                "Enrichment apply results",
                extra={"item_key": item_key, "applied": applied, "failed": failed},
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
