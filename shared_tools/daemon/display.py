#!/usr/bin/env python3
"""
Display module for daemon operations.

Provides metadata formatting and display utilities with color support.
"""

import logging
from typing import Dict, Any, Optional

from shared_tools.ui.colors import Colors, ColorScheme


class MetadataDisplay:
    """Formats and displays metadata for user presentation."""
    
    def __init__(self, color_scheme: Optional[ColorScheme] = None, logger: Optional[logging.Logger] = None):
        """Initialize metadata display.
        
        Args:
            color_scheme: Optional color scheme for formatting
            logger: Optional logger instance
        """
        self.colors = color_scheme or Colors()
        self.logger = logger or logging.getLogger(__name__)
    
    def format_metadata(self, metadata: Dict[str, Any]) -> str:
        """Format metadata dictionary as a readable string.
        
        Args:
            metadata: Metadata dictionary
            
        Returns:
            Formatted metadata string
        """
        lines = []
        
        if metadata.get('title'):
            lines.append(f"Title: {metadata['title']}")
        
        if metadata.get('authors'):
            authors_str = ', '.join(metadata['authors'])
            lines.append(f"Authors: {authors_str}")
        
        if metadata.get('year'):
            lines.append(f"Year: {metadata['year']}")
        
        if metadata.get('journal'):
            lines.append(f"Journal: {metadata['journal']}")
        
        if metadata.get('doi'):
            lines.append(f"DOI: {metadata['doi']}")
        
        if metadata.get('url'):
            lines.append(f"URL: {metadata['url']}")
        
        return '\n'.join(lines)
    
    def display_metadata(self, metadata: Dict[str, Any], title: str = "Extracted Metadata"):
        """Display metadata to user with formatting.
        
        Args:
            metadata: Metadata dictionary to display
            title: Title for the metadata section
        """
        print(f"\n{title}")
        print("-" * len(title))
        formatted = self.format_metadata(metadata)
        print(formatted)
        print()
    
    def format_field(self, field_name: str, value: Any, width: int = 20) -> str:
        """Format a single metadata field.
        
        Args:
            field_name: Name of the field
            value: Value of the field
            width: Width for field name alignment
            
        Returns:
            Formatted field string
        """
        if value is None:
            return f"{field_name:>{width}}: (not available)"
        
        if isinstance(value, list):
            value_str = ', '.join(str(v) for v in value)
        else:
            value_str = str(value)
        
        return f"{field_name:>{width}}: {value_str}"
    
    def display_field_comparison(
        self,
        field_name: str,
        current: Any,
        proposed: Any,
        width: int = 20
    ):
        """Display comparison of current vs proposed field value.
        
        Args:
            field_name: Name of the field
            current: Current value
            proposed: Proposed new value
            width: Width for field name alignment
        """
        current_str = str(current) if current else "(empty)"
        proposed_str = str(proposed) if proposed else "(empty)"
        
        print(f"{field_name:>{width}}:")
        print(f"  Current:  {current_str}")
        print(f"  Proposed: {proposed_str}")

