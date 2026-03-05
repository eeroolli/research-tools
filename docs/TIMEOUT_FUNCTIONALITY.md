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

**Files:**
- `scripts/paper_processor_daemon.py` – main daemon prompts and legacy wrapper `_input_with_timeout`
- `shared_tools/ui/navigation.py` – multi-page NavigationEngine used for enrichment and note flows
- `shared_tools/ui/input_timeout.py` – new cross-platform input/timeout helper

#### A. Configuration Loading
In `load_config()` (daemon), we still load:
```python
# Get UX configuration
self.page_offset_timeout = self.config.getint('UX', 'page_offset_timeout', fallback=10)
```

#### B. Cross-platform input helper (`shared_tools/ui/input_timeout.py`)

We now centralize timeout handling in a dedicated helper:

```python
read_line_with_timeout(
    prompt: str,
    timeout: float | None,
    default: str | None = None,
    clear_buffered: bool = False,
) -> str | None

drain_stdin(
    max_lines: int = 5,
    timeout_per_line: float = 0.05,
) -> int
```

Platform behavior:

- **Unix/WSL (non-win32)**:
  - Uses `select.select([sys.stdin], [], [], timeout)` to implement timeouts.
  - Uses non-blocking reads in `drain_stdin` to clear buffered input between prompts.
- **Windows (win32)**:
  - Avoids `select()` on `sys.stdin` entirely (to prevent `WinError 10038`).
  - Uses `msvcrt.kbhit()` / `msvcrt.getwch()` polling to:
    - Collect characters into a line until Enter is pressed.
    - Enforce a timeout and return `default` when no input is received in time.
  - `drain_stdin` uses `msvcrt.kbhit()/getwch()` in a short loop to clear pending keystrokes.

Return semantics:

- Returns the line the user typed (without newline) on normal input.
- Returns `default` when timeout occurs and a default is provided.
- Returns `None` on timeout when `default` is `None`, or on `KeyboardInterrupt`/`EOFError`.

#### C. Daemon wrapper `_input_with_timeout()` (delegates to helper)

The daemon’s `_input_with_timeout()` is now a thin wrapper:

```python
from shared_tools.ui.input_timeout import read_line_with_timeout

def _input_with_timeout(...):
    if timeout_seconds is None:
        timeout_seconds = self.prompt_timeout

    user_input = read_line_with_timeout(
        prompt,
        timeout=timeout_seconds,
        default=default,
        clear_buffered=clear_buffered,
    )

    if user_input is None:
        if default is not None:
            # Timeout with default
            print(\"⏱️  Timeout reached - proceeding with default\")
            return default
        else:
            # Timeout with no default
            print(\"⏱️  Timeout reached\")
            return None

    user_input = user_input.strip()
    return user_input if user_input else default
```

This preserves existing daemon semantics (including timeout messages) while delegating all platform-specific behavior to `input_timeout.py`.

#### D. NavigationEngine integration

`NavigationEngine` in `shared_tools/ui/navigation.py` now uses the helper:

- `_drain_stdin_nonblocking()`:

```python
from shared_tools.ui.input_timeout import drain_stdin

def _drain_stdin_nonblocking(...):
    return drain_stdin(max_lines=max_lines, timeout_per_line=0.05)
```

- Timed page input in `show_page()`:

```python
from shared_tools.ui.input_timeout import read_line_with_timeout

if timeout_to_use > 0 and has_default:
    prompt_text = page.prompt.lstrip('\\n') if page.prompt.startswith('\\n') else page.prompt
    user_input = read_line_with_timeout(
        prompt_text,
        timeout=timeout_to_use,
        default=page.default,
        clear_buffered=False,
    )
    if user_input is None:
        # Fallback: treat as timeout with no default
        print(\"⏱️  Timeout reached - proceeding with default\")
        user_input = page.default
    elif user_input == page.default:
        # Helper applied default due to timeout
        print(\"⏱️  Timeout reached - proceeding with default\")
        self._drain_stdin_nonblocking(max_lines=3)
else:
    user_input = read_line_with_timeout(
        page.prompt,
        timeout=None,
        default=None,
        clear_buffered=False,
    )
```

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

- **Unix/WSL (Primary):**
  - Uses `select.select()` for non-blocking input with timeout and buffer draining.
  - Honors all configured timeouts (`page_offset_timeout`, `prompt_timeout`, navigation page `timeout_seconds`).
- **Windows (First-class):**
  - Uses `msvcrt`-based polling for timeouts and buffer draining.
  - No longer uses `select()` on `sys.stdin`, avoiding `OSError: [WinError 10038]`.
  - Honors the same timeout settings as Unix/WSL.
- **Timeout Disabled:** If `page_offset_timeout = 0` (or a page has timeout 0/None), falls back to regular blocking input.

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

