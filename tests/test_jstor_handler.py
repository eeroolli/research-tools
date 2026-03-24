from shared_tools.metadata.jstor_handler import JSTORHandler


class FakeAPIClient:
    def __init__(self, metadata=None):
        self.metadata = metadata

    def get_metadata_by_doi(self, doi):
        return self.metadata


class FakePriorityManager:
    def __init__(self):
        self.enabled = True

    def get_ordered_apis(self, api_list):
        return api_list

    def is_api_enabled(self, api_name):
        return True


class FakeJstorClient:
    def __init__(self, metadata=None):
        self.metadata = metadata

    def fetch_metadata_from_url(self, url):
        return self.metadata


def test_jstor_handler_basic_enrichment():
    api_metadata = {"source": "crossref", "title": "API Title"}
    handler = JSTORHandler(
        api_clients={"crossref": FakeAPIClient(api_metadata)},
        priority_manager=FakePriorityManager(),
        jstor_client=FakeJstorClient({"doi": "10.1234/example", "title": "JSTOR Title"})
    )

    result = handler.process_jstor_id("12345")
    assert result
    assert result["metadata"]["title"] == "API Title"
    assert result["method"] == "jstor+crossref"
