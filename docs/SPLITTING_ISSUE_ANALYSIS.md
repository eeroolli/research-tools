# Two-Up Page Splitting Issue Analysis

## Problem Summary

Users report that double-page splits are poorly executed:
1. **Extra thin pages**: Often an extra page appears between two pages of text, containing only a thin slice with the gutter
2. **Text cutting**: When black borders were present, the split often cuts through text lines, which is unacceptable
3. **Timeline**: This issue has been occurring for the last week, affecting all double splits

## Root Cause Analysis

### Issue 1: Coordinate System Mismatch in Gutter Detection

**Location**: `_find_gutter_position()` lines 4623-4625

**Problem**:
```python
gutter_px = content_left_px + min_idx
gutter_pdf_points = (gutter_px / img_width) * page_width
```

- `gutter_px` is calculated relative to the content area (excluding borders detected per page)
- Conversion to PDF points uses full `page_width`
- Border removal **whitens** borders but does **not crop** pages (page dimensions unchanged)
- If borders vary per page, the content area shifts differently on each page, but the conversion assumes a consistent coordinate system
- This can result in `gutter_x` being calculated in the wrong coordinate space

**Impact**: Gutter position may be offset, causing splits to cut through text or create very thin pages

### Issue 2: Border Variation Not Handled

**Problem**:
- Borders can vary significantly from page to page (manual book placement on scanner)
- Gutter detection analyzes 3 pages and uses a single `median_gutter` for all pages
- If borders vary, the same `gutter_x` may be incorrect for pages with different border configurations
- Border detection happens per page in `_find_gutter_position()`, but the final gutter position is a single value applied to all pages

**Impact**: Gutter position may be correct for some pages but wrong for others, especially when borders are asymmetric or vary

### Issue 3: Gutter Detection May Find Wrong Position

**Location**: `_find_gutter_position()` lines 4568-4621

**Problem**:
- Algorithm searches middle 60% of content area (20-80% of content width)
- If borders are large and asymmetric, content area can be:
  - Very small (< 30% threshold causes page skip)
  - Shifted significantly from center
- Search region may miss actual gutter or find false minimum (e.g., within text)
- When borders are present, gutter detection might pick a position that cuts through text rather than finding the actual gutter

**Impact**: Incorrect gutter detection leads to splits that cut through text lines

### Issue 4: No Validation of Split Result

**Location**: `_split_with_custom_gutter()` lines 4902-4910

**Problem**:
- Creates pages without checking if split is reasonable
- If `gutter_x` is too close to 0 or `page_width`, creates very thin page
- No minimum page width validation
- No check that gutter position makes sense relative to content

**Impact**: Very thin pages containing only gutter are created and not filtered out

### Issue 5: Thin Page Hypothesis (User Observation)

**Problem**:
- If `gutter_x` is detected incorrectly (too close to edge or within text), one split page becomes very thin
- This thin page contains mostly just the gutter area
- Appears as "extra page between two pages of text"
- These thin pages should be detected and either:
  - Deleted (if they're just gutter artifacts)
  - Or the split should be rejected and user notified

**Impact**: Poor user experience with unnecessary thin pages in output

## Current Workflow

1. **Landscape detection** (BEFORE border removal) - `_process_selected_item()` line 8627-8650
2. **Border removal** - `_check_and_remove_dark_borders()` line 8653
3. **Gutter detection** - `_find_gutter_position()` called from `_split_with_mutool()` line 4940
4. **Splitting** - `_split_with_custom_gutter()` or geometric fallback

## Key Code Locations

- `_find_gutter_position()`: `scripts/paper_processor_daemon.py` lines 4358-4817
- `_split_with_custom_gutter()`: `scripts/paper_processor_daemon.py` lines 4864-4927
- `_split_with_mutool()`: `scripts/paper_processor_daemon.py` lines 4929-5061
- `_check_and_remove_dark_borders()`: `scripts/paper_processor_daemon.py` lines 5638-5750
- Border removal implementation: `shared_tools/pdf/border_remover.py`

## Proposed Solution Requirements

### 1. Fix Coordinate System Consistency

- Ensure gutter position is calculated in a consistent coordinate system
- Account for border variation when converting between pixel and PDF coordinates
- Consider calculating gutter position relative to content area, then converting properly to full page coordinates

### 2. Handle Per-Page Border Variation

- Option A: Calculate gutter position per page (more accurate but slower)
- Option B: Use border-aware coordinate conversion that accounts for border variation
- Option C: Detect if borders vary significantly and warn user or use per-page detection

### 3. Add Validation and Safety Checks

- **Minimum page width check**: Reject splits that would create pages < 10% of original width
- **Gutter position validation**: Ensure gutter is reasonable (30-70% of page width, not within text)
- **Content-aware validation**: Check that split doesn't cut through text (could use OCR or content density)
- **Thin page detection**: After splitting, detect and optionally remove pages that are mostly gutter

### 4. User Choice: "Leave Page Alone" Option

**Critical Requirement**: When detection results are questionable, give user the option to skip processing.

**Scenarios where user should be prompted**:
- Gutter position is outside normal range (30-70% of page width)
- Border variation is high (std dev > 20% of mean)
- Content area is very small (< 30% of page width)
- Gutter detection confidence is low
- Split would create very thin pages (< 10% of page width)

**User options**:
1. **Proceed with detected values** (current behavior)
2. **Use geometric split** (50% fallback)
3. **Leave page alone** - Skip border removal and/or splitting for this page/document
   - Useful when borders/gutter contain important content (images, annotations)
   - Useful when detection is clearly wrong
   - User can manually process later if needed

**Implementation suggestion**:
```python
def _validate_gutter_detection(gutter_x, page_width, borders, confidence_score):
    """Validate gutter detection and return (is_valid, warnings, user_choice_needed)"""
    warnings = []
    user_choice_needed = False
    
    # Check gutter position
    gutter_ratio = gutter_x / page_width
    if gutter_ratio < 0.3 or gutter_ratio > 0.7:
        warnings.append(f"Gutter position ({gutter_ratio:.1%}) is outside normal range (30-70%)")
        user_choice_needed = True
    
    # Check for thin pages
    left_width = gutter_x
    right_width = page_width - gutter_x
    min_page_ratio = min(left_width, right_width) / page_width
    if min_page_ratio < 0.1:
        warnings.append(f"Split would create very thin page ({min_page_ratio:.1%} of page width)")
        user_choice_needed = True
    
    # Check border variation
    if borders_vary_significantly(borders):
        warnings.append("Borders vary significantly across pages - detection may be inaccurate")
        user_choice_needed = True
    
    return (not user_choice_needed, warnings, user_choice_needed)
```

### 5. Post-Split Cleanup

- Detect and remove thin pages that are mostly gutter (< 5% content, > 80% white/gutter)
- Or merge thin pages with adjacent pages if they're clearly artifacts
- Log what was removed for user review

## Testing Requirements

1. **Test with varying borders**: PDFs where borders differ significantly per page
2. **Test with large asymmetric borders**: One side has much larger border than other
3. **Test edge cases**: Gutter detection near edges, within text, etc.
4. **Test "leave alone" option**: Verify user can skip processing when detection is poor
5. **Test thin page removal**: Verify thin gutter pages are detected and handled correctly

## Implementation Priority

1. **High**: Add validation and "leave alone" option (prevents bad splits)
2. **High**: Fix coordinate system consistency (fixes root cause)
3. **Medium**: Handle border variation (improves accuracy)
4. **Medium**: Post-split cleanup (improves output quality)
5. **Low**: Per-page gutter detection (optimization, if needed)

## Related Files

- `scripts/paper_processor_daemon.py` - Main daemon with splitting logic
- `shared_tools/pdf/border_remover.py` - Border detection and removal
- `docs/update book chapter splitting process.md` - Previous implementation notes

## Notes

- Border removal **whitens** borders but does **not crop** - page dimensions stay the same
- Gutter detection happens **after** border removal, so it works on cleaned pages
- Current code has instrumentation added for debugging (can be removed after fix)
- User reports this started happening "last week" - may be related to recent changes

