"""Tests for AuthorValidator, including strict (last-name only) matching for regex sources."""

import pytest

from shared_tools.utils.author_validator import AuthorValidator


def _get_validator_or_skip():
    """Return an AuthorValidator if config and DB exist; otherwise skip the test."""
    try:
        return AuthorValidator()
    except (FileNotFoundError, ValueError, OSError):
        pytest.skip("Zotero config or database not available")


def test_allow_partial_match_false_uses_only_lastname():
    """With allow_partial_match=False, only last-name matches count; phrase fragments do not match."""
    validator = _get_validator_or_skip()

    # "Business Media" has last name "media". With strict matching, only Zotero authors
    # whose last name is "media" would match. Most libraries have no such author, so
    # we expect no match. With allow_partial_match=True, "media" or "business" in any
    # author name would match (causing false positives).
    result_strict = validator.validate_authors(["Business Media"], allow_partial_match=False)
    result_partial = validator.validate_authors(["Business Media"], allow_partial_match=True)

    # Strict must not have more known_authors than partial (strict is a subset of matching)
    assert len(result_strict["known_authors"]) <= len(result_partial["known_authors"])

    # With strict, "Business Media" should typically be unknown (no last name "media" in Zotero)
    # If the library has an author with last name "media", this assertion may need adjusting
    if len(result_strict["known_authors"]) == 0:
        assert any(u["name"] == "Business Media" for u in result_strict["unknown_authors"])


def test_allow_partial_match_false_still_matches_lastname():
    """With allow_partial_match=False, real last-name matches still work (e.g. N. Romm -> Norma Romm)."""
    validator = _get_validator_or_skip()

    # "N. Romm" has last name "romm". If Zotero has "Norma Romm", strict should find her.
    result = validator.validate_authors(["N. Romm"], allow_partial_match=False)

    # Either we have a match (romm in lastname_index) or unknown; no wrong-name matches
    if result["known_authors"]:
        assert any("romm" in a["name"].lower() for a in result["known_authors"])


def test_strict_never_adds_more_matches_than_partial():
    """For any input list, allow_partial_match=False yields at most as many known_authors as True."""
    validator = _get_validator_or_skip()

    inputs = ["Business Media", "N. Romm", "Pierre Bourdieu", "Some Accounts of Old-Fashioned"]
    result_strict = validator.validate_authors(inputs, allow_partial_match=False)
    result_partial = validator.validate_authors(inputs, allow_partial_match=True)

    assert len(result_strict["known_authors"]) <= len(result_partial["known_authors"])
