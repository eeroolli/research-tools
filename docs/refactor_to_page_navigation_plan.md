# Plan: Refactor to Page-Based Navigation System

## Recent Changes (Nov 1-3, 2025)

### Commits Since Plan Was Written

1. **fix: standardize navigation in handle_item_selected UX** (Nov 3, 17:45)
   - PROPOSED ACTIONS is now nested inside REVIEW loop (improves structure)
   - Note prompt properly returns to PROPOSED ACTIONS (not exits)
   - z/q navigation is now consistent across flow
   - Navigation hierarchy: REVIEW & PROCEED → PROPOSED ACTIONS → Note Prompt

2. **fix: add cancel option to note prompt** (Nov 3, 16:20)
   - Note prompt now has 'z' (cancel/go back) option
   - Returns False when cancelled, causing return to PROPOSED ACTIONS

3. **feature: add handwritten note prompt to Zotero items** (Nov 3, 16:04)
   - `_prompt_for_note()` function implemented
   - Integrated into handle_item_selected flow
   - Multi-line note input support

4. **fix: proper handling of restart command in Zotero search** (Nov 3, 16:18)
   - 'r' command now properly restarts instead of quitting
   - Added to year confirmation prompt

### Impact on Plan

**Positive Changes:**
- Navigation structure is already improved (PROPOSED ACTIONS nested in REVIEW)
- Note prompt is already extracted as separate function
- z/q navigation is more consistent (though still needs full page system)

**Plan Updates:**
- Removed outdated line number references (code has moved)
- Updated NOTE_PROMPT_PAGE description to reflect current implementation
- Updated flow descriptions to match current nested structure
- Acknowledged that some navigation improvements are already in place

## Problem Analysis

### Current Issues
1. **Nested loops with breaks** - Fragile control flow, hard to debug (partially addressed by recent refactoring)
2. **Inconsistent navigation** - z/q/r commands work differently in different contexts (partially improved)
3. **Deep nesting** - `handle_item_selected` has 3+ levels of nested if/elif/while (structure improved but still needs page system)
4. **Mixed concerns** - Display, input, navigation, and business logic all intertwined
5. **Hard to test** - Can't test individual pages in isolation
6. **Hard to extend** - Adding new pages requires understanding entire flow

### Root Cause
The current architecture mixes navigation logic with business logic, creating tight coupling and making it impossible to reason about control flow statically. Recent refactoring has improved structure but a formal page system is still needed.

## Solution: Page-Based Navigation System

### Core Concept
- **Pages** are self-contained units with: display content, input validation, navigation handlers
- **Context** object carries state between pages
- **Navigation** is explicit: `next_page = handlers[choice](context)`
- **Standard commands**: z (back), q (quit), r (restart) work consistently

### Benefits
1. **Testable** - Each page can be tested independently
2. **Maintainable** - Clear separation of concerns
3. **Debuggable** - Can log current page state
4. **Extensible** - Add new pages without touching existing code
5. **Consistent** - Same navigation model everywhere

## Implementation Plan

### Phase 1: Design & Foundation (Week 1)

#### Step 1.1: Define Page Data Structure
- [ ] Create `Page` dataclass or TypedDict with:
  - `page_id: str` - Unique identifier
  - `title: str` - Page header
  - `content: Callable[[Context], List[str]]` - Dynamic content generator
  - `prompt: str` - Input prompt text
  - `valid_inputs: List[str]` - Allowed inputs (e.g., ['y', 'n', 'z', 'q'])
  - `handlers: Dict[str, Callable[[Context], NavigationResult]]` - Action handlers
  - `default: Optional[str]` - Default choice (Enter key)
  - `back_page: Optional[str]` - Previous page ID (for 'z')
  - `quit_action: Optional[Callable[[Context], None]]` - Action for 'q'

- [ ] Create `Context` class/typeddict for state:
  - `pdf_path: Path`
  - `metadata: dict`
  - `selected_item: dict`
  - `target_filename: Optional[str]`
  - `item_key: Optional[str]`
  - Any other state needed

- [ ] Create `NavigationResult` enum/class:
  - `ShowPage(page_id: str)`
  - `ReturnToCaller()`
  - `QuitScan()`
  - `ProcessPDF()` - Exit and process

#### Step 1.2: Create Navigation Engine
- [ ] Create `NavigationEngine` class:
  - `show_page(page_id: str, context: Context) -> NavigationResult`
  - `handle_input(page: Page, user_input: str, context: Context) -> NavigationResult`
  - `standardize_input(raw_input: str, page: Page) -> str` - Normalize Enter/defaults
  - `validate_input(user_input: str, page: Page) -> bool`
  - `run_page_flow(start_page: str, context: Context) -> NavigationResult`

### Phase 2: Refactor handle_item_selected (Week 1-2)

#### Step 2.1: Extract Page Definitions
Map current flow to pages (updated to reflect recent code changes):

1. **REVIEW_AND_PROCEED_PAGE**
   - Current: Function `handle_item_selected()` - main outer loop
   - Inputs: y (proceed), e (edit), z (back)
   - Handlers:
     - 'y' → PROPOSED_ACTIONS_PAGE (now nested inside REVIEW loop)
     - 'e' → EDIT_TAGS_PAGE
     - 'z' → ReturnToCaller()
   - Note: PROPOSED_ACTIONS is now nested inside REVIEW loop (improved structure from recent refactoring)

2. **EDIT_TAGS_PAGE**
   - Current: Inside `handle_item_selected()` - tag editing submenu
   - Inputs: t (edit tags), z (back), m (manual review)
   - Handlers:
     - 't' → EDIT_TAGS_INTERACTIVE (uses existing `edit_tags_interactively()`)
     - 'z' → REVIEW_AND_PROCEED_PAGE
     - 'm' → QuitScan(move_to_manual=True)

3. **EDIT_TAGS_INTERACTIVE_PAGE**
   - Uses: `edit_tags_interactively()` - already separate function
   - After editing: PROCEED_AFTER_EDIT_PAGE (inline prompt after tag editing)

4. **PROCEED_AFTER_EDIT_PAGE**
   - Current: Inline prompt after tag editing
   - Inputs: y (proceed), n (back)
   - Handlers:
     - 'y' → PROPOSED_ACTIONS_PAGE
     - 'n' → REVIEW_AND_PROCEED_PAGE

5. **PROPOSED_ACTIONS_PAGE**
   - Current: Nested loop inside REVIEW loop (recently refactored)
   - Inputs: y (proceed), z (back), q (quit)
   - Handlers:
     - 'y' → NOTE_PROMPT_PAGE
     - 'z' → REVIEW_AND_PROCEED_PAGE (breaks out of nested loop)
     - 'q' → QuitScan(move_to_manual=True)

6. **NOTE_PROMPT_PAGE**
   - Current: `_prompt_for_note()` - already separate function
   - **UPDATED**: Inputs: Enter (skip), n (add note), z (cancel/go back)
   - Handlers:
     - Enter → ProcessPDF()
     - 'n' → NOTE_INPUT_PAGE (multi-line input)
     - 'z' → PROPOSED_ACTIONS_PAGE (returns False, causes continue in PROPOSED ACTIONS loop)
   - Note: Already extracted as separate function. The 'z' cancel option was added in recent commit.

7. **NOTE_INPUT_PAGE**
   - Current: Inside `_prompt_for_note()` - multi-line input collection
   - Multi-line input
   - After input: ProcessPDF()

#### Step 2.2: Implement Page Definitions
- [ ] Create `handle_item_selected_pages.py` module (or section in daemon)
- [ ] Define each page as constant dictionary
- [ ] Wire up handlers (initially call existing functions)
- [ ] Test each page in isolation

#### Step 2.3: Refactor handle_item_selected
- [ ] Replace nested loops with `NavigationEngine.run_page_flow(REVIEW_AND_PROCEED_PAGE, context)`
- [ ] Create initial context from parameters
- [ ] Handle NavigationResult:
  - `ReturnToCaller()` → return
  - `QuitScan()` → move_to_manual_review and return
  - `ProcessPDF()` → call `_process_selected_item` and return
- [ ] **Preserve**: Current nested structure where PROPOSED ACTIONS is inside REVIEW loop (this is good design from recent refactoring)

#### Step 2.4: Extract Helper Functions
Keep these as separate functions (already good):
- `_display_zotero_item_details()` ✓
- `edit_tags_interactively()` ✓
- `_prompt_for_note()` ✓ (already extracted, needs page integration to return NavigationResult)
- `_process_selected_item()` ✓
- `_generate_filename_from_zotero_metadata()` - Extract if needed

### Phase 3: Standardize Navigation Commands (Week 2)

#### Step 3.1: Standard Command Mapping
- [ ] Define standard commands:
  - `z` - Go back one page (always available) - **Already partially implemented**
  - `q` - Quit scan (move to manual review, always available) - **Already partially implemented**
  - `r` - Restart search (where applicable) - **Already implemented in search flows**
  - `Enter` - Default action (page-specific) - **Already implemented**

- [ ] Add to all pages:
  - 'z' handler → `show_page(page.back_page, context)`
  - 'q' handler → `page.quit_action(context)`

#### Step 3.2: Update All Pages
- [ ] Add 'z' and 'q' to all page definitions
- [ ] Set `back_page` on all pages
- [ ] Set `quit_action` on all pages
- [ ] Test navigation works consistently
- [ ] **Note**: Current implementation already has good z/q support, formalize in page system

### Phase 4: Testing & Validation (Week 2)

#### Step 4.1: Unit Tests
- [ ] Test each page independently:
  - Content generation
  - Input validation
  - Handler execution
  - Navigation results

#### Step 4.2: Integration Tests
- [ ] Test full flow:
  - Review → Proceed → Actions → Note → Process ✓
  - Review → Edit → Tags → Proceed → Actions → Process ✓
  - Review → z (back to caller) ✓
  - Actions → z (back to review) ✓
  - Note → z (back to actions) ✓
  - Any page → q (quit) ✓

#### Step 4.3: Manual Testing
- [ ] Test with real PDFs
- [ ] Test edge cases (missing metadata, etc.)
- [ ] Verify files are processed correctly
- [ ] Verify files are moved to done/ correctly

### Phase 5: Expand to Other Flows (Week 3+)

#### Step 5.1: Identify Other Navigation Flows
- [ ] `handle_create_new_item()` - Similar nested structure
- [ ] `search_and_display_local_zotero()` - Author selection flow
- [ ] `process_paper()` - Main workflow orchestration
- [ ] Any other interactive flows

#### Step 5.2: Apply Same Pattern
- [ ] Extract pages for each flow
- [ ] Use NavigationEngine
- [ ] Test thoroughly

## Implementation Details

### Page Definition Example

```python
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional
from enum import Enum

class NavigationResult(Enum):
    SHOW_PAGE = "show_page"
    RETURN_TO_CALLER = "return_to_caller"
    QUIT_SCAN = "quit_scan"
    PROCESS_PDF = "process_pdf"

@dataclass
class Page:
    page_id: str
    title: str
    content: Callable[[dict], List[str]]  # context -> list of lines
    prompt: str
    valid_inputs: List[str]
    handlers: Dict[str, Callable[[dict], NavigationResult]]
    default: Optional[str] = None
    back_page: Optional[str] = None
    quit_action: Optional[Callable[[dict], NavigationResult]] = None

# Example page definition
REVIEW_AND_PROCEED_PAGE = Page(
    page_id="review_and_proceed",
    title="REVIEW & PROCEED",
    content=lambda ctx: [
        "  (y/Enter) Proceed with attaching PDF to this item",
        "  (e) Edit metadata in Zotero first",
        "  (z) Go back to item selection",
        "  (q) Quit - move to manual review"
    ],
    prompt="Proceed or edit? [y/e/z/q]:",
    valid_inputs=['y', 'e', 'z', 'q'],
    handlers={
        'y': lambda ctx: NavigationResult.SHOW_PAGE('proposed_actions'),
        'e': lambda ctx: NavigationResult.SHOW_PAGE('edit_tags'),
        'z': lambda ctx: NavigationResult.RETURN_TO_CALLER,
        'q': lambda ctx: NavigationResult.QUIT_SCAN
    },
    default='y',
    back_page=None,  # Top level
    quit_action=lambda ctx: NavigationResult.QUIT_SCAN
)
```

### NavigationEngine Implementation

```python
class NavigationEngine:
    def __init__(self, pages: Dict[str, Page]):
        self.pages = pages
        self.context = {}
    
    def show_page(self, page_id: str, context: dict):
        """Display a page and handle user input."""
        page = self.pages[page_id]
        
        # Display
        print("\n" + "="*70)
        print(page.title)
        print("="*70)
        for line in page.content(context):
            print(line)
        print("="*70)
        print()
        
        # Get input
        while True:
            user_input = input(page.prompt).strip().lower()
            
            # Handle empty input (default)
            if not user_input and page.default:
                user_input = page.default
            
            # Handle standard commands
            if user_input == 'z' and page.back_page:
                return NavigationResult.SHOW_PAGE(page.back_page)
            if user_input == 'q' and page.quit_action:
                return page.quit_action(context)
            
            # Validate
            if user_input not in page.valid_inputs:
                print(f"⚠️  Invalid choice. Valid: {', '.join(page.valid_inputs)}")
                continue
            
            # Execute handler
            handler = page.handlers.get(user_input)
            if handler:
                result = handler(context)
                return result
            else:
                print(f"⚠️  Handler not found for '{user_input}'")
                continue
    
    def run_flow(self, start_page: str, context: dict):
        """Run page flow starting from start_page."""
        current_page = start_page
        
        while True:
            result = self.show_page(current_page, context)
            
            if result == NavigationResult.RETURN_TO_CALLER:
                return result
            elif result == NavigationResult.QUIT_SCAN:
                return result
            elif result == NavigationResult.PROCESS_PDF:
                return result
            elif isinstance(result, tuple) and result[0] == NavigationResult.SHOW_PAGE:
                current_page = result[1]
            else:
                # Unexpected result
                raise ValueError(f"Unexpected navigation result: {result}")
```

### Context Object

```python
@dataclass
class ItemSelectedContext:
    """Context for handle_item_selected flow."""
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
        """Convert to dict for page handlers."""
        return {
            'pdf_path': self.pdf_path,
            'metadata': self.metadata,
            'selected_item': self.selected_item,
            'item_key': self.item_key or self.selected_item.get('key'),
            'target_filename': self.target_filename,
            'scan_size_mb': self.scan_size_mb,
            'pdf_name': self.pdf_path.name,
            'has_pdf': self.has_pdf,
            # ... other fields
        }
```

## Risk Assessment

### High Risk
- **Breaking existing functionality** - Mitigation: Extensive testing, gradual migration
- **Performance regression** - Mitigation: Pages are lightweight, minimal overhead

### Medium Risk
- **Learning curve** - New developers need to understand page system
- **Migration complexity** - Need to migrate all flows eventually

### Low Risk
- **Code size increase** - Pages are data structures, not code bloat
- **Over-engineering** - Pages are simple enough, just better organized

## Success Criteria

1. ✅ `handle_item_selected` has no nested loops (max 1 level)
2. ✅ All pages support z/q/r consistently
3. ✅ Navigation flow is clear from page definitions
4. ✅ Each page can be tested independently
5. ✅ Files are still processed correctly (moved to done/)
6. ✅ No regression in user experience
7. ✅ Code is easier to understand and maintain

## Timeline

- **Week 1**: Phases 1-2 (Design + Refactor handle_item_selected)
- **Week 2**: Phases 3-4 (Standardize + Test)
- **Week 3+**: Phase 5 (Expand to other flows)

## Additional Notes

1. **Current Code Structure**: The recent navigation standardization commit (c4eaa0b8) has already improved the structure by nesting PROPOSED ACTIONS inside REVIEW. This is a good pattern to preserve.

2. **Note Prompt Integration**: The `_prompt_for_note()` function is already extracted and integrated. It needs to be adapted to return NavigationResult instead of bool for full page system integration.

3. **Line Numbers**: Removed specific line number references as code has changed. Use function names and descriptions instead.

4. **Progress**: Some goals (navigation consistency, function extraction) are partially achieved. The page system will formalize and extend these improvements.

## Next Steps

1. Review this plan
2. Approve approach
3. Start with Phase 1: Create Page data structures and NavigationEngine
4. Implement one page as proof of concept
5. Refactor handle_item_selected incrementally

