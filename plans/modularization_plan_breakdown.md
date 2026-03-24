---
name: Modularization Plan Breakdown
overview: Break down the comprehensive modularization plan from docs/Modularization plan.md into manageable, agent-friendly chunks with clear dependencies, scope, and implementation instructions.
todos: []
---

# Modularization Plan Breakdown into Agent-Friendly Chunks

## Overview

This plan breaks down the comprehensive modularization plan into discrete, manageable chunks that can be safely assigned to agents without conflicts. Each chunk is self-contained with clear dependencies, scope, and deliverables.

**Important Notes:**
- This repository contains multiple scripts beyond `paper_processor_daemon.py`:
  - `pdf_self_fixer.py` (inherits from PaperProcessorDaemon - needs careful handling)
  - `process_scanned_papers.py`, `ocr_pdf.py`, `find_isbn_from_photos.py`
  - Analysis scripts, book processing scripts, etc.
- Git commits are included at logical checkpoints using the project's commit message format:
  - `feature:` for new features/modules
  - `fix:` for bug fixes
  - `debug:` for debugging changes
  - `minor:` for minor improvements

## Chunk Organization Strategy

Chunks are organized by:

1. **Dependency order** - foundational chunks come first

2. **Risk level** - low-risk chunks (new files) before high-risk (refactoring)

3. **Testability** - chunks that can be tested independently

4. **Scope size** - chunks should be completable in 1-2 hours

## Phase 1: Critical Improvements (Foundation)

### Chunk 1.1: Create Exception Hierarchy

**Priority:** High (foundation for error handling)

**Risk:** Low (new file, no changes to existing code)

**Dependencies:** None

**Files to create:**

- `shared_tools/daemon/__init__.py` (empty, makes it a package)

- `shared_tools/daemon/exceptions.py`

**Deliverables:**

- Exception classes: `DaemonError`, `ServiceError`, `FileOperationError`, `MetadataExtractionError`, `ZoteroError`, `ConfigurationError`

- All exceptions inherit from base `DaemonError`

- Google-style docstrings for each exception
- Type hints

**Instructions:**

- Create the daemon package directory structure

- Define exception hierarchy as specified in the plan

- Add docstrings explaining when to use each exception type

**Git Commit (after completion):**
```
feature: Add daemon exception hierarchy module

- Create shared_tools/daemon package structure
- Add exception classes: DaemonError, ServiceError, FileOperationError, MetadataExtractionError, ZoteroError, ConfigurationError
- Foundation for structured error handling in daemon refactoring
```

---

### Chunk 1.2: Create Constants Module

**Priority:** High (foundation for removing magic numbers)

**Risk:** Low (new file)

**Dependencies:** None

**Files to create:**

- `shared_tools/daemon/constants.py`

**Deliverables:**

- `DaemonConstants` class with all constants from the plan:

- Timeouts (FILE_WRITE_DELAY, PROMPT_TIMEOUT, PAGE_OFFSET_TIMEOUT, SERVICE_STARTUP_TIMEOUT)

- File patterns (PDF_EXTENSION, PID_FILENAME)

- Directories (DONE_SUBDIR, FAILED_SUBDIR, SKIPPED_SUBDIR)

- Extract constants by searching daemon for hardcoded values

- Document each constant

**Instructions:**

- Search `scripts/paper_processor_daemon.py` for hardcoded timeouts, file extensions, directory names

- Create constants class with all identified values

- Add docstrings

**Git Commit (after completion):**
```
feature: Add daemon constants module

- Extract hardcoded values from daemon to DaemonConstants class
- Centralize timeouts, file patterns, and directory names
- Foundation for removing magic numbers/strings
```

---

### Chunk 1.3: Create Service Manager Module (Design + Implementation)

**Priority:** High (critical for distributed setup)

**Risk:** Medium (new module, needs integration later)

**Dependencies:** Chunk 1.1 (uses exceptions)

**Files to create:**

- `docs/SERVICE_MANAGER_DESIGN.md`

- `docs/NETWORK_RESILIENCE_PATTERNS.md`

- `shared_tools/daemon/service_manager.py`

**Deliverables:**

- Service manager class with network resilience

- Design documentation

- Network error handling patterns documentation
- Health checks with exponential backoff

- Local/remote service detection
- Support for distributed setup (blacktower/P1)

**Instructions:**

- Extract service management design from the plan document

- Implement ServiceManager class as specified

- Include network resilience patterns (retries, backoff, error classification)

- Document configuration requirements in design doc

- Note: Integration with daemon comes in later chunk

**Git Commit (after completion):**
```
feature: Add service manager module with network resilience

- Create ServiceManager class for GROBID and Ollama lifecycle management
- Support for distributed setup (blacktower/P1)
- Health checks with exponential backoff
- Network error handling patterns
- Add design documentation for service management
```

---

### Chunk 1.4: Add Configuration Validation

**Priority:** High (security and reliability)

**Risk:** Low (new utility, minimal changes)

**Dependencies:** Chunk 1.1 (uses exceptions)

**Files to create:**

- `shared_tools/daemon/config_validator.py`

**Deliverables:**

- `ConfigValidator` class with validation methods:

- `validate_path()` - path validation and normalization

- `validate_port()` - port number validation

- `validate_config()` - comprehensive config validation

- Integration with existing config loading
- Clear error messages

**Instructions:**

- Create validator class

- Add validation methods for paths, ports, required keys

- Include validation for distributed setup (remote host reachability)
- Document usage patterns

**Git Commit (after completion):**
```
feature: Add configuration validation module

- Create ConfigValidator class for path, port, and config validation
- Support for distributed setup validation
- Clear error messages for invalid configurations
```

---

### Chunk 1.5: Create Path Utilities Module

**Priority:** Medium (reduce duplication)

**Risk:** Low (new utility, can coexist with existing code)

**Dependencies:** None

**Files to check/update:**

- `shared_tools/utils/path_utils.py` (check if exists, enhance if needed)

- Search for `normalize_path_for_wsl` usage

**Deliverables:**

- Centralized path utilities

- Remove duplication of `normalize_path_for_wsl()`

- Ensure all scripts use centralized version

- WSL/Windows path handling

**Instructions:**

- Check if path_utils.py exists, create/enhance as needed
- Find all instances of path normalization code

- Consolidate into single utility

- Update imports in scripts (can be done incrementally)

**Git Commit (after completion):**
```
minor: Consolidate path utilities

- Centralize normalize_path_for_wsl() and other path utilities
- Remove duplication across scripts
- Ensure consistent path handling
```

---

## Phase 2: Maintainability (Refactoring)

### Chunk 2.1: Extract File Operations Module

**Priority:** High (foundation for daemon modularization)

**Risk:** Medium (extracting from daemon)

**Dependencies:** Chunk 1.1 (uses exceptions), Chunk 1.2 (uses constants)

**Files to create:**

- `shared_tools/daemon/file_operations.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py` (extract methods, add imports)

**Deliverables:**

- File operations module with:

- `copy_file_safely()` - atomic file copy with verification

- `move_file_safely()` - safe file move

- `validate_file_path()` - path validation (security)

- Context managers for temporary files

- All file operations from daemon extracted

- Proper error handling with specific exceptions

- Resource cleanup (context managers)

**Instructions:**

- Identify all file operation methods in daemon

- Extract to new module with proper error handling

- Replace broad exception catches with specific exceptions

- Add context managers for temporary files

- Update daemon to use new module (keep daemon working)

**Important:** Verify `pdf_self_fixer.py` (inherits from PaperProcessorDaemon) still works after changes.

**Git Commit (after completion):**
```
feature: Extract file operations module from daemon

- Create shared_tools/daemon/file_operations.py
- Extract file copy/move operations with atomic operations
- Add context managers for temporary files
- Replace broad exception catches with specific exceptions
- Update daemon to use new module
```

---

### Chunk 2.2: Extract PDF Processing Module

**Priority:** High (large, complex functionality)

**Risk:** Medium (extracting complex logic)

**Dependencies:** Chunk 1.1, Chunk 1.2

**Files to create:**

- `shared_tools/daemon/pdf_processor.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- PDF processing module with:

- PDF preprocessing

- PDF splitting (page offset handling)

- Border removal integration
- Rotation handling
- Context managers for temporary PDFs

- Proper error handling

**Instructions:**

- Extract PDF-related methods from daemon

- Include border removal and rotation logic

- Add context managers for cleanup
- Update daemon to use new module

**Important:** Verify `pdf_self_fixer.py` still works after changes.

**Git Commit (after completion):**
```
feature: Extract PDF processing module from daemon

- Create shared_tools/daemon/pdf_processor.py
- Extract PDF preprocessing, splitting, border removal, rotation
- Add context managers for temporary PDF cleanup
- Update daemon to use new module
```

---

### Chunk 2.3: Extract Service Manager Integration

**Priority:** High (enables distributed setup)

**Risk:** Medium (modifies daemon initialization)

**Dependencies:** Chunk 1.3 (ServiceManager exists)

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- Replace daemon's service initialization with ServiceManager

- Update GROBID/Ollama initialization to use ServiceManager

- Maintain backward compatibility

- Proper error handling with new exceptions

**Instructions:**

- Replace `_initialize_services()` in daemon to use ServiceManager

- Update all service checks to use ServiceManager methods

- Test with distributed setup (blacktower/P1)

- Ensure graceful degradation when services unavailable

**Important:** Verify `pdf_self_fixer.py` still works (it may skip service initialization).

**Git Commit (after completion):**
```
feature: Integrate ServiceManager into daemon

- Replace daemon service initialization with ServiceManager
- Update GROBID/Ollama initialization to use ServiceManager
- Support for distributed setup (blacktower/P1)
- Maintain backward compatibility
```

---

### Chunk 2.4: Extract Metadata Workflow Module

**Priority:** Medium (workflow orchestration)

**Risk:** Medium (extracting workflow logic)

**Dependencies:** Chunk 1.1, existing metadata processor

**Files to create:**

- `shared_tools/daemon/metadata_workflow.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- Metadata workflow orchestration module

- Coordinates metadata extraction strategies

- Handles confirmation workflow
- Error handling and recovery

**Instructions:**

- Extract metadata extraction workflow from `process_paper()`

- Coordinate between GREP, GROBID, Ollama strategies

- Include user confirmation logic

- Handle errors gracefully

**Git Commit (after completion):**
```
feature: Extract metadata workflow module from daemon

- Create shared_tools/daemon/metadata_workflow.py
- Extract metadata extraction workflow orchestration
- Coordinate GREP, GROBID, Ollama strategies
- Update daemon to use new module
```

---

### Chunk 2.5: Extract Zotero Workflow Module

**Priority:** Medium (workflow orchestration)

**Risk:** Medium (extracting workflow logic)

**Dependencies:** Chunk 1.1, existing zotero processor

**Files to create:**

- `shared_tools/daemon/zotero_workflow.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- Zotero workflow orchestration

- Search, matching, attachment logic
- User interaction for Zotero operations
- Error handling

**Instructions:**

- Extract Zotero-related workflow from daemon

- Include search, matching, attachment logic

- Coordinate with ZoteroPaperProcessor
- Handle errors with specific exceptions

**Git Commit (after completion):**
```
feature: Extract Zotero workflow module from daemon

- Create shared_tools/daemon/zotero_workflow.py
- Extract Zotero search, matching, attachment logic
- Update daemon to use new module
```

---

### Chunk 2.6: Extract User Interaction Module

**Priority:** Medium (UI separation)

**Risk:** Low (UI code, less critical)

**Dependencies:** Chunk 1.1, Chunk 1.2

**Files to create:**

- `shared_tools/daemon/user_interaction.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- User interaction module with:

- Menu display and navigation

- User prompts and input handling
- Timeout handling
- Clear user feedback

**Instructions:**

- Extract menu and prompt methods from daemon

- Include navigation logic

- Add timeout handling using constants

- Improve user feedback messages

**Git Commit (after completion):**
```
feature: Extract user interaction module from daemon

- Create shared_tools/daemon/user_interaction.py
- Extract menu display, navigation, and prompts
- Update daemon to use new module
```

---

### Chunk 2.7: Extract Display Module

**Priority:** Low (presentation layer)

**Risk:** Low (display code only)

**Dependencies:** Chunk 1.1, Chunk 1.2

**Files to create:**

- `shared_tools/daemon/display.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Deliverables:**

- Display module for metadata formatting

- Pretty-print metadata

- Color/formatting utilities
- Consistent display format

**Instructions:**

- Extract metadata display methods

- Include formatting and color utilities

- Ensure consistent display format

- Use constants for formatting parameters

**Git Commit (after completion):**
```
feature: Extract display module from daemon

- Create shared_tools/daemon/display.py
- Extract metadata display and formatting utilities
- Update daemon to use new module
```

---

### Chunk 2.8: Extract Core Daemon Module

**Priority:** High (final core extraction)

**Risk:** High (major refactoring)

**Dependencies:** All previous chunks (2.1-2.7)

**Files to create:**

- `shared_tools/daemon/core.py`

**Files to modify:**

- `scripts/paper_processor_daemon.py` (becomes thin wrapper or imports core)

**Deliverables:**

- Core daemon class with:

- File watching logic

- Daemon lifecycle (start/stop)

- Event handling
- Main processing loop

- Thin wrapper script that instantiates core class

**Instructions:**

- Extract core daemon functionality

- Keep file watching and lifecycle management

- Coordinate with all extracted modules
- Ensure script still works as executable

**Important:** Verify `pdf_self_fixer.py` (inherits from PaperProcessorDaemon) still works after core extraction.

**Git Commit (after completion):**
```
feature: Extract core daemon module

- Create shared_tools/daemon/core.py
- Extract file watching, lifecycle, event handling
- Refactor paper_processor_daemon.py to use core module
- Major milestone: daemon fully modularized
```

---

### Chunk 2.9: Break Down Large Methods

**Priority:** Medium (code quality)

**Risk:** Medium (refactoring existing methods)

**Dependencies:** All Phase 2 chunks (method extraction)

**Files to modify:**

- All daemon modules (2.1-2.8)

**Deliverables:**

- Break down `process_paper()` and other large methods

- Methods should be <100 lines each

- Clear method names and responsibilities
- Proper error handling

**Instructions:**

- Identify methods >100 lines in extracted modules

- Break into smaller, focused methods

- Maintain single responsibility

- Update tests if they exist

**Git Commit (after completion):**
```
minor: Break down large methods in daemon modules

- Refactor methods >100 lines into smaller, focused methods
- Improve code readability and maintainability
- Update tests as needed
```

---

### Chunk 2.10: Add Comprehensive Docstrings

**Priority:** Medium (documentation)

**Risk:** Low (adding documentation only)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules

**Deliverables:**

- Google-style docstrings for all public methods

- Document parameters, return values, exceptions
- Include usage examples where helpful

- Architecture documentation

**Instructions:**

- Add docstrings to all public methods

- Use Google style format

- Document exceptions raised

- Create `docs/ARCHITECTURE.md` with system overview

**Git Commit (after completion):**
```
feature: Add comprehensive docstrings to daemon modules

- Add Google-style docstrings to all public methods
- Create docs/ARCHITECTURE.md with system overview
- Document parameters, return values, exceptions
```

---

## Phase 3: Reliability and Testing

### Chunk 3.1: Create Unit Tests for Service Manager

**Priority:** High (critical module)

**Risk:** Low (new tests)

**Dependencies:** Chunk 1.3

**Files to create:**

- `tests/daemon/__init__.py`

- `tests/daemon/test_service_manager.py`

**Deliverables:**

- Unit tests for ServiceManager
- Mock network calls

- Test retry logic

- Test local vs remote detection

- Test error handling

**Instructions:**

- Create test module structure

- Mock requests for network calls

- Test health checks with retries

- Test service startup/shutdown

- Achieve >80% coverage for ServiceManager

**Git Commit (after completion):**
```
feature: Add unit tests for ServiceManager

- Create tests/daemon/test_service_manager.py
- Test health checks, retries, local/remote detection
- Mock network calls for testing
```

---

### Chunk 3.2: Create Unit Tests for File Operations

**Priority:** High (file operations are critical)

**Risk:** Low (new tests)

**Dependencies:** Chunk 2.1

**Files to create:**

- `tests/daemon/test_file_operations.py`

**Deliverables:**

- Unit tests for file operations

- Test atomic copy operations

- Test path validation (security)

- Test context managers

- Test error handling

**Instructions:**

- Test file copy/move operations

- Test path validation (including path traversal prevention)

- Test context managers for cleanup

- Test error scenarios

**Git Commit (after completion):**
```
feature: Add unit tests for file operations module

- Create tests/daemon/test_file_operations.py
- Test atomic copy/move, path validation, context managers
- Test error handling and security
```

---

### Chunk 3.3: Create Integration Tests

**Priority:** Medium (end-to-end testing)

**Risk:** Low (new tests)

**Dependencies:** All Phase 2 chunks

**Files to create:**

- `tests/daemon/test_integration.py`

**Deliverables:**

- Integration tests for workflows

- Test paper processing workflow

- Test with mock services

- Test error recovery

**Instructions:**

- Create integration test framework

- Test complete paper processing workflow

- Mock external services (GROBID, Ollama, Zotero)

- Test error scenarios and recovery

**Git Commit (after completion):**
```
feature: Add integration tests for daemon workflows

- Create tests/daemon/test_integration.py
- Test complete paper processing workflow
- Test with mocked external services
```

---

### Chunk 3.4: Improve Error Recovery

**Priority:** High (reliability)

**Risk:** Medium (modifying error handling)

**Dependencies:** All Phase 2 chunks, Chunk 1.1

**Files to modify:**

- All daemon modules

**Deliverables:**

- Replace all `except Exception:` with specific exceptions

- Add retry logic for transient failures

- Improve error messages

- Add error recovery strategies

**Instructions:**

- Search for all `except Exception:` in daemon modules

- Replace with specific exception types

- Add retry logic where appropriate

- Improve error messages (user-friendly)

- Document error recovery strategies

**Git Commit (after completion):**
```
fix: Replace generic exception handling with specific exceptions

- Replace all 'except Exception:' with specific exception types
- Add retry logic for transient failures
- Improve error messages and recovery strategies
```

---

## Phase 4: Security and Best Practices

### Chunk 4.1: Secure Configuration Handling

**Priority:** High (security)

**Risk:** Low (enhancing existing code)

**Dependencies:** Chunk 1.4 (ConfigValidator)

**Files to modify:**

- Config loading code

- `shared_tools/daemon/config_validator.py`

**Deliverables:**

- Environment variable support for sensitive data

- Config file permission validation
- Secure config loading

- Validation on config load

**Instructions:**

- Add environment variable support for API keys

- Check config file permissions (chmod 600 for personal config)

- Validate config on load

- Document secure configuration practices

**Git Commit (after completion):**
```
feature: Add secure configuration handling

- Support environment variables for sensitive data
- Validate config file permissions
- Enhance ConfigValidator with security checks
```

---

### Chunk 4.2: Improve Subprocess Security

**Priority:** High (security)

**Risk:** Low (improving existing code)

**Dependencies:** None

**Files to modify:**

- All files with subprocess calls

**Deliverables:**

- Safe subprocess utility functions
- Use `shlex.quote()` for arguments

- Never use `shell=True` with user input

- Validate script paths

**Instructions:**

- Find all subprocess calls

- Create safe subprocess wrapper

- Use list form of subprocess.run

- Validate all inputs
- Document safe practices

**Git Commit (after completion):**
```
fix: Improve subprocess security across codebase

- Create safe subprocess wrapper functions
- Use shlex.quote() for arguments
- Remove shell=True usage with user input
- Validate script paths
```

---

### Chunk 4.3: Add Type Hints Throughout

**Priority:** Medium (code quality)

**Risk:** Low (adding type hints, non-breaking)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules

**Deliverables:**

- Type hints for all functions

- Return type annotations

- Parameter type annotations

- Use of typing module (Optional, Dict, List, Tuple, Any)

**Instructions:**

- Add type hints to all functions

- Use mypy-compatible annotations

- Handle Optional types correctly

- Document type expectations

---

### Chunk 4.4: Set Up Type Checking

**Priority:** Low (tooling)

**Risk:** Low (adding tooling)

**Dependencies:** Chunk 4.3

**Files to create:**

- `mypy.ini` or `pyproject.toml` (mypy config)

**Files to modify:**

- Add mypy to development dependencies

**Deliverables:**

- mypy configuration

- Type checking in CI (if applicable)

- Fix type errors (target: <5 errors)

- Type checking documentation

**Instructions:**

- Configure mypy for the project

- Run mypy and fix errors

- Document type checking practices

- Add to development workflow

**Git Commit (after completion):**
```
minor: Set up type checking with mypy

- Add mypy configuration
- Fix type errors (target: <5 errors)
- Document type checking practices
```

---

## Phase 5: Documentation and Polish

### Chunk 5.1: Write Architecture Documentation

**Priority:** Medium (documentation)

**Risk:** Low (documentation only)

**Dependencies:** All previous phases

**Files to create:**

- `docs/ARCHITECTURE.md`

**Deliverables:**

- System architecture overview

- Module responsibilities

- Data flow diagrams

- Key design decisions

- Integration patterns

**Instructions:**

- Document overall architecture

- Describe each module's responsibilities
- Create data flow diagrams (Mermaid)

- Document design decisions and rationale

- Include integration examples

**Git Commit (after completion):**
```
feature: Add architecture documentation

- Create docs/ARCHITECTURE.md
- Document system architecture and module responsibilities
- Add data flow diagrams and design decisions
```

---

### Chunk 5.2: Create Upgrade Guide

**Priority:** Low (documentation)

**Risk:** Low (documentation only)

**Dependencies:** All previous phases

**Files to create:**

- `docs/UPGRADE.md`

**Deliverables:**

- Upgrade process documentation

- Breaking changes log

- Migration scripts (if needed)
- Version compatibility matrix

**Instructions:**

- Document upgrade process

- List breaking changes

- Provide migration guidance
- Include version compatibility info

**Git Commit (after completion):**
```
feature: Create upgrade guide

- Create docs/UPGRADE.md
- Document upgrade process and breaking changes
- Provide migration guidance
```

---

### Chunk 5.3: Update Configuration Documentation

**Priority:** Medium (usability)

**Risk:** Low (documentation only)

**Dependencies:** Chunk 1.3, Chunk 1.4

**Files to modify:**

- `config.conf` (comments)

- Configuration documentation

**Deliverables:**

- Updated config.conf with SERVICE_RESILIENCE section

- Documentation for new config options

- Examples for distributed setup
- Validation requirements

**Instructions:**

- Add SERVICE_RESILIENCE section to config.conf

- Document all new config options

- Provide examples for blacktower/P1 setup

- Document validation requirements

**Git Commit (after completion):**
```
minor: Update configuration documentation

- Add SERVICE_RESILIENCE section to config.conf
- Document new config options
- Add examples for distributed setup (blacktower/P1)
```

---

## Phase 6: Codebase Cleanup

### Chunk 6.1: Clean Up Original Daemon File

**Priority:** High (final cleanup of refactored code)

**Risk:** Medium (removing code, need to ensure nothing broken)

**Dependencies:** All Phase 2 chunks (extraction complete), Chunk 2.8 (core extraction)

**Files to modify:**

- `scripts/paper_processor_daemon.py`

**Files to verify:**

- `scripts/pdf_self_fixer.py` (inherits from PaperProcessorDaemon - ensure it still works)
- Other scripts that may import from daemon

**Deliverables:**

- Remove all extracted methods (file operations, PDF processing, metadata workflow, Zotero workflow, user interaction, display)
- Remove unused imports (only keep imports for core daemon functionality)
- Remove unused helper methods that were replaced by modules
- Remove commented-out code from refactoring
- File size should be significantly reduced (target: <2000 lines)
- Clean, focused daemon file with only core functionality

**Instructions:**

- Verify all extracted methods are not referenced in remaining code
- Remove methods that were extracted to modules
- Check for unused imports (use tools like `pylint` or `flake8` with unused-import warnings)
- Remove commented-out code blocks
- Remove duplicate helper functions that exist in modules
- Ensure daemon still functions correctly (run tests)
- Document any methods kept for backward compatibility

**Verification:**

- Run daemon and test basic functionality
- Check that all imports are used
- Verify no broken references
- Check file size reduction

**Git Commit (after completion):**
```
minor: Clean up original daemon file after modularization

- Remove extracted methods (now in modules)
- Remove unused imports
- Remove commented-out code
- Reduce file size significantly (<2000 lines)
- Verify pdf_self_fixer.py still works
```

---

### Chunk 6.2: Remove Unused Imports Across All Modules

**Priority:** Medium (code quality)

**Risk:** Low (removing unused imports, non-breaking)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules (shared_tools/daemon/*.py)
- `scripts/paper_processor_daemon.py`
- All scripts in `scripts/` directory (check for unused imports)

**Deliverables:**

- No unused imports in any module
- Clean import statements (no duplicate imports)
- Organized imports (stdlib, third-party, local)
- All imports are actually used in the file

**Instructions:**

- Use tools to detect unused imports (pylint, flake8, or autoflake)
- Remove unused imports from all daemon modules
- Organize imports (PEP 8 style: stdlib, third-party, local)
- Remove duplicate imports
- Verify functionality still works

**Verification:**

- Run linter to check for unused imports
- Run tests to ensure nothing broken
- Manual review of import statements

**Git Commit (after completion):**
```
minor: Remove unused imports across codebase

- Clean up unused imports in all daemon modules
- Clean up unused imports in scripts
- Organize imports (PEP 8 style)
- Remove duplicate imports
```

---

### Chunk 6.3: Remove Duplicated Code

**Priority:** Medium (code quality)

**Risk:** Low (consolidating code)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules
- Any scripts using duplicated code (check all scripts in `scripts/` directory)

**Deliverables:**

- No duplicated code blocks
- All common functionality uses shared utilities
- Single source of truth for each operation
- Consistent implementation patterns

**Instructions:**

- Search for duplicated code patterns (use tools like jscpd or manual review)
- Identify common patterns that should use shared utilities
- Consolidate duplicated logic into shared functions
- Update all call sites to use consolidated code
- Remove duplicate implementations

**Verification:**

- Run tests to ensure functionality unchanged
- Review code for consistency
- Check for similar patterns that can be unified

**Git Commit (after completion):**
```
minor: Remove duplicated code across codebase

- Consolidate duplicated logic into shared functions
- Update all call sites to use consolidated code
- Ensure single source of truth for each operation
```

---

### Chunk 6.4: Remove Commented-Out Code and Dead Code

**Priority:** Medium (code cleanliness)

**Risk:** Low (removing unused code)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules
- `scripts/paper_processor_daemon.py`
- All scripts in `scripts/` directory (check for commented-out code)

**Deliverables:**

- No commented-out code blocks (unless documenting why something is disabled)
- No unreachable code
- No dead code paths
- Clean, readable code

**Instructions:**

- Search for large commented-out code blocks
- Remove commented-out code that was replaced by modules
- Remove unreachable code (after return statements, etc.)
- Keep only comments that explain "why", not "what"
- If code is intentionally disabled, add a comment explaining why

**Verification:**

- Code review for commented-out blocks
- Run static analysis tools
- Ensure code still functions correctly

**Git Commit (after completion):**
```
minor: Remove commented-out code and dead code paths

- Remove commented-out code blocks from refactoring
- Remove unreachable code (after return statements, etc.)
- Clean up dead code paths
```

---

### Chunk 6.5: Remove Obsolete Helper Functions

**Priority:** Medium (code quality)

**Risk:** Medium (removing functions, need to verify not used)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- `scripts/paper_processor_daemon.py`
- Any other files with obsolete helpers (check all scripts)

**Deliverables:**

- No obsolete helper functions (replaced by module methods)
- All helper functions are actually used
- Clear separation: helpers in modules, core logic in daemon

**Instructions:**

- Identify helper functions that were replaced by module methods
- Verify functions are not used anywhere (grep/search codebase)
- Remove obsolete helper functions
- Keep only helpers that are daemon-specific and not in modules

**Verification:**

- Search codebase for function names before removing
- Run tests to ensure nothing broken
- Check for any imports of removed functions

**Git Commit (after completion):**
```
minor: Remove obsolete helper functions

- Remove helper functions replaced by module methods
- Verify functions are unused before removing
- Keep only daemon-specific helpers
```

---

### Chunk 6.6: Clean Up Temporary Files and Backups

**Priority:** Low (housekeeping)

**Risk:** Low (removing temporary files)

**Dependencies:** All previous phases

**Files to check/remove:**

- Any `.bak` files created during refactoring
- Any temporary test files
- Any backup copies of files

**Deliverables:**

- No temporary files from refactoring
- No backup files (unless intentionally kept)
- Clean repository structure

**Instructions:**

- Search for `.bak` files (especially from UltraEdit as mentioned in rules)
- Check for temporary files with patterns like `*.tmp`, `*_backup.*`, `*_old.*`
- Remove temporary files created during refactoring
- Keep only intentional backups (documented)
- Update .gitignore if needed

**Verification:**

- List all files in repository
- Check for temporary file patterns
- Verify no important files removed

**Git Commit (after completion):**
```
minor: Clean up temporary files and backups

- Remove .bak files from refactoring
- Remove temporary test files
- Clean repository structure
- Update .gitignore if needed
```

---

### Chunk 6.7: Ensure Consistent Code Style

**Priority:** Medium (code quality)

**Risk:** Low (formatting only)

**Dependencies:** All Phase 2 chunks

**Files to modify:**

- All daemon modules
- All scripts in `scripts/` directory (ensure consistent style)

**Deliverables:**

- Consistent code style across all modules
- PEP 8 compliant code
- Consistent naming conventions
- Consistent formatting (spacing, indentation, etc.)

**Instructions:**

- Run code formatter (black, autopep8, or similar)
- Ensure consistent naming (camelCase vs snake_case)
- Consistent docstring style (Google style)
- Consistent error handling patterns
- Consistent logging patterns

**Verification:**

- Run linter (pylint, flake8)
- Run formatter in check mode
- Manual review for consistency

**Git Commit (after completion):**
```
minor: Ensure consistent code style across codebase

- Apply PEP 8 formatting to all modules
- Ensure consistent naming conventions
- Consistent docstring style (Google style)
- Consistent error handling and logging patterns
```

---

### Chunk 6.8: Remove Dead Code Paths

**Priority:** Medium (code quality)

**Risk:** Low (removing unreachable code)

**Dependencies:** All Phase 2 chunks, Chunk 6.4

**Files to modify:**

- All daemon modules
- All scripts in `scripts/` directory

**Deliverables:**

- No unreachable code paths
- No code after return statements (in same block)
- No code in conditional blocks that can never be true
- Clean control flow

**Instructions:**

- Use static analysis tools to detect unreachable code
- Remove code after return statements
- Remove impossible conditional branches
- Simplify control flow where possible

**Verification:**

- Run static analysis tools (pylint, mypy)
- Manual code review
- Run tests to ensure functionality unchanged

**Git Commit (after completion):**
```
minor: Remove dead code paths

- Remove unreachable code
- Simplify control flow
- Clean up impossible conditional branches
```

---

### Chunk 6.9: Update and Clean Documentation

**Priority:** Medium (documentation quality)

**Risk:** Low (documentation only)

**Dependencies:** All previous phases

**Files to modify:**

- `docs/Modularization plan.md` (mark as completed or archive)
- Any outdated documentation
- README files if needed

**Deliverables:**

- Updated documentation reflecting new structure
- Removed obsolete documentation
- Clean documentation structure
- All documentation is current and accurate

**Instructions:**

- Review `docs/Modularization plan.md` - mark completed chunks or archive
- Remove outdated documentation
- Update any documentation referencing old structure
- Ensure ARCHITECTURE.md reflects final structure
- Update README if structure changed significantly

**Verification:**

- Review all documentation files
- Check for references to old structure
- Ensure documentation matches code structure

**Git Commit (after completion):**
```
minor: Update and clean documentation after modularization

- Mark modularization plan as completed
- Remove outdated documentation
- Update documentation to reflect new structure
- Ensure ARCHITECTURE.md is current
```

---

### Chunk 6.10: Final Codebase Verification

**Priority:** High (quality assurance)

**Risk:** Low (verification only)

**Dependencies:** All cleanup chunks (6.1-6.9)

**Files to verify:**

- All daemon modules
- `scripts/paper_processor_daemon.py`
- Tests

**Deliverables:**

- Clean codebase verification report
- All tests passing
- No linting errors
- No unused imports
- No dead code
- Consistent code style
- Documentation up to date

**Instructions:**

- Run full test suite
- Run linter on all files
- Check for unused imports
- Verify no dead code
- Review code style consistency
- Verify documentation accuracy
- Create verification report

**Verification:**

- All tests pass
- Linter reports clean
- Code review checklist complete
- Documentation review complete

**Git Commit (after completion):**
```
minor: Final codebase verification after modularization

- Run full test suite (all tests passing)
- Linter reports clean
- No unused imports or dead code
- Consistent code style
- Documentation up to date
- Clean codebase verification complete
```

---

## Implementation Guidelines

### Dependency Graph

```javascript
Phase 1 (Foundation):
  1.1 (Exceptions) → 1.3, 1.4, 2.x (all use exceptions)
  1.2 (Constants) → 2.x (all use constants)
  1.3 (ServiceManager) → 2.3 (integration)
  1.4 (ConfigValidator) → 4.1 (security)
  1.5 (PathUtils) → 2.1 (file operations)

Phase 2 (Refactoring):
  2.1-2.7 (Extract modules) → 2.8 (Core extraction)
  2.1-2.8 → 2.9 (Break down methods)
  2.1-2.9 → 2.10 (Docstrings)

Phase 3 (Testing):
  3.x depends on corresponding 2.x modules

Phase 4 (Best Practices):
  4.1 depends on 1.4
  4.3 depends on Phase 2
  4.4 depends on 4.3

Phase 5 (Documentation):
  5.x depends on all previous phases

Phase 6 (Cleanup):
  6.1 depends on Phase 2 (especially 2.8)
  6.2-6.5 depend on Phase 2
  6.6 depends on all phases
  6.7-6.8 depend on Phase 2
  6.9 depends on all phases
  6.10 depends on all cleanup chunks (6.1-6.9)
```

### Risk Mitigation

1. **Low Risk Chunks First**: Create new files (exceptions, constants) before refactoring

2. **Incremental Integration**: Extract modules one at a time, test after each

3. **Backward Compatibility**: Keep daemon working after each extraction

4. **Testing**: Add tests as modules are extracted

5. **Documentation**: Document as you go, not at the end

### Agent Instructions Template

For each chunk, provide:

- **Objective**: What this chunk accomplishes

- **Dependencies**: Which chunks must be completed first

- **Files**: Exact files to create/modify

- **Deliverables**: Specific outputs expected

- **Testing**: How to verify completion

- **Rollback**: How to undo if something goes wrong

### Success Criteria

- Each chunk can be completed independently
- No chunk conflicts with another
- Daemon remains functional after each chunk
- Final codebase is clean and maintainable
- No unused code or imports
- Consistent code style throughout
- Documentation is up to date

### Cleanup Principles

1. **Verify Before Removing**: Always verify code is unused before removing
2. **Incremental Cleanup**: Clean up as you extract, not all at the end
3. **Test After Cleanup**: Run tests after each cleanup chunk
4. **Document Decisions**: If keeping code, document why
5. **Backup If Uncertain**: When in doubt, comment out before removing
6. **Use Tools**: Leverage linting and static analysis tools
7. **Code Review**: Review cleanup changes before committing

