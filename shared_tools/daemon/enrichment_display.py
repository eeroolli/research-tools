"""
Display helpers for enrichment diffs and summaries.
"""
from typing import Dict, List, Optional
from shared_tools.ui.colors import Colors, ColorScheme


def display_enrichment_summary(
    zotero_metadata: Dict,
    online_metadata: Dict,
    plan: Dict,
    heading: str = "ENRICHMENT SUMMARY",
    show_manual: bool = True,
) -> None:
    print("\n" + "=" * 60)
    print(Colors.colorize(heading, ColorScheme.PAGE_TITLE))
    print("=" * 60)

    updates = plan.get("updates", {})
    manual_fields: List[str] = plan.get("manual_fields", [])

    if updates:
        print(Colors.colorize("\nFields to fill (Zotero empty -> online value):", ColorScheme.ACTION))
        for field, val in updates.items():
            current = zotero_metadata.get(field, "")
            source = online_metadata.get(field, val)
            print(f"  {field}:")
            # Source coloring:
            # - Zotero values: green
            # - Auto-enriched online values: turquoise
            print(Colors.colorize(f"    Zotero: {current or '(empty)'}", ColorScheme.ENRICH_ZOTERO))
            print(Colors.colorize(f"    Online: {source}", ColorScheme.ENRICH_AUTO))
    else:
        print(Colors.colorize("\nNo fillable fields detected.", ColorScheme.MUTED))

    if show_manual and manual_fields:
        print(Colors.colorize("\nFields needing manual review/confirmation:", ColorScheme.WARN))
        for field in manual_fields:
            z_val = zotero_metadata.get(field, "")
            o_val = online_metadata.get(field, "")
            print(f"  {field}:")
            # Source coloring:
            # - Zotero values: green
            # - Manual-choice online values: orange
            print(Colors.colorize(f"    Zotero: {z_val or '(empty)'}", ColorScheme.ENRICH_ZOTERO))
            print(Colors.colorize(f"    Online: {o_val or '(empty)'}", ColorScheme.ENRICH_MANUAL))
