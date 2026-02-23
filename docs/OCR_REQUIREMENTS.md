# OCR Requirements and Document Characteristics

## Document Type

**Scanned paper printouts with personal annotations**

These are NOT original documents that can be downloaded fresh. They are:
- Paper printouts that have been read and annotated
- Unique documents with personal value
- Must be scanned and OCR'd to preserve both text and annotations

## Document Characteristics

### Languages
- **English** (en)
- **Norwegian** (no)
- **Swedish** (sv)
- **Finnish** (fi)
- **German** (de)

### Formats
- **Portrait**: Single page per sheet
- **Landscape**: Two pages per sheet (two-up pages)

### Annotations (Must Be Preserved)

1. **Handwritten notes and comments**
   - Personal annotations written with pen
   - Valuable insights and thoughts
   - Must be preserved in OCR'd PDF

2. **Underlined sections**
   - Pencil underlines
   - Important passages marked
   - Must be visible in OCR'd PDF

3. **Highlighted sections**
   - Yellow marker highlights
   - Key information marked
   - Must be preserved in OCR'd PDF

## OCR Requirements

### Functional Requirements

1. **Multi-language OCR**
   - Support all 5 languages (EN, NO, SV, FI, DE)
   - Automatic language detection or manual selection
   - Accurate text extraction for all languages

2. **Two-up Page Handling**
   - Detect landscape scans (two pages per sheet)
   - Split into single pages before OCR
   - Process each page separately
   - Reassemble into single PDF

3. **Annotation Preservation**
   - Preserve handwritten notes (visible in final PDF)
   - Preserve underlines (pencil markings)
   - Preserve highlights (yellow marker)
   - OCR text must be searchable while annotations remain visible

4. **Performance**
   - GPU acceleration (5-10x faster than CPU)
   - Reasonable processing time per page
   - Batch processing support

### Technical Requirements

1. **OCR Engine**
   - EasyOCR with CUDA support (GPU)
   - Fallback to CPU if GPU unavailable
   - Multi-language model support

2. **PDF Processing**
   - Convert PDF to images (high DPI for quality)
   - Process each page
   - Create searchable PDF with annotations preserved
   - Handle both portrait and landscape orientations
   - handle multi column layouts

3. **Configuration**
   - Configurable OCR method (Epson/GPU/CPU/none)
   - Language selection
   - Quality settings (DPI)
   - Two-up page auto-split option

## Implementation Considerations

### Annotation Preservation

**Challenge**: OCR typically creates a new PDF with searchable text, but annotations (handwritten notes, underlines, highlights) are on the original scanned image.

**Solution Options:**
1. **Overlay approach**: OCR text as invisible layer, keep original image with annotations visible
2. **Hybrid approach**: OCR text as searchable layer, preserve annotations as image overlay
3. **Smart detection**: Detect and preserve annotation regions while OCR'ing text regions

**Recommended**: Overlay approach (invisible searchable text + visible annotated image)

### Two-up Page Splitting

**Challenge**: Landscape scans have two pages side-by-side on one sheet.

**Solution**:
- Use existing `split_two_up_pdf()` function from `scripts/ocr_pdf.py`
- Auto-detect based on filename (`_double.pdf` suffix) or aspect ratio
- Split before OCR, process each page separately
- Reassemble into single PDF

### Multi-language OCR

**Challenge**: Documents may contain multiple languages or unknown language.

**Solution**:
- Use EasyOCR with all 5 languages loaded
- EasyOCR can handle multiple languages in one model
- Slightly slower initialization but better accuracy
- Alternative: Language detection + single language OCR (faster but less accurate)

**Recommended**: Load all languages (en,no,sv,fi,de) for best accuracy

## Testing Requirements

### Test Cases

1. **Portrait single-page document** (English)
   - With handwritten notes
   - With underlines
   - With highlights
   - Verify annotations preserved

2. **Landscape two-up document** (Norwegian)
   - Auto-split detection
   - Process both pages
   - Verify annotations preserved on both pages

3. **Multi-language document** (Swedish + English)
   - Verify both languages OCR'd correctly
   - Verify annotations preserved

4. **Performance tests**
   - GPU vs CPU speed comparison
   - Multi-language vs single-language speed
   - Two-up splitting overhead

## Success Criteria

### Must Have
- ✅ Multi-language OCR (EN, NO, SV, FI, DE)
- ✅ Two-up page splitting (landscape scans)
- ✅ Annotation preservation (handwritten notes, underlines, highlights)
- ✅ GPU acceleration (5-10x faster than CPU)
- ✅ Searchable PDF output
- ✅ Configurable OCR method

### Nice to Have
- ⚠️ Automatic language detection
- ⚠️ Annotation region detection
- ⚠️ Batch processing optimization

---

*These requirements ensure that the OCR system handles the unique characteristics of annotated scanned printouts while providing fast, accurate text extraction.*

