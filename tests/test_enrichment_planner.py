from shared_tools.metadata.enrichment_planner import EnrichmentPlanner, DEFAULT_FIELD_POLICY


def test_planner_fills_missing_fields():
    planner = EnrichmentPlanner()
    zotero = {"title": "Paper", "authors": ["Doe"], "year": "2020"}
    candidate = {
        "title": "Paper",
        "authors": ["Doe"],
        "year": "2020",
        "doi": "10.1234/abc",
        "pages": "10-20",
        "language": "en",
    }
    decision = {"evidence": {"language": {"confidence": 0.95}}}

    plan = planner.build_plan(zotero, candidate, decision)
    assert plan["updates"]["pages"] == "10-20"
    assert plan["updates"]["doi"] == "10.1234/abc"


def test_planner_respects_manual_on_conflict():
    policy = DEFAULT_FIELD_POLICY.copy()
    planner = EnrichmentPlanner(policy)
    zotero = {"doi": "10.1111/existing"}
    candidate = {"doi": "10.2222/new"}
    decision = {"evidence": {"language": {"confidence": 0.95}}}

    plan = planner.build_plan(zotero, candidate, decision)
    assert "doi" not in plan["updates"]
    assert "doi" in plan["manual_fields"]
