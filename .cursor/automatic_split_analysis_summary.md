# Automatic PDF Split Analysis Summary

**Date:** January 2026  
**Issue:** Automatic gutter detection produces incorrect split results  
**Status:** Analysis complete, root cause hypotheses identified, requires instrumentation to confirm

---

## Problem Description

The automatic PDF split functionality is producing incorrect results:
- **Left pages**: Text is cut off at the right edge (missing right portion of left column)
- **Right pages**: Contain only a few words from the beginning of each line (1-2% content, 98-99% white)
- **User observation**: Gutter is not in the middle of the page, and there's a black border roughly 10-15% into the page

---

## Evidence from Runtime Logs

### Split Results
- **Page width**: 870.36 points
- **Detected gutter position**: 380.5 points (43.7% of page width)
- **Left page width**: 380.5 points (43.7%)
- **Right page width**: 489.9 points (56.3%)

### Content Analysis (Post-Split)
- **Left pages**: 
  - Text length: 1511-3185 characters
  - Content ratio: 15-25%
  - White ratio: 74-80%
  - Status: Contains full text but right edge is cut off

- **Right pages**:
  - Text length: 178-206 characters (only a few words)
  - Content ratio: 1-2%
  - White ratio: 98-99%
  - Status: Contains only beginning of right column text

### Gutter Detection Details
- **Method used**: Content-based detection (not spine-based)
- **Detected position**: 43.7% of page width (380.5 points)
- **Expected position**: ~50-60% (435-522 points based on user's manual attempt at 60%)
- **Validation**: Position accepted (within 30-70% range)
- **Shape analysis**: Not identified as column edge, accepted as default

---

## Root Cause Hypotheses

### H1: Gutter Detection Finding Wrong Position (PRIMARY HYPOTHESIS)
**Status:** LIKELY - Strong evidence from logs

**Evidence:**
- Gutter detected at 43.7% instead of expected ~50-60%
- Right pages contain only beginning of text (suggests split is too far left)
- Left pages have text cut off at right edge (confirms split is too far left)

**Possible causes:**
1. Detection algorithm is finding the left edge of the right text column instead of the actual gutter
2. The black border at 10-15% into the page may be interfering with detection
3. Content density analysis may be incorrectly identifying the minimum content point

**Required investigation:**
- Add instrumentation to log:
  - Content projection profile (density per column)
  - Spine detection signal strength
  - All candidate gutter positions before selection
  - Why content method was chosen over spine method
  - Border detection stats (if borders were removed)

---

### H2: Border Removal Interaction Issue
**Status:** NEEDS CONFIRMATION - Missing log evidence

**Problem:**
- Logs show "Before border removal" but no "After border removal" entry
- Unclear if borders were actually removed
- If borders were removed, the black border at 10-15% should have been eliminated
- If borders were NOT removed, the black border may be interfering with gutter detection

**Required investigation:**
- Check if border removal actually occurred
- If borders were removed: Verify border detection stats are being used correctly in gutter detection
- If borders were NOT removed: Determine why (user rejection? detection failure?)
- Add instrumentation to log border removal status and border detection stats

---

### H3: Manual Split PDF Selection Issue
**Status:** IDENTIFIED - Code fix attempted but needs verification

**Problem:**
- Manual split was using `processed_pdf` (already split) instead of correct source
- If borders were removed: Should use border-removed PDF (not original, not split)
- If borders NOT removed: Should use original PDF

**Current state:**
- Code was changed to use `original_pdf` for manual split
- **BUT**: This may be incorrect if borders were removed (should use border-removed PDF, not original)

**Required investigation:**
- Determine preprocessing state tracking:
  - Original PDF → Border-removed PDF → Split PDF
  - Manual split should use: border-removed PDF (if borders removed) OR original PDF (if not)
- Add instrumentation to log which PDF is being used for manual split and why

---

## Preprocessing Workflow Analysis

### Current Order (from code):
1. **Border removal** (if requested) → Creates `border_removed_pdf`, updates `current_pdf`
2. **Split** (if requested) → Uses `current_pdf` (which may have borders removed)
3. **Trim** (if requested)

### Key Questions:
1. **Were borders removed in this run?**
   - Logs show "Before border removal" entry
   - No "After border removal" entry found
   - Need to confirm if removal occurred or was rejected

2. **What PDF should gutter detection use?**
   - If borders removed: Should use border-removed PDF
   - If borders NOT removed: Should use original PDF
   - Current code: Uses `current_pdf` which should be correct, but needs verification

3. **What PDF should manual split use?**
   - If borders removed: Should use border-removed PDF (not original, not split)
   - If borders NOT removed: Should use original PDF
   - Current code: Uses `original_pdf` (may be incorrect if borders were removed)

---

## Required Instrumentation

### For Gutter Detection (`_find_gutter_position`):
1. **Content projection profile**: Log density values per column to see where minimum occurs
2. **Spine vs content method selection**: Log signal strengths and why content method was chosen
3. **Border detection stats**: Log if available and how they're used
4. **All candidate positions**: Log all potential gutter positions before final selection
5. **Shape analysis details**: Log why position was accepted/rejected

### For Border Removal (`_check_and_remove_dark_borders`):
1. **Removal status**: Log whether borders were actually removed or rejected
2. **Border detection stats**: Log left/right border positions in pixels and PDF points
3. **Page dimensions**: Log before/after dimensions if removal occurred

### For Manual Split (`_handle_manual_split`):
1. **PDF selection**: Log which PDF is being used (original, border-removed, or split)
2. **Preprocessing state**: Log current state (border_removal, split_method, etc.)
3. **Border stats availability**: Log if border_detection_stats are available and how they're used

### For Split Operation (`_split_with_custom_gutter`):
1. **Input PDF**: Log which PDF is being split (original, border-removed, or already split)
2. **Gutter position**: Log the exact gutter_x value and how it was calculated
3. **Page dimensions**: Log page width/height before split

---

## Next Steps for Planning Agent

1. **Add comprehensive instrumentation** to capture:
   - Border removal status and stats
   - Gutter detection process (projection profiles, method selection, candidate positions)
   - PDF selection logic (which PDF is used at each step)
   - Preprocessing state tracking

2. **Reproduce the issue** with full instrumentation to capture:
   - Whether borders were removed
   - Why gutter was detected at 43.7% instead of ~50-60%
   - What PDF is being used for each operation

3. **Analyze logs** to confirm/reject hypotheses:
   - H1: Gutter detection finding wrong position
   - H2: Border removal interaction issue
   - H3: Manual split PDF selection issue

4. **Fix root cause** based on log evidence:
   - If H1 confirmed: Fix gutter detection algorithm
   - If H2 confirmed: Fix border removal integration
   - If H3 confirmed: Fix PDF selection logic for manual split

5. **Verify fix** with post-fix instrumentation and user confirmation

---

## Related Files

- `scripts/paper_processor_daemon.py`:
  - `_find_gutter_position()`: Gutter detection algorithm
  - `_check_and_remove_dark_borders()`: Border removal
  - `_preprocess_pdf_with_options()`: Preprocessing workflow
  - `_split_with_custom_gutter()`: Actual split operation
  - `_preview_and_modify_preprocessing()`: Manual split handler

- `scripts/handle_item_selected_pages.py`:
  - `_handle_manual_split()`: Manual split UI handler

---

## User Context

- **User reported**: Automatic split results are "horrible"
- **User observation**: Black border at 10-15% into page, gutter not in middle
- **User attempted**: Manual split at 60% (would be ~522 points, much further right than detected 380.5 points)
- **User expectation**: Gutter should be around 50-60% of page width, not 43.7%

---

## Notes

- The user did NOT ask for manual split - they came with results showing automatic split failed
- The issue is with **automatic** gutter detection, not manual split
- Manual split PDF selection is a separate issue that was identified during analysis
- Border removal interaction needs investigation - unclear if borders were removed or not
