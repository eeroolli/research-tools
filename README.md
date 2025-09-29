# Research-Tools

A comprehensive system for processing academic papers and books with ISBN extraction, metadata lookup, and Zotero integration.

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
cd process_books
python scripts/process_books.py

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
- **Smart Image Processing** - Intel GPU optimized ISBN extraction
- **Barcode Detection** - Fast barcode scanning with pyzbar
- **OCR Processing** - Multiple preprocessing strategies
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
├── shared_tools/           # Common utilities
│   ├── utils/             # ISBN matcher, file utilities
│   ├── metadata/          # Unified metadata extraction
│   ├── config/            # Configuration management
│   └── api/               # API client base classes
├── process_books/         # Book processing
│   ├── src/               # Source code
│   │   ├── processors/    # Image processing (SmartIntegratedProcessorV3)
│   │   ├── extractors/    # ISBN extraction
│   │   └── integrations/  # Zotero integration
│   ├── scripts/           # Processing scripts
│   └── config/            # Book-specific configuration
├── process_papers/        # Paper processing
│   ├── src/               # Source code
│   │   ├── models/        # Data models
│   │   ├── core/          # OCR, metadata extraction, Zotero matching
│   │   └── pipelines/     # Processing pipelines
│   ├── scripts/           # Processing scripts
│   └── config/            # Paper-specific configuration
├── config.conf            # Main configuration file
├── environment.yml        # Conda environment specification
└── test_integration.py    # Integration test script
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

# Process photos
cd process_books
python scripts/process_books.py

# Look up metadata
python scripts/enhanced_isbn_lookup_detailed.py

# Add to Zotero
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
- Processing speed: 0.6s (barcode), 60-120s (OCR)
- Intel GPU acceleration: Enabled and working

### Paper Processing
- OCR accuracy: 90%+ for clean academic papers
- Metadata extraction: 85%+ for standard formats
- Zotero matching: 95%+ with DOI, 80%+ without

## Integration Status

✅ **Completed:**
- Directory structure reorganization
- Shared tools foundation
- ISBN matcher utility
- Configuration management system
- Book processing migration
- Paper processing framework
- Integration testing

🔄 **In Progress:**
- API client implementations
- Additional paper processing scripts

📋 **Pending:**
- Complete API client implementations
- Advanced paper processing pipelines
- Documentation updates

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
