# System Architecture

## Overview

The paper processor daemon is a modular system for processing scanned academic papers. It watches a directory for new PDF files, extracts metadata, integrates with Zotero, and manages file operations. A legacy, monolithic script still orchestrates parts of the flow while module extraction continues.

## Architecture Principles

1. **Modular Design**: System is broken into focused modules with single responsibilities
2. **Separation of Concerns**: Clear boundaries between file operations, PDF processing, metadata extraction, and Zotero integration
3. **Error Handling**: Structured exception hierarchy for specific error types
4. **Network Resilience**: Robust handling of distributed services (blacktower ↔ P1)
5. **Testability**: Dependency injection and mockable interfaces
6. **Incremental Refactor**: Legacy orchestration remains in `scripts/paper_processor_daemon.py` while new modules are phased in

## Module Structure

### Daemon Modules (`shared_tools/daemon/`)

```
shared_tools/daemon/
├── __init__.py           # Package initialization
├── core.py               # Core daemon (file watching, lifecycle)
├── service_manager.py    # Service lifecycle management (GROBID, Ollama)
├── file_operations.py    # File copy, move, path validation
├── pdf_processor.py      # PDF preprocessing, splitting, border removal
├── metadata_workflow.py  # Metadata extraction orchestration
├── zotero_workflow.py    # Zotero search, matching, attachment
├── enrichment_workflow.py# Online enrichment orchestration (match policy + planner)
├── enrichment_display.py # Console rendering for enrichment summaries
├── user_interaction.py   # Menus, prompts, input handling
├── display.py            # Metadata formatting and display
├── exceptions.py         # Exception hierarchy
├── constants.py          # Centralized constants
└── config_validator.py   # Configuration validation
```

### Utility Modules (`shared_tools/utils/`)

```
shared_tools/utils/
├── identifier_extractor.py  # PDF text extraction and identifier extraction
├── identifier_validator.py  # Identifier validation (DOI, arXiv, etc.)
├── author_extractor.py      # Author name extraction from text (regex-based)
├── author_validator.py      # Author name validation
├── document_classifier.py   # Document type classification (handwritten detection)
├── grobid_validator.py      # GROBID hallucination validation
├── api_priority_manager.py  # API priority and routing management
├── filename_generator.py    # Smart filename generation
├── path_utils.py            # Path handling utilities (WSL/Windows)
└── ...                      # Other utility modules
```

### Metadata Modules (`shared_tools/metadata/`)

```
shared_tools/metadata/
├── paper_processor.py    # Main paper metadata extraction orchestrator
├── jstor_handler.py      # JSTOR workflow orchestration
├── extractor.py          # Metadata extraction base classes
├── enrichment_policy.py  # Match policy scoring for online enrichment
├── enrichment_planner.py # Field-level update planning for enrichment
└── ...                   # Other metadata modules
```

### Enrichment Workflow (`enrichment_workflow.py`)

- Evaluates online candidates (CrossRef/arXiv/etc.) with a match policy
- Builds a fill-only update plan (field policy-driven)
- Applies safe fields to Zotero on auto-accept and logs applied/failed fields
- Provides summary rendering via `enrichment_display.py`

## Key Modules

### Core Daemon (`core.py`)

- File watching using watchdog library
- Event handling for new PDF files
- Lifecycle management (start/stop)
- Signal handling for graceful shutdown
- PID file management

### Service Manager (`service_manager.py`)

- GROBID service management (local/remote)
- Ollama service management (local/remote)
- Health checks with exponential backoff
- Network resilience for distributed setup
- Service discovery and auto-start

### File Operations (`file_operations.py`)

- Atomic file copy operations
- Safe file moves
- Path validation (security)
- Context managers for temporary files

### PDF Processor (`pdf_processor.py`)

- PDF preprocessing
- Page offset handling
- Border removal integration
- Two-up splitting support (gutter detection + geometric fallback)
- Context managers for temporary PDFs

### Metadata Workflow (`metadata_workflow.py`)

- Coordinates metadata extraction strategies
- GREP → GROBID → Ollama fallback chain
- Error handling and recovery

### Zotero Workflow (`zotero_workflow.py`)

- Zotero library search
- Item matching and selection
- PDF attachment to items
- New item creation

## Utility Modules

### Identifier Extractor (`identifier_extractor.py`)

- General-purpose PDF text extraction (`extract_text()`)
- Identifier extraction (DOI, arXiv, JSTOR, ISBN, etc.)
- First-page identifier extraction for fast-path optimization
- Book chapter text extraction with gutter detection

### Author Extractor (`author_extractor.py`)

- Regex-based author name extraction from text
- Pattern matching for various author name formats
- Filtering of non-author entities (institutions, places, titles)
- Supports both "Last, First" and "First Last" formats

### Document Classifier (`document_classifier.py`)

- Handwritten note detection (low text threshold)
- Configurable text threshold from config files
- Uses `identifier_extractor.extract_text()` for text extraction
- Helps skip non-academic documents early in processing

### GROBID Validator (`grobid_validator.py`)

- Validates GROBID-extracted authors against PDF text
- Filters hallucinated authors that don't appear in document
- Word boundary matching to prevent false positives
- Falls back to regex-extracted authors when available

### JSTOR Handler (`jstor_handler.py`)

- Orchestrates JSTOR metadata fetching workflow
- Extracts DOI from JSTOR pages when available
- Enriches metadata via DOI-based APIs (CrossRef, OpenAlex, PubMed)
- Handles failures gracefully with fallback to GROBID

### Paper Processor (`paper_processor.py`)

- Main orchestrator for paper metadata extraction
- Uses utility modules (AuthorExtractor, DocumentClassifier, JSTORHandler, GrobidValidator)
- Coordinates extraction strategies (GREP → API → GROBID → Ollama)
- Maintains backward compatibility with existing API

## Data Flow

```
New PDF File
    ↓
File Watcher (core.py) or legacy loop in `scripts/paper_processor_daemon.py`
    ↓
PDF Preprocessing (pdf_processor.py + `shared_tools/pdf/content_detector.py`)
    ↓
Metadata Extraction (metadata_workflow.py)
    ↓
Paper Processor (paper_processor.py)
    ├── Document Classifier → Check if handwritten note
    ├── Identifier Extractor → Extract identifiers (DOI, arXiv, JSTOR, etc.)
    ├── API Lookup → Try CrossRef, OpenAlex, PubMed, arXiv
    ├── JSTOR Handler → Process JSTOR IDs (if found)
    ├── GROBID Extraction → Full metadata extraction
    │   └── GROBID Validator → Filter hallucinated authors
    ├── Author Extractor → Regex-based author extraction (fallback)
    └── Ollama Extraction → AI-based extraction (final fallback)
    ↓
Zotero Search (zotero_workflow.py)
    ↓
Online Enrichment (enrichment_workflow.py)
    ├── Auto-accept: when an existing Zotero item is selected, best candidate is evaluated and shown in an ENRICHMENT REVIEW page; defaults to apply fill-only updates on timeout/Enter
    └── Manual review: ENRICHMENT REVIEW page defaults to skip on timeout; user can apply all or select fields (including explicit overwrites)
    ↓
User Interaction (user_interaction.py)
    ↓
File Operations (file_operations.py)
    ├── Copy to publications
    └── Move to done/failed/skipped
```

## Module Dependencies

```
paper_processor.py (orchestrator)
    ↓ uses
author_extractor.py → author_validator.py
grobid_validator.py → identifier_extractor.py (extract_text)
document_classifier.py → identifier_extractor.py (extract_text)
jstor_handler.py → jstor_client.py, api_clients
identifier_extractor.py → PyPDF2 (text extraction)
content_detector.py → PyMuPDF + OpenCV (gutter detection)
border_remover.py → OpenCV (border detection/removal)
```

## Distributed Setup (blacktower ↔ P1)

- **blacktower**: Runs daemon (file watching, workflow orchestration)
- **P1**: Runs GROBID and Ollama services
- Network resilience handled by ServiceManager
- Health checks with retries and exponential backoff
- Graceful degradation when services unavailable

## Error Handling

Structured exception hierarchy:

- `DaemonError` (base)
  - `ServiceError` (service issues)
  - `FileOperationError` (file operations)
  - `MetadataExtractionError` (metadata extraction)
  - `ZoteroError` (Zotero operations)
  - `ConfigurationError` (configuration issues)

## Configuration

Centralized configuration in `config.conf`:

- Service settings (GROBID, Ollama)
- Network resilience settings
- Processing options
- Path configurations

## Testing Strategy

- Unit tests for individual modules
- Integration tests for workflows
- Mock external services (GROBID, Ollama, Zotero)
- Test network resilience patterns

## Design Decisions

1. **Polling Observer**: Uses PollingObserver for file watching (more reliable than native observer on WSL)
2. **Context Managers**: Extensive use of context managers for resource cleanup
3. **Dependency Injection**: Optional dependencies for testing
4. **Modular Extraction**: Gradual extraction from monolithic daemon to modules
5. **Backward Compatibility**: Maintain compatibility during refactoring
6. **Reusable Utilities**: Extracted common functionality (author extraction, text extraction, validation) into reusable utility modules
7. **Single Responsibility**: Each utility module has a focused purpose (author extraction, document classification, validation)
8. **Exception Routing**: Exception handlers route to existing processing paths instead of creating ad-hoc solutions

## Current Integration Notes

- The primary orchestration entry point is still `scripts/paper_processor_daemon.py`.
- `shared_tools/daemon/` modules are available and used selectively (e.g., service management, config loading).
- Metadata extraction is centralized in `shared_tools/metadata/paper_processor.py`, which calls the shared utilities.
