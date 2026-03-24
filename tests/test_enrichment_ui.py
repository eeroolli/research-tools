from shared_tools.utils.enrichment_ui import parse_index_selection, clear_enrichment_context


def test_parse_index_selection_empty():
    assert parse_index_selection("", 10) == []
    assert parse_index_selection("   ", 10) == []


def test_parse_index_selection_commas_and_ranges():
    assert parse_index_selection("1,3-5", 10) == [1, 3, 4, 5]
    assert parse_index_selection("5-3", 10) == [3, 4, 5]
    assert parse_index_selection("2, 4 , 6", 10) == [2, 4, 6]


def test_parse_index_selection_bounds_and_invalid_tokens():
    # Out of range ignored
    assert parse_index_selection("0,1,99", 5) == [1]
    # Invalid tokens ignored
    assert parse_index_selection("a,1,b-3,2", 5) == [1, 2]


def test_clear_enrichment_context_removes_key():
    ctx = {"enrichment": {"status": "auto_accept"}, "other": 1}
    clear_enrichment_context(ctx)
    assert "enrichment" not in ctx
    assert ctx["other"] == 1

