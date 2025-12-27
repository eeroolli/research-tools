# Paper Processor Daemon - UX Flow Chart

**Last Updated:** January 2025  
**Status:** Current implementation with path utilities refactoring

## Overview

This document describes the complete user experience flow for the paper processor daemon, including recent improvements to path handling and file operations.

---

## Main Processing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                    SCANNER WORKFLOW                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  1. File Detection (Watchdog)                                   │
│     - PDF detected in watch directory                           │
│     - Language prefix detected (NO_, EN_, DE_, FI_, SV_, DA_)   │
│     - File moved to processing queue                            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  2. Metadata Extraction                                         │
│     ├─ GROBID extraction (first 2 pages)                        │
│     ├─ Regex identifier extraction (DOI, arXiv, URL, JSTOR)     │
│     ├─ Document type detection                                  │
│     └─ Fallback to Ollama if needed                             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  3. Year Confirmation                                           │
│     - Multi-source validation (GREP, GROBID, API)               │
│     - Conflict detection and resolution                          │
│     - Manual entry option                                       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  4. Document Type Selection                                     │
│     - Auto-detection with confirmation                          │
│     - Manual selection menu (journal, book, chapter, etc.)       │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  5. Author Selection                                            │
│     - Interactive author list with letters (a-z)                 │
│     - Zotero recognition (paper counts)                         │
│     - Options: select order, edit, add, delete                   │
│     - Commands: 'a', 'ab', 'all', 'e', 'n', '-a', 'z', 'r'      │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  6. Zotero Search                                               │
│     - Search by selected authors + year                         │
│     - Local Zotero database query                               │
│     - Results displayed with match quality scores                │
└─────────────────────────────────────────────────────────────────┘
                              │
                    ┌─────────┴─────────┐
                    │                   │
            ┌───────▼───────┐   ┌───────▼───────┐
            │  MATCHES      │   │  NO MATCHES   │
            │  FOUND        │   │  FOUND        │
            └───────┬───────┘   └───────┬───────┘
                    │                   │
                    ▼                   ▼
```

---

## Zotero Matches Found - User Actions

```
┌─────────────────────────────────────────────────────────────────┐
│  ZOTERO MATCHES DISPLAYED                                       │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  [A-Z] Select item from list above                       │  │
│  │  [1] 🔍 Change author/year search parameters              │  │
│  │  [2] 🔍 Change all search parameters                      │  │
│  │  [3] None of these items - create new                     │  │
│  │  [4] ❌ Skip document                                     │  │
│  │  (z) ⬅️  Back to author selection                         │  │
│  │  (r) 🔄 Restart from beginning                            │  │
│  │  (q) Quit daemon                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ [A-Z] Select  │   │ [1] Change    │   │ [2] Change    │
│ Item          │   │ Author/Year   │   │ All Params    │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                     │
        │                   ▼                     ▼
        │           ┌───────────────┐   ┌───────────────┐
        │           │ Author        │   │ Full Metadata │
        │           │ Selection     │   │ Editor        │
        │           │ (select/edit) │   │ (all fields)  │
        │           └───────┬───────┘   └───────┬───────┘
        │                   │                     │
        │                   └─────────┬───────────┘
        │                             │
        │                             ▼
        │                     ┌───────────────┐
        │                     │ Re-search      │
        │                     │ Zotero         │
        │                     └───────┬───────┘
        │                             │
        └─────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Item Selected         │
        └───────────┬───────────┘
                    │
                    ▼
```

---

## Item Selected - 3-Step Attachment Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  STEP 1: Metadata Comparison                                    │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  EXTRACTED METADATA    │    ZOTERO ITEM METADATA         │  │
│  │  ────────────────────  │    ─────────────────────        │  │
│  │  Title: ...            │    Title: ...                   │  │
│  │  Authors: ...          │    Authors: ...                 │  │
│  │  Year: ...             │    Year: ...                    │  │
│  │  Journal: ...           │    Journal: ...                 │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                   │
│  Options:                                                        │
│  [1] Use extracted metadata (Replace in Zotero)                 │
│  [2] Use Zotero metadata as-is (Keep existing)                  │
│  [3] Merge both (field-by-field comparison)                      │
│  [4] Edit manually                                               │
│  [5] 🔍 Search for more metadata online                          │
│  [6] 📝 Manual processing later                                  │
│  [7] 📄 Create new Zotero item from extracted metadata            │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 2: Tags Comparison                                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  Current tags: [tag1] [tag2] [tag3]                       │  │
│  │  Options: Add, Remove, Edit tags interactively            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STEP 3: PDF Attachment                                         │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  1/4 Preparing split for two-up file (if needed)           │  │
│  │  2/4 Copying to publications directory                     │  │
│  │  3/4 Attaching to Zotero item                              │  │
│  │  4/4 Moving original to done/                              │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## No Zotero Matches Found - User Actions

```
┌─────────────────────────────────────────────────────────────────┐
│  NO MATCHES FOUND                                               │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  WHAT WOULD YOU LIKE TO DO?                               │  │
│  │  [1] 📄 Create new Zotero item with extracted metadata    │  │
│  │  [2] ✏️  Edit metadata before creating item               │  │
│  │  [3] 🔍 Search Zotero with additional info                 │  │
│  │  [4] ❌ Skip document (not academic)                       │  │
│  │  [5] 📝 Manual processing later                            │  │
│  │  (q) Quit daemon                                            │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        │                     │                     │
        ▼                     ▼                     ▼
┌───────────────┐   ┌───────────────┐   ┌───────────────┐
│ [1] Create    │   │ [2] Edit      │   │ [3] Search    │
│ New Item      │   │ Metadata      │   │ Again         │
└───────┬───────┘   └───────┬───────┘   └───────┬───────┘
        │                   │                     │
        │                   ▼                     │
        │           ┌───────────────┐             │
        │           │ Full Metadata │             │
        │           │ Editor        │             │
        │           └───────┬───────┘             │
        │                   │                     │
        │                   └─────────┬───────────┘
        │                             │
        └─────────────────────────────┘
                    │
                    ▼
        ┌───────────────────────┐
        │ Create New Item       │
        └───────────┬───────────┘
                    │
                    ▼
```

---

## File Operations Flow (With Path Utilities)

```
┌─────────────────────────────────────────────────────────────────┐
│  PDF COPY OPERATION                                             │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  1. Source Path Validation                                 │  │
│  │     ├─ Check if file exists (WSL check)                   │  │
│  │     └─ Validate via PowerShell if needed                   │  │
│  │                                                             │  │
│  │  2. Path Conversion                                         │  │
│  │     ├─ Normalize to WSL format (_normalize_path)           │  │
│  │     ├─ Convert to Windows (_convert_wsl_to_windows_path)   │  │
│  │     └─ Uses path_utils.ps1 for robust conversion           │  │
│  │                                                             │  │
│  │  3. Copy Method Selection                                  │  │
│  │     ├─ Try native Python copy first (shutil.copy2)        │  │
│  │     │  └─ Fast, works for WSL-accessible paths            │  │
│  │     └─ Fallback to PowerShell if needed                   │  │
│  │        └─ Uses path_utils.ps1 copy-file command           │  │
│  │           └─ Handles cloud drives (Google Drive, etc.)    │  │
│  │                                                             │  │
│  │  4. Verification                                            │  │
│  │     ├─ File size check                                     │  │
│  │     └─ Hash verification (if PowerShell copy)             │  │
│  │                                                             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

### Path Utilities Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  PATH UTILITIES SYSTEM                                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  Python Layer (paper_processor_daemon.py)                  │  │
│  │  ├─ _normalize_path()          - WSL/Windows normalization │  │
│  │  ├─ _get_path_utils_script_win() - Script path helper     │  │
│  │  ├─ _convert_wsl_to_windows_path() - Path conversion     │  │
│  │  ├─ _validate_path_via_powershell() - Path validation     │  │
│  │  └─ _copy_file_universal()     - Universal copy method     │  │
│  │                                                             │  │
│  │  PowerShell Layer (path_utils.ps1)                         │  │
│  │  ├─ convert-wsl-to-windows    - Path conversion           │  │
│  │  ├─ convert-windows-to-wsl    - Reverse conversion        │  │
│  │  ├─ test-path                  - File validation          │  │
│  │  ├─ test-directory             - Directory validation      │  │
│  │  ├─ ensure-directory           - Directory creation        │  │
│  │  └─ copy-file                  - File copy with verify    │  │
│  │                                                             │  │
│  │  Benefits:                                                  │  │
│  │  ✓ Works with cloud drives not accessible from WSL         │  │
│  │  ✓ Intelligent fallback (native Python → PowerShell)       │  │
│  │  ✓ JSON responses for programmatic use                     │  │
│  │  ✓ Universal and reusable across projects                  │  │
│  │                                                             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Recent Improvements (January 2025)

### 1. Menu Clarity Improvements
- **Before:** "[2] ✏️ Edit metadata" (confusing - edits search params, not Zotero item)
- **After:** "[2] 🔍 Change all search parameters" (clear distinction)
- **Impact:** Users understand they're editing search parameters, not Zotero item metadata

### 2. Universal Path Utilities
- **Created:** `path_utils.ps1` - Universal PowerShell utility for path operations
- **Created:** Helper methods in Python for consistent path handling
- **Benefit:** Works reliably with cloud drives (Google Drive, OneDrive) that aren't accessible from WSL

### 3. Intelligent File Copy
- **Method:** `_copy_file_universal()` - Tries native Python first, falls back to PowerShell
- **Benefit:** Fast for local paths, robust for cloud drives
- **Handles:** `/tmp/` paths, cloud drive paths, path conversion failures

### 4. Path Validation
- **Method:** `_validate_path_via_powershell()` - Validates paths from Windows perspective
- **Benefit:** Catches path issues before attempting operations
- **Use:** Validates source files exist before copying

---

## Planned Refactoring (See REFACTORING_PLAN.md)

### Step 1: Generalized Script Path Helper
- Create `_get_script_path_win(script_name)` for any PowerShell script
- Refactor `_get_path_utils_script_win()` to use it

### Step 2: Remove Duplicate Methods
- Remove `_windows_to_wsl_path()` (use `_normalize_path()` instead)
- Update `_to_windows_path()` to use `_convert_wsl_to_windows_path()`

### Step 3: Consolidate Standalone Function
- Make `_normalize_path()` static method
- Update `normalize_path_for_wsl()` to call static method

**Impact:** Cleaner code, less duplication, easier maintenance

---

## Error Handling Flow

```
┌─────────────────────────────────────────────────────────────────┐
│  ERROR HANDLING                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                                                             │  │
│  │  Path Conversion Failure                                   │  │
│  │  ├─ Try wslpath first                                      │  │
│  │  ├─ Fallback to manual conversion                          │  │
│  │  └─ Use path_utils.ps1 if available                         │  │
│  │                                                             │  │
│  │  File Copy Failure                                         │  │
│  │  ├─ Native Python fails → Try PowerShell                    │  │
│  │  ├─ PowerShell fails → Clear error message                  │  │
│  │  └─ Move to manual_review/                                  │  │
│  │                                                             │  │
│  │  Source File Not Found                                     │  │
│  │  ├─ Validate via PowerShell (Windows perspective)          │  │
│  │  ├─ Check if path conversion issue                         │  │
│  │  └─ Provide clear error message                            │  │
│  │                                                             │  │
│  │  Cloud Drive Not Accessible                                │  │
│  │  ├─ Native Python copy fails                               │  │
│  │  ├─ Automatically fallback to PowerShell                   │  │
│  │  └─ PowerShell handles cloud drive access                  │  │
│  │                                                             │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## User Decision Points

### Decision Point 1: Zotero Match Found
- **Select item** → Proceed to 3-step attachment workflow
- **Change search params** → Return to author selection
- **Create new** → Skip to new item creation
- **Skip** → Move to manual_review/

### Decision Point 2: Metadata Comparison
- **Use extracted** → Replace Zotero metadata
- **Use Zotero** → Keep existing metadata
- **Merge** → Field-by-field comparison
- **Edit manually** → Full metadata editor
- **Search online** → Additional metadata sources
- **Manual processing** → Move to manual_review/

### Decision Point 3: PDF Attachment
- **Keep both** → Add with `_scan` suffix
- **Replace** → Overwrite existing PDF
- **Skip** → Create item without attachment

---

## Navigation Options

Throughout the workflow, users can:
- **(z)** Go back to previous step
- **(r)** Restart from beginning
- **(q)** Quit daemon

These options are available at most decision points.

---

## File Locations

### Input
- **Watch directory:** `/mnt/i/FraScanner/papers/` (or configured path)
- **Language prefixes:** `NO_`, `EN_`, `DE_`, `FI_`, `SV_`, `DA_`

### Processing
- **Split PDFs:** System temp directory (e.g., `/tmp/pdf_splits/`)
- **Border removal:** System temp directory (e.g., `/tmp/pdf_borders_removed/`)

### Output
- **Publications:** Configured path (e.g., `/mnt/g/My Drive/publications/`)
- **Done:** `watch_dir/done/`
- **Manual review:** `watch_dir/manual_review/`
- **Failed:** `watch_dir/failed/`
- **Skipped:** `watch_dir/skipped/`

---

## Related Documentation

- **PATH_UTILS_README.md** - Detailed documentation on path utilities
- **REFACTORING_PLAN.md** - Planned code improvements
- **implementation-plan.md** - Overall system architecture
- **SCANNER_SETUP.md** - Scanner configuration and setup

---

## Notes

- All path operations use universal utilities that work with both WSL and Windows
- Cloud drives are handled automatically via PowerShell fallback
- File operations are validated before execution
- Clear error messages guide users when issues occur
- Navigation is consistent throughout the workflow

