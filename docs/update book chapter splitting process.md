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

Implemented page 1 deletion for book chapters after splitting.

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

### **Features**
- Only triggers for book chapters after splitting
- Requires user confirmation before deletion
- Safe: only modifies temporary split files, preserves originals
- Error handling: falls back to original split if deletion fails
- Validates PDF has multiple pages before attempting deletion

### **Workflow**
1. PDF is split (either via `_double.pdf` suffix or user prompt)
2. If document type is `book_chapter`, user is prompted
3. If confirmed, page 1 is deleted from the split PDF
4. Modified PDF (or original if deletion skipped/failed) is used for Zotero attachment

Ready for testing. The feature only activates for book chapters after splitting, with user confirmation required.

## Future Enhancement: Black Border Removal (Low Priority)

### Request
Remove black borders from PDFs. This happens often if the paper being scanned is actually a copy made from a book.

### Status
✅ Added to implementation plan as low priority item

### Implementation Options
1. **Integrate into splitting workflow** - Offer black border removal after splitting book chapters (similar to page 1 deletion)
2. **Separate batch tool** - Create standalone script to process all PDFs in `publications/` directory, detect files with black borders, and trim them

### Technology Stack
- **PyMuPDF (fitz)** - PDF→image conversion and PDF reconstruction (already in use)
- **OpenCV (cv2)** - Edge detection and border cropping (already in use)
- **PIL/Pillow** - Image processing operations (already in use)

### Notes
- Not needed immediately; can be implemented later as standalone tool or workflow enhancement
- See `implementation-plan.md` Backlog section and Phase 4.4 for details 