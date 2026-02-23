Implementing page 1 deletion for book chapters after splitting. Reviewing the relevant sections, then making the changes.


[3 tools called]

Checking if PyMuPDF (fitz) is available and how it's used:


[2 tools called]

Implementing the changes:


[2 tools called]

Updating `_process_selected_item()` to add the book chapter page 1 deletion check:


[2 tools called]

Checking step numbering and linting errors:


[2 tools called]

No linting errors. Verifying the logic flow and checking for edge cases:


[1 tool called]

## Summary

Implemented page 1 deletion for book chapters after splitting, and intelligent gutter detection for two-up page splitting.

### **Changes Made**

1. **New method: `_delete_first_page_from_pdf()`** (lines 3416-3465)
   - Uses PyMuPDF (fitz) to remove page 1
   - Validates the PDF has more than 1 page
   - Creates a new temporary PDF without page 1
   - Returns the modified PDF path or None on failure

2. **Updated `_process_selected_item()`** (lines 5152-5164)
   - After splitting, checks if document type is `book_chapter`
   - Prompts user: "Delete page 1 from the split PDF? [y/N]:"
   - If confirmed, deletes page 1 and updates the PDF used for Zotero attachment
   - Falls back to original split PDF if deletion fails

3. **Intelligent Gutter Detection** (January 2026)
   - **New method: `_find_gutter_position()`** - Detects actual gutter position using image analysis
   - **New method: `_split_with_custom_gutter()`** - Splits PDFs at detected gutter coordinate
   - **Updated: `_split_with_mutool()`** - Now uses intelligent gutter detection before falling back to geometric split
   - **Updated workflow:** Border removal happens first, then intelligent splitting

### **Features**

#### Page 1 Deletion
- Only triggers for book chapters after splitting
- Requires user confirmation before deletion
- Safe: only modifies temporary split files, preserves originals
- Error handling: falls back to original split if deletion fails
- Validates PDF has multiple pages before attempting deletion

#### Intelligent Gutter Detection
- **Dual detection methods:**
  - **Spine detection** (physical books): Finds darker gray spine area in the middle
  - **Content detection** (printed articles): Finds minimum content density (white space)
- **Automatic method selection:** Chooses method based on signal strength (15% threshold)
- **Multi-page validation:** Analyzes 3 pages for consistency
- **Border-aware:** Accounts for dark borders when detecting gutter
- **Fallback:** Uses geometric split (50%) if detection fails

### **Workflow**

#### Two-Up Pages (Updated January 2026)
1. **Detect landscape/two-up pages** (BEFORE border removal to ensure accurate detection)
   - Check for `_double.pdf` filename pattern
   - For other files: Check aspect ratio and detect two-up layout using content analysis
   - Store detection results (dimensions, two-up status, gutter position)
2. **Remove borders** from entire PDF (consistent UX for all pages)
3. **Split at detected gutter** (or geometric if detection failed):
   - For physical books: Uses darker spine marker position
   - For printed articles: Uses content gap position
   - Falls back to 50% geometric split if detection failed
4. If document type is `book_chapter`, user is prompted to delete page 1
5. Modified PDF used for Zotero attachment

#### Single Pages (Updated January 2026)
1. **Detect landscape pages** (BEFORE border removal - stored but not split)
2. **Remove borders** from entire PDF (consistent UX)
3. **Trim leading pages** (if needed)

### **Technical Details**

**Gutter Detection Algorithm:**
- Renders pages as images (2x zoom)
- Detects borders first to exclude from analysis
- Calculates vertical projection profiles:
  - Spine method: Average brightness per column (lower = darker spine)
  - Content method: Content density per column (lower = less text)
- Finds minimum in middle 60% of content area
- Validates gutter is between 30-70% of page width
- Checks consistency across pages (std dev < 10%)

**Method Selection:**
- If spine signal > 15% darker than average → Use spine method (physical book)
- Otherwise → Use content method (printed article)

Ready for testing. The intelligent gutter detection significantly improves splitting accuracy for physical book scans with visible spines.

## Border Removal Integration (Completed January 2026)

### Status
✅ **COMPLETE** - Border removal now integrated into splitting workflow

### Implementation
- **Landscape detection happens FIRST** (before border removal) to ensure accurate detection
- Border removal happens **second** (after landscape detection, before splitting) for consistent UX
- Works for both single and two-up pages
- Uses existing `BorderRemover` class with projection profile analysis
- Interactive detection and removal with user confirmation

### Benefits
- Landscape detection works correctly even if border removal changes dimensions
- Cleaner pages for gutter detection
- Consistent workflow for all document types
- Borders removed before splitting prevents incorrect splits
- No redundant operations

### Technology Stack
- **PyMuPDF (fitz)** - PDF→image conversion and PDF reconstruction
- **OpenCV (cv2)** - Edge detection and border cropping
- **PIL/Pillow** - Image processing operations
- **BorderRemover** - Projection profile analysis for border detection

See `implementation-plan.md` Phase 4.4 for details. 