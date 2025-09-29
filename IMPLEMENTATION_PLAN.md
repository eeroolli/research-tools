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

### ❌ **Not Completed:**
- Detailed migration tasks from `AI_CHAT_DOCUMENTS.md` (Phases 2-4)
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

### **Phase 1: Complete Configuration-Driven System** 🚧
*Extend current working system with remaining APIs*

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

#### 3.2 AI-Enhanced OCR
- [ ] LLM-based text correction for OCR errors
- [ ] Context-aware metadata extraction
- [ ] Language detection and processing

#### 3.3 Smart Annotation Processing
- [ ] AI-powered annotation separation (handwritten notes, highlights)
- [ ] Keyword extraction from annotations
- [ ] Question and note identification

#### 3.4 AI Metadata Enhancement
- [ ] Fill missing metadata fields using AI
- [ ] Validate and correct extracted metadata
- [ ] Suggest tags and categories based on content

### **Phase 4: Detailed Migration Tasks** 📋
*From AI_CHAT_DOCUMENTS.md - migrate existing hardcoded systems*

#### 4.1 Book Processing Migration
- [ ] **File:** `process_books/scripts/enhanced_isbn_lookup_detailed.py`
  - **Action:** Replace hardcoded national library calls with config-driven manager
  - **Status:** Uses old hardcoded system, needs migration

- [ ] **File:** `process_books/scripts/zotero_api_book_processor_enhanced.py`
  - **Action:** Update to use new unified metadata system
  - **Status:** Uses old hardcoded system, needs migration

- [ ] **File:** `process_books/src/integrations/legacy_zotero_processor.py`
  - **Action:** Update to use new system
  - **Status:** Uses old hardcoded system, needs migration

#### 4.2 Paper Processing Migration
- [ ] **File:** `process_papers/src/core/metadata_extractor.py`
  - **Action:** Complete integration with config-driven system
  - **Status:** Partially updated, needs full migration

#### 4.3 Paper Scanning Workflow Implementation
- [ ] **First Page OCR/AI Processing**
  - **Action:** Implement first page processing for paper identification
  - **Requirements:** Extract DOI, title, authors, abstract
  - **Status:** New feature for scanning workflow

- [ ] **Automated File Management**
  - **Action:** Implement PDF renaming and storage workflow
  - **Requirements:** Meaningful filename generation, copy to `g:/publications`
  - **Status:** New feature for scanning workflow

- [ ] **Zotero Linked File Integration**
  - **Action:** Add papers as linked files in Zotero
  - **Requirements:** Link to stored PDF location
  - **Status:** New feature for scanning workflow

#### 4.4 Cleanup Phase
- [ ] **File:** `shared_tools/api/national_libraries.py`
  - **Action:** Delete after migration complete
  - **Status:** Old hardcoded clients, still exists

### **Phase 5: Integration & Testing** 🧪
*End-to-end testing and core functionality validation*

#### 5.1 Comprehensive Testing
- [ ] Test all migration scenarios
- [ ] Validate unified metadata system with edge cases
- [ ] Test AI-driven paper processing
- [ ] Core functionality validation

#### 5.2 Documentation & Cleanup
- [ ] Update all documentation
- [ ] Archive old planning documents
- [ ] Create user guides
- [ ] Basic performance benchmarks

### **Phase 6: Performance Optimization** ⚡
*Local DB integration and performance enhancements*

#### 6.1 Local Zotero Database Integration
- [ ] Investigate Zotero SQLite schema
- [ ] Implement local duplicate detection and metadata lookup
- [ ] Add schema version checking and fallback to API-only mode
- [ ] Background sync management (start, during operations, end)

#### 6.2 Hybrid Lookup + API Approach
- [ ] Implement local DB lookup for performance
- [ ] API-only for all write operations (add/update/delete)
- [ ] User choice presentation based on local data
- [ ] Batch local lookups for multiple items

#### 6.3 Advanced Performance Features
- [ ] Caching strategies for frequently accessed data
- [ ] Optimized sync timing and background operations
- [ ] Performance monitoring and metrics

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
1. **Add OpenAlex API** - Start with academic paper sources
2. **Design unified metadata system** - Smart routing architecture
3. **Test unified approach** - Validate with edge cases

### **Short Term (1-2 Sessions)**
1. Complete academic APIs (CrossRef, PubMed, arXiv)
2. Implement unified metadata manager
3. Start book processing migration

### **Medium Term (3-4 Sessions)**
1. Complete all migration tasks
2. Implement AI-driven paper processing
3. Comprehensive testing and core functionality validation

### **Long Term (5+ Sessions)**
1. Local DB performance optimization
2. Advanced AI features
3. User interface and documentation

## Key Decisions Needed

1. **Config Structure**: Separate configs vs unified with sections?
2. **AI Integration**: Local LLM vs API-based?
3. **Migration Strategy**: Big bang vs incremental?
4. **Priority Order**: Academic APIs first vs unified system first?
5. **Performance Optimization**: When to implement local DB integration (Phase 6)?

## Paper Scanning Workflow - Open Questions

1. **First Page Processing**: 
   - Should we process the entire first page or focus on specific areas?
   - What's the preferred identification priority (DOI → Title+Authors → Abstract)?

2. **Filename Convention**: 
   - What naming pattern for renamed PDFs? (`Author_Year_Title.pdf`, `Title_Author_Year.pdf`, etc.)
   - How to handle special characters in titles/authors?

3. **Storage Location**: 
   - Is `g:/publications` accessible from WSL? 
   - Should we use relative paths from config or absolute paths?

4. **Error Handling**: 
   - What to do if paper cannot be identified from first page?
   - How to handle multiple matches from database search?

5. **Zotero Integration**: 
   - Should linked files be added immediately or queued for batch processing?
   - How to handle duplicate detection in Zotero?

---

*This plan combines the detailed migration tasks from AI_CHAT_DOCUMENTS.md with the unified metadata system design and AI-driven paper processing enhancement.*
