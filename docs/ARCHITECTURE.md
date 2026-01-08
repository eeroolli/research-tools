# System Architecture

## Overview

The paper processor daemon is a modular system for processing scanned academic papers. It watches a directory for new PDF files, extracts metadata, integrates with Zotero, and manages file operations.

## Architecture Principles

1. **Modular Design**: System is broken into focused modules with single responsibilities
2. **Separation of Concerns**: Clear boundaries between file operations, PDF processing, metadata extraction, and Zotero integration
3. **Error Handling**: Structured exception hierarchy for specific error types
4. **Network Resilience**: Robust handling of distributed services (blacktower ↔ P1)
5. **Testability**: Dependency injection and mockable interfaces

## Module Structure

```
shared_tools/daemon/
├── __init__.py           # Package initialization
├── core.py               # Core daemon (file watching, lifecycle)
├── service_manager.py    # Service lifecycle management (GROBID, Ollama)
├── file_operations.py    # File copy, move, path validation
├── pdf_processor.py      # PDF preprocessing, splitting, border removal
├── metadata_workflow.py  # Metadata extraction orchestration
├── zotero_workflow.py    # Zotero search, matching, attachment
├── user_interaction.py   # Menus, prompts, input handling
├── display.py            # Metadata formatting and display
├── exceptions.py         # Exception hierarchy
├── constants.py          # Centralized constants
└── config_validator.py   # Configuration validation
```

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

## Data Flow

```
New PDF File
    ↓
File Watcher (core.py)
    ↓
PDF Preprocessing (pdf_processor.py)
    ↓
Metadata Extraction (metadata_workflow.py)
    ├── GREP identifier extraction
    ├── GROBID extraction (if needed)
    └── Ollama extraction (fallback)
    ↓
Zotero Search (zotero_workflow.py)
    ↓
User Interaction (user_interaction.py)
    ↓
File Operations (file_operations.py)
    ├── Copy to publications
    └── Move to done/failed/skipped
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

