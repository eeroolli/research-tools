# Splitting Bugs - Runtime Evidence Analysis

## Issues Reported (User Testing)

### Issue 1: Printout - Empty Pages Between Text Pages
**Symptom**: Split was done at the right place, but left an empty page between each text page.

**Analysis**:
- The split position was correct (gutter detection worked)
- But the result has pattern: `[left content, empty page, right content, left content, empty page, right content, ...]`
- This suggests the split is creating 3 pages per original instead of 2
- OR one of the split pages is very thin (mostly empty) and should be detected/removed

**Hypothesis**:
- Gutter detection found a position that creates a very thin left or right page
- The thin page cleanup code (lines 4995-5014) assumes a 3-page pattern but doesn't detect thin pages correctly
- Thin pages should be detected by width ratio (< 10% of page width) but aren't being removed

### Issue 2: Book Copy - Extra Gutter Pages Between Text Pages  
**Symptom**: Left an extra page containing the gutter between each text page.

**Analysis**:
- Similar to Issue 1, but the extra page contains the gutter (not empty)
- Pattern: `[left content, gutter page, right content, left content, gutter page, right content, ...]`
- This suggests the split is creating 3 pages: left, gutter slice, right

**Hypothesis**:
- Gutter detection found a position that's too close to an edge
- This creates a very thin page on one side (containing mostly gutter)
- The cleanup code at lines 4995-5014 tries to remove gutter pages but:
  - Assumes 3-page pattern (left, gutter, right)
  - Only triggers if `actual_pages > expected_pages` where `expected_pages = len(doc) * 2`
  - If split creates 2 pages per original but one is thin, `actual_pages == expected_pages`, so cleanup doesn't run
  - The cleanup logic is wrong - it looks for pattern `i * 3 + 1` which assumes 3 pages per original

### Issue 3: Page Deletion Bug - Dropped Wrong Pages
**Symptom**: Asked to drop page 1, but it actually dropped pages 1 & 3, kept page 2 (which contains the gutter).

**Analysis**:
- User wanted to drop page 1 (first page after splitting)
- Expected result: Drop page 1, keep pages 2, 3, 4, ...
- Actual result: Dropped pages 1 & 3, kept page 2
- This is a serious bug in page deletion logic

**Possible Causes**:
1. **Index confusion**: User says "page 1" (1-indexed) but code uses 0-indexed
2. **Multiple deletion calls**: Maybe deletion is called multiple times with wrong indices
3. **Index shifting bug**: When deleting pages, indices shift, and code deletes wrong pages
4. **Wrong function called**: Maybe `_create_pdf_from_page_offset` is used instead of `_delete_first_page_from_pdf`

**Code Analysis**:
- `_delete_first_page_from_pdf()` (line 5764): `for page_num in range(1, len(doc))` - should copy pages 1, 2, 3... (correct)
- `_create_pdf_from_page_offset()` (line 5387): Returns None if `page_offset < 1` - this might be the issue!
  - If user enters "1" to drop page 1, `page_offset=1` means start from page 2 (index 1)
  - But the check `if page_offset < 1: return None` means offset 0 returns None
  - If user wants to drop page 1, they might enter "1", which becomes `page_offset=1`, which starts from page 2 (correct)
  - But if there's confusion about 0-indexed vs 1-indexed, this could cause issues

**Hypothesis**:
- The trim function `_prompt_trim_leading_pages_for_attachment` calls `_create_pdf_from_page_offset(pdf_path, pages_to_drop)`
- If user enters "1", `pages_to_drop=1`, which means start from page 1 (index 1), which is page 2
- But maybe the function is being called multiple times, or there's an off-by-one error
- OR the deletion is happening on a PDF that already has thin pages, and the indices are wrong

## Root Causes

### Root Cause 1: Empty/White Page Detection Not Working
**Location**: `_split_with_custom_gutter()` lines 4995-5014

**Critical Understanding**: **ALL PAGES ARE A4 SIZE** - they all have the same width/height dimensions. The issue is not about page dimensions, but about **content density**.

**Problem**:
- Cleanup code assumes 3-page pattern (left, gutter, right)
- But split creates 2 pages per original (left, right)
- If one page is mostly empty/white (thin content strip), `actual_pages == expected_pages`, so cleanup doesn't trigger
- The cleanup code only checks page count, not content
- **Width-based detection won't work** because all pages are A4 size

**What Actually Happens**:
- Split creates 2 A4 pages per original page
- Left page: A4 size, but content only in left portion (right side is white/empty)
- Right page: A4 size, but content only in right portion (left side is white/empty)
- If gutter is detected incorrectly, one page might be mostly white/empty (just a thin strip of content or gutter)
- These empty/white pages need to be detected by **content analysis**, not width

**Fix Needed**:
- After splitting, check each page's **content density**:
  - Text content: Check if page has < 50 characters of text
  - Image content: Render page as image, check if > 90% white pixels or < 5% non-white pixels
- Remove pages that are mostly empty/white regardless of total page count
- This requires image analysis (numpy/cv2) for scanned documents

### Root Cause 2: Gutter Position Creates Thin Pages
**Location**: `_find_gutter_position()` and `_split_with_custom_gutter()`

**Problem**:
- Gutter detection may find position too close to edge (< 10% or > 90%)
- Validation should reject these, but might not be working
- Or validation rejects but code still uses the position

**Fix Needed**:
- Ensure validation rejects gutter positions that would create thin pages
- Auto-fallback to 50/50 split if gutter would create thin pages
- Add minimum page width check before creating split pages

### Root Cause 3: Page Deletion Logic Error
**Location**: `_create_pdf_from_page_offset()` or `_delete_first_page_from_pdf()`

**Problem**:
- User reports dropping pages 1 & 3, keeping page 2
- This suggests either:
  - Multiple deletion calls with wrong indices
  - Index shifting bug when deleting pages
  - Wrong function being called

**Fix Needed**:
- Add logging to track which pages are being deleted
- Verify page deletion logic handles indices correctly
- Test with PDFs that have thin pages to ensure indices are correct

## Code Locations

1. **Thin page cleanup**: `scripts/paper_processor_daemon.py` lines 4995-5014
2. **Page splitting**: `scripts/paper_processor_daemon.py` lines 4985-4993
3. **Gutter validation**: `scripts/paper_processor_daemon.py` lines 4902-4921
4. **Page deletion**: `scripts/paper_processor_daemon.py` lines 5733-5795
5. **Page offset creation**: `scripts/paper_processor_daemon.py` lines 5377-5420

## Recommended Fixes

### Fix 1: Detect and Remove Empty/White Pages After Splitting
**Note**: All pages are A4 size, so we must check content, not width.

```python
# After creating all split pages, check for empty/white pages
pages_to_remove = []
for page_idx in range(len(new_doc)):
    page = new_doc[page_idx]
    
    # Check 1: Text content (fast)
    text = page.get_text()
    text_length = len(text.strip()) if text else 0
    
    # Check 2: Image content density (for scanned pages)
    # Render page as image, check white pixel ratio
    # If > 90% white OR < 5% content, page is empty
    
    # Remove if: very little text (< 50 chars) AND mostly white (> 90% white)
    if text_length < 50 and is_mostly_white(page):
        pages_to_remove.append(page_idx)

# Remove empty pages in reverse order
for page_idx in reversed(pages_to_remove):
    new_doc.delete_page(page_idx)
```

### Fix 2: Validate Gutter Position Before Splitting
**Note**: Validation should check if gutter position would create a page with mostly empty content, not just width.

```python
# In _split_with_custom_gutter, before creating pages:
# Check if gutter position is reasonable (30-70% of page width)
# This ensures both left and right pages have substantial content area
gutter_ratio = gutter_x / page_width
if gutter_ratio < 0.3 or gutter_ratio > 0.7:
    self.logger.warning(f"Gutter position {gutter_ratio:.1%} outside reasonable range - rejecting")
    return None  # Fall back to geometric split

# Additional check: ensure minimum content area
# (This is already in code at lines 4978-4983, but may not be working correctly)
```

### Fix 3: Fix Page Deletion Logic
- Add detailed logging to track which pages are being deleted
- Verify indices are correct (0-indexed vs 1-indexed)
- Test with various page counts and thin pages
- Consider using a more explicit deletion method

## Testing Requirements

1. **Test empty page detection**: Create PDFs with gutters that create empty/white pages, verify they're detected and removed
   - Test with scanned documents (image-based detection)
   - Test with text-based documents (text-based detection)
   - Verify pages that are mostly white (> 90%) are removed
   - Verify pages with < 50 characters of text are removed if also mostly white
2. **Test page deletion**: Test dropping page 1 with various PDF structures (with/without empty pages)
3. **Test edge cases**: Gutter at 5%, 10%, 15%, 30%, 50%, 70%, 85%, 90%, 95% of page width
4. **Test page count**: Verify output has correct number of pages after splitting and cleanup
5. **Test content detection**: Verify that pages with actual content (even if narrow) are NOT removed

## Notes

- **CRITICAL**: All pages are A4 size - width-based detection will NOT work
- Empty/white pages must be detected by content analysis (text + image density)
- Debug log didn't capture splitting data (logging may have failed silently)
- User provided clear symptoms but we need runtime data to confirm hypotheses
- All three issues are related to page management after splitting
- Fixes should be coordinated to avoid creating new bugs

## Additional Analysis Needed

From terminal output:
- Document 1 (printout): Gutter at 385.8 points - created empty pages
- Document 2 (book): Gutter at 430.2 points - created gutter pages

**Questions for Planning Agent**:
1. Why does validation pass for gutters at 385.8 and 430.2 points? What is the page width?
2. Are these gutters actually within 30-70% range, or is validation not working?
3. How should we detect empty pages - text-based, image-based, or both?
4. What threshold should we use for "mostly white" (> 90%? > 95%?)?
5. Should we check content density before or after splitting, or both?

