---
name: Fix Splitting and Border Removal Bugs
overview: ""
todos:
  - id: ensure-page-width-set
    content: Ensure page_width is always set in _find_gutter_position() return dict and is not None
    status: completed
  - id: auto-50-50-fallback
    content: Add automatic fallback to 50/50 geometric split when gutter is outside 30-70% range (before validation warnings)
    status: completed
    dependencies:
      - ensure-page-width-set
  - id: add-border-removal-validation
    content: Add validation in process_entire_pdf() to check output page count equals input page count, return None if mismatch
    status: completed
  - id: investigate-border-bug
    content: Investigate why border removal creates 98 pages from 7 - check for page duplication in processing loop
    status: completed
    dependencies:
      - add-border-removal-validation
  - id: replace-width-cleanup-with-content
    content: "Replace width-based page cleanup with content-based detection (check text length < 50 chars AND image content < 10%) - CRITICAL: all pages are same size as original (not thin slices), must check content density"
    status: completed
---

# F

ix Splitting and Border Removal Bugs

## Issues Found

1. **EN_ document**: Gutter detected at 339.6 points (~28% of page width) - should warn but didn't, should use 50/50 split
2. **NO_ document**: Border removal created 98 pages from 7 (many thin white slices) - serious bug
3. **GROBID**: Found 0 authors when regex found real authors - need better fallback handling

## Fix 1: Detect Printout with No Gutter (Big White Space in Middle)

**Problem**: Printouts have big white space in 40-60% region (no actual gutter), should use 50/50 split. Current code detects edge of text as gutter.**Root Cause**: Algorithm finds minimum content density, but doesn't distinguish between:

- Physical book gutter (dark spine area)
- Printout spacing (big white space in middle 40-60%)

**Fix**: Add detection for large white space in 40-60% region.**File**: [`scripts/paper_processor_daemon.py`](scripts/paper_processor_daemon.py) lines 4560-4628**Add after finding min_idx, before converting to PDF coordinates**:

```python
# Check if middle region (40-60% of content width) has very low content density
# This indicates a printout with no real gutter - just white space between pages
middle_start_px = int(content_width_px * 0.4)
middle_end_px = int(content_width_px * 0.6)
middle_region = gray[:, content_left_px + middle_start_px:content_left_px + middle_end_px]

# Calculate content density in middle region (non-white pixels)
# White pixels are typically > 240 in grayscale
non_white_pixels = np.sum(middle_region < 240)
total_middle_pixels = middle_region.size
middle_content_ratio = non_white_pixels / total_middle_pixels if total_middle_pixels > 0 else 0

# If middle region is > 90% white, it's likely a printout with no gutter
# Also check if detected gutter is in this white region
if middle_content_ratio < 0.1:  # Less than 10% content in middle
    gutter_in_middle = (middle_start_px <= min_idx <= middle_end_px)
    if gutter_in_middle:
        # Big white space in middle + gutter detected in middle = printout, use 50/50
        self.logger.info(f"Detected printout with no gutter (middle region {middle_content_ratio:.1%} content) - using 50/50 split")
        # Skip this page for gutter detection, will fall through to geometric split
        continue  # Skip this page, don't add to gutter_positions
```

**Also add check in `_split_with_mutool()`**:

```python
if gutter_x is not None:
    # Check if gutter is reasonable - if not, use 50/50 split
    if page_width:
        gutter_ratio = gutter_x / page_width
        if gutter_ratio < 0.3 or gutter_ratio > 0.7:
            # Gutter is outside reasonable range - use 50/50 split
            self.logger.info(f"Gutter position {gutter_ratio:.1%} outside 30-70% range - using 50/50 geometric split")
            gutter_x = None  # Fall through to geometric split
        else:
            # Validate for other issues (consistency, border variation)
            validation_result = self._validate_gutter_detection(
                gutter_x, page_width, gutter_positions, borders_per_page
            )
            is_valid, warnings = validation_result
            
            if not is_valid or warnings:
                # Show warnings and prompt
                # ... existing warning code ...
```

## Fix 2: Border Removal Creating Extra Pages

**Problem**: Border removal created 98 pages from 7 original pages. This suggests pages are being split or duplicated during processing.**Investigation Needed**: Check `process_entire_pdf()` in `border_remover.py` - it should create 1 output page per input page.**Possible Causes**:

1. Border detection is finding many small borders and creating pages for each
2. Page processing loop is creating multiple pages per original
3. PDF saving/reopening is duplicating pages

**Fix**:

- Add validation: output page count should equal input page count
- If output has more pages, log error and return None (skip border removal)
- Check border removal logic for any page duplication

**File**: [`shared_tools/pdf/border_remover.py`](shared_tools/pdf/border_remover.py) lines 1239-1305**Add after processing all pages, before saving**:

```python
# Validate: output should have same number of pages as input
if len(output_doc) != len(doc):
    self.logger.error(f"Border removal created {len(output_doc)} pages from {len(doc)} - this is a bug, skipping border removal")
    output_doc.close()
    doc.close()
    return None  # Return None to skip border removal
```

## Fix 3: Ensure page_width is Always Set

**Problem**: Validation didn't run because `page_width` might be None in return dict.**Fix**: Ensure `page_width` is set from first page in `_find_gutter_position()`.**File**: [`scripts/paper_processor_daemon.py`](scripts/paper_processor_daemon.py) lines 4437-4439, 4848-4852**Check**: Ensure `page_width` is set before returning:

```python
# At start of function, set page_width from first page
if page_width is None:
    page_width = page_rect.width

# In return dict, ensure page_width is set
return {
    'gutter_x': float(median_gutter),
    'gutter_positions': [float(x) for x in gutter_positions],
    'borders_per_page': all_borders_per_page,
    'page_width': float(page_width) if page_width is not None else 0  # Ensure it's set
}
```

## Fix 4: Detect and Remove Empty/White Pages After Splitting

**CRITICAL UNDERSTANDING**: **After splitting, all pages are the SAME SIZE as the original** (typically A4, but can be Letter or other sizes for handwritten notes). The extra "gutter pages" are NOT thin slices - they are full-size pages (A4/Letter/etc.) that contain only a thin slice of content (the gutter). The issue is not about page dimensions, but about **content density**.

**Problem**:

- Split creates 2 pages per original page (same size as original - typically A4, but can be Letter or other sizes)
- If gutter is detected incorrectly, one page might be mostly white/empty (just a thin strip of content or gutter)
- The "gutter" page is a FULL-SIZE page (same size as original) that contains only a thin slice of content
- Current cleanup code (lines 4995-5014) assumes 3-page pattern but split creates 2 pages
- If one page is mostly empty, `actual_pages == expected_pages`, so cleanup doesn't trigger
- **Width-based detection won't work** because all pages are the same size as the original (not thin slices)

**Fix**: After splitting, check each page's **content density**:

- Text content: Check if page has < 50 characters of text
- Image content: Render page as image, check if > 90% white pixels or < 5% non-white pixels
- Remove pages that are mostly empty/white regardless of total page count

**File**: [`scripts/paper_processor_daemon.py`](scripts/paper_processor_daemon.py) lines 4995-5014**Replace existing cleanup code with content-based detection**:

```python
# After creating all split pages, check for empty/white pages
# CRITICAL: All pages are same size as original (typically A4, can be Letter) - must check content, not width
pages_to_remove = []
for page_idx in range(len(new_doc)):
    page = new_doc[page_idx]
    
    # Check 1: Text content (fast, for text-based PDFs)
    try:
        text = page.get_text()
        text_length = len(text.strip()) if text else 0
    except:
        text_length = 0
    
    # Check 2: Image content density (for scanned pages)
    # Render page as image and check white pixel ratio
    try:
        import fitz
        import numpy as np
        import cv2
        
        # Render page as image (low resolution for speed)
        pix = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.h, pix.w, 3)
        gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY) if len(img.shape) == 3 else img
        
        # Calculate non-white content percentage
        # White pixels are typically > 240 in grayscale
        non_white_pixels = np.sum(gray < 240)
        total_pixels = gray.size
        content_ratio = non_white_pixels / total_pixels if total_pixels > 0 else 0
        
        # Remove if: very little text (< 50 chars) AND mostly white (> 90% white)
        if text_length < 50 and content_ratio < 0.1:  # Less than 10% content
            pages_to_remove.append(page_idx)
            self.logger.info(f"Detected empty/white page {page_idx + 1} ({content_ratio:.1%} content, {text_length} chars) - removing")
    except Exception as e:
        # If image analysis fails, use text-only check
        self.logger.debug(f"Could not analyze page content: {e}")
        if text_length < 50:
            # Very little text - might be empty, but don't remove without image confirmation
            pass

# Remove empty pages in reverse order
for page_idx in reversed(pages_to_remove):
    new_doc.delete_page(page_idx)

if pages_to_remove:
    self.logger.info(f"Removed {len(pages_to_remove)} empty/white page(s)")
```

## Fix 5: Filter GROBID Garbage/Hallucinated Authors

**Problem**: GROBID reports garbage authors (OCR errors like "Smnrh-Lov►rl, Lmr", place names) AND hallucinates authors that don't exist in the document. User reported case where GROBID found 12 authors, none mentioned in the document. Regex finds correct authors but is only used as fallback.

**Current Flow**: GROBID → if finds authors (even garbage/hallucinated), use them → user sees garbage → regex only used if GROBID finds 0 authors

**Root Cause**:

- GROBID is removed from `reliable_methods` (already fixed in previous implementation)
- But GROBID authors are still being used if GROBID finds any authors
- No validation that GROBID authors actually appear in the document text
- Need to validate GROBID authors against both document text AND Zotero

**Fix**:

- When GROBID finds authors, validate them:

  1. Check if authors appear in document text (prevent hallucinations)
  2. Check if authors are in Zotero (filter garbage)

- If GROBID authors don't appear in document text OR are mostly unknown, fall back to regex
- Regex results should also be filtered, but they're more reliable than GROBID garbage/hallucinations

**File**: [`scripts/paper_processor_daemon.py`](scripts/paper_processor_daemon.py) - author extraction flow around lines 3520-3593

**Implementation**:

```python
# After GROBID extraction (around line 3528), validate authors
if metadata.get('authors'):
    grobid_authors = metadata['authors']
    
    # Get document text for validation (check if authors appear in document)
    try:
        import pdfplumber
        with pdfplumber.open(str(pdf_to_use)) as pdf:
            doc_text = ""
            # Check first 3 pages for author mentions
            for page in pdf.pages[:min(3, len(pdf.pages))]:
                page_text = page.extract_text()
                if page_text:
                    doc_text += page_text.lower()
    except Exception as e:
        self.logger.debug(f"Could not extract text for validation: {e}")
        doc_text = ""
    
    # Validate GROBID authors against document text
    authors_in_text = []
    authors_not_in_text = []
    
    for author in grobid_authors:
        # Check if author name (or parts) appears in document text
        author_lower = author.lower()
        # Try full name, last name, and first name
        name_parts = author_lower.split(',')
        last_name = name_parts[0].strip() if name_parts else ""
        first_name = name_parts[1].strip() if len(name_parts) > 1 else ""
        
        # Check if author appears in text
        found_in_text = False
        if last_name and len(last_name) > 2:
            if last_name in doc_text:
                found_in_text = True
        if first_name and len(first_name) > 2 and not found_in_text:
            if first_name in doc_text:
                found_in_text = True
        if not found_in_text and author_lower in doc_text:
            found_in_text = True
        
        if found_in_text:
            authors_in_text.append(author)
        else:
            authors_not_in_text.append(author)
    
    # If most GROBID authors don't appear in document, they're hallucinated
    # Fall back to regex which extracts from actual document text
    total = len(grobid_authors)
    if total > 0 and len(authors_in_text) / total < 0.3:  # Less than 30% found in text
        self.logger.info(f"GROBID authors don't appear in document ({len(authors_in_text)}/{total} found) - likely hallucinations, falling back to regex")
        # Clear GROBID authors, will fall through to regex extraction
        metadata['authors'] = []
        metadata.pop('extraction_method', None)
    
    # Also check Zotero validation for remaining authors
    elif grobid_authors:
        validation = self.author_validator.validate_authors(grobid_authors)
        known_count = len(validation['known_authors'])
        unknown_count = len(validation['unknown_authors'])
        
        # If most are unknown, also fall back to regex
        if total > 0 and (unknown_count / total) > 0.7:
            self.logger.info(f"GROBID authors mostly unknown in Zotero ({unknown_count}/{total}) - falling back to regex")
            metadata['authors'] = []
            metadata.pop('extraction_method', None)
```

**Note**: This ensures GROBID hallucinations (authors not in document) and garbage are filtered out, and regex (which finds real authors from document text) is used instead.

## Bug Agent Analysis (Complete)

**Bug agent analysis is complete** - see `docs/SPLITTING_BUGS_RUNTIME_EVIDENCE.md` for full findings.

### Key Findings:

1. **CRITICAL**: After splitting, all pages are the SAME SIZE as the original (typically A4, but can be Letter or other sizes for handwritten notes). The extra "gutter pages" are full-size pages containing only a thin slice of content. Width-based detection will NOT work. Must use content-based detection.

2. **Empty/White Page Detection**: 

   - Split creates 2 pages per original (same size as original, not 3)
   - But sometimes creates 3: left, gutter, right (all same size as original)
   - The "gutter" page is full-size but contains only a thin slice of content
   - Current cleanup code assumes 3-page pattern but doesn't work
   - Need to detect pages with < 50 chars text AND < 10% image content

3. **Gutter Detection Issues**:

   - Detects edge of text instead of actual gutter
   - Validation didn't trigger (page_width may not be set)
   - Need to detect printouts (big white space in 40-60% region)

4. **Border Removal Bug**: 

   - Created 98 pages from 7 - needs investigation
   - Add validation to check page count matches

5. **Page Deletion Bug**: 

   - User reports dropping pages 1 & 3 when trying to drop page 1
   - Possible index confusion or multiple deletion calls

**Action**: Proceed with implementation based on bug agent findings.

## Implementation Order

**Based on bug agent analysis:**

1. **Fix page_width in return dict** - Ensure validation can run (bug agent found validation didn't trigger)
2. **Add printout detection** - Detect big white space in 40-60% region, skip gutter detection for those pages
3. **Add automatic 50/50 fallback** - When gutter outside 30-70%, use geometric split
4. **Replace width-based cleanup with content-based detection** - Detect empty/white pages by content density (CRITICAL: all pages are same size as original, not thin slices - must check content, not width)
5. **Add border removal validation** - Check page count matches (safety check for 7→98 bug)
6. **Investigate border removal bug** - Debug why it creates 98 pages from 7 (bug agent identified this as critical)
7. **Fix page deletion bug** - Add logging and verify indices (bug agent found index confusion)

## Testing

1. **Test EN_ document** - should use 50/50 split (gutter at 28%), empty pages should be removed
2. **Test content-based detection** - verify pages with < 50 chars text AND < 10% image content are removed
3. **Test border removal** - should not create extra pages (7 → 7, not 7 → 98)
4. **Test page deletion** - verify correct pages are deleted (not pages 1 & 3 when user wants page 1)

## Critical Notes

- **ALL PAGES ARE A4 SIZE** - width-based detection will NOT work
- Empty/white pages must be detected by content analysis (text + image density)
- Current cleanup code assumes 3-page pattern but split creates 2 pages per original