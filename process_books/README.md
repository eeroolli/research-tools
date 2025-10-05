# Process Books - Book ISBN Extraction and Zotero Integration

This module handles the complete book processing workflow from photo to Zotero library entry.

## Features

- **Smart Image Processing** (SmartIntegratedProcessorV3 with Intel GPU optimization)
- **ISBN Pattern Recognition** with enhanced regex patterns
- **Barcode Detection** using pyzbar
- **OCR Processing** with multiple preprocessing strategies
- **Batch Processing** with intelligent crop detection
- **Zotero Integration** for automatic library management
- **International Metadata Sources** (Norwegian, Finnish, Library of Congress, OpenLibrary, Google Books)
- **Intel GPU Acceleration** for faster processing

## Quick Start

```bash
# Activate conda environment (from research-tools root)
conda activate research-tools

# Process books
python scripts/find_isbn_from_photos.py

# Look up ISBN metadata
python scripts/enhanced_isbn_lookup_detailed.py

# Add to Zotero
python scripts/zotero_api_book_processor_enhanced.py
```

## Workflow

### 1. Take Photos
- Focus camera on ISBN/barcode area
- Ensure good lighting
- Take clear, focused photo
- **Requirements:** ISBN or barcode must be visible

### 2. Transfer Photos to Computer
- Use the external photo transfer script: `/mnt/f/prog/getphotosfromphone/move_photos.sh`
- Copy photos to `/mnt/i/FraMobil/Camera/Books/`
- Photos will be automatically organized into `done/` and `failed/` folders

### 3. Process Photos
```bash
python scripts/process_books.py
```
- Uses SmartIntegratedProcessorV3 with Intel GPU optimization
- Detects barcodes (0.6 seconds) and OCR text (60-120 seconds)
- Moves successful photos to `done/` folder
- Moves failed photos to `failed/` folder

### 4. Find ISBN
- System automatically extracts ISBNs from photos
- Barcode detection: 95% success rate
- OCR detection: 70% success rate
- Results saved to `data/book_processing_log.json`

### 5. Find Library Data
```bash
python scripts/enhanced_isbn_lookup_detailed.py
```
- Fetches metadata from multiple sources:
  - OpenLibrary API
  - Google Books API
  - Norwegian National Library API
  - Finnish National Library API
- Retrieves: title, authors, abstracts, subject tags, publication info

### 6. Enter Data to Zotero
```bash
python scripts/zotero_api_book_processor_enhanced.py
```
- Interactive processing of found ISBNs
- Searches existing library to avoid duplicates
- Adds books with rich metadata
- Smart tag management with memory
- Robust ISBN matching with ISBN-10/ISBN-13 conversion

## Architecture

### Core Components

1. **SmartIntegratedProcessorV3** - Advanced image processing with Intel GPU optimization
2. **ISBNExtractor** - Enhanced ISBN pattern recognition
3. **ZoteroProcessor** - Library integration
4. **MetadataExtractor** - International metadata lookup

### Processing Pipeline

1. **Image Analysis** - Detect orientation, brightness, crop status
2. **Barcode Detection** - Fast barcode scanning with rotation
3. **OCR Processing** - Multiple preprocessing strategies
4. **ISBN Extraction** - Pattern matching and validation
5. **Metadata Lookup** - International library databases
6. **Zotero Integration** - Library management and duplicate checking

## Configuration

- **config/process_books.conf** - Main configuration
- **config/zotero_api.conf** - Zotero API settings (if exists)
- **shared-tools/config/manager.py** - Centralized configuration management

## Success Metrics

- **Success rate:** 100% (2/2 images in recent test)
- **Barcode detection:** 0.6 seconds (early exit)
- **OCR detection:** 60-120 seconds (multiple strategies)
- **Intel GPU:** Acceleration enabled and working

## Integration with Research-Tools

This module integrates with the shared-tools infrastructure:
- **shared-tools/utils/isbn_matcher.py** - ISBN matching utilities
- **shared-tools/metadata/extractor.py** - Unified metadata extraction
- **shared-tools/config/manager.py** - Centralized configuration
- **shared-tools/api/** - API clients for metadata sources
