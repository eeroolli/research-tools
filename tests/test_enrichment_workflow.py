from shared_tools.daemon.enrichment_workflow import EnrichmentWorkflow


class DummyZoteroProcessor:
    def __init__(self):
        self.calls = []

    def update_item_field_if_missing(self, item_key: str, field_name: str, field_value: str) -> bool:
        self.calls.append(("if_missing", item_key, field_name, field_value))
        return True

    def update_item_field(self, item_key: str, field_name: str, field_value) -> bool:
        self.calls.append(("overwrite", item_key, field_name, field_value))
        return True

    def update_item_tags(self, item_key: str, add_tags: list = None, remove_tags: list = None) -> bool:
        self.calls.append(("tags", item_key, tuple(add_tags or []), tuple(remove_tags or [])))
        return True


class DummyMetadataProcessor:
    # minimal stub
    pass


def test_apply_plan_updates_missing_fields():
    wf = EnrichmentWorkflow(metadata_processor=DummyMetadataProcessor())
    plan = {"updates": {"pages": "10-20", "doi": "10.1/x"}, "manual_fields": []}
    zp = DummyZoteroProcessor()

    result = wf.apply_plan(zp, "K1", plan)

    assert set(result["applied"]) == {"pages", "doi"}
    assert result["failed"] == []
    assert len(zp.calls) == 2


def test_apply_plan_supports_overwrite_fields():
    wf = EnrichmentWorkflow(metadata_processor=DummyMetadataProcessor())
    plan = {"updates": {"pages": "10-20"}, "manual_fields": ["doi", "tags"]}
    zp = DummyZoteroProcessor()

    result = wf.apply_plan(
        zp,
        "K2",
        plan,
        overwrite_fields={"doi", "tags"},
        candidate_metadata={"doi": "10.555/xyz", "tags": ["a", "b"]},
    )

    assert set(result["applied"]) == {"pages", "doi", "tags"}
    assert result["failed"] == []
    assert ("if_missing", "K2", "pages", "10-20") in zp.calls
    assert ("overwrite", "K2", "doi", "10.555/xyz") in zp.calls
    assert ("tags", "K2", ("a", "b"), ()) in zp.calls


def test_evaluate_and_plan_builds_plan():
    wf = EnrichmentWorkflow(metadata_processor=DummyMetadataProcessor())
    zotero = {"title": "Alpha", "authors": ["Doe"], "year": "2020"}
    candidates = [
        {"title": "Alpha", "authors": ["Doe"], "year": "2020", "pages": "5-10"},
    ]

    summary = wf.evaluate_and_plan(zotero, candidates)
    assert summary["candidate"] is not None
    assert summary["decision"] is not None
    assert summary["plan"] is not None
    assert "pages" in summary["plan"]["updates"]


def test_search_online_includes_additional_candidates():
    wf = EnrichmentWorkflow(metadata_processor=DummyMetadataProcessor())
    metadata = {"title": "Test", "authors": ["Author"], "year": "2020"}
    additional = [
        {"title": "Test", "authors": ["Author"], "year": "2020", "isbn": "123", "source": "national_library"}
    ]
    
    results = wf.search_online(metadata, additional_candidates=additional)
    assert len(results) >= 1
    assert any("isbn" in r for r in results)
