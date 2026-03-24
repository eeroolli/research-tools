# Fix PDF Splitting "page is None" Error

## Problem Statement

The PDF splitting functionality is failing with "page is None" AssertionError, preventing two-up pages from being split. Additionally:
1. Split fails silently - no error shown to user
2. Preview shows original PDF instead of processed version
3. Filename shows original instead of `PREPROCESSED_..._split.pdf`

## Root Cause Analysis

### Primary Issue: PyMuPDF `get_pixmap(clip=...)` Failure

The error occurs when calling `source_page.get_pixmap(clip=left_clip_rect)`. Even though:
- Page access succeeds (`doc[page_num]` returns valid Page object)
- Page validation passes (page is not None, rect is valid)
- Clip rectangle is within bounds

PyMuPDF's internal C code raises `AssertionError: "page is None"` when using the `clip` parameter. This appears to be a PyMuPDF internal issue where the page reference becomes invalid during the clip operation.

### Secondary Issues

1. **Incorrect Fallback**: The previous fallback used `fitz.Pixmap(full_pixmap, x, y, w, h)` constructor which doesn't exist or has incorrect signature
2. **Complex PIL Conversion**: The old approach converted pixmap → numpy → PIL → PNG → Pixmap, which was fragile
3. **No Processed File Created**: When split fails, `processed_pdf` remains the original, so preview shows wrong file

## Solution

### Approach: Use PIL Cropping + Direct Image Stream Insertion

Instead of using PyMuPDF's problematic `clip` parameter or trying to create new Pixmaps, use a simpler, more reliable approach:

1. **Get full pixmap** (without clip parameter - this works reliably)
2. **Calculate crop coordinates** in pixmap pixel space
3. **Convert to PIL Image** and crop using PIL's reliable `crop()` method
4. **Insert directly as PNG stream** using `insert_image(..., stream=...)` instead of `pixmap=...`

### Why This Works

- `get_pixmap()` without clip parameter works reliably
- PIL's `crop()` is well-tested and doesn't have PyMuPDF's internal issues
- `insert_image(..., stream=...)` accepts PNG bytes directly, avoiding Pixmap creation issues
- Simpler code path = fewer failure points

## Implementation Plan

### Step 1: Replace Left Page Splitting Code

**Location**: `scripts/paper_processor_daemon.py`, lines ~6713-6765

**Current approach** (failing):
- Tries `get_pixmap(clip=...)` → fails with "page is None"
- Falls back to `fitz.Pixmap(full_pixmap, x, y, w, h)` → incorrect API

**New approach**:
```python
# Get full pixmap (no clip - this works)
full_pixmap = source_page.get_pixmap()

# Calculate crop coordinates
scale_x = full_pixmap.width / source_rect.width
scale_y = full_pixmap.height / source_rect.height
clip_x0 = int(left_clip_rect.x0 * scale_x)
clip_y0 = int(left_clip_rect.y0 * scale_y)
clip_x1 = int(left_clip_rect.x1 * scale_x)
clip_y1 = int(left_clip_rect.y1 * scale_y)

# Crop with PIL
from PIL import Image
import io
img_data = full_pixmap.tobytes("png")
pil_img = Image.open(io.BytesIO(img_data))
cropped_img = pil_img.crop((clip_x0, clip_y0, clip_x1, clip_y1))

# Insert as stream
img_bytes = io.BytesIO()
cropped_img.save(img_bytes, format='PNG')
left_page.insert_image(left_page.rect, stream=img_bytes.getvalue())
```

### Step 2: Replace Right Page Splitting Code

**Location**: `scripts/paper_processor_daemon.py`, lines ~6740-6791

Apply the same approach as Step 1, but for the right page.

### Step 3: Remove Old Debug Logging

Remove or update the old "Before show_pdf_page" logging messages that are no longer relevant.

## Expected Outcomes

### After Implementation

1. ✅ **Split succeeds**: No more "page is None" errors
2. ✅ **Preview works**: Shows `PREPROCESSED_..._split.pdf` file
3. ✅ **Correct filename**: Preview uses processed filename, not original
4. ✅ **Reliable operation**: PIL cropping is more stable than PyMuPDF's clip parameter

### Testing Checklist

- [ ] Test with PDF that has `_double.pdf` suffix
- [ ] Test with PDF that has detected two-up layout
- [ ] Test with 50-50 geometric split
- [ ] Verify preview shows split PDF, not original
- [ ] Verify filename shows `PREPROCESSED_..._split.pdf`
- [ ] Test with PDFs of different sizes (small, medium, large)
- [ ] Test with PDFs with different page counts

## Technical Details

### Why `insert_image(..., stream=...)` Instead of `pixmap=...`

- `stream=` parameter accepts PNG bytes directly
- Avoids creating intermediate Pixmap objects that can fail
- More reliable for scanned documents (already raster images)
- Simpler code path

### Why PIL Instead of Direct Pixmap Cropping

- PyMuPDF's pixmap cropping API is unclear/unreliable
- PIL's `crop()` is well-documented and stable
- PIL handles image format conversions reliably
- Already used elsewhere in codebase (border_remover.py)

### Performance Considerations

- PIL conversion adds minimal overhead for scanned PDFs (already raster)
- Memory usage: Full pixmap loaded once, then cropped (acceptable for typical page sizes)
- Quality: No quality loss for scanned documents (already raster)

## Files to Modify

1. `scripts/paper_processor_daemon.py`
   - Replace left page splitting code (~lines 6713-6765)
   - Replace right page splitting code (~lines 6740-6791)
   - Remove obsolete debug logging

## Related Issues

- This fixes the core splitting functionality
- Once split works, preview/filename issues should resolve automatically
- May need to verify preview logic handles split PDFs correctly

## Notes

- The old approach tried to be too clever with PyMuPDF's clip parameter
- Simpler is better - PIL cropping + stream insertion is more reliable
- This approach was used successfully in other parts of the codebase (border_remover.py)

## Implementation Status

- [x] Step 1: Replace left page code
- [x] Step 2: Replace right page code  
- [x] Step 3: Remove old logging (removed debug logging blocks)
- [ ] Step 4: Test with various PDFs
- [ ] Step 5: Verify preview/filename issues resolved

## Changes Made

### Left Page Splitting (lines ~6688-6746)
- Removed problematic `get_pixmap(clip=...)` attempt
- Removed old debug logging
- Implemented PIL-based cropping with direct stream insertion
- Uses `insert_image(..., stream=...)` instead of `pixmap=...`

### Right Page Splitting (lines ~6797-6850)
- Removed problematic `get_pixmap(clip=...)` attempt
- Implemented PIL-based cropping with direct stream insertion
- Uses `insert_image(..., stream=...)` instead of `pixmap=...`

### Key Improvements
1. **No more clip parameter**: Always gets full pixmap first
2. **PIL cropping**: More reliable than PyMuPDF's internal cropping
3. **Stream insertion**: Direct PNG bytes insertion avoids Pixmap creation issues
4. **Simpler code path**: Fewer failure points
