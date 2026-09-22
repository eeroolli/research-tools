# PDF Processing Utilities

PDF processing utilities for the research-tools project.

## BorderRemover

Remove dark borders from scanned document pages.

```python
from shared_tools.pdf import BorderRemover

remover = BorderRemover({'max_border_width': 600})
processed_image = remover.remove_borders(image)
```

Configuration:
- `max_border_width`: Maximum border width to detect in pixels (default: 300)

## PDFRotationHandler

Detect and correct PDF rotation for GROBID processing.

```python
from shared_tools.pdf import PDFRotationHandler

handler = PDFRotationHandler()
pdf_path, rotation = handler.process_pdf_with_rotation(pdf_path)
```

Used automatically by GROBID client for rotated PDFs.

## add_text_layer

Add a searchable Tesseract text layer via ocrmypdf. Original page images stay; output is a sibling `*_ocr.pdf` (never overwrites the source). `--clean` (unpaper) is optional and usually needs WSL.

```python
from shared_tools.pdf.text_layer import add_text_layer

out = add_text_layer("scan.pdf", oversample=300)
```
