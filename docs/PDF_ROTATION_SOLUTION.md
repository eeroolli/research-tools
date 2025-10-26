# PDF Rotation Handling for GROBID

## Problem

GROBID performs poorly on PDFs that are rotated 90 degrees, which is common with scanned book chapters where two pages are scanned per sheet and rotated for scanning. This results in:

- Poor metadata extraction
- Incorrect author detection
- Failed title extraction
- Poor abstract parsing

## Solution

This solution automatically detects and corrects PDF rotation before sending to GROBID, using the existing rotation detection logic from the book processing module.

## Features

### ✅ **Automatic Rotation Detection**
- Detects PDFs rotated 90°, 180°, or 270°
- Uses fast OCR-based detection on first 2 pages
- Looks for academic paper indicators (abstract, introduction, DOI, etc.)

### ✅ **Smart Rotation Correction**
- Creates corrected PDF versions automatically
- Preserves original PDFs
- Cleans up temporary files after processing

### ✅ **GROBID Integration**
- Seamlessly integrated with existing GROBID workflow
- No changes needed to existing paper processing
- Configurable rotation handling

### ✅ **Configuration Options**
- Enable/disable rotation handling
- Configure pages to check for rotation
- Set Tesseract path for OCR

## Files Added/Modified

### New Files
- `shared_tools/pdf/pdf_rotation_handler.py` - Core rotation detection and correction
- `scripts/test_pdf_rotation.py` - Test script for rotation handling
- `PDF_ROTATION_SOLUTION.md` - This documentation

### Modified Files
- `shared_tools/api/grobid_client.py` - Added rotation handling to GROBID client
- `scripts/paper_processor_daemon.py` - Updated to use rotation handling
- `config.conf` - Added rotation configuration options

## Configuration

Add these settings to your `config.conf`:

```ini
[GROBID]
# ... existing GROBID settings ...
# PDF rotation handling for scanned book chapters
handle_rotation = true
# Maximum pages to check for rotation detection
rotation_check_pages = 2
```

## Usage

### Automatic Usage
The rotation handling is now automatic when using the paper processor daemon. No changes needed to your existing workflow.

### Manual Testing
Test the rotation handling with a specific PDF:

```bash
python scripts/test_pdf_rotation.py /path/to/rotated.pdf
```

### Programmatic Usage
```python
from shared_tools.api.grobid_client import GrobidClient

# Create GROBID client with rotation handling
client = GrobidClient(config={'handle_rotation': True})

# Extract metadata (rotation handled automatically)
metadata = client.extract_metadata(pdf_path)

# Cleanup temporary files
client.cleanup_temp_files()
```

## How It Works

1. **Detection**: When processing a PDF, the system first checks if rotation is needed by:
   - Converting first 2 pages to images
   - Testing OCR on rotated versions (90°, 180°, 270°)
   - Looking for academic paper indicators in the text

2. **Correction**: If rotation is detected:
   - Creates a corrected PDF with proper orientation
   - Uses PyMuPDF to apply rotation to all pages
   - Saves corrected version to temporary location

3. **Processing**: Sends corrected PDF to GROBID for metadata extraction

4. **Cleanup**: Removes temporary corrected PDFs after processing

## Rotation Detection Logic

The system uses the same sophisticated rotation detection logic from the book processing module:

- **Fast Detection**: Uses small images for quick OCR testing
- **Academic Indicators**: Looks for keywords like "abstract", "introduction", "DOI", "journal"
- **Confidence Scoring**: Requires multiple indicators to confirm rotation
- **Multiple Angles**: Tests 90°, 180°, and 270° rotations

## Performance Impact

- **Minimal Overhead**: Only checks first 2 pages for rotation
- **Fast Processing**: Uses optimized OCR settings for detection
- **Temporary Storage**: Corrected PDFs are cleaned up automatically
- **Memory Efficient**: Processes pages individually to avoid memory issues

## Troubleshooting

### GROBID Still Fails
- Check if PDF is actually rotated by running the test script
- Verify Tesseract is installed and accessible
- Check GROBID server logs for other issues

### Rotation Not Detected
- PDF might not be rotated, or rotation is different than expected
- Check if academic indicators are present in the text
- Try manual rotation detection with the test script

### Performance Issues
- Reduce `rotation_check_pages` in config to check only first page
- Disable rotation handling if not needed: `handle_rotation = false`

## Dependencies

The solution uses existing dependencies:
- **PyMuPDF (fitz)**: For PDF manipulation and rotation
- **OpenCV**: For image processing and rotation
- **Tesseract**: For OCR-based rotation detection
- **PIL**: For image format conversion

## Future Enhancements

Potential improvements:
- **Machine Learning**: Use ML models for better rotation detection
- **Batch Processing**: Process multiple PDFs with rotation detection
- **Quality Metrics**: Assess rotation correction quality
- **User Interface**: GUI for manual rotation correction

## Testing

Test with various types of rotated PDFs:
- Scanned book chapters (90° rotated)
- Conference papers (180° rotated)
- Journal articles (270° rotated)
- Mixed orientation PDFs

The test script provides detailed logging to help diagnose issues.

## Support

For issues or questions:
1. Check the logs for error messages
2. Run the test script to verify rotation detection
3. Verify GROBID server is running and accessible
4. Check configuration settings in `config.conf`
