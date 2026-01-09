---
name: Content-Aware Border Removal and Split Detection
overview: "Complete reworking of gutter detection and border removal using content-aware approach: detect text columns/white margins instead of dark borders. Uses binary search edge detection algorithm for efficiency. Includes manual border removal, content validation, and preview skip logic."
todos: []
---

# Content-Aware Border Removal and Split Detection - Complete Plan

## Problem Statement

Current implementation has multiple critical issues:

1. **Border removal** removes thin slices that cut through text content
2. **Gutter detection** finds wrong position - splits happen too close to left column (43.7% instead of 50-60%)
3. **Column edge vs gutter confusion**: Algorithm accepts column edges as gutters due to lenient validation
4. **Border variation**: Single gutter position applied to all pages doesn't account for per-page border differences
5. **No content validation**: No verification that split preserved content correctly
6. **No manual override**: Users can't manually specify border removal percentages

## Root Cause Analysis

### Issue 1: Border Removal Cutting Through Text

- **Current approach**: Detects dark pixels at edges, removes only dark borders
- **Problem**: Border detection is too aggressive, may detect text regions as borders
- **Result**: Thin slices removed that contain actual text content

### Issue 2: Gutter Detection Finding Wrong Position

- **Current approach**: Finds minimum content density in projection profile
- **Problem**: Minimum may be at column edge (e.g., 43.7%) instead of actual gutter (~50-60%)
- **Evidence**: Left pages have text cut off, right pages contain only beginning of text lines
- **Validation too lenient**: Accepts positions with high gradients (1675-1725) that indicate column edges

### Issue 3: Content Validation Missing

- **Current**: No verification that split preserved content
- **Need**: Compare first 50 words of original page with left page, last 50 words with right page
- **Challenge**: OCR text layers may be lost/corrupted during split operations

## Proposed Solution: Content-Aware Detection

### Core Concept Shift

**FROM**: Detect dark pixels → Remove dark borders → Find minimum density → Split at minimum

**TO**: Detect text content regions → Preserve content + headers/footers → Find gap between columns → Split at gap

### Key Principles

1. **Content-First**: Find actual text content regions, not artifacts (dark pixels)
2. **Preserve Structure**: Headers, footers, page numbers automatically preserved
3. **Unified Algorithm**: Same detection method for both border removal and gutter detection
4. **Adaptive Threshold**: Uses actual page samples to determine text density
5. **Binary Search Efficiency**: O(log n) edge detection instead of O(n) projection profiles

## Algorithm Design

### Step 1: Text Density Threshold (Skip Page 1)

**Critical Decision**: Page 1 is often special (title page, cover, abstract) - **SKIP IT**

```
1. Render pages 2 and 3 as images (2x zoom)
2. Sample small square from middle of page 2 (e.g., 100x100px)
3. Sample small square from middle of page 3 (same size, same position)
4. Calculate content density for both samples:
   - Non-white pixels (grayscale < 240) / total pixels
5. Validation:
   - If densities are similar (within 10-15%): use average as threshold
   - If pages differ significantly: use page 2 density
   - Final fallback: default threshold (0.15 = 15% content)
```

### Step 2: Binary Search Edge Detection

**Algorithm**: Fast binary search approach with large initial jumps, refined precision near boundaries

**Example for LEFT edge detection** (from user's suggestion, with middle-region sampling):

```
center_x = 50% of page width (known text region)
left_edge_guess = 5% of page width (likely border)

# Define middle region to avoid edge artifacts (e.g., dark border at bottom)
# Only sample from middle 35-65% of page height - avoids top/bottom borders
middle_region_top = int(image_height * 0.35)    # Start at 35% from top
middle_region_bottom = int(image_height * 0.65) # End at 65% from top

current_pos = center_x
while not converged:
  # Large jump toward edge
  jump = (current_pos - left_edge_guess) / 2
  test_pos = current_pos - jump
  
  # Sample strip at test_pos - ONLY from middle region (avoids bottom/top borders)
  # 20px wide vertical strip, but only from middle 35-65% of height
  strip = image[middle_region_top:middle_region_bottom, 
                max(0, test_pos-10):min(width, test_pos+10)]
  density = calculate_density(strip)  # non-white pixels / total
  
  if density >= threshold:
    # Still in text, can go further left
    current_pos = test_pos
    left_edge_guess = min(left_edge_guess, test_pos)
  elif density < threshold * 0.1:
    # Hit white border, go back toward center
    current_pos = test_pos + jump/2  # Binary search back
  else:
    # Hit dark border or mixed, need to refine
    binary_search_refine(test_pos, current_pos, threshold)

# Be conservative: detected edge with safety margin
final_left_edge = max(0, left_edge_guess - 1px)  # Safety margin
```

**Key improvement**: Sampling only from middle 35-65% prevents false positives from dark borders at bottom/top/sides. For example, when detecting left edge, a wide dark border at the bottom won't corrupt the detection because we ignore the bottom 35% and top 35% of the page. This narrower middle region is safer and focuses on core text content.

**For single-page content detection:**

1. Start from page center (known text region)
2. For each direction (left, right, top, bottom):
   - Use binary search with large initial jumps (20-30% of dimension)
   - Sample 20px wide/tall strip at each position, but ONLY from middle 35-65% region
   - Vertical edges: sample from middle 35-65% of height (avoids top/bottom borders)
   - Horizontal edges: sample from middle 35-65% of width (avoids left/right borders)
   - If text detected: continue toward edge
   - If border detected: binary search back toward center
   - Refine with smaller jumps when near boundary
   - Return conservative edge position with 1-2px safety margin

**For two-up page detection:**

1. Estimate column centers: left ~25% width, right ~75% width
2. For each column independently:
   - Left column: binary search right edge (toward gutter), left edge (toward margin)
   - Right column: binary search left edge (toward gutter), right edge (toward margin)

3. Gutter position = gap between columns (right edge of left, left edge of right)
4. Much more reliable than finding minimum in projection profile

**Advantages:**

- **Much faster**: O(log n) vs O(n) for pixel-by-pixel or projection profiles
- **Large initial jumps**: Quickly finds approximate boundary (20-30% jumps)
- **Precise refinement**: Binary search narrows down exact edge position
- **Conservative approach**: Safety margins ensure no text is cut
- **Handles mixed regions**: Detects dark borders, white margins, and text edges

### Step 3: Header/Footer Preservation

**Critical Requirement**: Do NOT remove headers, footers, and page numbers

```
After finding content bounding box:
1. Expand box to preserve structure:
   - Top: extend upward by 5-10% of page height (preserve header/page numbers)
   - Bottom: extend downward by 5-10% of page height (preserve footer/page numbers)
   - Left/Right: extend by small amount (2-3% of page width) for safety margin
2. Final bounding box = content + headers/footers + safety margin
3. Only remove margins outside this expanded box
```

### Step 4: Content Validation After Split

**Requirement**: Verify split preserved content correctly

**Challenge**: OCR text layers may be lost/corrupted during PyMuPDF split operations using `show_pdf_page` with `clip`.

**Solution**:

1. **Before split**: Extract text from original two-up page
   - First 50 words (should appear on left page after split)
   - Last 50 words (should appear on right page after split)
   - Use PDF text extraction if OCR layer exists, fallback to OCR if needed

2. **After split**: Extract text from split pages
   - First 50 words from left page
   - First 50 words from right page

3. **Validation**:
   - Original first 50 words ≈ Left page first 50 words (allow some OCR variance)
   - Original last 50 words ≈ Right page first 50 words
   - If mismatch: warn user, suggest manual split or different gutter position

**Implementation Notes**:

- If PDF has text layer: use `page.get_text()` (fast)
- If no text layer or text missing: render as image and OCR sample regions (slower but reliable)
- Compare using word-level similarity (fuzzy matching for OCR errors)

### Step 5: Skip Preview When No Changes

**Requirement**: When no border removal, no split, and no trim → skip preview stage

**Logic**:

```
Check preprocessing_state:
  - border_removal == False (or no borders detected/removed)
  - split_method == 'none' (or split not attempted/failed)
  - trim_leading == False (or trimming not applied)

If all true → skip _preview_and_modify_preprocessing(), use original PDF directly
```

## Implementation Phases

### Phase 1: Create Content-Aware Detector

**File**: `shared_tools/pdf/content_detector.py` (NEW)

**Class**: `ContentDetector`

**Methods**:

1. `detect_text_density_threshold(page2_image, page3_image, sample_size=100)` → float
   - **SKIPS PAGE 1** (often special - title page, cover)
   - Samples middle regions from pages 2 and 3 (standard content pages)
   - Returns average density if samples are similar (within 10-15%)
   - Falls back to page 2 density if pages differ significantly
   - Falls back to default threshold (0.15 = 15%) if both pages fail

2. `detect_content_edge_binary_search(image, density_threshold, direction, start_pos, edge_hint, middle_region_pct=0.3)` → int
   - Implements binary search for finding content edge in one direction
   - Parameters:
     - `direction`: 'left', 'right', 'top', 'bottom'
     - `start_pos`: Known text position (center of page/column)
     - `edge_hint`: Approximate edge position (e.g., 5% of page dimension)
     - `middle_region_pct`: Percentage of page to sample from middle (default 0.3 = 35-65%)
   - Algorithm:
     1. Define middle sampling region to avoid edge artifacts:
        - For vertical edges (left/right): Use middle 35-65% of page height (exclude top/bottom 35%)
        - For horizontal edges (top/bottom): Use middle 35-65% of page width (exclude left/right 35%)
     2. Make large jumps (20-30% of dimension) from start_pos toward edge_hint
     3. Sample strip at each position:
        - Vertical edges: 20px wide strip, but ONLY from middle region (avoids bottom dark borders)
        - Horizontal edges: 20px tall strip, but ONLY from middle region (avoids side dark borders)
     4. Calculate density (non-white pixels / total pixels) from sampled middle region only
     5. If density >= threshold: continue toward edge (still in text)
     6. If density < threshold * 0.1: binary search back toward start_pos (white border)
     7. If density between thresholds: refine with smaller jumps (dark border or mixed)
     8. Return conservative edge position with 1-2px safety margin
   - Returns edge coordinate (x for left/right, y for top/bottom)
   - **Safety**: Middle region sampling prevents false positives from dark borders at page edges

3. `detect_content_region_binary_search(image, density_threshold, center_x=None, center_y=None)` → tuple
   - Uses binary search edge detection for all 4 directions
   - Returns (left, top, right, bottom) coordinates
   - Preserves headers/footers with padding (5-10% page height top/bottom)
   - Much faster than projection: O(log n) per direction

4. `detect_two_column_regions_binary_search(image, density_threshold)` → tuple
   - Detects two text columns using binary search edge detection
   - Estimates column centers (left ~25% width, right ~75% width)
   - For each column, finds all 4 edges independently using binary search
   - **Per-page variation check**: Calculate gutter position per page, use median across pages
   - If variation between pages > 5%, fall back to geometric 50/50 split
   - Returns (left_box, right_box, gutter_x) where:
     - left_box = (left, top, right, bottom) for left column
     - right_box = (left, top, right, bottom) for right column
     - gutter_x = gap position between columns (PDF points, median across pages)
   - More reliable than minimum-finding in projection profile
   - Faster: O(log n) vs O(n) for each edge

5. `verify_gutter_position_safety(image, gutter_x, density_threshold)` → tuple[bool, str]
   - **CRITICAL SAFETY CHECK**: Verify gutter position won't cut through text
   - Sample pixels in 20px wide strip centered at gutter_x position
   - **IMPORTANT**: Sample ONLY from middle 35-65% of page height (avoid top/bottom edge artifacts like dark borders)
   - Calculate content density in this middle-region strip (non-white pixels / total pixels)
   - If content density > 20% → reject (would cut through text)
   - Returns (is_safe, warning_message)
   - If not safe, fall back to geometric 50/50 split
   - **Why middle region**: Avoids false positives from headers/footers or dark borders at page edges that could corrupt verification

6. `expand_content_box_for_headers_footers(bounding_box, image_size, top_padding=0.1, bottom_padding=0.1, side_padding=0.03)` → tuple
   - Adds padding to preserve headers, footers, page numbers
   - top_padding: percentage of page height to extend upward (default 10%)
   - bottom_padding: percentage of page height to extend downward (default 10%)
   - side_padding: percentage of page width for left/right safety margin (default 3%)
   - Returns expanded bounding box (left, top, right, bottom)

**Algorithm Implementation Details**:

- **Initial jump size**: 20-30% of page dimension (large jumps toward edge)
- **Refinement jump size**: Decreases as we get closer to edge (binary search halves distance)
- **Strip sampling**:
  - **Vertical edges (left/right)**: 20px wide strip, but sampled ONLY from middle 35-65% of page height
  - **Horizontal edges (top/bottom)**: 20px tall strip, but sampled ONLY from middle 35-65% of page width
  - **Why**: Avoids false positives from dark borders at bottom/top/sides that could corrupt edge detection
  - **Narrower region**: 35-65% (instead of 20-80%) focuses on core text content and is safer, avoiding headers/footers and edge artifacts
  - **Example**: When detecting left edge, if page has wide dark border at bottom, full-height sampling would include bottom border pixels and give false result. Middle-region sampling (35-65%) ignores bottom border and focuses on main text column.
- **Density calculation**: non-white pixels (grayscale < 240) / total pixels
- **Convergence**: Stop when jump size < 2px OR when position stabilizes (no change for 3 iterations)
- **Safety margin**: After finding edge, move 1-2px further out (toward margin) to be conservative
- **Border detection**:
  - White border: density < threshold * 0.1 (10% of threshold)
  - Dark border: density > threshold but pixels are dark (< 60 grayscale value)
  - Text region: density >= threshold AND pixels are text-like (60-240 grayscale)

### Phase 2: Refactor Border Removal

**File**: `shared_tools/pdf/border_remover.py`

**Changes**:

- Replace dark-pixel detection with content-aware binary search edge detection
- Use `ContentDetector` to find content regions with headers/footers preserved
- Remove everything outside expanded bounding box (margins only, not headers/footers)
- Add option: remove only dark margins, or remove all margins (white + dark)
- Preserve headers, footers, page numbers automatically (within expanded box)

**Integration**:

- Modify `detect_borders()` to use `ContentDetector.detect_content_region_binary_search()`
- Keep existing `remove_borders()` logic but use new detection method
- Maintain backward compatibility if possible

### Phase 3: Refactor Gutter Detection

**File**: `scripts/paper_processor_daemon.py`

**Method**: `_find_gutter_position()` → Refactor to use `ContentDetector`

**Changes**:

- For two-up pages: use `detect_two_column_regions_binary_search()`
- Gutter = gap between two columns (much more reliable than finding minimum)
- Use column boundaries directly from binary search → no guessing
- Algorithm naturally finds gap between columns
- Remove old projection profile approach (keep as fallback if needed)

**New Return Format**:

```python
{
    'gutter_x': float,  # Gutter position in PDF points
    'left_column_box': (left, top, right, bottom),  # Left column bounding box
    'right_column_box': (left, top, right, bottom),  # Right column bounding box
    'method': 'binary_search_columns',  # Detection method used
    'confidence': float  # Confidence score (0-1)
}
```

### Phase 4: Add Manual Border Removal

**UI**: Add option in preprocessing menu (`pdf_preview` page)

**File**: `scripts/handle_item_selected_pages.py` and `scripts/paper_processor_daemon.py`

**Implementation**:

1. **UI Option**: Add "[N] Manual border removal" to preprocessing preview menu
   - Number dynamically assigned based on current options

2. **Prompt User**:
   ```
   Manual Border Removal
   =====================
   Enter percentages to remove from each side (0-50%):
   
   Left margin to remove (%): [user input, default: 0]
   Right margin to remove (%): [user input, default: 0]
   Top margin to remove (%): [user input, default: 0]
   Bottom margin to remove (%): [user input, default: 0]
   
   Note: Headers, footers, and page numbers will be preserved
         even if you remove top/bottom margins.
   
   Apply removal? [Y/n]:
   ```

3. **Validation**:
   - Ensure percentages are between 0-50 (safety limit)
   - Warn if sum of left+right > 80% or top+bottom > 80%
   - Show preview of resulting dimensions before applying
   - Calculate and display: "Resulting page: WxH (from original WxH)"

4. **Apply Removal**:
   - Convert percentages to pixel coordinates based on page dimensions
   - Crop PDF to new dimensions OR whiten margins (user preference?)
   - Store manual settings in preprocessing state

5. **Store Settings**: Save manual percentages in `preprocessing_state['manual_border_removal']`
   - Format: `{'left': float, 'right': float, 'top': float, 'bottom': float, 'method': 'manual'}`
   - Used later to skip auto-detection if manual removal was applied

### Phase 5: Content Validation After Split

**File**: `scripts/paper_processor_daemon.py`

**Method**: `_validate_split_content(original_pdf_path, split_pdf_path, page_num=0)` → tuple[bool, str]

**Implementation**:

```python
def _validate_split_content(original_pdf_path, split_pdf_path, page_num=0):
    """
    Validate that split preserved content correctly.
    
    Args:
        original_pdf_path: Path to original two-up PDF
        split_pdf_path: Path to split PDF
        page_num: Page number to validate (default: 0 = first page)
    
    Returns:
        Tuple of (is_valid, warning_message)
        - is_valid: True if content matches, False if mismatch detected
        - warning_message: Description of issue if validation fails
    """
    # 1. Extract text from original page (before split)
    original_text = extract_text_from_page(original_pdf_path, page_num)
    original_first_50 = get_first_n_words(original_text, 50)
    original_last_50 = get_last_n_words(original_text, 50)
    
    # 2. Extract text from split pages (after split)
    left_text = extract_text_from_page(split_pdf_path, page_num * 2)  # Even pages = left
    right_text = extract_text_from_page(split_pdf_path, page_num * 2 + 1)  # Odd pages = right
    
    left_first_50 = get_first_n_words(left_text, 50)
    right_first_50 = get_first_n_words(right_text, 50)
    
    # 3. Compare using fuzzy matching (account for OCR errors)
    left_match = fuzzy_match_words(original_first_50, left_first_50, threshold=0.7)
    right_match = fuzzy_match_words(original_last_50, right_first_50, threshold=0.7)
    
    # 4. Return validation result
    if left_match and right_match:
        return True, ""
    else:
        issues = []
        if not left_match:
            issues.append("Left page content doesn't match original first 50 words")
        if not right_match:
            issues.append("Right page content doesn't match original last 50 words")
        return False, "; ".join(issues)
```

**Helper Functions Needed**:

- `extract_text_from_page(pdf_path, page_num)` → str
  - Try PDF text extraction first (`page.get_text()`)
  - Fallback to OCR if text layer missing/corrupted
- `get_first_n_words(text, n)` → str
- `get_last_n_words(text, n)` → str
- `fuzzy_match_words(text1, text2, threshold=0.7)` → bool
  - Use `rapidfuzz` library (preferred, faster) or `fuzzywuzzy` with `python-Levenshtein` for string comparison
  - Require > 70% similarity to pass validation (conservative threshold - catches real issues while allowing OCR variance)
  - Return True if similarity >= 0.7, False otherwise

**Integration**:

- Call `_validate_split_content()` after `_split_with_custom_gutter()`
- If validation fails: warn user, suggest manual split or different gutter position
- Log validation results for debugging

### Phase 6: Skip Preview When No Changes

**File**: `scripts/paper_processor_daemon.py`

**Method**: `_preview_and_modify_preprocessing()` → Add skip logic

**Location**: `_handle_pdf_attachment_step()` or similar caller

**Logic**:

```python
# After preprocessing
processed_pdf, preprocessing_state = self._preprocess_pdf_with_options(...)

# Check if any changes were made
has_changes = (
    preprocessing_state.get('border_removal', False) or
    preprocessing_state.get('split_method', 'none') != 'none' or
    preprocessing_state.get('trim_leading', False)
)

if not has_changes:
    # No changes made - skip preview, use original PDF
    final_pdf = original_pdf
    final_state = preprocessing_state
else:
    # Changes made - show preview for user approval
    final_pdf, final_state = self._preview_and_modify_preprocessing(
        original_pdf, processed_pdf, preprocessing_state
    )
```

**Edge Cases**:

- Border detection attempted but no borders found → `border_removal = False` → skip preview
- Split attempted but failed/cancelled → `split_method = 'none'` → skip preview
- Trim attempted but user cancelled → `trim_leading = False` → skip preview

## Files to Modify

1. **`shared_tools/pdf/content_detector.py`** (NEW)
   - Complete new module with `ContentDetector` class
   - Binary search edge detection algorithms
   - Two-column detection
   - Header/footer preservation logic

2. **`shared_tools/pdf/border_remover.py`**
   - Refactor `detect_borders()` to use `ContentDetector`
   - Keep `remove_borders()` logic but use new detection
   - Add header/footer preservation

3. **`scripts/paper_processor_daemon.py`**:
   - `_find_gutter_position()` - Refactor to use `ContentDetector.detect_two_column_regions_binary_search()`
   - `_check_and_remove_dark_borders()` - Refactor to use content-aware detection
   - `_preview_and_modify_preprocessing()` - Add skip logic when no changes
   - `_validate_split_content()` - NEW method for content validation
   - `_preprocess_pdf_with_options()` - Integrate manual border removal option
   - `_handle_pdf_attachment_step()` - Add preview skip check

4. **`scripts/handle_item_selected_pages.py`**:
   - Add manual border removal UI option to `pdf_preview` page
   - Handler for manual border removal prompt

## Testing Strategy

### Unit Tests

1. **ContentDetector Tests**:
   - `test_detect_text_density_threshold()` - Verify page 1 is skipped, pages 2-3 used
   - `test_detect_content_edge_binary_search()` - Verify binary search finds correct edges
   - `test_detect_two_column_regions_binary_search()` - Verify two-column detection works
   - `test_expand_content_box_for_headers_footers()` - Verify padding preserves headers/footers

2. **Border Removal Tests**:
   - Test with various border types (dark, white, mixed)
   - Test that headers/footers are preserved
   - Test with text near edges (should not cut)

3. **Gutter Detection Tests**:
   - Test with problematic PDFs from analysis docs
   - Verify gutter position is between columns (50-60%), not at column edge (43%)
   - Test with physical book scans (dark spine) vs printed articles (white gutter)

4. **Content Validation Tests**:
   - Test with PDFs that have text layer
   - Test with scanned PDFs (no text layer, requires OCR)
   - Test fuzzy matching handles OCR errors

### Integration Tests

1. **End-to-End Workflow**:
   - Process problematic PDF: `EN_20260109-131419_002_double.pdf`
   - Verify border removal doesn't cut text
   - Verify gutter detection finds correct position (~50-60%, not 43.7%)
   - Verify split content validation passes

2. **Preview Skip Logic**:
   - Test PDF with no borders → preview should be skipped
   - Test PDF with no split needed → preview should be skipped
   - Test PDF with changes → preview should be shown

3. **Manual Border Removal**:
   - Test percentage input validation
   - Test application of manual removal
   - Test that manual removal is stored in preprocessing state

## Success Criteria

- ✅ Border removal never cuts through text
- ✅ Headers, footers, and page numbers are preserved (not removed)
- ✅ Gutter detection finds correct position (between columns at ~50-60%, not at column edge at 43%)
- ✅ Binary search algorithm is faster than projection profiles (O(log n) vs O(n))
- ✅ Content validation catches incorrect splits
- ✅ Manual border removal works as expected with percentage inputs
- ✅ Preview skipped when no changes made (no border removal, no split, no trim)
- ✅ Text density threshold adapts to page content (works for different document types)
- ✅ Page 1 is skipped for threshold detection (uses pages 2 and 3)

## Performance Considerations

**Binary Search Algorithm Efficiency**:

- Traditional projection: O(width × height) - analyzes every pixel in every row/column
- Binary search: O(log n) where n = distance from center to edge
- Typical speedup: 5-10x faster for normal documents (content centered, edges far)
- Worst case: content fills entire page → still O(log n), similar performance to projection

**Optimization Strategies**:

- Use lower resolution for initial detection (1x zoom), refine with 2x zoom only when needed
- Cache density threshold across pages (similar pages should have similar thresholds)
- Parallel processing: detect content on multiple pages simultaneously (if needed)
- Early termination: if binary search jumps beyond 90% of page, assume edge is near page boundary

**Content Validation Performance**:

- PDF text extraction: Fast (~10-50ms per page)
- OCR fallback: Slow (~1-5s per page) but only used when text layer missing
- Use text extraction when available, OCR only as fallback

## UI/UX Improvements

### Manual Border Removal UI

**Prompt Design**:

- Clear instructions with examples
- Show current page dimensions
- Preview resulting dimensions before applying
- Warning messages for extreme values

**Visual Feedback**:

- Show detected content region (if auto-detection was used)
- Show proposed removal regions highlighted
- Allow user to see before/after preview

### Content Validation Feedback

**If Validation Fails**:

- Clear warning message explaining issue
- Suggest options: manual split, different gutter position, skip validation
- Show comparison of mismatched text snippets

### Preview Skip Notification

**When Preview Skipped**:

- Brief message: "No changes detected - skipping preview"
- Log entry for debugging
- Option to force preview if user wants (debug mode?)

## Migration Strategy

**Backward Compatibility**:

- Keep old methods as fallback if new detection fails
- Gradual rollout: use new algorithm by default, fall back to old if needed
- Configuration option to force old algorithm (for debugging/comparison)

**Rollout Plan**:

1. Implement `ContentDetector` class (Phase 1)
2. Add to border removal (Phase 2) - test with subset of PDFs
3. Add to gutter detection (Phase 3) - test with problematic PDFs
4. Add manual removal and validation (Phases 4-5)
5. Add preview skip (Phase 6)
6. Full deployment after testing

## Related Documentation

- `.cursor/automatic_split_analysis_summary.md` - Problem analysis
- `docs/GUTTER_DETECTION_IMPROVEMENTS_SUMMARY.md` - Improvement suggestions
- `docs/SPLITTING_ISSUE_ANALYSIS.md` - Root cause analysis
- `docs/UX_FLOW_CHART.md` - Current workflow documentation

## Additional Requirements from Previous Plan

**Note**: These requirements from `gutter_detection_and_border_removal_rework_1cf3759b.plan.md` must be incorporated:

### Critical Safety Checks (MUST IMPLEMENT)

1. **Gutter Position Safety Verification**:
   - After detecting gutter position, sample pixels in 20px strip around detected position
   - **IMPORTANT**: Sample ONLY from middle 35-65% of page height (avoid edge artifacts)
   - Calculate content density in this middle-region strip (non-white pixels / total pixels)
   - If content density > 20% at split line → REJECT (would cut through text)
   - Fall back to geometric 50/50 split if verification fails
   - **Implementation**: Add `verify_gutter_position_safety()` method to `ContentDetector`
   - **Why middle region (35-65%)**: Prevents false positives from dark borders at bottom/top. Narrower region focuses on core text content.

2. **Border Removal Safety Checks**:
   - **Text content checks before removal**: Before removing border region, check if it contains text
     - If text detected: reduce border width or skip removal
     - **Minimum text-free margin**: 10px without text before removing border
   - **Minimum border width validation**: Only remove borders if detected width > 20px (avoid thin slices)
   - **Text content validation**: Validate that removed region has < 5% text content
   - Sample border region for text content before removal

3. **Multiple Candidate Evaluation** (Optional but recommended):
   - Find top 3 minimum positions in search region (if using projection as fallback)
   - Evaluate each candidate using shape analysis
   - Select candidate that best matches "real gutter" characteristics
   - Or: Try multiple gutter positions if primary fails safety check

4. **Per-Page Gutter Calculation**:
   - Calculate gutter position per page (accounting for page-specific borders)
   - Use median across pages for consistency check
   - If variation between pages > 5%, fall back to geometric split
   - **Note**: Binary search approach should handle this naturally, but verify

### Implementation Details from Previous Plan

1. **Content Validation Similarity Threshold**: Use 70% similarity (not 80%) - more conservative
2. **Fuzzy Matching Library**: Specify `rapidfuzz` (preferred) or `fuzzywuzzy` with `python-Levenshtein`
3. **Changes Made Tracking**: Explicitly track `changes_made: bool` in `preprocessing_state` dict
   - Set to `True` if any of: border removal applied, split applied, trim applied
   - Set to `False` if all preprocessing steps were skipped/rejected
   - Check this flag (not individual flags) for preview skip logic

4. **Manual Border Removal Validation**:
   - Warn if any percentage > 25% (extreme value warning)
   - Validate percentages are reasonable (0-50% range, warn if > 25%)

5. **Content Validation Integration**:
   - If validation fails, offer options: Accept anyway, Retry with different gutter, Re-OCR and re-validate
   - Log validation results (which method: PDF text vs OCR, similarity scores)

### Testing Requirements from Previous Plan

- Test with problematic PDF: `EN_20260109-131419_002_double.pdf`
- Verify column edges are rejected (positions at 43% should fail safety check)
- Verify gutters are detected correctly (between columns at 50-60%)

## Notes

- **OCR Text Layer Handling**: PyMuPDF `show_pdf_page` with `clip` may lose/corrupt OCR text layers. Content validation must handle this by re-OCRing if needed.
- **Conservative Approach**: All edge detections use safety margins (1-2px) to ensure no text is cut.
- **Adaptive Threshold**: Using pages 2-3 for threshold makes algorithm robust across document types.
- **Binary Search Precision**: Algorithm balances speed (large jumps) with precision (refinement near boundaries).
- **Safety First**: Multiple layers of safety checks (gutter position verification, border text checks, content validation) ensure no text is cut.
- **Middle Region Sampling (35-65%)**: All edge detection and gutter verification samples only from middle 35-65% of page (excludes top/bottom 35% and left/right 35%). This prevents false positives from dark borders at page edges that could corrupt detection. Narrower than initial 20-80% suggestion for better focus on core text content.
