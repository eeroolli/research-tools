# Research-Tools

A comprehensive system for processing academic papers and books with ISBN extraction, metadata lookup, and Zotero integration.


## Work in Progress
There is a file implementation-plan.md that describes the current status. The book processing system is fully functional with advanced OCR capabilities, while the paper processing system and unified metadata system are in development.


## Overview

Research-Tools is organized into three main modules:

- **shared_tools** - Common utilities and infrastructure
- **process_books** - Book processing with ISBN extraction and Zotero integration  
- **process_papers** - Academic paper scanning, OCR, and Zotero integration

## Quick Start

```bash
# Activate conda environment
conda activate research-tools

# Test the installation
python test_integration.py

# Process books
python scripts/find_isbn_from_photos.py

# Process papers  
cd process_papers
python scripts/process_papers.py
```

## Features

### Shared Tools
- **ISBN Matching** - Robust ISBN comparison and validation
- **Configuration Management** - Centralized config for all modules
- **Metadata Extraction** - Unified metadata extraction framework
- **API Clients** - Base classes for various metadata sources

### Book Processing
- **Smart Image Processing** - Intel GPU optimized ISBN extraction with CPU throttling
- **Two-Tier Processing** - Small images first (25% size), then full-size fallback for better OCR accuracy
- **Barcode Detection** - Fast barcode scanning with pyzbar
- **OCR Processing** - Multiple preprocessing strategies with parallel rotation processing
- **Image Management** - Smart retry system with permanently_failed category after 3 attempts
- **International Metadata** - Norwegian, Finnish, Library of Congress, OpenLibrary, Google Books
- **Zotero Integration** - Automatic library management with duplicate checking

### Paper Processing
- **OCR Engine** - Optimized for academic papers with annotations
- **Metadata Extraction** - DOI, ISSN, Title, Authors, Journal, Abstract
- **Zotero Matching** - Fuzzy matching against existing library
- **Annotation Preservation** - Keeps handwritten notes as image overlay
- **Language Detection** - EN, DE, NO, FI, SE support

## Architecture

```
research-tools/
├── data/                  # Centralized data directory
│   ├── books/            # Book processing results and logs
│   │   ├── pending/      # Photos waiting to be processed
│   │   ├── done/         # Successfully processed photos
│   │   ├── failed/       # Failed photos (retryable)
│   │   ├── permanently_failed/  # Failed after max retries
│   │   └── metadata/     # Book metadata from ISBN lookups
│   ├── papers/           # Paper processing results
│   ├── logs/             # All application logs
│   ├── cache/            # Temporary cache files
│   ├── output/           # Final processed outputs
│   └── temp/             # Temporary files
├── scripts/              # All executable scripts
│   ├── find_isbn_from_photos.py  # Main book processing script
│   ├── manual_isbn_metadata_search.py  # Manual ISBN lookup and metadata search
│   └── zotero_api_book_processor_enhanced.py  # Zotero integration
├── shared_tools/         # Common utilities
│   ├── utils/            # ISBN matcher, file utilities
│   ├── metadata/         # Unified metadata extraction
│   ├── config/           # Configuration management
│   └── api/              # API client base classes
├── process_books/        # Book processing code
│   ├── src/              # Source code
│   │   ├── processors/   # Image processing (SmartIntegratedProcessorV3)
│   │   ├── extractors/   # ISBN extraction
│   │   └── integrations/ # Zotero integration
│   └── config/           # Book-specific configuration
├── process_papers/       # Paper processing code
│   ├── src/              # Source code
│   │   ├── models/       # Data models
│   │   ├── core/         # OCR, metadata extraction, Zotero matching
│   │   └── pipelines/    # Processing pipelines
│   └── config/           # Paper-specific configuration
├── config.conf           # Main configuration file
├── environment.yml       # Conda environment specification
└── tests/                # Test scripts
    └── test_integration.py  # Integration test script
```

## Configuration

The system uses a centralized configuration approach:

- **config.conf** - Main configuration file with paths, API settings, and processing options
- **Module-specific configs** - Each module has its own configuration file
- **Environment variables** - For sensitive data like API keys

## Environment Setup

The system uses the `research-tools` conda environment with Intel GPU optimizations:

```bash
# Create environment
conda env create -f environment.yml

# Activate environment
conda activate research-tools
```

## Dependencies

### Core Dependencies
- Python 3.11 (Intel optimized)
- OpenCV with Intel GPU support
- PyZotero for Zotero integration
- Multiple OCR engines (Tesseract, EasyOCR, PaddleOCR)

### Optional Dependencies
- PyMuPDF (fitz) for advanced PDF processing
- Intel Math Kernel Library (MKL)
- Intel OpenMP and TBB for parallel processing

## Usage Examples

### Book Processing
```bash
# Take photos of book ISBNs/barcodes
# Transfer to /mnt/i/FraMobil/Camera/Books/

# Process photos (main script)
python scripts/find_isbn_from_photos.py

# Look up metadata and add to Zotero
python scripts/zotero_api_book_processor_enhanced.py
```

### Paper Processing
```bash
# Scan papers to /mnt/i/documents/scan/

# Process papers
cd process_papers
python scripts/process_papers.py

# Match with Zotero
python scripts/match_zotero.py

# Integrate into Zotero
python scripts/integrate_zotero.py
```

## Success Metrics

### Book Processing
- ISBN extraction accuracy: 95%+ (barcode), 70%+ (OCR)
- Processing speed: 0.6s (barcode), 12-60s (OCR with two-tier processing)
- Intel GPU acceleration: Enabled for image preprocessing
- CPU throttling: Prevents system overload during parallel OCR
- File management: Smart retry system with 3 attempts before permanent failure

### Paper Processing
- OCR accuracy: 90%+ for clean academic papers
- Metadata extraction: 85%+ for standard formats
- Zotero matching: 95%+ with DOI, 80%+ without

## Integration Status

✅ **Completed:**
- Directory structure reorganization
- Centralized data directory with organized subfolders
- Shared tools foundation
- ISBN matcher utility
- Configuration management system
- Book processing migration with advanced OCR capabilities
- CPU throttling and two-tier image processing
- File management system with smart retry logic
- CSV logging system for better data analysis
- Legacy data migration (66 book records + 25+ log files)
- Integration testing

🔄 **In Progress:**
- Unified metadata system design
- Academic paper APIs (OpenAlex, CrossRef, PubMed, arXiv)

📋 **Pending:**
- AI-driven paper processing enhancement
- Complete migration of hardcoded systems
- Advanced paper processing pipelines

## Testing

Run the integration test to verify all components work correctly:

```bash
python test_integration.py
```

This tests:
- Directory structure
- Shared tools components
- Book processing components  
- Paper processing components

## Contributing

1. Follow the established directory structure
2. Use the shared tools for common functionality
3. Maintain configuration in the centralized system
4. Test integration with `test_integration.py`
5. Update documentation as needed

## License

MIT License - see individual module licenses for details.

## Acknowledgments

- Intel GPU optimization for faster image processing
- OpenCV for computer vision capabilities
- PyZotero for Zotero API integration
- Norwegian National Library API for Nordic book metadata
