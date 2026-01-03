# Page Offset Prompt Timeout Functionality

**Date:** Current Session  
**Status:** ✅ Implemented  
**Related Files:**
- `scripts/paper_processor_daemon.py` - Main implementation
- `config.conf` - Configuration settings

## Overview

Added a configurable timeout to the page offset prompt in the paper processor daemon. If the user doesn't respond within the configured time (default: 10 seconds), the system automatically proceeds with page 1 (default) and continues processing.

## User Request

The user wanted to add a timer to the "Document Starting Page" prompt:
- If no response within 10 seconds (configurable), automatically proceed with page 1
- Continue to next stage of processing without waiting

## Implementation Details

### 1. Configuration Added

**File:** `config.conf`

Added new `[UX]` section:
```ini
[UX]
# User experience configuration
# Timeout in seconds for page offset prompt (0 = no timeout, wait indefinitely)
# If user doesn't respond within this time, defaults to page 1 and continues processing
page_offset_timeout = 10
```

### 2. Code Changes

**File:** `scripts/paper_processor_daemon.py`

#### A. Import Statement
Added `select` module import with fallback:
```python
try:
    import select
    HAS_SELECT = True
except ImportError:
    HAS_SELECT = False
```

#### B. Configuration Loading
In `load_config()` method, added:
```python
# Get UX configuration
self.page_offset_timeout = self.config.getint('UX', 'page_offset_timeout', fallback=10)
```

#### C. Enhanced `_prompt_for_page_offset()` Method

**Location:** Line ~4334

**Key Changes:**
1. Reads timeout from config
2. Shows timeout message if timeout is enabled
3. Uses `select.select()` for non-blocking input with timeout (Unix/WSL)
4. Falls back to regular `input()` if `select` unavailable or timeout disabled
5. Automatically returns `0` (page 1) if timeout expires

**Implementation Logic:**
- If `timeout_seconds > 0` and `HAS_SELECT`:
  - Uses `select.select([sys.stdin], [], [], timeout_seconds)` to wait for input
  - If input available: reads and processes normally
  - If timeout: prints message and returns `0` (page 1 default)
- Otherwise: Uses regular blocking `input()` (no timeout)

### 3. User Experience

**Before timeout:**
```
================================================================================
📄 Document Starting Page
================================================================================
This PDF scan has 38 physical page(s).

⚠️  IMPORTANT: We're counting the SCAN PAGES...
...
Enter starting scan page number (1-38) or press Enter for page 1: 
[waits indefinitely]
```

**After timeout implementation:**
```
================================================================================
📄 Document Starting Page
================================================================================
This PDF scan has 38 physical page(s).

⚠️  IMPORTANT: We're counting the SCAN PAGES...
...
⏱️  Auto-proceeding with page 1 in 10 seconds if no input...

Enter starting scan page number (1-38) or press Enter for page 1: 
[waits up to 10 seconds, then proceeds automatically]
```

**If timeout expires:**
```
⏱️  Timeout reached - proceeding with page 1 (default)
Extracting metadata...
```

## Technical Details

### Platform Support

- **Unix/WSL (Primary):** Uses `select.select()` for non-blocking input with timeout
- **Windows (Fallback):** Falls back to regular `input()` if `select` unavailable
- **Timeout Disabled:** If `page_offset_timeout = 0`, uses regular blocking input

### Behavior

1. **Timeout Enabled (> 0):**
   - Shows countdown message
   - Waits for input with timeout
   - If input received: processes normally
   - If timeout: proceeds with page 1 (offset 0)

2. **Timeout Disabled (= 0):**
   - No timeout message shown
   - Uses regular blocking input
   - Waits indefinitely (original behavior)

3. **Invalid Input:**
   - If user enters invalid page number, loop continues
   - Timeout applies to each prompt attempt (not just first)

## Configuration Options

### Default Behavior
- **Default timeout:** 10 seconds
- **Configurable in:** `config.conf` or `config.personal.conf`
- **Disable timeout:** Set `page_offset_timeout = 0`

### Example Configurations

**Fast processing (5 seconds):**
```ini
[UX]
page_offset_timeout = 5
```

**Slower processing (20 seconds):**
```ini
[UX]
page_offset_timeout = 20
```

**No timeout (original behavior):**
```ini
[UX]
page_offset_timeout = 0
```

## Code Location

- **Function:** `_prompt_for_page_offset()` 
- **File:** `scripts/paper_processor_daemon.py`
- **Line:** ~4334-4420
- **Called from:** `_preprocess_split_if_needed()` at line ~3510

## Future Improvements (Potential)

1. **Visual countdown:** Show remaining seconds (e.g., "5... 4... 3...")
2. **Per-prompt timeout:** Different timeout for first prompt vs retries
3. **Windows support:** Implement timeout for Windows using `msvcrt` or `threading`
4. **Configurable default action:** Allow configuring what happens on timeout (page 1, cancel, etc.)
5. **Timeout for other prompts:** Extend timeout functionality to other user prompts

## Testing Notes

- Tested with `select` available (Unix/WSL environment)
- Fallback behavior when `select` unavailable needs testing
- Timeout behavior with user typing needs verification
- Edge cases: very fast typing, partial input, etc.

## Related Changes

This session also included:
- UX improvement: Changed note prompt from 'n' to 'a' for "Add a note"
- Language support: Added Danish (DA_) and changed Swedish from SE_ to SV_
- Language codes: Updated to use ISO 639-1 codes for Zotero compatibility

## Questions for Next Session

1. Should timeout apply to all prompts or just page offset?
2. Should we show a visual countdown timer?
3. Should timeout be different for first prompt vs validation retries?
4. Do we need Windows-specific timeout implementation?
5. Should timeout behavior be configurable (what happens on timeout)?

