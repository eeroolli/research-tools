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


def test_planner_ignores_equivalent_document_type_aliases():
    planner = EnrichmentPlanner()
    zotero = {
        "title": "Paper",
        "document_type": "journalArticle",
        "authors": ["A"],
        "year": "2020",
    }
    candidate = {
        "title": "Paper",
        "document_type": "journal_article",
        "authors": ["A"],
        "year": "2020",
        "pages": "1-2",
    }
    plan = planner.build_plan(zotero, candidate, {"evidence": {}})
    assert "document_type" not in plan["manual_fields"]
    assert plan["updates"].get("pages") == "1-2"


def test_planner_skips_present_volume_issue_pages():
    planner = EnrichmentPlanner()
    zotero = {
        "title": "Paper",
        "authors": ["Doe"],
        "year": "2002",
        "volume": "36",
        "issue": "1",
        "pages": "48-72",
    }
    candidate = {
        "title": "Paper",
        "authors": ["Doe"],
        "year": "2002",
        "volume": "36",
        "issue": "1",
        "pages": "48-72",
        "doi": "10.1177/example",
    }
    plan = planner.build_plan(zotero, candidate, {"evidence": {}})
    assert "volume" not in plan["updates"]
    assert "issue" not in plan["updates"]
    assert "pages" not in plan["updates"]
    assert plan["updates"].get("doi") == "10.1177/example"
