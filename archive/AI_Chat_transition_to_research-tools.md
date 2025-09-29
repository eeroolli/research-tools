# AI Chat: Transition to Research-Tools

**Date:** September 2025  
**Purpose:** Comprehensive plan for transitioning existing projects to organized research-tools structure  
**Status:** 🚧 IN PROGRESS - Basic structure created, configuration-driven national library system implemented

## Current State Analysis

### 🚧 **PARTIAL TRANSITION COMPLETED**
- **scanpapers** → **process_books** - Basic structure created, functionality partially migrated
- **sshphone** - Photo transfer from Android phone to computer (separate project)
- **research-tools** - Basic organized structure implemented
- **Configuration-driven national library system** - New architecture implemented and tested

### 🚧 **Current Structure (Partially Implemented)**
```
/mnt/f/prog/research-tools/
├── shared_tools/                    # 🚧 Common utilities and infrastructure
│   ├── api/                         # ✅ Configuration-driven national library system
│   │   ├── national_library_config.yaml  # ✅ YAML config for all libraries
│   │   ├── config_driven_client.py       # ✅ Generic client using config
│   │   ├── config_driven_manager.py      # ✅ Manager for all libraries
│   │   └── base_client.py               # ✅ Base API client class
│   ├── metadata/                    # 🚧 Unified metadata extraction (basic)
│   ├── config/                      # ✅ Centralized configuration
│   └── utils/                       # ✅ ISBN matcher and utilities
├── process_books/                   # 🚧 Book processing (basic structure)
│   ├── src/                         # 🚧 Source code (copied, needs integration)
│   ├── scripts/                     # 🚧 Processing scripts (copied, needs updates)
│   └── config/                      # ✅ Book-specific configuration
├── process_papers/                  # 🚧 Paper processing framework
│   ├── src/                         # 🚧 OCR, metadata extraction (basic framework)
│   ├── scripts/                     # 🚧 Processing scripts (placeholder)
│   └── config/                      # ✅ Paper-specific configuration
├── config.conf                      # ✅ Main project configuration
├── environment.yml                  # ✅ Conda environment with Intel GPU optimization
└── test_integration.py              # ✅ Integration testing
```

### 🎯 **Two Parallel Work Streams:**
```
1. Continue research-tools transition (original plan)
   - Complete functionality migration from scanpapers
   - Implement missing components
   - Full integration testing

2. Configuration-driven national library migration (new)
   - Migrate existing hardcoded national library code to new system
   - See MIGRATION_PLAN.md for detailed strategy
```

## Detailed Component Design

### process_papers (Academic Paper Processing)
**Complete scan-to-Zotero pipeline based on scan workflow:**

1. **Epson Document Pro Integration**
   - High-resolution color scanning
   - Batch processing capabilities
   - Quality optimization

2. **Language Detection and Organization**
   - Config file for language prefixes (EN, DE, NO, FI, SE)
   - Automatic file naming with language prefix
   - Save to `\documents\scan` with language prefix

3. **Academic Metadata Extraction**
   - DOI, ISSN, Title, Journal, Author, Date, Pages
   - Multiple extraction strategies (OCR, API lookup)
   - AI-enhanced extraction for incomplete data

4. **Library Database Supplementation**
   - **OpenAlex API** (comprehensive academic metadata - 200M+ papers)
   - **CrossRef API** (DOI-based publisher data - 130M+ scholarly works)
   - **PubMed API** (medical/biological papers - 35M+ biomedical papers)
   - **arXiv API** (preprints and physics/math - 2M+ preprints)
   - **National Libraries** (Norwegian, Swedish, Finnish for regional books)
   - **OpenLibrary** (comprehensive book metadata - 25M+ books)
   - **Google Books** (recent publications and previews)

5. **Annotation Separation**
   - Colored pen markings detection
   - Underlinings and comments extraction
   - Color marker keyword identification
   - Questions and notes separation
   - Save annotations separately from main text

6. **PDF Optimization**
   - PDF/A conversion for archival quality
   - Significant size reduction
   - Quality preservation

7. **Zotero Integration**
   - Duplicate checking (signature detection in top-right corner)
   - PDF linking and storage. If there exists a PDF in zotero, that is probably 
     downloaded from a journal, and is of better quality than a scan of a a paper copy. Use the best one.
   - Annotation storage and linking. 
   - Is it possible to add annotation from paper version to a official journal version?
   - Metadata supplementation

8. **Folder Metadata Processing**
   - Keywords and tags from paper folders
   - Questions and notes from folders
   - Manual input during Zotero import (decision needed)

### process_books (Book Processing)
**Enhanced with international metadata sources:**

1. **ISBN Extraction**
   - Photo-based ISBN detection
   - Barcode scanning with pyzbar
   - OCR-based ISBN extraction
   - Multiple preprocessing strategies

2. **Comprehensive Book Metadata Lookup**
   - **OpenLibrary API** (primary - 25M+ books, comprehensive metadata)
   - **Google Books API** (secondary - recent publications, previews)
   - **National Libraries** (Norwegian, Swedish, Finnish for regional books)
   - **Fallback chain** for incomplete data

3. **Zotero Book Integration**
   - Rich metadata import
   - Duplicate checking
   - Smart tag management
   - ISBN-10/ISBN-13 conversion

### shared-tools (Common Utilities)
**Unified infrastructure for both papers and books:**

1. **Unified Metadata Component**
   ```python
   class MetadataExtractor:
       def extract_paper_metadata(self, doi=None, title=None, authors=None)
       def extract_book_metadata(self, isbn=None, title=None, authors=None)
       def enhance_with_ai(self, partial_metadata, document_type)
   ```

2. **API Clients**
   - Zotero API client (unified for papers and books)
   - **Academic metadata APIs**: OpenAlex, CrossRef, PubMed, arXiv
   - **Book metadata APIs**: OpenLibrary (primary), Google Books (secondary), National Libraries
   - Rate limiting and error handling
   - Caching to avoid repeated calls
   - utils.isbn_matcher.py 

3. **OCR and Image Processing**
   - Tesseract, EasyOCR, PaddleOCR
   - OpenCV with Intel GPU optimization
   - Image preprocessing and enhancement
   - Batch processing capabilities

4. **PDF Processing**
   - PyPDF2, pdfplumber
   - PDF/A conversion
   - Size optimization
   - Annotation extraction and separation

5. **AI Enhancement Layer**
   - LLM-based metadata extraction
   - Metadata validation and completion
   - Language detection (EN, DE, NO, FI, SE)
   - Citation parsing and normalization

6. **Configuration Management**
   - API keys and endpoints
   - Scan folder preferences
   - Language detection settings
   - Processing parameters

7. **File Organization**
   - Batch processing utilities
   - File naming conventions
   - Directory structure management
   - Logging and tracking

8. **Database Utilities**
   - SQLite for processing logs
   - Hash tracking for duplicates
   - Processing history

## Migration Plan

### Phase 1: Repository Setup
- [x] Analyze current project structure
- [x] Clone isbn-book-processor repository to /mnt/f/prog/
- [x] Create research-tools workspace configuration
- [ ] Verify existing research-tools content

### Phase 2: Shared Components
- [x] Create unified metadata extractor (basic framework)
- [x] Create ISBN matcher utility
- [x] Implement configuration-driven API clients for national libraries
- [ ] Set up AI enhancement layer framework
- [x] Create configuration management system
- [ ] Build file organization utilities

### Phase 3: Process-Papers Migration
- [x] Move academic paper processing from scanpapers (basic structure)
- [ ] Implement OCR engine with annotation preservation
- [ ] Add language detection and prefixing
- [ ] Create annotation separation system framework
- [ ] Build PDF optimization pipeline
- [x] Integrate with shared metadata component (basic)

### Phase 4: Process-Books Migration
- [x] Move book processing from scanpapers (basic structure)
- [ ] Integrate isbn-book-processor content
- [ ] Add international metadata sources
- [ ] Use ISBN to select the right country and metadata source
- [ ] Enhance Zotero integration
- [x] Connect to shared metadata component (basic)

### Phase 5: Integration and Testing
- [x] Test basic components in new structure
- [x] Verify configuration-driven national library system
- [ ] Test AI enhancement capabilities
- [ ] Validate Zotero integration
- [ ] Performance optimization

### Phase 6: Documentation and Cleanup
- [x] Create basic documentation
- [x] Update configuration files
- [ ] Create user guides
- [ ] Clean up old directories

## 🎯 **NEW PHASE: Configuration-Driven National Library Migration**

### **Current Status:**
- ✅ Configuration-driven architecture implemented and tested
- ✅ Norwegian National Library API working (1M+ results)
- ✅ All 6/6 integration tests passing
- ✅ YAML configuration system functional

### **Next Tasks (See MIGRATION_PLAN.md):**
- [ ] **Phase 1:** Migrate shared components to config-driven system
- [ ] **Phase 2:** Migrate book processing scripts to new system
- [ ] **Phase 3:** Migrate paper processing to new system
- [ ] **Phase 4:** Cleanup old hardcoded system

## Key Technical Decisions

### ✅ **Configuration-Driven National Library Architecture**
1. **YAML-based configuration**: Single file defines all library APIs
2. **Generic client approach**: One client handles all libraries dynamically
3. **Field mapping system**: Flexible mapping for different API structures
4. **Country/language/ISBN prefix mapping**: Automatic library selection
5. **No hardcoded endpoints**: All API details in configuration

### ✅ **AI Integration Strategy**
1. **Fallback approach**: Traditional APIs first, then AI enhancement
2. **Validation**: AI results validated against known good data
3. **Learning**: System learns from corrections over time
4. **Selective use**: AI only when traditional methods fail

### ✅ **Metadata Standardization**
- Unified metadata format across all sources
- Consistent field mapping via YAML configuration
- Quality scoring for metadata completeness
- Confidence levels for AI-generated data

### ✅ **Configuration Management**
- Centralized config for all APIs
- YAML-based national library configuration
- Environment-specific settings
- Secure API key management
- User preference storage

### ✅ **Optimal API Sources Strategy**
**For Books:**
- **Primary**: OpenLibrary (25M+ books, comprehensive metadata, free)
- **Secondary**: Google Books (recent publications, previews)
- **Regional**: National Libraries (Norwegian, Swedish, Finnish for local books)

**For Scientific Papers:**
- **Primary**: OpenAlex (200M+ papers, comprehensive academic metadata, free)
- **Secondary**: CrossRef (130M+ scholarly works, DOI-based, publisher data)
- **Specialized**: PubMed (35M+ biomedical papers), arXiv (2M+ preprints)

## Environment Requirements

### Conda Environment
- **Name**: research-tools (existing)
- **Intel GPU optimization** for image processing
- **Python 3.11** with Intel optimizations
- **Key packages**: OpenCV, Tesseract, EasyOCR, PaddleOCR, PyZotero, requests

### Dependencies
- Intel Math Kernel Library (MKL)
- Intel OpenMP and TBB
- Multiple OCR engines
- PDF processing libraries
- API client libraries

## 🚧 **PARTIAL SUCCESS METRICS**

### 🚧 **Paper Processing**
- [ ] High-resolution scan quality (OCR engine - basic framework)
- [ ] Accurate language detection (framework - not implemented)
- [ ] Complete metadata extraction (unified extractor - basic)
- [ ] Successful annotation separation (framework - not implemented)
- [ ] PDF optimization (pipeline - not implemented)
- [ ] Zotero integration success (matcher - basic framework)

### 🚧 **Book Processing**
- [x] ISBN extraction accuracy (copied from scanpapers with Intel GPU)
- [x] Metadata completeness from multiple sources (6 libraries configured)
- [ ] Zotero integration with rich metadata (needs integration)
- [x] Processing speed optimization (Intel GPU acceleration)

### ✅ **Shared Components**
- [x] API reliability and fallback chains (configuration-driven system)
- [ ] AI enhancement effectiveness (framework - not implemented)
- [x] Configuration management (centralized system)
- [ ] File organization efficiency (structured directories - basic)

### 🎯 **NEW SUCCESS METRICS (Configuration-Driven Migration)**
- [ ] All existing functionality preserved with new system
- [ ] Norwegian library integration working (1M+ results confirmed)
- [ ] No hardcoded API endpoints remaining
- [ ] Easy to add new libraries via YAML configuration
- [ ] Migration completed without breaking existing workflows

## 🎯 **NEXT STEPS: Two Parallel Work Streams**

### **🚧 CONTINUE: Research-Tools Transition**
The basic structure is created, but much work remains:

1. **Complete functionality migration** from scanpapers
2. **Implement missing components** (OCR, PDF processing, etc.)
3. **Integrate isbn-book-processor** content properly
4. **Build paper processing pipeline** (annotation separation, etc.)
5. **Complete Zotero integration** for both books and papers
6. **Full integration testing** of all components

### **🚀 NEW: Configuration-Driven Migration**
The national library system is ready for migration:

1. **Review MIGRATION_PLAN.md** - Detailed strategy for config-driven migration
2. **Start Phase 1** - Migrate shared components to new system
3. **Test Norwegian library** - Use as known working example
4. **Migrate book processing** - Update scripts to use config-driven system
5. **Migrate paper processing** - Integrate with new national library system
6. **Cleanup old system** - Remove hardcoded clients

### **📋 Key Documents for New AI Chat:**
- **MIGRATION_PLAN.md** - Complete migration strategy
- **CONFIGURATION_DRIVEN_APPROACH.md** - Architecture explanation
- **AI_CHAT_DOCUMENTS.md** - All files and context needed
- **test_config_driven_national_libraries.py** - Working examples

## ✅ **IMPLEMENTATION NOTES**

- **✅ Memory references**: User prefers conda over pip, uses WSL, requires ISBN/barcode for book processing
- **✅ Existing functionality**: scanpapers functionality successfully migrated with Intel GPU optimization
- **✅ Workflow integration**: Paper scanning workflow preserved and enhanced
- **✅ API considerations**: Configuration-driven system supports all international sources

### **🎯 Current Status:**
- **🚧 Basic research-tools structure implemented**
- **✅ Configuration-driven national library system ready**
- **✅ Norwegian National Library API tested and working**
- **🚧 Some components integrated and tested**
- **🚀 Ready for two parallel work streams**

### **📋 For New AI Chat:**
- **Start with MIGRATION_PLAN.md** for detailed migration strategy
- **Use Norwegian library as test case** (confirmed working)
- **Follow incremental migration approach** (test after each phase)
- **Maintain backward compatibility** during migration

---

*This document now accurately reflects the current state: basic research-tools structure created with configuration-driven national library system ready. Two parallel work streams are needed: completing the original research-tools transition and migrating to the configuration-driven national library system.*
