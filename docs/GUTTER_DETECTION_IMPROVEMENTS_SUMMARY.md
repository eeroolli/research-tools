# Gutter Detection Improvements - Summary for Planning Agent

## Problem Summary

Users report two critical issues with PDF preprocessing:
1. **Border removal** removes thin slices that cut through text content
2. **Split position** is incorrect - splits happen too close to the left column instead of at the actual gutter position

Both issues result in damaged output PDFs with text cut off.

## Runtime Evidence from Debug Logs

### Issue 1: Split Position Too Close to Left Column

From logs for PDF `EN_20260109-131419_002_double.pdf`:

**Detected Gutter Positions:**
- Page 0: `min_idx_ratio = 0.4376` (43.7% of content width), method: "content"
- Page 1: `min_idx_ratio = 0.4366` (43.6% of content width), method: "content"  
- Page 2: `min_idx_ratio = 0.3136` (31.3% of content width), method: "spine" (suspicious - too close to left edge)

**Final gutter position used:** `gutter_x = 380.49` PDF points (43.7% of page width = 870.36)

**Result:** Split creates left page at 43.7% width (380.49 pts) and right page at 56.3% width (489.86 pts). This is **too close to the left column**, cutting through text.

**Shape Analysis Data:**
- Page 0: `avg_gradient = 1675`, `max_gradient = 20845`, `valley_width_ratio = 0.51`, `avg_second_deriv = 1376`
- Page 1: `avg_gradient = 1725`, `max_gradient = 21543`, `valley_width_ratio = 0.52`, `avg_second_deriv = 1585`
- Page 2: `avg_gradient = 4.7`, `max_gradient = 61`, `valley_width_ratio = 0.23`, `avg_second_deriv = 4.4` (spine method)

**Key Observation:** Pages 0 and 1 have **high gradients** (1675-1725 avg, 20845 max) indicating **sharp transitions** typical of **column edges**, not gradual gutters. The validation accepts these because:
- They're not "near_edge" (43.7% is between 20-80% threshold)
- Valley width ratio (0.51) is > 0.4, so doesn't trigger "narrow valley" rejection
- Max gradient is high but avg_second_deriv (1376-1585) is < 2000 threshold

### Issue 2: Border Removal Cutting Through Text

No specific logs captured for border removal in this run, but user reports that "border removal kept removing thin slices that also cut through the text." This suggests:
- Border detection is too aggressive (detecting text regions as borders)
- Or border removal is not accounting for text content when determining border width
- Or minimum border width validation is insufficient

## Current Validation Logic Analysis

### Current Shape Validation (lines 5822-5845)

**Rejects column edge if:**
1. `near_edge` (min_idx_ratio < 0.2 or > 0.8) **AND**:
   - `avg_gradient > 1000` **AND** `valley_width_ratio < 0.4`, OR
   - `max_gradient > 10000` **AND** `avg_second_deriv > 2000`
2. **OR** if not near_edge but `max_gradient > 20000` **AND** `avg_second_deriv > 3000` **AND** `valley_width_ratio < 0.3`

**Accepts as real gutter if:**
- `avg_gradient < 500` **AND** `valley_width_ratio > 0.6` **AND** `avg_second_deriv < 500`

**Problem:** The thresholds are too lenient. The detected positions (43.7%) have:
- High gradients (1675-1725) suggesting sharp transitions (column edges)
- Moderate valley width (0.51) - not narrow enough to trigger rejection
- Not near enough to edges (< 20% or > 80%) to trigger edge rejection
- Result: **Column edges are being accepted as gutters**

## Root Cause Analysis

### 1. Column Edge vs Gutter Distinction

The algorithm finds the **minimum content density position** but doesn't effectively distinguish between:
- **Real gutters**: Gradual valley with smooth transitions, typically near 50% of page width
- **Column edges**: Sharp drop from text to white space, can appear at various positions (e.g., 43-44% if left column has narrower margins)

**Current algorithm weakness:** It assumes any minimum in the middle region (20-80%) is a valid gutter, but column edges can appear anywhere.

### 2. Validation Thresholds Too Permissive

The shape analysis exists but thresholds are too lenient:
- `avg_gradient > 1000` should be a strong indicator of column edge (sharp transition), but current logic only rejects if combined with narrow valley or very high curvature
- Real gutters should have `avg_gradient < 500` (gradual), but positions with `avg_gradient = 1675` are still accepted
- The "near_edge" definition (20-80%) is too wide - column edges can appear at 43-44% and still cut through text

### 3. Coordinate System Issues (Potential)

The gutter position is calculated relative to content area (after border removal), then converted to PDF points using full page width. If borders vary per page:
- Content area shifts differently on each page
- Single `gutter_x` may not align correctly for all pages
- This could cause the split to be off-center

### 4. Border Removal Impact on Split

Border removal happens **before** gutter detection. If borders are removed incorrectly:
- Content area calculation may be wrong
- Gutter detection searches in wrong region
- Split position becomes incorrect

## Suggested Improvements

### 1. Stricter Shape Validation Thresholds

**Modify validation to reject column edges more aggressively:**

```python
# Reject as column edge if ANY of these conditions:
# 1. High gradient suggests sharp transition (column edge)
if avg_gradient > 800:  # Lowered from 1000, or require combination with other indicators
    is_column_edge = True

# 2. High max gradient with moderate curvature (sharp drop)
if max_gradient > 15000 and avg_second_deriv > 1000:  # Lowered thresholds
    is_column_edge = True

# 3. Position too far from center for real gutter (gutters are typically 45-55%)
if not (0.45 <= min_idx_ratio <= 0.55):  # Stricter center region
    if avg_gradient > 600:  # Combine with gradient check
        is_column_edge = True
```

**Accept as real gutter only if ALL conditions met:**
```python
is_real_gutter = (avg_gradient < 400 and  # Stricter - must be gradual
                  valley_width_ratio > 0.5 and  # Wide valley
                  avg_second_deriv < 400 and  # Smooth transition
                  0.45 <= min_idx_ratio <= 0.55)  # Near center
```

### 2. Improve Gutter Position Accuracy

**Consider multiple candidates:**
- Find top 3 minimum positions in search region
- Analyze shape for each candidate
- Select the one that best matches "real gutter" characteristics (gradual, wide, centered)
- If none match, fall back to geometric 50/50 split

**Use median instead of mean:**
- Current: Average of positions from 3 pages
- Better: Use median position to handle outliers (like page 2 at 31.3%)
- Reject pages where position differs > 10% from median

### 3. Add Content Density Verification

**After detecting gutter position, verify it's actually a gutter:**
- Sample pixels in a narrow strip (e.g., 20px wide) around detected gutter
- Calculate content density (non-white pixels / total pixels)
- If content density > 20%, reject - this is cutting through text, not a gutter
- Fall back to geometric split

### 4. Account for Border Variation

**Per-page gutter calculation:**
- Current: Single `gutter_x` applied to all pages
- Better: Calculate gutter position per page, accounting for page-specific borders
- Use median across pages for consistency check
- If variation > 5%, fall back to geometric split

### 5. Improve Border Removal Safety

**Add text content checks:**
- Before removing a border region, check if it contains text (OCR or pixel density analysis)
- If text detected in border region, reduce border width or skip removal
- Minimum text-free margin requirement: At least 10px without text before removing border

**Add minimum border width:**
- Only remove borders if detected width > 20px (avoid thin slices)
- Validate that removed region has < 5% text content

### 6. Better Fallback Strategy

**Current:** Geometric 50/50 split if gutter detection fails
**Better:** 
1. Try gutter detection with strict validation
2. If rejected, try geometric split with border-aware center calculation
3. Verify split doesn't cut through text (sample pixels at split line)
4. If verification fails, prompt user for manual split ratio

## Implementation Priority

**High Priority:**
1. Stricter shape validation thresholds (#1) - Direct fix for column edge acceptance
2. Content density verification (#3) - Prevents cutting through text
3. Improved border removal safety (#5) - Fixes border removal issue

**Medium Priority:**
4. Multiple candidates with best match (#2) - Improves accuracy
5. Per-page gutter calculation (#4) - Handles border variation

**Low Priority:**
6. Better fallback strategy (#6) - Enhanced user experience

## Testing Recommendations

1. **Test with problematic PDF:** Use `EN_20260109-131419_002_double.pdf` or similar
2. **Verify shape analysis:** Check that column edges are rejected (avg_gradient > 800)
3. **Verify real gutters:** Test with physical book scans - should detect correctly
4. **Border removal tests:** Verify borders with text nearby are not removed
5. **Split accuracy:** Verify split doesn't cut through text lines

## Related Files

- `scripts/paper_processor_daemon.py`: Lines 5466-6000 (`_find_gutter_position`), lines 6495-6700 (`_split_with_mutool`), lines 7281-7400 (`_check_and_remove_dark_borders`)
- `shared_tools/pdf/border_remover.py`: Border detection logic
- `docs/SPLITTING_ISSUE_ANALYSIS.md`: Previous analysis document
- `.cursor/debug.log`: Runtime evidence data

## Recent Improvements (January 2026)

### Improved Edge Detection Algorithm

**Problem:** The binary search edge detection was defaulting to restrictive `edge_hint` values (40-60%) when it encountered white space, causing all detections to converge to 50% regardless of actual layout.

**Solution:** Implemented a new approach based on core principles:
1. **Never cut content** - Always find actual content boundaries
2. **Always split between content** - Gutter is the midpoint of detected edges
3. **Start from safe positions** - Begin search from column centers (25%, 75%) where content is guaranteed
4. **Search freely** - Remove restrictive `edge_hint` limits to find actual boundaries

**Changes Made:**
- **Left column right edge**: Search from 25% rightward with `edge_hint=img_width` (no upper limit)
- **Right column left edge**: Search from 75% leftward with `edge_hint=0` (no lower limit)
- **Binary search logic**: Improved white space handling - when hitting white space, continue searching in smaller increments to find the transition point instead of stopping
- **Gutter calculation**: Uses edges without safety margin for accurate positioning, while safety margin is still applied to bounding boxes to avoid cutting text

### Outer-Edge Mode (Two-Column Layouts)

**Problem:** In skewed or header-heavy scans, edge detection consistently found the **outer edges** of both columns instead of the inner edges. This caused inner-edge validations to fail, even though the outer edges were reliable and safe to use.

**Solution:** Added an **outer-edge mode**:
- If detected edges overlap (`left_col_right_no_margin >= right_col_left_no_margin`), treat them as **outer edges**
- Compute gutter as the **midpoint between outer edges**
- Validate the gutter position (40–60%) instead of rejecting on negative gap
- Propagate `edge_mode` to `_find_gutter_position` so the overlap check uses the correct range

**Benefits:**
- Works reliably with skewed scans and strong headers
- Uses stable outer edges for safe border removal
- Preserves “never cut content” by splitting at the outer-edge midpoint

**Files Modified:**
- `shared_tools/pdf/content_detector.py`: Added `edge_mode` and outer-edge gutter validation
- `scripts/paper_processor_daemon.py`: Overlap check respects `edge_mode`

**Benefits:**
- Handles asymmetric layouts (e.g., 55/45 splits) correctly
- Finds actual content boundaries instead of defaulting to hints
- Handles empty pages (searches until it finds the other column)
- Never cuts content (finds real edges with safety margins for boxes)
- Splits between content (gutter is midpoint of detected edges)

**Files Modified:**
- `shared_tools/pdf/content_detector.py`: Updated `detect_two_column_regions()` and `detect_content_edge_binary_search()`

## Notes

- Shape analysis instrumentation is already in place (lines 5701-5743, 5814-5850)
- Current validation logic exists but needs tightening (lines 5822-5845)
- Border detection stats are passed to split logic but may not be used optimally
- Manual split option exists in preview menu but may not be sufficient for all cases
- Edge detection now uses unrestricted search from column centers to find actual boundaries