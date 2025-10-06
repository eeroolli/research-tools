# Research-Tools Implementation Plan

**Date:** September 2025  
**Purpose:** Comprehensive plan for completing research-tools system  
**Status:** 🚧 IN PROGRESS - Configuration-driven system implemented, migration and AI integration pending

## Current Status Summary

### ✅ **Completed:**
- Configuration-driven national library system implemented and working
- Norwegian, Swedish, Finnish libraries tested and functional
- XML parsing support added for German library
- Test suite organized and working (`tests/` directory)
- Environment renamed to `research-tools`
- ISBN validation and prefix extraction centralized
- OpenLibrary and Google Books integration working
- **Project restructuring** - Centralized scripts/ and data/ directories
- **CPU throttling system** - Prevents system overload during parallel OCR processing
- **Two-tier image processing** - Small images first, then full-size fallback for better OCR accuracy
- **Code refactoring** - Eliminated duplication in strategy processing
- **File management system** - Smart retry logic with permanently_failed category
- **Process indicators** - Better user feedback during processing
- **CSV logging system** - Converted from JSON to CSV for better data analysis
- **Environment cleanup** - Removed unused dependencies for leaner setup
- **Data structure cleanup** - Consolidated scattered data directories and logs

### ❌ **Not Completed:**
- Detailed migration tasks from `archive/AI_CHAT_DOCUMENTS.md` (Phases 2-4)
- Unified metadata system with smart routing
- AI-driven paper processing enhancement
- Academic paper APIs (OpenAlex, CrossRef, PubMed, arXiv)

## Primary Use Case: Paper Scanning Workflow

**Input**: `scan_timestamp.pdf` (single paper scan)
**Process**:
1. OCR/AI process first page to extract identifying information
2. Find paper in academic databases (OpenAlex, CrossRef, PubMed, arXiv)
3. Retrieve complete metadata
4. Rename PDF with meaningful filename
5. Copy to `g:/publications` storage location
6. Add as linked file in Zotero

**Key Requirements**:
- First page processing for paper identification
- Smart routing based on extracted identifiers (DOI, title, authors)
- Automated filename generation from metadata
- Windows drive access from WSL for storage
- Zotero integration for linked files

## Implementation Phases

### **Phase 0: Data Structure Cleanup** 🧹
*Consolidate scattered data directories and logs*

#### 0.0 Ollama Installation and Setup
- [ ] **Install Ollama** - Local AI for privacy-sensitive processing
- [ ] **Configure models** - llama2, codellama, mistral for different tasks
- [ ] **Environment setup** - GPU acceleration with Intel UHD Graphics 630
- [ ] **Integration testing** - Verify Ollama works with research-tools system

#### 0.1 Consolidate Data Directories ✅
- [x] **Remove duplicate data directories** - process_books/data/, process_papers/data/, scripts/data/
- [x] **Consolidate all logs** - Move scattered logs to data/logs/
- [x] **Update code references** - Fix hardcoded paths to old data directories
- [x] **Test functionality** - Ensure all scripts work with new structure
- [x] **Migrate legacy data** - Copied 66 book records + 25+ log files from scanpapers
- [x] **Convert legacy data** - JSON to CSV conversion for compatibility

### **Phase 1: Complete Configuration-Driven System** 🚧
*Extend current working system with remaining APIs*

#### 1.0 Fix OCR Processing Performance ✅
- [x] **CPU throttling for parallel tesseract processes** - Prevent system overload
- [x] **Global thread pool limiting** - Max 4-6 concurrent tesseract processes
- [x] **CPU usage monitoring** - Throttle when CPU exceeds 80%
- [x] **Sequential photo processing** - One photo at a time with parallel rotations
- [x] **Two-tier image processing** - Small images first, then full-size fallback
- [x] **Code refactoring** - Eliminated duplication in strategy processing
- [x] **Process indicators** - Better user feedback during processing
- [x] **CSV logging system** - Converted from JSON to CSV for better data analysis
- [x] **Environment cleanup** - Removed unused dependencies for leaner setup

#### 1.1 Add Academic Paper APIs
- [ ] **OpenAlex API** (200M+ papers, comprehensive academic metadata)
- [ ] **CrossRef API** (130M+ scholarly works, DOI-based)
- [ ] **PubMed API** (35M+ biomedical papers)
- [ ] **arXiv API** (2M+ preprints, physics/math)

#### 1.2 Enhanced Configuration
- [ ] Split config into `books_metadata_config.yaml` and `papers_metadata_config.yaml`
- [ ] Add hybrid sources (CrossRef handles both books and papers)
- [ ] Implement smart routing logic

### **Phase 2: Unified Metadata System** 🆕
*Implement smart routing and auto-detection with API-only approach*

#### 2.1 Smart Identifier Routing
```python
def search_metadata(identifier):
    """Find best metadata regardless of source type"""
    if identifier.startswith("10."):  # DOI
        return papers_manager.search(identifier)
    elif is_isbn(identifier):  # ISBN
        return books_manager.search(identifier)
    else:
        # Try both and return best result
        return unified_manager.search_all_sources(identifier)
```

#### 2.2 Auto Zotero Type Detection
- [ ] Map metadata source to appropriate Zotero item type
- [ ] Handle edge cases (reports with ISBN+ISSN, conference proceedings)
- [ ] Implement confidence scoring for metadata quality

#### 2.3 Unified Manager Interface
```python
class UnifiedMetadataManager:
    def get_best_metadata(self, identifier):
        """Returns best metadata with auto-determined Zotero type"""
        pass
    
    def search_all_sources(self, query):
        """Search all sources and rank results"""
        pass
```

### **Phase 3: AI-Driven Paper Processing** 🆕
*Enhance paper processing with AI capabilities*

#### 3.1 First Page Processing (Paper Scanning Workflow)
- [ ] OCR/AI processing of first page for paper identification
- [ ] Extract DOI, title, authors, abstract from first page
- [ ] Smart identification strategy (DOI → Title+Authors → Abstract keywords)
- [ ] Handle multiple identification methods with confidence scoring
- [ ] **Hybrid AI approach** - Claude for complex reasoning, Ollama for privacy-sensitive data
- [ ] **Fallback strategy** - Use both AI systems for redundancy and accuracy

#### 3.2 AI-Enhanced OCR
- [ ] LLM-based text correction for OCR errors
- [ ] Context-aware metadata extraction
- [ ] Language detection and processing
- [ ] **Ollama integration** - Local AI for OCR text correction and metadata parsing
- [ ] **Claude integration** - Cloud AI for complex reasoning and high-accuracy extraction

#### 3.3 Smart Annotation Processing
- [ ] AI-powered annotation separation (handwritten notes, highlights)
- [ ] Keyword extraction from annotations
- [ ] Question and note identification

#### 3.4 AI Metadata Enhancement
- [ ] Fill missing metadata fields using AI
- [ ] Validate and correct extracted metadata
- [ ] Suggest tags and categories based on content
- [ ] **Dual AI validation** - Cross-check results between Claude and Ollama
- [ ] **Confidence scoring** - Rate metadata quality from each AI system

### **Phase 4: Paper Scanning Workflow** 📄
*New dedicated workflow for academic papers using Ollama 7B*

#### 4.1 Paper Processing Architecture
- [x] **Create `scripts/process_scanned_papers.py`** - New paper workflow scaffold
- [ ] **Extend existing `DetailedISBNLookupService`** - Add academic paper APIs
- [ ] **Reuse Zotero integration** - Leverage existing `ZoteroAPIBookProcessor` code
- [ ] **Shared utilities** - Common OCR, file management, logging functions

#### 4.2 Ollama 7B Integration
- [ ] **Identifier extraction** - Extract DOI, title, authors, journal, year from first page
- [ ] **OCR text cleaning** - Handle messy OCR output with AI
- [x] **Structured output** - Return JSON with extracted identifiers (scaffold in place)
- [ ] **Fallback strategies** - Multiple extraction approaches if primary fails

#### 4.3 Academic Metadata Lookup
- [ ] **CrossRef API integration** - DOI-based paper lookup
- [ ] **PubMed API integration** - Medical/biological papers
- [ ] **arXiv API integration** - Preprints and technical papers
- [ ] **OpenAlex API integration** - Comprehensive academic database
- [ ] **Smart routing** - Route queries to appropriate APIs based on identifiers

#### 4.4 File Management System
- [ ] **PDF processing** - Extract first page for OCR
- [ ] **File renaming** - `Author_Year_Title.pdf` format
- [ ] **Directory organization** - Store in `g:/publications/` structure
- [ ] **Zotero linking** - Attach renamed files to Zotero items

#### 4.5 Workflow Integration
- [ ] **Separate but similar** - Books and papers use same underlying systems
- [ ] **Configuration sharing** - Reuse existing config system
- [ ] **Logging consistency** - Same CSV logging format
- [ ] **User interface** - Similar interaction patterns

### **Phase 5: Detailed Migration Tasks** 📋
*From archive/AI_CHAT_DOCUMENTS.md - migrate existing hardcoded systems*

#### 5.1 Book Processing Migration
- [ ] **File:** `process_books/scripts/enhanced_isbn_lookup_detailed.py`
  - **Action:** Replace hardcoded national library calls with config-driven manager
  - **Status:** Uses old hardcoded system, needs migration

- [ ] **File:** `process_books/scripts/zotero_api_book_processor_enhanced.py`
  - **Action:** Update to use new unified metadata system
  - **Status:** Uses old hardcoded system, needs migration

- [ ] **File:** `process_books/src/integrations/legacy_zotero_processor.py`
  - **Action:** Update to use new system
  - **Status:** Uses old hardcoded system, needs migration

#### 5.2 Paper Processing Migration
- [ ] **File:** `process_papers/src/core/metadata_extractor.py`
  - **Action:** Complete integration with config-driven system
  - **Status:** Partially updated, needs full migration

#### 5.3 Cleanup Phase
- [ ] **File:** `shared_tools/api/national_libraries.py`
  - **Action:** Delete after migration complete
  - **Status:** Old hardcoded clients, still exists, **VERIFIED UNUSED**
- [ ] **File:** `process_papers/` (entire directory)
  - **Action:** Delete unused paper processing module
  - **Status:** Not used, paper processing planned for Phase 4
- [ ] **File:** `test_isbn_detection.py`
  - **Action:** Delete obsolete test file
  - **Status:** Temporary debugging file, not used
- [ ] **Reference:** See `cleaning_the_codebase_after_verification.md` for detailed cleanup analysis

### **Phase 6: Integration & Testing** 🧪
*End-to-end testing and core functionality validation*

#### 6.1 Comprehensive Testing
- [ ] Test all migration scenarios
- [ ] Validate unified metadata system with edge cases
- [ ] Test AI-driven paper processing
- [ ] Core functionality validation

#### 6.2 Documentation & Cleanup
- [ ] Update all documentation
- [ ] Archive old planning documents
- [ ] Create user guides
- [ ] Basic performance benchmarks

### **Phase 7: Performance Optimization** ⚡
*Local DB integration and performance enhancements*

#### 7.1 Local Zotero Database Integration
- [ ] Investigate Zotero SQLite schema
- [ ] Implement local duplicate detection and metadata lookup
- [ ] Add schema version checking and fallback to API-only mode
- [ ] Background sync management (start, during operations, end)

#### 7.2 Hybrid Lookup + API Approach
- [ ] Implement local DB lookup for performance
- [ ] API-only for all write operations (add/update/delete)
- [ ] User choice presentation based on local data
- [ ] Batch local lookups for multiple items

#### 7.3 Advanced Performance Features
- [ ] Caching strategies for frequently accessed data
- [ ] Optimized sync timing and background operations
- [ ] Performance monitoring and metrics

### **Phase 8: Hybrid Photo Processing** 📸
*Experimental workflow combining book and paper approaches*

#### 8.1 Photo-Based Document Processing
- [ ] **Photo capture** - Take photo of book cover or paper title page
- [ ] **OCR processing** - Extract text from photo
- [ ] **AI analysis** - Use Ollama 7B to determine document type (book vs paper)
- [ ] **Smart routing** - Route to appropriate workflow based on AI analysis
- [ ] **Metadata extraction** - Extract identifiers using appropriate method

#### 8.2 Hybrid Workflow Logic
```python
def process_document_photo(photo_path):
    """Process photo to determine document type and extract metadata"""
    # 1. OCR the photo
    ocr_text = extract_ocr_from_photo(photo_path)
    
    # 2. Use AI to determine document type
    doc_type = ollama_analyze_document_type(ocr_text)
    
    # 3. Route to appropriate workflow
    if doc_type == "book":
        return process_as_book(ocr_text)
    elif doc_type == "paper":
        return process_as_paper(ocr_text)
    else:
        return manual_classification(ocr_text)
```

#### 8.3 Implementation Considerations
- [ ] **Accuracy assessment** - Evaluate AI's ability to distinguish document types
- [ ] **Fallback handling** - Manual classification when AI is uncertain
- [ ] **User interface** - Clear indication of detected document type
- [ ] **Performance impact** - Additional AI processing time
- [ ] **Value proposition** - Determine if complexity is worth the convenience

## Technical Architecture

### **Unified Metadata System Design**
```
┌─────────────────────────────────────────────────────────┐
│                UnifiedMetadataManager                   │
├─────────────────────────────────────────────────────────┤
│  Smart Routing Logic                                   │
│  ├── DOI → Papers Manager                              │
│  ├── ISBN → Books Manager                              │
│  └── Unknown → Try Both, Return Best                   │
├─────────────────────────────────────────────────────────┤
│  Books Manager          │  Papers Manager              │
│  ├── OpenLibrary        │  ├── OpenAlex                │
│  ├── Google Books       │  ├── CrossRef                 │
│  ├── National Libraries │  ├── PubMed                   │
│  └── Hybrid Sources     │  └── arXiv                    │
├─────────────────────────────────────────────────────────┤
│  Auto Zotero Type Detection                            │
│  ├── Book → "book"                                     │
│  ├── Report → "report"                                 │
│  ├── Journal Article → "journalArticle"                │
│  └── Conference Paper → "conferencePaper"              │
└─────────────────────────────────────────────────────────┘
```

### **AI-Driven Paper Processing**
```
┌─────────────────────────────────────────────────────────┐
│                AI-Enhanced Paper Pipeline               │
├─────────────────────────────────────────────────────────┤
│  Scan → OCR → AI Correction → Metadata Extraction      │
│   ↓      ↓        ↓              ↓                     │
│  PDF   Text    Clean Text    Enhanced Metadata         │
│   ↓      ↓        ↓              ↓                     │
│  Annotations → AI Analysis → Keywords/Questions        │
└─────────────────────────────────────────────────────────┘
```

### **Paper Scanning Workflow Architecture**
```
┌─────────────────────────────────────────────────────────┐
│                Paper Processing Pipeline                │
├─────────────────────────────────────────────────────────┤
│  PDF → First Page OCR → Ollama 7B → Identifier Extraction │
│   ↓           ↓              ↓              ↓             │
│  File    Raw Text      Clean Text    DOI/Title/Authors   │
│   ↓           ↓              ↓              ↓             │
│  Storage  AI Analysis   Structured    Academic APIs      │
│   ↓           ↓              ↓              ↓             │
│  Zotero  Document Type  JSON Output   Metadata Lookup    │
└─────────────────────────────────────────────────────────┘
```

### **Hybrid AI Architecture**
```
┌─────────────────────────────────────────────────────────┐
│                Dual AI Processing System               │
├─────────────────────────────────────────────────────────┤
│  OCR Text → Routing Logic → AI Processing               │
│     ↓           ↓              ↓                         │
│  Raw Text  Sensitive?    Claude (Cloud)                │
│     ↓           ↓              ↓                         │
│  Clean Text  Public?     Ollama (Local)                │
│     ↓           ↓              ↓                         │
│  Metadata ← Cross-Validation ← Results                 │
└─────────────────────────────────────────────────────────┘
```

## Success Metrics

### **Configuration-Driven System**
- [ ] All 4 academic APIs integrated and tested
- [ ] Smart routing handles 95%+ of identifier types correctly
- [ ] Auto Zotero type detection 90%+ accurate

### **AI-Driven Processing**
- [ ] OCR accuracy improved by 20%+ with AI correction
- [ ] Metadata completeness 85%+ for academic papers
- [ ] Annotation separation 90%+ accurate

### **Migration Success**
- [ ] All hardcoded systems replaced with config-driven
- [ ] No functionality lost during migration
- [ ] Performance maintained or improved

## Implementation Priority

### **Immediate (Next Session)**
1. **Install and configure Ollama** - Local AI for privacy-sensitive processing
2. **Add OpenAlex API** - Start with academic paper sources
3. **Design unified metadata system** - Smart routing architecture
4. **Test unified approach** - Validate with edge cases
5. **Migrate existing hardcoded systems** - Replace old book processing scripts

### **Short Term (1-2 Sessions)**
1. Complete academic APIs (CrossRef, PubMed, arXiv)
2. Implement unified metadata manager
3. Start book processing migration
4. **Begin paper scanning workflow** - Create `process_scanned_papers.py`

### **Medium Term (3-4 Sessions)**
1. Complete all migration tasks
2. Implement AI-driven paper processing
3. Comprehensive testing and core functionality validation
4. **Complete paper scanning workflow** - Full integration with Zotero

### **Long Term (5+ Sessions)**
1. Local DB performance optimization
2. Advanced AI features
3. User interface and documentation
4. **Hybrid photo processing** - Experimental workflow evaluation

## Key Decisions Needed

1. **Config Structure**: Separate configs vs unified with sections?
2. **AI Integration**: Local LLM vs API-based?
3. **Migration Strategy**: Big bang vs incremental?
4. **Priority Order**: Academic APIs first vs unified system first?
5. **Performance Optimization**: When to implement local DB integration (Phase 6)?
6. **GPU OCR Optimization**: When to implement Intel OpenVINO for GPU-accelerated OCR?
7. **Paper Workflow**: Ollama 7B vs cloud AI for identifier extraction?
8. **Hybrid Processing**: Is photo-based document classification worth the complexity?

## Completed Features & Current Capabilities

### **Book Processing System** ✅
*Fully functional with advanced features*

#### Core Functionality
- **ISBN Extraction**: Barcode detection (pyzbar) + OCR processing (Tesseract)
- **Smart Image Processing**: SmartIntegratedProcessorV3 with Intel GPU optimization
- **Multi-Strategy OCR**: 8+ different preprocessing strategies with intelligent fallback
- **Batch Processing**: Handles multiple photos with intelligent crop detection
- **Success Tracking**: Moves successful photos to `done/`, failed to `failed/`

#### ISBN Processing Pipeline
- **Barcode Detection**: 0.6 seconds average, 95% success rate
- **OCR Processing**: 60-120 seconds with multiple strategies
- **ISBN Validation**: Enhanced regex patterns with ISBN-10/ISBN-13 conversion
- **CSV Logging**: Comprehensive logging to `data/books/book_processing_log.csv`

#### Metadata Lookup System
- **OpenLibrary API**: Books with detailed metadata, subjects, excerpts
- **Google Books API**: Additional book information, categories
- **Norwegian National Library API**: Norwegian-specific books, content classes
- **Smart Scoring**: Combines results from all sources, picks best match
- **Tag Integration**: Merges metadata tags from all sources

#### Zotero Integration
- **Multi-Digit Input System**: Combine actions like `17` (group1 tags + update metadata)
- **Configurable Tag Groups**: group1, group2, group3 from config files
- **Smart Item Handling**: Different workflows for existing vs new items
- **Duplicate Detection**: Searches existing library, shows duplicates found
- **Interactive Menu**: Enhanced menu with action descriptions and differences
- **Metadata Comparison**: Shows differences between Zotero and online data
- **Tag Management**: Add/remove tags, combine with metadata tags
- **Item Updates**: Update author, title, or all metadata fields
- **Item Removal**: Delete items with confirmation

#### Configuration System
- **Two-Tier Config**: `config.conf` (public) + `config.personal.conf` (private)
- **Tag Groups**: Configurable tag groups for different purposes
- **Action Definitions**: Configurable actions with descriptions
- **Menu Options**: Configurable display options
- **API Credentials**: Secure Zotero API key management

#### File Management
- **Photo Organization**: Automatic sorting into `done/` and `failed/` folders
- **CSV Logging**: Standardized logging format for analysis
- **Error Handling**: Comprehensive error logging and retry logic
- **Path Management**: Relative paths for portability

### **Shared Tools & Infrastructure** ✅
*Common utilities and services used across the system*

#### ISBN Matching System
- **ISBNMatcher Class**: Centralized ISBN utilities in `shared_tools/utils/isbn_matcher.py`
- **Normalization**: Converts ISBN-10 to ISBN-13, handles various formats
- **Extraction**: Extracts clean ISBN from text with additional info like "(pbk.)"
- **Validation**: Validates ISBN checksums and formats
- **Matching**: Enhanced matching with substring approach and format conversion

#### Configuration Management
- **ConfigParser Integration**: Loads from multiple config files with override logic
- **Personal Overrides**: `config.personal.conf` overrides `config.conf` settings
- **Section Support**: TAG_GROUPS, ACTIONS, MENU_OPTIONS, APIS sections
- **Error Handling**: Graceful fallback when config sections missing

#### Data Structure
- **Centralized Data Directory**: Single `data/` directory with organized subfolders
- **CSV Logging**: Converted from JSON to CSV for better analysis
- **Standardized Fields**: filename, status, isbn, method, confidence, attempts, processing_time, retry_count, timestamp, error
- **Zotero Fields**: Extended with zotero_decision, zotero_item_key, zotero_action_taken, zotero_timestamp

#### API Integration
- **Zotero API**: Full CRUD operations (create, read, update, delete)
- **Rate Limiting**: Built-in delays to respect API limits
- **Error Handling**: Comprehensive error handling with user feedback
- **Library Support**: Both user and group libraries supported

### **Development Infrastructure** ✅
*Tools and processes for development and maintenance*

#### Environment Setup
- **Conda Environment**: `research-tools` environment with all dependencies
- **Intel GPU Optimization**: OpenVINO integration for image preprocessing
- **CPU Throttling**: Global thread pool manager prevents system overload
- **Dependency Management**: Cleaned up unused dependencies (EasyOCR, PaddleOCR, PyMuPDF)

#### Testing & Debugging
- **Debug Mode**: Environment variable `DEBUG=1` for verbose output
- **Process Indicators**: Real-time feedback during processing
- **Error Logging**: Comprehensive error tracking and reporting
- **Success Metrics**: Performance tracking and success rate monitoring

#### Code Quality
- **Modular Design**: Shared utilities and common functions
- **Error Handling**: Graceful failure with detailed error messages
- **Code Refactoring**: Eliminated duplication, improved maintainability
- **Documentation**: Inline comments and docstrings throughout

### **Current Scripts & Functionality** ✅
*Working scripts and their specific capabilities*

#### `scripts/find_isbn_from_photos.py`
- **Purpose**: Extract ISBNs from book photos using barcode detection and OCR
- **Input**: Photos in `/mnt/i/FraMobil/Camera/Books/`
- **Output**: CSV log with ISBNs and processing details
- **Features**: 
  - SmartIntegratedProcessorV3 with Intel GPU optimization
  - 6 OCR preprocessing strategies with fallback
  - Automatic photo organization (done/failed folders)
  - Comprehensive error logging and retry logic

#### `scripts/add_or_remove_books_zotero.py`
- **Purpose**: Interactive Zotero integration for processed ISBNs
- **Input**: ISBNs from `data/books/book_processing_log.csv`
- **Output**: Books added to Zotero with rich metadata
- **Features**:
  - Multi-digit input system (e.g., `17` for group1 tags + update metadata)
  - Configurable tag groups (group1, group2, group3)
  - Smart item handling (existing vs new items)
  - Duplicate detection and management
  - Metadata comparison and updates
  - Interactive menu with action descriptions

#### `scripts/manual_isbn_metadata_search.py`
- **Purpose**: Manual ISBN lookup and metadata search
- **Input**: Single ISBN from user input
- **Output**: Detailed metadata from multiple sources
- **Features**:
  - Interactive ISBN input and validation
  - Multi-source metadata lookup (OpenLibrary, Google Books, Norwegian Library)
  - Rich metadata display with tags and abstracts
  - Zotero integration for adding items

#### `shared_tools/utils/isbn_matcher.py`
- **Purpose**: Centralized ISBN utilities and matching
- **Features**:
  - ISBN normalization (ISBN-10 ↔ ISBN-13)
  - Clean ISBN extraction from complex text
  - ISBN validation with checksum verification
  - Enhanced matching with format conversion
  - Substring matching for partial ISBNs

### **Data Files & Logs** ✅
*Current data structure and logging system*

#### `data/books/book_processing_log.csv`
- **Purpose**: Central log for all book processing activities
- **Fields**: filename, status, isbn, method, confidence, attempts, processing_time, retry_count, timestamp, error, zotero_decision, zotero_item_key, zotero_action_taken, zotero_timestamp
- **Usage**: Tracks processing history and Zotero decisions

#### `data/logs/`
- **Purpose**: Application logs for debugging and monitoring
- **Content**: Processing logs, error logs, performance metrics
- **Rotation**: Year-based log rotation for easy management

#### `config.conf` & `config.personal.conf`
- **Purpose**: Configuration management with personal overrides
- **Sections**: TAG_GROUPS, ACTIONS, MENU_OPTIONS, APIS
- **Security**: Personal config not committed to GitHub

### **OCR Processing Improvements** ✅
- **CPU Throttling**: Implemented global thread pool manager with CPU monitoring
- **Two-Tier Processing**: Small images (25% size) processed first, then full-size fallback
- **Code Refactoring**: Eliminated 40+ lines of duplicated strategy processing code
- **File Management**: Smart retry system with permanently_failed category after 3 attempts
- **Process Indicators**: Better user feedback showing progress through strategies

### **Project Structure** ✅
- **Centralized Directories**: All scripts in `scripts/`, all data in `data/`
- **Configuration Management**: Centralized config files with CPU throttling settings
- **Environment Setup**: Intel GPU optimizations for OpenCV preprocessing
- **CSV Logging**: Converted from JSON to CSV for better data analysis and reporting
- **Environment Cleanup**: Removed unused dependencies (EasyOCR, PaddleOCR, PyMuPDF, etc.)

### **Data Management** ✅
- **CSV Logging**: Converted from JSON to CSV for better data analysis
- **Benefits**: Easy Excel/Google Sheets analysis, better reporting, smaller file sizes
- **Structure**: Standardized fields (filename, status, isbn, method, confidence, attempts, processing_time, retry_count, timestamp, error)
- **Compatibility**: Maintains same data structure for existing scripts
- **Data Structure Cleanup**: Consolidated all scattered data directories and logs
- **Legacy Data Migration**: Successfully migrated 66 book records and 25+ log files from scanpapers
- **Centralized Structure**: Single data/ directory with organized subfolders for books/, papers/, logs/, cache/, output/, temp/

### **GPU Optimization Research** 📋
- **Documentation Created**: `gpu-optimization-suggestions.md` with 5 different approaches
- **Intel OpenVINO**: Recommended approach for true GPU acceleration
- **Current Status**: Intel GPU used for image preprocessing, OCR still CPU-bound
- **Future Enhancement**: Ready for implementation when needed

### **Zotero Deduplicator Tool** 🔧
- **Current Status**: Duplicate detection implemented in enhanced Zotero processor
- **Features Implemented**:
  - Multiple search approaches (ISBN field, general search, normalized search)
  - Duplicate detection and logging during processing
  - Summary display of found duplicates
  - Zotero item codes saved for deletion
- **Future Implementation Needed**:
  - Standalone deduplicator script
  - Interactive duplicate resolution interface
  - **Merge information from duplicates** (combine tags, metadata, notes from all copies)
  - Merge/delete duplicate items functionality
  - Batch processing of duplicate lists
  - Integration with Zotero API for safe removal

### **Ollama Installation and Configuration** 🤖
- **Installation Commands**:
  ```bash
  # Install Ollama
  curl -fsSL https://ollama.ai/install.sh | sh
  
  # Pull useful models
  ollama pull llama2:7b        # General purpose AI
  ollama pull codellama:7b      # Code assistance
  ollama pull mistral:7b        # Alternative general model
  
  # Test installation
  ollama run llama2:7b "Hello, how are you?"
  ```
- **GPU Configuration** (Intel UHD Graphics 630):
  ```bash
  # Enable Intel GPU acceleration
  export OLLAMA_GPU_LAYERS=1
  export OLLAMA_GPU_MEMORY_FRACTION=0.5
  
  # Test GPU acceleration
  ollama run llama2:7b "Test GPU performance"
  ```
- **Integration with Research-Tools**:
  - Privacy-sensitive PDF processing
  - Offline metadata extraction
  - Fallback AI system for redundancy
  - Local processing for confidential research data

---

*This plan combines the detailed migration tasks from archive/AI_CHAT_DOCUMENTS.md with the unified metadata system design, AI-driven paper processing enhancement, and the new paper scanning workflow using Ollama 7B.*
