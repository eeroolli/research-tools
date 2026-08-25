#!/usr/bin/env python3
"""Unit tests for author name splitter and apply/revert safety helpers."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

project_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(project_root))

from shared_tools.utils.author_name_splitter import (
    WellFormedAuthor,
    as_name_str,
    build_wellformed_index,
    creators_equal,
    decide_apply_action,
    decide_revert_action,
    group_suggestions,
    is_likely_organization,
    is_malformed_personal_creator,
    lastname_in_text,
    replace_malformed_creator,
    suggest_split,
    wellformed_from_sqlite_row,
)


@pytest.fixture(scope="module")
def fix_author_script():
    path = project_root / "scripts" / "fix_zotero_author_name_order.py"
    spec = importlib.util.spec_from_file_location("fix_zotero_author_name_order", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_digit_lastname_does_not_break():
    """lastName='6' with firstName Perry/Perri must not crash or be a candidate."""
    # Non-string int must coerce safely (would crash on `(6 or \"\").strip()`).
    assert as_name_str(6) == "6"
    assert as_name_str("6") == "6"
    wf = wellformed_from_sqlite_row(6, "Perry")
    assert wf is not None
    assert wf.last_name == "6"
    assert wf.first_name == "Perry"

    assert not is_malformed_personal_creator("6", "Perry")
    assert not is_malformed_personal_creator(6, "Perri")
    assert not is_malformed_personal_creator("6", "")  # single token

    index = build_wellformed_index(
        [
            WellFormedAuthor(last_name="6", first_name="Perry"),
            WellFormedAuthor(last_name=6, first_name="Perri"),  # type: ignore[arg-type]
        ]
    )
    # Indexing digit last names must succeed
    assert "6" in index
    assert len(index["6"]) >= 1

    # High-confidence match when one-field form is \"Perry 6\"
    sug = suggest_split("Perry 6", index)
    assert sug is not None
    assert sug.confidence == "high"
    assert sug.last_name == "6"
    assert sug.first_name == "Perry"

    # Without a library twin, do not invent medium digit-only surnames
    assert suggest_split("Perry 6", build_wellformed_index([])) is None

    # replace/compare must tolerate numeric lastName in existing creators
    creators = [
        {"creatorType": "author", "lastName": 6, "firstName": "Perry"},
        {"creatorType": "author", "lastName": "Brendon Swedlow", "firstName": ""},
    ]
    out = replace_malformed_creator(creators, "Brendon Swedlow", "Swedlow", "Brendon")
    assert out[0]["lastName"] == "6"
    assert out[0]["firstName"] == "Perry"
    assert out[1]["lastName"] == "Swedlow"
    assert creators_equal(
        [{"lastName": 6, "firstName": "Perry", "creatorType": "author"}],
        [{"lastName": "6", "firstName": "Perry", "creatorType": "author"}],
    )


def test_lastname_in_text_short_digit_word_boundary():
    """Digit last names match as whole tokens, not inside longer numbers."""
    assert lastname_in_text("6", "perry 6 et al") is True
    assert lastname_in_text(6, "Perri 6 and colleagues") is True
    assert lastname_in_text("6", "volume 16 appendix") is False
    assert lastname_in_text("6", "page 60 notes") is False
    # Long names may use substring fallback
    assert lastname_in_text("smith", "johnsmith", allow_substring_if_long=True) is True
    assert lastname_in_text("6", "x6y", allow_substring_if_long=True) is False


def test_author_summary_coerces_int_lastname():
    # Reuse linked-PDF script helper via parallel import pattern
    path = project_root / "scripts" / "fix_zotero_linked_pdf_attachment_titles.py"
    spec = importlib.util.spec_from_file_location(
        "fix_zotero_linked_pdf_attachment_titles", path
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    assert mod._author_summary([{"firstName": "Perry", "lastName": 6}]) == "Perry 6"
    assert mod._author_summary([{"firstName": "Perri", "lastName": "6"}]) == "Perri 6"
    assert mod._author_summary([{"name": "Consortium"}]) == "Consortium"


def test_swedlow_high_confidence_against_existing():
    index = build_wellformed_index(
        [WellFormedAuthor(last_name="Swedlow", first_name="Brendon")]
    )
    sug = suggest_split("Brendon Swedlow", index)
    assert sug is not None
    assert sug.confidence == "high"
    assert sug.last_name == "Swedlow"
    assert sug.first_name == "Brendon"


def test_longest_suffix_wins_over_short_lastname():
    index = build_wellformed_index(
        [
            WellFormedAuthor(last_name="Waals", first_name="Johannes"),
            WellFormedAuthor(last_name="van der Waals", first_name="Johannes Diderik"),
        ]
    )
    sug = suggest_split("Johannes Diderik van der Waals", index)
    assert sug is not None
    assert sug.confidence == "high"
    assert sug.last_name == "van der Waals"
    assert sug.first_name == "Johannes Diderik"


def test_org_skip():
    assert is_likely_organization("University of Oslo")
    assert is_likely_organization("Max Planck Institute")
    assert is_likely_organization("Some Research Foundation")
    assert not is_likely_organization("Brendon Swedlow")
    index = build_wellformed_index([])
    assert suggest_split("University of Oslo", index) is None
    assert not is_malformed_personal_creator("University of Oslo", "")


def test_wellformed_two_field_not_candidate():
    assert not is_malformed_personal_creator("Swedlow", "Brendon")
    assert not is_malformed_personal_creator("Smith", "")  # single token
    assert is_malformed_personal_creator("Brendon Swedlow", "")
    assert is_malformed_personal_creator("Brendon Swedlow", "", field_mode=1)
    assert is_malformed_personal_creator("", "", name="Brendon Swedlow")
    assert not is_malformed_personal_creator("Swedlow, Brendon", "")


def test_medium_unmatched_heuristic():
    index = build_wellformed_index([])
    sug = suggest_split("Brendon Swedlow", index)
    assert sug is not None
    assert sug.confidence == "medium"
    assert sug.last_name == "Swedlow"
    assert sug.first_name == "Brendon"


def test_medium_particle_heuristic():
    index = build_wellformed_index([])
    sug = suggest_split("Johannes van der Waals", index)
    assert sug is not None
    assert sug.confidence == "medium"
    assert sug.last_name == "van der Waals"
    assert sug.first_name == "Johannes"


def test_group_filters_medium_unless_include_unmatched():
    index = build_wellformed_index(
        [WellFormedAuthor(last_name="Swedlow", first_name="Brendon")]
    )
    high = suggest_split("Brendon Swedlow", index)
    medium = suggest_split("Jane Mystery", build_wellformed_index([]))
    assert high and medium
    high.item_keys = ["A"]
    medium.item_keys = ["B"]

    only_high = group_suggestions([high, medium], include_unmatched=False)
    assert len(only_high) == 1
    assert only_high[0].original == "Brendon Swedlow"

    both = group_suggestions([high, medium], include_unmatched=True)
    assert len(both) == 2


def test_group_respects_skipped_and_merges_items():
    index = build_wellformed_index(
        [WellFormedAuthor(last_name="Swedlow", first_name="Brendon")]
    )
    a = suggest_split("Brendon Swedlow", index)
    b = suggest_split("Brendon Swedlow", index)
    assert a and b
    a.item_keys = ["ITEM1"]
    a.sample_titles = ["Title One"]
    b.item_keys = ["ITEM2"]
    b.sample_titles = ["Title Two"]

    merged = group_suggestions([a, b], include_unmatched=False)
    assert len(merged) == 1
    assert set(merged[0].item_keys) == {"ITEM1", "ITEM2"}

    hidden = group_suggestions(
        [a], include_unmatched=False, skipped_names={"Brendon Swedlow"}
    )
    assert hidden == []


def test_already_fixed_not_malformed_second_run():
    """After a successful fix, two-field creators are not candidates."""
    assert not is_malformed_personal_creator("Swedlow", "Brendon")


def test_replace_malformed_creator():
    creators = [
        {"creatorType": "author", "lastName": "Brendon Swedlow", "firstName": ""},
        {"creatorType": "author", "firstName": "Other", "lastName": "Person"},
    ]
    out = replace_malformed_creator(creators, "Brendon Swedlow", "Swedlow", "Brendon")
    assert out[0] == {
        "creatorType": "author",
        "firstName": "Brendon",
        "lastName": "Swedlow",
    }
    assert out[1]["lastName"] == "Person"


def test_replace_api_name_field():
    creators = [{"creatorType": "author", "name": "Brendon Swedlow"}]
    out = replace_malformed_creator(creators, "Brendon Swedlow", "Swedlow", "Brendon")
    assert out[0]["lastName"] == "Swedlow"
    assert out[0]["firstName"] == "Brendon"
    assert "name" not in out[0]


def test_decide_apply_actions():
    before = [{"creatorType": "author", "lastName": "Brendon Swedlow", "firstName": ""}]
    after = [{"creatorType": "author", "firstName": "Brendon", "lastName": "Swedlow"}]
    assert decide_apply_action(before, before, after) == "apply"
    assert decide_apply_action(after, before, after) == "skip_already_applied"
    changed = [{"creatorType": "author", "firstName": "B.", "lastName": "Swedlow"}]
    assert decide_apply_action(changed, before, after) == "skip_changed"


def test_decide_revert_actions():
    before = [{"creatorType": "author", "lastName": "Brendon Swedlow", "firstName": ""}]
    after = [{"creatorType": "author", "firstName": "Brendon", "lastName": "Swedlow"}]
    assert decide_revert_action(after, before, after) == "revert"
    assert decide_revert_action(before, before, after) == "skip_already_reverted"
    changed = [{"creatorType": "author", "firstName": "B.", "lastName": "Swedlow"}]
    assert decide_revert_action(changed, before, after) == "skip_changed"


def test_creators_equal_normalizes():
    a = [{"creatorType": "author", "firstName": "Brendon", "lastName": "Swedlow"}]
    b = [{"creatorType": "author", "lastName": "Swedlow", "firstName": "Brendon"}]
    assert creators_equal(a, b)


def test_suggestions_to_dict_and_approved(fix_author_script):
    index = build_wellformed_index(
        [WellFormedAuthor(last_name="Swedlow", first_name="Brendon")]
    )
    sug = suggest_split("Brendon Swedlow", index)
    assert sug is not None
    sug.item_keys = ["ABC123"]
    data = fix_author_script.suggestions_to_dict([sug])
    assert data["group_count"] == 1
    assert data["groups"][0]["approved"] is None
    data["groups"][0]["approved"] = True
    approved = fix_author_script.dict_to_approved_plans(data)
    assert len(approved) == 1
    data["groups"][0]["approved"] = False
    assert fix_author_script.dict_to_approved_plans(data) == []
