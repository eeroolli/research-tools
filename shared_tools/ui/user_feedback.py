"""Shared user-facing messages for interactive CLI flows."""

from .colors import ColorScheme, Colors

UNACCEPTABLE_INPUT_MESSAGE = "⚠️  Input is not acceptable."

# Tokens that mean "clear / delete this field" (Enter alone still means keep).
_CLEAR_FIELD_TOKENS = frozenset({"-", "clear"})


def is_clear_field_input(raw: str) -> bool:
    """Return True if input means clear/delete the current field value.

    Enter (empty string) means keep — that is not a clear. Whitespace-only
    input (e.g. a single space), '-', or 'clear' means clear the field.
    Pass the raw ``input()`` result before stripping.
    """
    if raw is None or raw == "":
        return False
    stripped = raw.strip()
    if stripped == "":
        return True
    return stripped.lower() in _CLEAR_FIELD_TOKENS


def print_unacceptable_input() -> None:
    """Print a single generic warning when user input fails validation in a prompt loop."""
    print(Colors.colorize(UNACCEPTABLE_INPUT_MESSAGE, ColorScheme.WARNING))
