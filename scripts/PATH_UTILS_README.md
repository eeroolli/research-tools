# Path Utilities for WSL/Windows

A universal PowerShell utility and Python wrapper for handling file paths and operations in WSL (Windows Subsystem for Linux) environments, with special support for cloud drives (Google Drive, OneDrive, etc.) that may not be accessible from WSL but are accessible from Windows PowerShell.

## Quick Reference

```powershell
# Convert paths
powershell.exe -File path_utils.ps1 convert-wsl-to-windows "/mnt/g/My Drive/publications"
powershell.exe -File path_utils.ps1 convert-windows-to-wsl "G:\My Drive\publications"

# Validate paths
powershell.exe -File path_utils.ps1 test-path "G:\My Drive\publications"
powershell.exe -File path_utils.ps1 test-directory "G:\My Drive\publications"

# File operations
powershell.exe -File path_utils.ps1 ensure-directory "G:\My Drive\new_folder"
powershell.exe -File path_utils.ps1 copy-file "source.pdf" "target.pdf" [-Replace]
```

All commands return JSON for programmatic use. See [PowerShell Usage](#powershell-usage) for details.

## Problem Statement

When working with WSL, you may encounter situations where:

1. **Cloud drives aren't accessible from WSL**: Google Drive, OneDrive, and other cloud storage services mounted as Windows drives (e.g., `G:\My Drive\`) may not be accessible from WSL even when mounted, causing `wslpath` to fail with "No such device" errors.

2. **Path conversion is unreliable**: The standard `wslpath` command fails when drives aren't accessible, making it impossible to convert paths like `/mnt/g/My Drive/publications` to `G:\My Drive\publications`.

3. **File operations fail**: Native Python `shutil.copy2()` fails when trying to copy files to cloud drives that aren't accessible from WSL.

## Solution

This utility provides:

- **Path conversion** without relying on `wslpath` (works even when drives aren't accessible from WSL)
- **Path validation** from Windows perspective (where cloud drives are accessible)
- **Intelligent file copying** that tries native Python first, then falls back to PowerShell
- **JSON-based responses** for programmatic use

## Files

- **`path_utils.ps1`**: Universal PowerShell utility with multiple commands
- **Python wrapper methods**: Integrated into `paper_processor_daemon.py` (refactored for consistency and maintainability)

## Refactoring Status

The path utilities have been refactored (see `REFACTORING_PLAN.md` for details) to:
- Eliminate code duplication
- Use centralized helper methods
- Improve maintainability
- Maintain backward compatibility

**Key improvements:**
- `_get_script_path_win()` - Generalized helper for any PowerShell script
- `_normalize_path()` - Now a static method with better sanitization
- `_to_windows_path()` - Uses robust PowerShell helper with fallback
- Removed duplicate `_windows_to_wsl_path()` method
- `normalize_path_for_wsl()` - Now calls static `_normalize_path()` method

## PowerShell Usage

### Basic Commands

```powershell
# Convert WSL path to Windows path
powershell.exe -File path_utils.ps1 convert-wsl-to-windows "/mnt/g/My Drive/publications"
# Output: G:\My Drive\publications

# Convert Windows path to WSL path
powershell.exe -File path_utils.ps1 convert-windows-to-wsl "G:\My Drive\publications"
# Output: /mnt/g/My Drive/publications

# Test if path exists (returns JSON)
powershell.exe -File path_utils.ps1 test-path "G:\My Drive\publications"
# Output: {"exists":true,"isFile":false,"isDirectory":true,"accessible":true,"error":null}

# Test directory accessibility (returns JSON)
powershell.exe -File path_utils.ps1 test-directory "G:\My Drive\publications"
# Output: {"exists":true,"accessible":true,"writable":true,"error":null}

# Ensure directory exists (creates if needed, returns JSON)
powershell.exe -File path_utils.ps1 ensure-directory "G:\My Drive\new_folder"
# Output: {"exists":true,"created":true,"accessible":true,"error":null}

# Copy file with verification (returns JSON)
powershell.exe -File path_utils.ps1 copy-file "C:\source\file.pdf" "G:\My Drive\target\file.pdf"
powershell.exe -File path_utils.ps1 copy-file "C:\source\file.pdf" "G:\My Drive\target\file.pdf" -Replace
```

### Exit Codes

- `0` = Success
- `1` = Invalid command or missing arguments
- `2` = Path conversion failed
- `3` = Path validation/copy failed
- `4` = Source file not found
- `5` = Target exists but differs (when -Replace not specified)
- `6` = Copy operation failed
- `7` = Verification failed

### JSON Response Format

All commands that return JSON follow this structure:

**test-path:**
```json
{
  "exists": true,
  "isFile": false,
  "isDirectory": true,
  "accessible": true,
  "error": null
}
```

**test-directory:**
```json
{
  "exists": true,
  "accessible": true,
  "writable": true,
  "error": null
}
```

**ensure-directory:**
```json
{
  "exists": true,
  "created": true,
  "accessible": true,
  "error": null
}
```

**copy-file:**
```json
{
  "success": true,
  "error": null,
  "errorCode": 0,
  "message": "File copied and verified",
  "sourceSize": 1048576,
  "targetSize": 1048576,
  "sourceSizeMB": 1.0,
  "copied": true,
  "verified": true
}
```

## Python Usage

### Example: Universal File Copy

```python
from pathlib import Path

def copy_file_universal(source_path: Path, target_path: Path, replace_existing: bool = False) -> tuple:
    """Universal file copy that tries native Python first, falls back to PowerShell.
    
    Returns:
        Tuple of (success: bool, error_msg: Optional[str])
    """
    # First, try native Python copy (fastest, works for most paths)
    try:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        if target_path.exists() and not replace_existing:
            return (False, f"Target file already exists: {target_path}")
        
        if target_path.exists() and replace_existing:
            target_path.unlink()
        
        shutil.copy2(source_path, target_path)
        
        # Verify copy
        if not target_path.exists():
            return (False, "Target file not found after copy")
        
        source_size = source_path.stat().st_size
        target_size = target_path.stat().st_size
        if source_size != target_size:
            target_path.unlink()
            return (False, f"Size mismatch")
        
        return (True, None)
        
    except (OSError, PermissionError, FileNotFoundError):
        # Native copy failed - likely a cloud drive not accessible from WSL
        # Fall back to PowerShell
        return copy_file_via_powershell(source_path, target_path, replace_existing)
```

### Example: Path Conversion

The refactored codebase uses centralized helper methods:

```python
from scripts.paper_processor_daemon import PaperProcessorDaemon

# Create daemon instance (or use static methods)
daemon = PaperProcessorDaemon(watch_dir)

# Convert WSL to Windows path (uses PowerShell utility with fallback)
wsl_path = "/mnt/g/My Drive/publications"
windows_path = daemon._convert_wsl_to_windows_path(wsl_path)
# Returns: G:\My Drive\publications

# Normalize path to WSL format (static method, can be called standalone)
win_path = "G:\\My Drive\\publications"
wsl_path = PaperProcessorDaemon._normalize_path(win_path)
# Returns: /mnt/g/My Drive/publications

# Or use standalone function (wrapper around static method)
from scripts.paper_processor_daemon import normalize_path_for_wsl
wsl_path = normalize_path_for_wsl(win_path)
# Returns: /mnt/g/My Drive/publications

# Convert Path object to Windows path (for Zotero attachments)
from pathlib import Path
wsl_path_obj = Path("/mnt/g/My Drive/paper.pdf")
windows_path = daemon._to_windows_path(wsl_path_obj)
# Returns: G:\My Drive\paper.pdf
```

**Key Methods (after refactoring):**

- `_get_script_path_win(script_name: str)` - Generalized helper to get Windows path for any PowerShell script
- `_normalize_path(path_str: str)` - Static method to normalize paths to WSL format (with sanitization)
- `normalize_path_for_wsl(path_str: str)` - Standalone function wrapper (calls static `_normalize_path()`)
- `_convert_wsl_to_windows_path(wsl_path: str)` - Converts WSL→Windows using PowerShell utility
- `_to_windows_path(path: Path)` - Converts Path object to Windows format (uses `_convert_wsl_to_windows_path()` with fallback)

## Design Philosophy

### Why Not Use Standard Libraries?

We investigated existing solutions:

- **`shutil` + `pathlib`**: Standard library handles cross-platform operations but doesn't handle WSL→Windows path conversion or cloud drives inaccessible from WSL.
- **Third-party libraries**: No production-quality library found that specifically handles WSL path conversion when `wslpath` fails or provides automatic fallback to PowerShell for cloud drives.

### Why This Approach?

1. **Tries native Python first**: Fast and simple for WSL-accessible paths
2. **Falls back intelligently**: Only uses PowerShell when necessary (cloud drives)
3. **Minimal dependencies**: Uses standard Python libraries + PowerShell (already available on Windows)
4. **Reusable**: Can be used across multiple projects
5. **Robust**: Handles edge cases like unmounted drives, network issues, etc.

## When to Use

### Use Native Python (`shutil.copy2`) When:
- Source and target are both accessible from WSL
- Working with local filesystems (`/mnt/f/`, `/home/`, etc.)
- Performance is critical (native Python is faster)

### Use PowerShell Fallback When:
- Target is a cloud drive (Google Drive, OneDrive) not accessible from WSL
- `wslpath` fails with "No such device" errors
- Native Python copy fails with permission/access errors

## Integration into Other Projects

### Option 1: Copy Files Directly

Simply copy `path_utils.ps1` to your project and use the Python wrapper methods as examples.

### Option 2: Extract as Module

Extract the Python wrapper methods into a separate module (e.g., `wsl_path_utils.py`) that can be imported:

```python
from wsl_path_utils import copy_file_universal, convert_wsl_to_windows_path

# Use in your code
success, error = copy_file_universal(source, target)
```

### Option 3: Package as Library

**Note: Future Consideration**

This utility could be packaged as a standalone Python library (e.g., `wsl-path-utils` on PyPI) for broader use. Benefits would include:

- Standardized installation via `pip install wsl-path-utils`
- Version management and updates
- Community contributions and bug fixes
- Documentation and examples
- Testing across different WSL/Windows configurations

If you find this utility useful across multiple projects, consider:
1. Creating a separate repository for the utility
2. Adding proper tests and CI/CD
3. Publishing to PyPI
4. Maintaining it as a standalone project

For now, it's kept as a project utility to avoid premature abstraction, but the code is structured to be easily extractable.

## Troubleshooting

### "No such device" Errors

If you see errors like `wslpath: /mnt/g/My Drive/publications: No such device`, this means:
- The drive isn't accessible from WSL
- The utility will automatically fall back to PowerShell
- This is expected behavior for cloud drives

### PowerShell Execution Policy

If you get execution policy errors, ensure the script is called with:
```powershell
powershell.exe -ExecutionPolicy Bypass -File path_utils.ps1 ...
```

### Path Conversion Fails

If path conversion fails:
1. Check that the path format is correct (WSL paths start with `/mnt/`)
2. Verify the drive letter is correct
3. Check that the path doesn't contain invalid characters

## Examples

### Example 1: Copy PDF to Google Drive

```python
from pathlib import Path

source = Path("/mnt/i/FraScanner/papers/scan.pdf")
target = Path("/mnt/g/My Drive/publications/paper.pdf")

success, error = copy_file_universal(source, target)
if success:
    print("✅ Copied successfully")
else:
    print(f"❌ Failed: {error}")
```

### Example 2: Validate Directory Before Use

```python
import subprocess
import json

def validate_directory(dir_path: str) -> bool:
    """Validate that directory exists and is accessible."""
    script_path = Path(__file__).parent / 'path_utils.ps1'
    # ... convert script path ...
    
    result = subprocess.run(
        ['powershell.exe', '-ExecutionPolicy', 'Bypass', '-File', script_win,
         'test-directory', dir_path],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        data = json.loads(result.stdout.strip())
        return data.get('exists', False) and data.get('accessible', False)
    return False
```

## License

This utility is part of the research-tools project. Adapt as needed for your projects.

## Contributing

If you find bugs or have improvements:
1. Test with different WSL/Windows configurations
2. Ensure PowerShell fallback works correctly
3. Verify JSON responses are properly formatted
4. Test with various cloud drive configurations

