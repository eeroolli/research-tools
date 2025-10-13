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

### 🚧 **In Progress:**
- Smart preprocessing and evidence-based classification for Ollama optimization
- Sample testing and validation (20 PDFs per type)
- Document profiler implementation

### ❌ **Not Completed:**
- Detailed migration tasks from `archive/AI_CHAT_DOCUMENTS.md` (Phases 2-4)
- Unified metadata system with smart routing
- Academic paper APIs (OpenAlex, PubMed) - CrossRef and arXiv completed ✅
- Smart preprocessing Phase C-E implementation

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

#### 0.0 Ollama Installation and Setup ✅
- [x] **Install Ollama** - Local AI for privacy-sensitive processing (v0.12.3)
- [x] **Configure models** - llama2:7b installed and tested
- [x] **Environment setup** - CPU-based (Intel GPU has limited LLM support)
- [x] **Integration testing** - Verified Ollama works, discovered hallucination issues
- [x] **Smart workflow** - Created optimized extraction: regex → API → Ollama fallback (60-100x faster for papers with DOI)

#### 0.1 Consolidate Data Directories ✅
- [x] **Remove duplicate data directories** - process_books/data/, process_papers/data/, scripts/data/
- [x] **Consolidate all logs** - Move scattered logs to data/logs/
- [x] **Update code references** - Fix hardcoded paths to old data directories
- [x] **Test functionality** - Ensure all scripts work with new structure
- [x] **Migrate legacy data** - Copied 66 book records + 25+ log files from scanpapers
- [x] **Convert legacy data** - JSON to CSV conversion for compatibility

#### 0.2 Smart Paper Processing System ✅
*Optimized paper metadata extraction with validation*

- [x] **Identifier Extraction** - Fast regex-based DOI/ISSN/ISBN/**arXiv ID**/URL extraction (1-2 seconds)
- [x] **Identifier Validation** - ISSN/ISBN checksum validation, DOI/arXiv/URL format validation, hallucination detection
- [x] **CrossRef API Client** - Full Zotero fields: title, authors, journal, volume, issue, pages, abstract, tags
- [x] **arXiv API Client** - Preprint metadata with categories, abstracts, DOI of published versions
- [x] **Ollama Integration** - Fallback AI for papers without identifiers (with validation and hallucination detection)
- [x] **Smart Workflow** - Priority: DOI → arXiv → ISBN → URL/Ollama → Nothing/Ollama
- [x] **Testing Framework** - pytest with 25 unit tests for validation
- [x] **Performance** - 60-100x faster for papers with DOIs/arXiv IDs (1s vs 120-180s)
- [x] **Code Organization** - Prototypes in `scripts/prototypes/`, production in `shared_tools/`, analysis in `scripts/analysis/`
- [x] **Configuration Management** - CrossRef email in config files (polite pool), auto-activation of conda environment
- [x] **Context-Aware Prompts** - Comprehensive Ollama prompts with international date formats, multilingual support
- [x] **Book Chapter Support** - Extracts chapter + book metadata, uses repeating headers as valuable clues
- [x] **User-Facing Script** - `scripts/process_scanned_papers.py` with done/failed directories and CSV logging

#### 0.3 Evidence-Based Document Classification 🔬
*Intelligent preprocessing and classification for Ollama optimization*

##### Current Approach (Implemented):
- Regex finds identifiers (DOI, ISBN, URL)
- If found → Fast API lookup (1-2s)
- If not found → Ollama fallback (120-180s)

##### Optimization Strategy (Planned):
**Problem**: Ollama searches for identifiers we know don't exist, wastes time/effort

**Solution**: Preprocessing + targeted prompts based on document characteristics

**Phase A: Evidence-Based Analysis** ✅
- [x] **Analyze existing collection** - 17,490 Zotero items analyzed in 40 seconds
- [x] **Extract patterns** - Discovered clear patterns by document type:
  * **Journal articles**: 32.3% have DOI, 87.4% have pages field (1,600 items)
  * **Book chapters**: 0% have DOI, 81.7% have pages field (1,052 items) 
  * **Newspaper articles**: 50% have URL, 54.8% have PDFs (42 items)
  * **Reports**: 56.8% have pages field, 38.2% have PDFs (838 items)
  * **Thesis**: 12.2% have PDFs (188 items)
- [x] **Discovered orphaned PDFs** - Only 11 out of 1,950 attachments (well-organized library!)
- [ ] **Build classifier rules** - Evidence-based heuristics from discovered data

**Phase B: Test Smaller Model**
- [ ] **Install llama3.2:3b** - 3x faster for simple classification
- [ ] **Compare performance** - Classification speed/accuracy vs llama2:7b
- [ ] **Decide on model** - Speed vs accuracy tradeoff

**Phase C: Smart Preprocessing**
- [ ] **Document profiling** - Extract metadata before Ollama:
  * Page count
  * Word count
  * Has URL? (from regex)
  * Has identifiers? (from regex)
  * Text patterns (Chapter, Abstract, Submitted, etc.)
  * Language detection
  * Repeating text detection (headers/footers)
- [ ] **Classification hints** - Pass to Ollama:
  * "Likely NEWS ARTICLE (2 pages, URL found, no DOI/ISBN)"
  * "Likely BOOK CHAPTER (15 pages, repeating headers, no identifiers)"
  * "Likely REPORT (45 pages, no URL, no identifiers)"
- [ ] **Targeted prompts** - Don't ask Ollama for what can't exist:
  * News articles: Skip DOI/ISBN search, focus on "By [Author]" pattern
  * Book chapters: Skip DOI/URL, focus on chapter+book metadata, use headers
  * Reports: Skip URL, focus on organization, report number, ISSN

**Phase D: Multi-Page Extraction**
- [ ] **Extract 2-3 pages** - Makes repeating headers obvious
- [ ] **Pattern detection** - Identify what repeats (book title vs chapter title)
- [ ] **Better context** - More data for Ollama to work with

**Phase E: Iterative Testing & Validation**
- [ ] **Move orphaned PDFs** - 11 PDFs from Zotero to scanner for testing
- [ ] **Random sampling** - Select 20 random PDFs per document type from existing collection
- [ ] **Process sample** - Run smart workflow on samples (~400 PDFs total)
- [ ] **Quality validation** - Compare extracted metadata vs Zotero metadata
  * Measure accuracy: title match, author match, year match, type detection
  * Identify systematic errors and hallucinations
  * Calculate success rates by document type
- [ ] **Iterate improvements** - Fix issues, refine prompts, adjust rules
- [ ] **Scale testing** - Once quality is good, test with 100 per type
- [ ] **Production readiness** - Deploy when accuracy > 90% on sample

**Phase F: Metadata Enrichment** (Future)
- [ ] **Enrich existing Zotero items** - Add missing abstracts, keywords, tags
- [ ] **Batch processing** - Process items with incomplete metadata
- [ ] **Quality improvement** - Fill gaps in existing collection
- [ ] **Smart updates** - Only update if new data is higher quality

**Expected Results:**
- Faster Ollama processing (60-90s vs 120-180s)
- Higher accuracy (focused extraction)
- Better book chapter handling (headers used correctly)
- Validated quality through comparison with known data
- Scalable to commercial use (evidence-based, not guesswork)

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
- [x] **CrossRef API** (130M+ scholarly works, DOI-based) - ✅ Implemented with full Zotero fields
- [ ] **PubMed API** (35M+ biomedical papers)
- [x] **arXiv API** (2M+ preprints, physics/math) - ✅ Implemented with categories and abstracts

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


### **Phase 4: Paper Scanning Workflow** 🚧
*New dedicated workflow for academic papers - DETAILED SPECIFICATION COMPLETE*

**Status:** 🚧 **Ready for Implementation** - Detailed specification in `daemon_implementation_spec.md`

**Architecture Decision:** Daemon-based real-time processing triggered by Epson scanner

#### 4.1 Paper Processing Architecture ✅
- [x] **Architecture designed** - File-watching daemon with smart launcher
- [x] **Folder structure defined** - `I:\FraScanner\papers\` with done/failed subdirectories
- [x] **Integration points identified** - Reuses existing `PaperMetadataProcessor` and config system
- [x] **Shared utilities planned** - Common OCR, file management, logging functions
- [ ] **Implementation in progress** - See `daemon_implementation_spec.md` for details

#### 4.2 Daemon System Design ✅
- [x] **Smart launcher** - `scripts/start_paper_processor.py` (idempotent, Epson-triggered)
- [x] **File watcher daemon** - `scripts/paper_processor_daemon.py` (watchdog-based)
- [x] **Clean shutdown** - `scripts/stop_paper_processor.py` (signal handling)
- [x] **PID management** - Process tracking and stale file cleanup
- [x] **Implementation complete** - All daemon components implemented (Oct 11, 2025)

#### 4.3 Zotero Integration for Papers ✅
- [x] **Zotero processor designed** - `shared_tools/zotero/paper_processor.py`
- [x] **Duplicate detection** - By DOI and title similarity
- [x] **Item type detection** - Journal article, conference paper, book chapter, etc.
- [x] **PDF linking** - Linked files to `G:\my Drive\publications\`
- [x] **Metadata mapping** - Our format → Zotero format
- [x] **API integration complete** - paper_processor.py implemented (Oct 11, 2025)
- [x] **Local DB search complete** - local_search.py for fast fuzzy matching (Oct 11, 2025)
- [x] **Dual access pattern** - Read from local DB, write through API

#### 4.4 File Management System ✅
- [x] **PDF processing** - Extract first page for metadata (reuses existing code)
- [x] **File renaming** - `Author_Year_Title.pdf` format (implemented in process_scanned_papers.py)
- [x] **Directory organization** - Store in `G:\my Drive\publications\` (single folder for now)
- [x] **Original preservation** - Move to `done/` folder with scanner filename
- [ ] **Extraction to shared module** - Move common functions to `shared_tools/papers/file_manager.py`

#### 4.5 Workflow Integration 🚧
- [x] **Separate workflows** - Books and papers use same underlying systems but different entry points
- [x] **Configuration sharing** - Reuse existing config system (config.personal.conf)
- [x] **Logging consistency** - Extend CSV logging with Zotero fields
- [ ] **Scanner integration** - Epson buttons to be configured for NO/EN/DE languages
- [x] **Conference detection** - conference_detector.py for presentations (Oct 11, 2025)
- [ ] **Interactive menu** - PENDING: Add to process_scanned_papers.py (NEXT SESSION)
- [ ] **Testing** - End-to-end testing with real scanner

#### 4.6 User Workflow (Target) ✅
```
1. Press Epson scanner button (NO/EN/DE)
2. Scanner saves PDF to I:\FraScanner\papers\
3. Scanner triggers start_paper_processor.py
4. Daemon processes automatically (5-130 seconds depending on identifiers)
5. ✅ INTERACTIVE MENU: User reviews and approves actions
6. Execute approved actions
7. Ready for next scan
```

**Target timing:** 5-10 seconds for papers with DOI/arXiv, 65-130 seconds for papers needing Ollama

#### 4.7 Interactive Menu System ✅ ENHANCED
**Status:** 🚧 **In Progress** - Universal metadata display system implemented (Oct 13, 2025)

- ✅ **Universal Metadata Display**: Smart field grouping and intelligent formatting for any document type
- ✅ **Document Type Awareness**: Shows relevant fields for journal articles, book chapters, conference papers, books, legal docs, etc.
- ✅ **Metadata Source Flexibility**: Works with Zotero local, CrossRef API, arXiv, national libraries, OCR extraction, manual entry
- ✅ **Future-Proof Design**: Automatically displays new fields without code changes
- ✅ **Enhanced User Experience**: Grouped, formatted, intelligent display with proper field labeling
- 🚧 **Interactive Menu**: Menu system with user choices (use as-is, edit, search Zotero, skip, manual processing)
- 🚧 **Failed Extraction Workflow**: Guided manual metadata entry for failed extractions
- 🚧 **Metadata Editing**: Interactive field editing with current value display

**Next steps:**
1. Review `daemon_implementation_spec.md`
2. Implement in Cursor (estimated 2-3 hours)
3. Test with sample PDFs
4. Configure Epson scanner
5. Process first papers from backlog!


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
