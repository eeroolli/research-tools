"""Tests for config-driven document type aliases."""
from shared_tools.metadata.document_types import (
    clear_document_type_cache,
    document_types_equivalent,
    to_zotero_item_type,
    type_match_score,
)
from shared_tools.metadata.enrichment_planner import EnrichmentPlanner
from shared_tools.metadata.enrichment_policy import MatchPolicy
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor


def setup_function():
    clear_document_type_cache()


def test_to_zotero_maps_internal_crossref_csl_coar():
    assert to_zotero_item_type("journal_article") == "journalArticle"
    assert to_zotero_item_type("journal-article") == "journalArticle"
    assert to_zotero_item_type("article-journal") == "journalArticle"
    assert to_zotero_item_type("journal article") == "journalArticle"
    assert to_zotero_item_type("journalArticle") == "journalArticle"
    assert to_zotero_item_type("book_chapter") == "bookSection"
    assert to_zotero_item_type("book part") == "bookSection"
    assert to_zotero_item_type("bookPart") == "bookSection"
    assert to_zotero_item_type("working paper") == "preprint"
    assert to_zotero_item_type("review") == "journalArticle"
    assert to_zotero_item_type("proceedings-article") == "conferencePaper"


def test_unmapped_type_returns_none():
    assert to_zotero_item_type("physical sample") is None
    assert to_zotero_item_type("") is None
    assert to_zotero_item_type(None) is None


def test_document_types_equivalent():
    assert document_types_equivalent("journalArticle", "journal_article")
    assert document_types_equivalent("journalArticle", "journal-article")
    assert document_types_equivalent("bookSection", "book part")
    assert not document_types_equivalent("journalArticle", "conference_paper")
    assert not document_types_equivalent("journalArticle", "dataset")


def test_type_match_score_partial_journal_conference():
    assert type_match_score("journalArticle", "journal_article") == 1.0
    assert type_match_score("journalArticle", "conferencePaper") == 0.3
    assert type_match_score("journalArticle", "thesis") == 0.0


def test_planner_skips_equivalent_document_type():
    planner = EnrichmentPlanner()
    zotero = {"document_type": "journalArticle", "title": "Paper"}
    candidate = {"document_type": "journal_article", "title": "Paper"}
    plan = planner.build_plan(zotero, candidate, {"evidence": {}})
    assert "document_type" not in plan["manual_fields"]


def test_planner_flags_real_document_type_conflict():
    planner = EnrichmentPlanner()
    zotero = {"document_type": "journalArticle"}
    candidate = {"document_type": "conference_paper"}
    plan = planner.build_plan(zotero, candidate, {"evidence": {}})
    assert "document_type" in plan["manual_fields"]


def test_match_policy_type_uses_aliases():
    policy = MatchPolicy()
    assert policy._type_match("journalArticle", "journal_article") == 1.0
    assert policy._type_match("bookSection", "book_chapter") == 1.0
    assert policy._type_match("journalArticle", "conference_paper") == 0.3


def test_normalize_field_name_document_type():
    assert ZoteroPaperProcessor._normalize_field_name(
        ZoteroPaperProcessor, "document_type"
    ) == "itemType"


def test_coerce_item_type_value():
    # Instance methods need self; call unbound via a minimal stub
    class _P:
        _coerce_field_value = ZoteroPaperProcessor._coerce_field_value
        _normalize_field_name = ZoteroPaperProcessor._normalize_field_name

    p = _P()
    assert p._coerce_field_value("itemType", "journal_article") == "journalArticle"
    assert p._coerce_field_value("itemType", "not_a_real_type") is None
    assert p._coerce_field_value("pages", "1-2") == "1-2"


def test_determine_item_type_uses_conf():
    class _P:
        determine_item_type = ZoteroPaperProcessor.determine_item_type

    p = _P()
    assert p.determine_item_type({"document_type": "book_chapter"}) == "bookSection"
    assert p.determine_item_type({"document_type": "working paper"}) == "preprint"
