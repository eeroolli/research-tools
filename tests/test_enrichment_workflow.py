from shared_tools.daemon.enrichment_workflow import EnrichmentWorkflow


class DummyZoteroProcessor:
    def __init__(self):
        self.calls = []

    def update_item_field_if_missing(self, item_key: str, field_name: str, field_value: str) -> bool:
        self.calls.append((item_key, field_name, field_value))
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
