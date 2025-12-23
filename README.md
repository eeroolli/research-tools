# Research-Tools

A comprehensive system for processing academic papers and books with ISBN extraction, metadata lookup, and Zotero integration.

## Current Status

**✅ Book Processing**: Fully functional with advanced OCR capabilities  
**✅ Paper Processing**: Complete interactive daemon with 3-step UX workflow  
**✅ Zotero Integration**: Enhanced workflow for attaching PDFs to existing items  
**🤖 AI Integration**: Ollama 7B installed and ready for paper processing

For detailed development status, technical architecture, and upcoming features, see the [Implementation Plan](implementation-plan.md).

## 🚀 Quick Start: Process Scanned Papers

**Want to scan and process academic papers?**

1. **Start the daemon:**
   - **Windows**: Double-click `scripts/start_scanner_daemon_restart.vbs` (recommended before scanning session)
   - **Linux/WSL**: `python scripts/paper_processor_daemon.py`

2. **Scan your papers** to the configured scanner folder (see `config.conf: scanner_papers_dir`)
   - Use any scanner that saves PDFs
   - Or drag-drop PDFs manually to the folder

3. **Review each paper** in the interactive menu:
   - Approve extracted metadata
   - Edit if needed
   - Search local Zotero database
   - Skip non-academic documents

4. **Stop when done:** Press Ctrl+C in the terminal

**Setup for Epson Scanner:**
1. **Before scanning**: Run `scripts/start_scanner_daemon_restart.vbs` to start/restart the daemon
2. In Epson Capture Pro, set "After Scan" action (Send Settings → Destination → Application) to run `scripts/start_scanner_daemon_quiet.vbs`
3. The quiet VBS runs silently in the background (no popup windows)

**Optimal Epson Scanner Settings for OCR Quality:**
- **Text Enhancement**: OFF (better OCR results when disabled)
- **Portrait Mode**: 400 dpi (single-page scans)
- **Landscape Mode**: 600 dpi (two-up scans that will be split later)
- **Note**: GPU acceleration is not currently used for scanner OCR processing     

**Startup Time:**
- **First scan of day**: ~60 seconds (GROBID startup + Python imports)
- **Subsequent scans**: ~5 seconds (Grobid already running)

**Features:**
- ✅ **GROBID Integration** - Advanced academic paper metadata extraction
- ✅ **Remote GROBID Support** - Use GROBID running on another machine (distributed processing)
- ✅ **Smart Author Extraction** - Processes only first 2 pages to avoid citation pollution
- ✅ **Document Type Detection** - Automatically identifies journal articles, books, conferences, etc.
- ✅ **Enhanced Metadata** - Extracts keywords, publisher, volume, issue, pages, language
- ✅ **Daemon Locking** - Prevents multiple daemon instances (local and remote checking)
- ✅ Interactive review and approval with 3-step workflow
- ✅ Local Zotero database search with enhanced UX
- ✅ Metadata comparison and field-by-field merging
- ✅ Duplicate detection and conflict resolution
- ✅ Smart filename generation
- ✅ Manual processing option for ambiguous cases

[Detailed scanner setup (Epson auto-trigger) →](SCANNER_SETUP.md)

---

## Overview

Research-Tools provides two main workflows:

- **Book Processing** - Extract ISBNs from photos and add to Zotero with rich metadata
- **Paper Processing** - Scan academic papers and integrate with Zotero with interactive workflow

## Quick Start

```bash
# Activate conda environment
conda activate research-tools

# Process books
python scripts/find_isbn_from_photos.py
python scripts/add_or_remove_books_zotero.py

# Process papers (see Quick Start section above for interactive daemon)
python scripts/paper_processor_daemon.py
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

## Paper Processing (Working)

### What It Does
- **GROBID Integration** - Advanced academic paper metadata extraction using GROBID
- **Smart Processing** - Extracts metadata from first 2 pages only (configurable)
- **Document Type Detection** - Automatically identifies journal articles, books, conferences, theses, etc.
- **Enhanced Metadata** - Extracts keywords, publisher, volume, issue, pages, language, conference info
- **Fallback Processing** - Uses Ollama 7B when GROBID is unavailable
- Look up complete metadata from academic databases (CrossRef, arXiv)
- Add papers to Zotero with proper file linking and organization
- **Enhanced 3-step workflow** for attaching PDFs to existing Zotero items

### Enhanced 3-Step UX Workflow
When a Zotero match is found, users get a sophisticated 3-step process:

#### Step 1: Metadata Comparison
- Side-by-side comparison of extracted vs Zotero metadata
- 6 user options including manual processing and creating new items
- Field-by-field merging capability

#### Step 2: Tags Comparison  
- Integration with existing interactive tag system
- Tag groups, online tags, and custom tag management

#### Step 3: PDF Attachment
- PDF conflict resolution (keep both/replace/cancel)
- Smart filename generation and duplicate handling
- Complete file management and cleanup

### Current Status
✅ **Paper processing is fully implemented and working!** The interactive daemon provides a complete workflow for processing scanned academic papers with enhanced Zotero integration.

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
- **Complete interactive paper processing workflow**
- **3-step UX flow for Zotero PDF attachment**
- **Enhanced metadata comparison and merging**
- **GROBID Integration** - Advanced academic paper metadata extraction
- **Smart Author Extraction** - Page-limited processing to avoid citation pollution
- **Document Type Detection** - Automatic classification of academic documents
- **Enhanced Metadata Extraction** - Keywords, publisher, volume, issue, pages, language
- **Path Utilities Refactoring** - Consolidated path handling, eliminated duplication, improved maintainability

### 🚧 In Progress
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
- **[GROBID Setup](GROBID_SETUP.md)** - GROBID integration and configuration guide
- **[Path Utilities](scripts/PATH_UTILS_README.md)** - WSL/Windows path handling utilities documentation

## License

[Add your license information here]

## Support

For detailed technical information, development status, and upcoming features, please refer to the [Implementation Plan](implementation-plan.md).