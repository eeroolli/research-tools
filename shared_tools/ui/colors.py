"""Color utilities for terminal output.

Uses ANSI escape codes for cross-platform color support.
Colors are disabled if output is not a TTY (e.g., when piped).
"""

import sys


class Colors:
    """ANSI color codes for terminal output."""
    
    # Reset
    RESET = '\033[0m'
    
    # Text colors
    BLACK = '\033[30m'
    RED = '\033[31m'
    GREEN = '\033[32m'
    YELLOW = '\033[33m'
    BLUE = '\033[34m'
    MAGENTA = '\033[35m'
    CYAN = '\033[36m'
    WHITE = '\033[37m'
    
    # Bright colors
    BRIGHT_BLACK = '\033[90m'
    BRIGHT_RED = '\033[91m'
    BRIGHT_GREEN = '\033[92m'
    BRIGHT_YELLOW = '\033[93m'
    BRIGHT_BLUE = '\033[94m'
    BRIGHT_MAGENTA = '\033[95m'
    BRIGHT_CYAN = '\033[96m'
    BRIGHT_WHITE = '\033[97m'
    
    # Check if colors should be enabled
    @staticmethod
    def is_enabled() -> bool:
        """Check if colors should be enabled (output is a TTY)."""
        return sys.stdout.isatty()
    
    @staticmethod
    def colorize(text: str, color_code: str) -> str:
        """Apply color to text if colors are enabled.
        
        Args:
            text: Text to colorize
            color_code: ANSI color code
            
        Returns:
            Colorized text or original text if colors disabled
        """
        if Colors.is_enabled():
            return f"{color_code}{text}{Colors.RESET}"
        return text


# Color scheme for the application
class ColorScheme:
    """Color scheme for different UI elements."""
    
    # Page titles
    PAGE_TITLE = Colors.BRIGHT_CYAN
    
    # Lists
    LIST = Colors.CYAN
    
    # Action items and info
    ACTION = Colors.BRIGHT_YELLOW
    INFO = Colors.BRIGHT_YELLOW
    
    # Main info before confirmation (unconfirmed metadata)
    METADATA_UNCONFIRMED = Colors.YELLOW
    
    # Main info after confirmation (confirmed metadata for Zotero)
    METADATA_CONFIRMED = Colors.BRIGHT_GREEN
    
    # Timeout messages (low contrast - low information value)
    TIMEOUT = Colors.BRIGHT_BLACK

    # Muted/low-contrast secondary text
    MUTED = Colors.BRIGHT_BLACK
    
    # Success/Error
    SUCCESS = Colors.BRIGHT_GREEN
    ERROR = Colors.BRIGHT_RED
    WARNING = Colors.BRIGHT_YELLOW

    # Alias (some modules use WARN)
    WARN = WARNING

    # Enrichment diff colors (source-based)
    # - Zotero values (already present)
    ENRICH_ZOTERO = Colors.BRIGHT_GREEN
    # - Online values that will be auto-enriched (fillable)
    ENRICH_AUTO = Colors.BRIGHT_CYAN
    # - Online values requiring user choice / manual review
    ENRICH_MANUAL = Colors.BRIGHT_YELLOW

