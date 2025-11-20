"""Page-based navigation system for interactive CLI flows.

This module provides a clean, testable framework for managing multi-page
interactive flows with consistent navigation commands (z=back, q=quit, etc.).
"""

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Union
from pathlib import Path
from enum import Enum


class NavigationResult:
    """Result of a page handler or navigation action.
    
    This class uses a factory pattern to create different result types:
    - NavigationResult.show_page(page_id) - Navigate to another page
    - NavigationResult.return_to_caller() - Return to calling function
    - NavigationResult.quit_scan(move_to_manual=False) - Quit with optional manual review
    - NavigationResult.process_pdf() - Process the PDF and exit
    """
    
    class Type(Enum):
        """Types of navigation results."""
        SHOW_PAGE = "show_page"
        RETURN_TO_CALLER = "return_to_caller"
        QUIT_SCAN = "quit_scan"
        PROCESS_PDF = "process_pdf"
    
    def __init__(self, result_type: Type, page_id: Optional[str] = None, 
                 move_to_manual: bool = False):
        """Create a navigation result.
        
        Args:
            result_type: Type of result
            page_id: Page ID to navigate to (for SHOW_PAGE only)
            move_to_manual: Whether to move to manual review (for QUIT_SCAN)
        """
        self.type = result_type
        self.page_id = page_id
        self.move_to_manual = move_to_manual
    
    @classmethod
    def show_page(cls, page_id: str) -> 'NavigationResult':
        """Create a result that navigates to another page."""
        return cls(cls.Type.SHOW_PAGE, page_id=page_id)
    
    @classmethod
    def return_to_caller(cls) -> 'NavigationResult':
        """Create a result that returns to the calling function."""
        return cls(cls.Type.RETURN_TO_CALLER)
    
    @classmethod
    def quit_scan(cls, move_to_manual: bool = False) -> 'NavigationResult':
        """Create a result that quits the scan flow.
        
        Args:
            move_to_manual: If True, move PDF to manual review
        """
        return cls(cls.Type.QUIT_SCAN, move_to_manual=move_to_manual)
    
    @classmethod
    def process_pdf(cls) -> 'NavigationResult':
        """Create a result that processes the PDF and exits."""
        return cls(cls.Type.PROCESS_PDF)
    
    def __eq__(self, other):
        """Compare navigation results."""
        if not isinstance(other, NavigationResult):
            return False
        return (self.type == other.type and 
                self.page_id == other.page_id and
                self.move_to_manual == other.move_to_manual)
    
    def __repr__(self):
        """String representation for debugging."""
        if self.type == NavigationResult.Type.SHOW_PAGE:
            return f"NavigationResult.show_page('{self.page_id}')"
        elif self.type == NavigationResult.Type.QUIT_SCAN:
            return f"NavigationResult.quit_scan(move_to_manual={self.move_to_manual})"
        else:
            return f"NavigationResult.{self.type.value}()"


@dataclass
class Page:
    """Represents a single page in a navigation flow.
    
    A page defines:
    - What to display (title and content)
    - What inputs are valid
    - How to handle each input (handlers)
    - Navigation behavior (back page, quit action, default)
    """
    page_id: str
    title: str
    content: Callable[[dict], List[str]]  # context -> list of lines to display
    prompt: str
    valid_inputs: List[str]
    handlers: Dict[str, Callable[[dict], NavigationResult]]
    default: Optional[str] = None  # Default choice for Enter key
    back_page: Optional[str] = None  # Page to go back to (for 'z' command)
    quit_action: Optional[Callable[[dict], NavigationResult]] = None  # Action for 'q' command
    
    def __post_init__(self):
        """Validate page configuration."""
        # Ensure standard commands are in valid_inputs if they're used
        if self.back_page and 'z' not in self.valid_inputs:
            self.valid_inputs.append('z')
        if self.quit_action and 'q' not in self.valid_inputs:
            self.valid_inputs.append('q')


@dataclass
class ItemSelectedContext:
    """Context for handle_item_selected flow.
    
    Carries all state needed between pages in the item selection flow.
    """
    pdf_path: Path
    metadata: dict
    selected_item: dict
    item_key: Optional[str] = None
    target_filename: Optional[str] = None
    scan_size_mb: Optional[float] = None
    zotero_authors: Optional[List[str]] = None
    zotero_title: Optional[str] = None
    zotero_year: Optional[str] = None
    zotero_item_type: Optional[str] = None
    has_pdf: bool = False
    
    def to_dict(self) -> dict:
        """Convert to dict for page handlers.
        
        Page handlers receive context as a dict for flexibility.
        """
        return {
            'pdf_path': self.pdf_path,
            'metadata': self.metadata,
            'selected_item': self.selected_item,
            'item_key': self.item_key or self.selected_item.get('key'),
            'target_filename': self.target_filename,
            'scan_size_mb': self.scan_size_mb,
            'pdf_name': self.pdf_path.name,
            'has_pdf': self.has_pdf,
            'zotero_authors': self.zotero_authors or self.selected_item.get('authors', []),
            'zotero_title': self.zotero_title or self.selected_item.get('title', ''),
            'zotero_year': self.zotero_year or self.selected_item.get('year', ''),
            'zotero_item_type': self.zotero_item_type or self.selected_item.get('itemType', 'journalArticle'),
        }


class NavigationEngine:
    """Engine for managing page-based navigation flows.
    
    Handles displaying pages, validating input, and executing navigation.
    Provides consistent behavior for standard commands (z=back, q=quit).
    """
    
    def __init__(self, pages: Dict[str, Page]):
        """Initialize navigation engine.
        
        Args:
            pages: Dictionary mapping page_id to Page objects
        """
        self.pages = pages
    
    def show_page(self, page_id: str, context: dict) -> NavigationResult:
        """Display a page and handle user input.
        
        Args:
            page_id: ID of page to show
            context: Context dict to pass to content generator and handlers
            
        Returns:
            NavigationResult indicating what to do next
        """
        page = self.pages.get(page_id)
        if not page:
            raise ValueError(f"Page not found: {page_id}")
        
        # Display page
        print("\n" + "="*70)
        print(page.title)
        print("="*70)
        for line in page.content(context):
            print(line)
        print("="*70)
        print()
        
        # Get and process input
        while True:
            user_input = input(page.prompt).strip().lower()
            
            # Standardize input (handle Enter key for default)
            user_input = self.standardize_input(user_input, page)
            
            # Validate input
            if not self.validate_input(user_input, page):
                print(f"⚠️  Invalid choice. Valid: {', '.join(page.valid_inputs)}")
                continue
            
            # Handle standard commands
            if user_input == 'z' and page.back_page:
                return NavigationResult.show_page(page.back_page)
            
            if user_input == 'q' and page.quit_action:
                return page.quit_action(context)
            
            # Execute handler for this input
            handler = page.handlers.get(user_input)
            if handler:
                result = handler(context)
                return result
            else:
                # Handler not found - this shouldn't happen if page is configured correctly
                print(f"⚠️  Handler not found for '{user_input}'")
                continue
    
    def standardize_input(self, raw_input: str, page: Page) -> str:
        """Normalize user input (e.g., Enter key -> default choice).
        
        Args:
            raw_input: Raw user input
            page: Current page
            
        Returns:
            Normalized input string
        """
        # Empty input (Enter key) -> use default if available
        if not raw_input and page.default:
            return page.default
        
        return raw_input
    
    def validate_input(self, user_input: str, page: Page) -> bool:
        """Validate that user input is allowed on this page.
        
        Args:
            user_input: User input to validate
            page: Current page
            
        Returns:
            True if input is valid
        """
        return user_input in page.valid_inputs
    
    def run_page_flow(self, start_page: str, context: dict) -> NavigationResult:
        """Run page flow starting from start_page.
        
        Continuously displays pages and handles navigation until a terminal
        result is reached (RETURN_TO_CALLER, QUIT_SCAN, or PROCESS_PDF).
        
        Special handling for pages that need custom input collection (e.g., multi-line).
        
        Args:
            start_page: Page ID to start from
            context: Context dict to pass between pages
            
        Returns:
            Final NavigationResult
        """
        current_page = start_page
        
        while True:
            page = self.pages.get(current_page)
            if not page:
                raise ValueError(f"Page not found: {current_page}")
            
            # Special handling for note_input page (multi-line input)
            if current_page == 'note_input':
                result = self._handle_note_input_page(page, context)
            else:
                result = self.show_page(current_page, context)
            
            # Terminal results - exit flow
            if result.type == NavigationResult.Type.RETURN_TO_CALLER:
                return result
            elif result.type == NavigationResult.Type.QUIT_SCAN:
                return result
            elif result.type == NavigationResult.Type.PROCESS_PDF:
                return result
            elif result.type == NavigationResult.Type.SHOW_PAGE:
                # Navigate to next page
                if not result.page_id:
                    raise ValueError("SHOW_PAGE result must have page_id")
                current_page = result.page_id
            else:
                raise ValueError(f"Unexpected navigation result type: {result.type}")
    
    def _handle_note_input_page(self, page: Page, context: dict) -> NavigationResult:
        """Handle note input page with multi-line input collection.
        
        Args:
            page: Note input page
            context: Context dict
            
        Returns:
            NavigationResult
        """
        # Display page
        print("\n" + "="*70)
        print(page.title)
        print("="*70)
        for line in page.content(context):
            print(line)
        print("="*70)
        
        # Collect multi-line input
        note_lines = []
        print()  # Empty line before input
        while True:
            try:
                line = input()
                if not line.strip():
                    break
                note_lines.append(line)
            except (KeyboardInterrupt, EOFError):
                # On interrupt, check if user wants to cancel
                print("\n⚠️  Input cancelled")
                return NavigationResult.show_page(page.back_page) if page.back_page else NavigationResult.return_to_caller()
        
        # Call the handler (which should be in handlers dict)
        # For note_input, we expect a handler that processes the note
        if note_lines:
            # Store note in context temporarily
            context['_note_lines'] = note_lines
            # Call handler if available (typically 'process')
            handler = page.handlers.get('process')
            if handler:
                return handler(context)
            else:
                # Default: process PDF after note
                return NavigationResult.process_pdf()
        else:
            # No note entered, process PDF
            return NavigationResult.process_pdf()

