# Epson Scanner Configuration Guide

## Overview

This guide explains how to configure your Epson scanner to automatically trigger the paper processing daemon when you scan documents.

---

## Prerequisites

- ✅ Epson Capture Pro installed on Windows
- ✅ WSL2 with research-tools installed
- ✅ Paper processor daemon implemented
- ✅ Batch/PowerShell launcher scripts created

---

## Step 1: Verify WSL Access

**Test from Windows Command Prompt:**

```cmd
wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python /mnt/f/prog/research-tools/scripts/start_paper_processor.py"
```

**Note:** This activates the `research-tools` conda environment properly, ensuring all dependencies (watchdog, pdfplumber, etc.) are available. If your conda is installed in a different location (e.g., `anaconda3` instead of `miniconda3`), adjust the path accordingly.

You should see:
```
============================================================
Starting paper processor daemon...
============================================================
...
```

---

## Step 2: Configure Epson Capture Pro

### Scan Destination Settings

1. **Open Epson Capture Pro**
2. **Select Job/Profile** (or create new one for papers)
3. **Configure Destination:**

   **Save Location:**
   ```
   I:\FraScanner\papers\
   ```

   **File Naming Pattern:**
   - Use Epson's built-in variables for language, date, time, page count
   - Target format: `<LANG>_YYYYMMDD_HHMMSS_<PAGES>.pdf`
   - Examples:
     - `EN_20251011_143522_5.pdf`
     - `NO_20251011_143522_3.pdf`
     - `DE_20251011_143522_2.pdf`

   **If Epson doesn't support this pattern:**
   - Use any pattern that includes language prefix (EN_, NO_, DE_)
   - Daemon will detect files starting with these prefixes

### Post-Scan Action

1. **Go to:** Advanced Settings → Post-Processing → Run Program
2. **Enable:** "Run program after job completion"
3. **Choose ONE option:**

   **Option A: Batch File (Recommended)**
   ```
   F:\prog\research-tools\scripts\start_scanner_daemon.bat
   ```
   - Simple
   - Easy to debug
   - Shows clear output

   **Option B: PowerShell Script**
   ```
   powershell.exe -ExecutionPolicy Bypass -File "F:\prog\research-tools\scripts\start_scanner_daemon.ps1"
   ```
   - Prettier output
   - More modern
   - Requires ExecutionPolicy bypass

   **Option C: Direct WSL Command**
   ```
   wsl.exe bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python /mnt/f/prog/research-tools/scripts/start_paper_processor.py"
   ```
   - Most direct
   - No intermediate files
   - Harder to debug
   - **Important:** Activates conda environment properly!

4. **Save settings**

---

## Step 3: Create Scanner Buttons/Profiles

### Button Configuration

Create separate jobs/profiles for each language:

**Norwegian Button:**
- Name: "Papers - Norwegian"
- Language prefix: NO_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.bat

**English Button:**
- Name: "Papers - English"
- Language prefix: EN_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.bat

**German Button:**
- Name: "Papers - German"
- Language prefix: DE_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.bat

---

## Step 4: Test the Setup

### Test Sequence

1. **Start fresh:**
   ```cmd
   wsl cat /mnt/i/FraScanner/papers/.daemon.pid
   ```
   If file exists, daemon is already running.

2. **Scan a test document:**
   - Press your configured scanner button
   - Watch for:
     - PDF saved to I:\FraScanner\papers\
     - Batch file runs (window may flash)
     - Daemon terminal appears (first time only)

3. **Verify daemon is running:**
   ```cmd
   wsl cat /mnt/i/FraScanner/papers/.daemon.pid
   wsl ps aux | findstr paper_processor_daemon
   ```

4. **Check processing:**
   - Watch daemon terminal for activity
   - Should show: "New scan detected: EN_..."
   - Should process automatically

5. **Test second scan:**
   - Scan another document
   - Batch file runs instantly (daemon already running)
   - New PDF processed automatically

---

## Workflow After Setup

```
┌─────────────────┐
│ Press Scanner   │
│ Button (NO/EN/DE)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Epson scans &   │
│ saves PDF to    │
│ I:\FraScanner\  │
│    papers\      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Epson triggers  │
│ start_scanner_  │
│ daemon.bat      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Batch calls WSL:│
│ Check if daemon │
│ running?        │
└────────┬────────┘
         │
    ┌────┴────┐
    │ NO  YES │
    │         │
    ▼         ▼
┌───────┐ ┌──────┐
│Start  │ │Exit  │
│Daemon │ │Fast  │
│Show   │ │(<1sec)│
│Terminal│ │      │
└───┬───┘ └──────┘
    │
    ▼
┌─────────────────┐
│ Daemon detects  │
│ new PDF         │
│ (within 2 sec)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Extract metadata│
│ (DOI/API/Ollama)│
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Interactive Menu│
│ (FUTURE)        │
│ User decides    │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Add to Zotero   │
│ Move to done/   │
│ or failed/      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ✅ Ready for    │
│ next scan       │
└─────────────────┘
```

---

## Troubleshooting

### Batch file doesn't run

**Check Epson Capture Pro settings:**
- Verify path is correct: `F:\prog\research-tools\scripts\start_scanner_daemon.bat`
- Try absolute path without spaces
- Check "Run as administrator" if needed

**Test manually:**
```cmd
F:\prog\research-tools\scripts\start_scanner_daemon.bat
```

### Daemon doesn't start

**Check WSL:**
```cmd
wsl --list --verbose
```
Should show Ubuntu/Debian running.

**Test Python path:**
```cmd
wsl python --version
wsl which python
```

**Check file permissions:**
```cmd
wsl ls -la /mnt/f/prog/research-tools/scripts/start_paper_processor.py
```

### PDFs not detected

**Known issue:** watchdog doesn't work on DrvFS/Google Drive mounts.

**Fix:** Edit `scripts/paper_processor_daemon.py` line 449:
```python
# Change from:
from watchdog.observers import Observer

# To:
from watchdog.observers.polling import PollingObserver as Observer
```

**Alternative:** Use batch processing manually:
```cmd
wsl python /mnt/f/prog/research-tools/scripts/process_scanned_papers.py
```

### Daemon terminal stays open

**This is expected behavior** for now - you see processing activity in real-time.

**Future option:** Add `--background` flag to run silently.

**Current workaround:** Minimize the terminal window.

---

## Advanced Configuration

### Silent Mode (Future)

Add flag to start_paper_processor.py:
```python
parser.add_argument("--background", action="store_true")
```

### Auto-start Daemon on Windows Boot

Create Windows Task Scheduler task:
1. Trigger: At startup
2. Action: Run batch file
3. Settings: Run only if network available

### Multiple Scanner Destinations

Create different batch files for different workflows:
- `scripts/start_scanner_daemon_papers.bat` → papers workflow
- `scripts/start_scanner_daemon_books.bat` → books workflow
- `scripts/start_scanner_daemon_other.bat` → other documents

---

## File Locations Summary

| File | Windows Path | WSL Path |
|------|-------------|----------|
| Batch launcher | `F:\prog\research-tools\scripts\start_scanner_daemon.bat` | `/mnt/f/prog/research-tools/scripts/start_scanner_daemon.bat` |
| PowerShell launcher | `F:\prog\research-tools\scripts\start_scanner_daemon.ps1` | `/mnt/f/prog/research-tools/scripts/start_scanner_daemon.ps1` |
| Python launcher | `F:\prog\research-tools\scripts\start_paper_processor.py` | `/mnt/f/prog/research-tools/scripts/start_paper_processor.py` |
| Daemon script | `F:\prog\research-tools\scripts\paper_processor_daemon.py` | `/mnt/f/prog/research-tools/scripts/paper_processor_daemon.py` |
| Scanner destination | `I:\FraScanner\papers\` | `/mnt/i/FraScanner/papers/` |
| Final PDFs | `G:\My Drive\publications\` | `/mnt/g/My Drive/publications/` |

---

## Testing Commands

**From Windows:**
```cmd
REM Test batch file
F:\prog\research-tools\scripts\start_scanner_daemon.bat

REM Check daemon status
wsl cat /mnt/i/FraScanner/papers/.daemon.pid

REM View daemon output
wsl tail -f /tmp/daemon.log

REM Stop daemon
wsl python /mnt/f/prog/research-tools/scripts/stop_paper_processor.py
```

**From WSL:**
```bash
# Start daemon manually
cd /mnt/f/prog/research-tools
python scripts/start_paper_processor.py

# Check if running
cat /mnt/i/FraScanner/papers/.daemon.pid
ps aux | grep paper_processor_daemon

# Stop daemon
python scripts/stop_paper_processor.py
```

---

## Next Steps

1. ✅ Configure Epson Capture Pro
2. ✅ Test with real scans
3. 🚧 Complete interactive workflow (next session)
4. 🚧 Add PollingObserver fix for file detection
5. 🚧 Fine-tune and optimize

---

**Questions?** Check SESSION_SUMMARY_2025-10-11.md for detailed implementation notes.

