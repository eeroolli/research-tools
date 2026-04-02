"""Tests for shared CLI user feedback helpers."""

from shared_tools.ui.user_feedback import UNACCEPTABLE_INPUT_MESSAGE, print_unacceptable_input


def test_print_unacceptable_input_writes_message(capsys) -> None:
    print_unacceptable_input()
    out = capsys.readouterr().out
    assert UNACCEPTABLE_INPUT_MESSAGE in out
