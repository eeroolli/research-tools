# Research-Tools

A comprehensive system for processing academic papers and books with ISBN extraction, metadata lookup, and Zotero integration.

## Current Status

**✅ Book Processing**: Fully functional with advanced OCR capabilities  
**🚧 Paper Processing**: Planned (see [Implementation Plan](implementation-plan.md))  
**🤖 AI Integration**: Ollama 7B installed and ready for paper processing

For detailed development status, technical architecture, and upcoming features, see the [Implementation Plan](implementation-plan.md).

## Overview

Research-Tools provides two main workflows:

- **Book Processing** - Extract ISBNs from photos and add to Zotero with rich metadata
- **Paper Processing** - Scan academic papers and integrate with Zotero (planned)

## Quick Start

```bash
# Activate conda environment
conda activate research-tools

# Process books (working)
python scripts/find_isbn_from_photos.py
python scripts/add_or_remove_books_zotero.py

# Process papers (planned - see implementation plan)
# python scripts/process_scanned_papers.py
```

## Book Processing (Working)

### What It Does
- Extracts ISBNs from book photos using barcode detection and OCR
- Looks up rich metadata from multiple international sources
- Adds books to your Zotero library with smart tag management
- Handles duplicates and provides interactive decision making

### Workflow
1. **Take Photos** - Focus on ISBN/barcode area with good lighting
2. **Transfer Photos** - Use your photo transfer script to move to `/mnt/i/FraMobil/Camera/Books/`
3. **Process Photos** - Run `python scripts/find_isbn_from_photos.py`
4. **Add to Zotero** - Run `python scripts/add_or_remove_books_zotero.py`

### Features
- **Smart Image Processing** with Intel GPU optimization
- **ISBN Pattern Recognition** with enhanced regex patterns
- **Barcode Detection** using pyzbar (95% success rate)
- **OCR Processing** with multiple preprocessing strategies
- **International Metadata Sources** (OpenLibrary, Google Books, Norwegian National Library)
- **Zotero Integration** with multi-digit input system
- **Smart Tag Management** with configurable tag groups

### Success Metrics
- **Barcode detection**: 0.6 seconds (early exit)
- **OCR detection**: 60-120 seconds (multiple strategies)
- **Success rate**: 100% in recent tests
- **Intel GPU**: Acceleration enabled and working

## Paper Processing (Planned)

### What It Will Do
- Process scanned academic papers using Ollama 7B for identifier extraction
- Extract DOI, title, authors, journal information from first page
- Look up complete metadata from academic databases (CrossRef, PubMed, arXiv, OpenAlex)
- Add papers to Zotero with proper file linking and organization

### Current Status
Paper processing is planned for **Phase 4** of development. See the [Implementation Plan](implementation-plan.md) for detailed technical specifications and timeline.

### Scaffold (available now)
To preview the future workflow shape without changing current behavior, a minimal scaffold exists:

```bash
# Extract identifiers from the first page of a scanned PDF (heuristic)
python scripts/process_scanned_papers.py /path/to/paper.pdf

# Optional: use the Ollama stub (same output structure, placeholder source)
python scripts/process_scanned_papers.py /path/to/paper.pdf --ollama
```

Notes:
- First-page text extraction uses PyPDF2 if installed; otherwise it returns an empty string.
- Identifier extraction uses a lightweight heuristic today and will be replaced by Ollama-based extraction in Phase 4.

## Configuration

The system uses a two-tier configuration approach:

1. **`config.conf`** (public, on GitHub) - Default settings
2. **`config.personal.conf`** (private, NOT on GitHub) - Personal overrides

### Key Configuration Sections

#### TAG_GROUPS (for book processing)
```ini
[TAG_GROUPS]
group1 = Eero har,personal,owned
group2 = Eero hadde,gitt bort,donated
group3 = political behavior,party preference,voting
```

#### APIS (Zotero credentials)
```ini
[APIS]
zotero_api_key = your_api_key
zotero_library_id = your_library_id
zotero_library_type = user
```

## File Organization

### Data Structure
```
data/
├── books/          # 📚 Book processing results and logs
├── papers/         # 📄 Paper processing results and logs  
├── logs/           # 📝 Application logs (all scripts)
├── cache/          # 💾 Temporary cache files
├── output/         # 📤 Processed outputs
└── temp/           # 🗂️ Temporary processing files
```

### File Naming Conventions

#### Books
- Photos: `IMG_YYYYMMDD_HHMMSS.jpg`
- Processed: Moved to `done/` or `failed/` folders

#### Papers (Planned)
- Scanned: `scan_timestamp.pdf`
- Processed: `{author}_{year}_{title}.pdf`

## Technical Architecture

### Current Implementation
- **SmartIntegratedProcessorV3** - Advanced image processing with Intel GPU optimization
- **ISBNExtractor** - Enhanced ISBN pattern recognition
- **ZoteroProcessor** - Library integration with multi-digit input system
- **MetadataExtractor** - International metadata lookup

### Planned Enhancements
- **Ollama 7B Integration** - AI-powered identifier extraction for papers
- **Academic Metadata APIs** - CrossRef, PubMed, arXiv, OpenAlex
- **Unified Metadata System** - Smart routing between books and papers
- **Hybrid Photo Processing** - Experimental document type classification

For detailed technical architecture and development phases, see the [Implementation Plan](implementation-plan.md).

## Development Status

### ✅ Completed
- Book processing with ISBN extraction
- Zotero integration with multi-digit input
- Intel GPU optimization
- CSV logging system
- Configuration management
- International metadata sources
- Ollama 7B installation

### 🚧 In Progress
- Paper scanning workflow (Phase 4)
- Academic metadata APIs (Phase 4)
- Unified metadata system (Phase 2-3)

### 📋 Planned
- Hybrid photo processing (Phase 8)
- Advanced duplicate detection
- Performance optimizations (Phase 7)
- Local Zotero database integration (Phase 7)

## Troubleshooting

### Common Issues

1. **No ISBNs found**: Run image processing first to populate the log
2. **Configuration errors**: Check file paths and section names
3. **API errors**: Verify Zotero credentials in config files
4. **GPU issues**: Check Intel GPU drivers and OpenVINO installation

### Debug Mode

Enable debug output by setting environment variable:
```bash
export DEBUG=1
python scripts/add_or_remove_books_zotero.py
```

## Contributing

This project follows the coding standards defined in `programming_preferences.md`. Key principles:
- Use relative paths for all critical files
- All scripts must source a single config file
- Write robust, clear, and maintainable code
- Follow industry best practices for security and testing

## Documentation

- **[Implementation Plan](implementation-plan.md)** - Detailed technical roadmap and development phases
- **[Programming Preferences](programming_preferences.md)** - Coding standards and best practices
- **[Ollama Setup](ollama-network-sharing.md)** - Ollama 7B installation and configuration
- **[GPU Optimization](gpu-optimization-suggestions.md)** - Performance optimization options

## License

[Add your license information here]

## Support

For detailed technical information, development status, and upcoming features, please refer to the [Implementation Plan](implementation-plan.md).