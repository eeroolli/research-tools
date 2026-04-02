"""Shared user-facing messages for interactive CLI flows."""

from .colors import ColorScheme, Colors

UNACCEPTABLE_INPUT_MESSAGE = "⚠️  Input is not acceptable."


def print_unacceptable_input() -> None:
    """Print a single generic warning when user input fails validation in a prompt loop."""
    print(Colors.colorize(UNACCEPTABLE_INPUT_MESSAGE, ColorScheme.WARNING))
