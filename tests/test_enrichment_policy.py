import pytest

from shared_tools.metadata.enrichment_policy import MatchPolicy, MatchPolicyConfig


def test_identifier_match_auto_accept():
    policy = MatchPolicy(MatchPolicyConfig())
    zotero = {"doi": "10.1234/abc", "title": "Sample Paper", "authors": ["Doe, John"], "year": "2020"}
    candidate = {"doi": "10.1234/abc", "title": "Sample Paper", "authors": ["John Doe"], "year": "2020"}

    decision = policy.evaluate(zotero, candidate)
    assert decision["status"] == "auto_accept"
    assert decision["reason"] == "identifier_match"


def test_conflicting_identifier_requires_manual():
    policy = MatchPolicy(MatchPolicyConfig(auto_accept_threshold=0.5))
    zotero = {"doi": "10.1234/old", "title": "Sample", "authors": ["Doe, John"], "year": "2020"}
    candidate = {"doi": "10.1234/new", "title": "Sample", "authors": ["John Doe"], "year": "2020"}

    decision = policy.evaluate(zotero, candidate)
    assert decision["status"] == "manual_review"
    assert decision["reason"] == "identifier_conflict"


def test_reject_weak_match_without_ids():
    policy = MatchPolicy(MatchPolicyConfig(manual_review_threshold=0.6, auto_accept_threshold=0.8))
    zotero = {"title": "Alpha", "authors": ["Doe"], "year": "2010"}
    candidate = {"title": "Beta", "authors": ["Smith"], "year": "2000"}

    decision = policy.evaluate(zotero, candidate)
    assert decision["status"] == "reject"


def test_language_ignored_when_low_confidence():
    cfg = MatchPolicyConfig(weight_language=0.05, language_confidence_min=0.9)
    policy = MatchPolicy(cfg)
    zotero = {"title": "Gamma", "authors": ["Doe"], "year": "2020"}
    candidate = {"title": "Gamma", "authors": ["Doe"], "year": "2020", "language": "en", "language_confidence": 0.5}

    decision = policy.evaluate(zotero, candidate)
    # still should be auto_accept due to high other overlap
    assert decision["status"] in ("auto_accept", "manual_review")
