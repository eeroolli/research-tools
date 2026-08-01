"""Tests for shared CLI user feedback helpers."""

from shared_tools.ui.user_feedback import (
    UNACCEPTABLE_INPUT_MESSAGE,
    is_clear_field_input,
    print_unacceptable_input,
)


def test_print_unacceptable_input_writes_message(capsys) -> None:
    print_unacceptable_input()
    out = capsys.readouterr().out
    assert UNACCEPTABLE_INPUT_MESSAGE in out


def test_is_clear_field_input_enter_keeps() -> None:
    assert is_clear_field_input("") is False


def test_is_clear_field_input_space_or_dash_clears() -> None:
    assert is_clear_field_input(" ") is True
    assert is_clear_field_input("  ") is True
    assert is_clear_field_input("-") is True
    assert is_clear_field_input(" - ") is True
    assert is_clear_field_input("clear") is True
    assert is_clear_field_input("CLEAR") is True


def test_is_clear_field_input_normal_values() -> None:
    assert is_clear_field_input("2024") is False
    assert is_clear_field_input("Smith") is False
    assert is_clear_field_input("n") is False
