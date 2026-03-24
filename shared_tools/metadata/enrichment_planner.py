"""
Build an enrichment update plan based on field policies and a match decision.
Only fills missing fields unless explicitly marked for manual review.
"""
from typing import Dict, Tuple


DEFAULT_FIELD_POLICY = {
    "title": "manual",
    "authors": "manual",
    "year": "manual",
    "document_type": "manual",
    "doi": "manual_on_conflict",
    "isbn": "manual_on_conflict",
    "issn": "auto_if_missing",
    "journal": "auto_if_missing",
    "publicationTitle": "auto_if_missing",
    "volume": "auto_if_missing",
    "issue": "auto_if_missing",
    "pages": "auto_if_missing",
    "publisher": "auto_if_missing",
    "url": "auto_if_missing",
    "abstract": "auto_if_missing",
    "language": "auto_if_missing_with_confidence",
    "tags": "manual",
}


class EnrichmentPlanner:
    def __init__(self, field_policy: Dict = None):
        self.field_policy = field_policy or DEFAULT_FIELD_POLICY

    def build_plan(
        self,
        zotero_metadata: Dict,
        candidate_metadata: Dict,
        decision: Dict,
    ) -> Dict:
        """Create a plan describing which fields to update and which require manual review."""
        updates = {}
        manual_fields = []
        policy = self.field_policy

        for field, rule in policy.items():
            z_val = zotero_metadata.get(field)
            c_val = candidate_metadata.get(field)

            if rule == "manual":
                if c_val and c_val != z_val:
                    manual_fields.append(field)
                continue

            if rule == "manual_on_conflict":
                if c_val and z_val and c_val != z_val:
                    manual_fields.append(field)
                elif c_val and not z_val:
                    updates[field] = c_val
                continue

            if rule == "auto_if_missing":
                if not z_val and c_val:
                    updates[field] = c_val
                continue

            if rule == "auto_if_missing_with_confidence":
                if not z_val and c_val:
                    lang_detail = decision.get("evidence", {}).get("language", {})
                    conf = lang_detail.get("confidence")
                    # confidence already filtered in policy; still double check
                    if conf is None or conf >= 0.90:
                        updates[field] = c_val
                    else:
                        manual_fields.append(field)
                continue

        return {
            "updates": updates,
            "manual_fields": manual_fields,
            "decision": decision,
        }
