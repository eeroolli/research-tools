# Epson Scanner Configuration Guide

## Overview

This guide explains how to configure your Epson scanner to automatically trigger the paper processing daemon when you scan documents.

---

## Prerequisites

- ✅ Epson Capture Pro installed on Windows
- ✅ WSL2 with research-tools installed
- ✅ Paper processor daemon implemented
- ✅ Batch/PowerShell launcher scripts created
- ✅ **GROBID Integration** - Advanced academic paper metadata extraction
- ✅ **Docker** - For GROBID container (auto-started by daemon)

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

   **VBS Launcher (Recommended)**
   ```
   F:\prog\research-tools\scripts\start_scanner_daemon.vbs
   ```
   - Epson compatible
   - Shows helpful startup message
   - Works on any Windows computer
   - User-friendly feedback

4. **Save settings**

---

## Step 3: Create Scanner Buttons/Profiles

### Button Configuration

Create separate jobs/profiles for each language:

**Norwegian Button:**
- Name: "Papers - Norwegian"
- Language prefix: NO_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.vbs

**English Button:**
- Name: "Papers - English"
- Language prefix: EN_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.vbs

**German Button:**
- Name: "Papers - German"
- Language prefix: DE_
- Destination: I:\FraScanner\papers\
- Post-action: Run scripts\start_scanner_daemon.vbs

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
| VBS launcher | `F:\prog\research-tools\scripts\start_scanner_daemon.vbs` | `/mnt/f/prog/research-tools/scripts/start_scanner_daemon.vbs` |
| Python launcher | `F:\prog\research-tools\scripts\start_paper_processor.py` | `/mnt/f/prog/research-tools/scripts/start_paper_processor.py` |
| Daemon script | `F:\prog\research-tools\scripts\paper_processor_daemon.py` | `/mnt/f/prog/research-tools/scripts/paper_processor_daemon.py` |
| Scanner destination | `I:\FraScanner\papers\` | `/mnt/i/FraScanner/papers/` |
| Final PDFs | `G:\My Drive\publications\` | `/mnt/g/My Drive/publications/` |

---

## GROBID Configuration

The paper processor daemon uses **GROBID** (GeneRation Of BIbliographic Data) for advanced academic paper metadata extraction.

### Automatic Setup
- ✅ **Auto-start**: GROBID Docker container starts automatically when daemon launches
- ✅ **Auto-stop**: Container stops when daemon shuts down (configurable)
- ✅ **Smart Processing**: Extracts metadata from first 2 pages only (prevents citation pollution)
- ✅ **Document Type Detection**: Automatically identifies journal articles, books, conferences, etc.

### Configuration Options
Edit `config.conf` to customize GROBID behavior:

```ini
[GROBID]
# Automatically start GROBID Docker container if not running
auto_start = true
# Stop GROBID container when daemon shuts down (if we started it)
auto_stop = true
# Docker container name for GROBID
container_name = grobid
# GROBID server port (default is 8070)
port = 8070
# Maximum pages to process for metadata extraction (prevents extracting authors from references)
max_pages = 2
```

### GROBID Features
- **Smart Author Extraction** - Only processes first 2 pages to avoid extracting authors from references
- **Document Type Detection** - Identifies journal articles, books, conferences, theses, reports, preprints
- **Enhanced Metadata** - Extracts keywords, publisher, volume, issue, pages, language, conference info
- **Fallback Support** - Falls back to Ollama 7B if GROBID is unavailable

### Troubleshooting GROBID
If GROBID fails to start:
1. **Check Docker**: Ensure Docker is running on Windows
2. **Check Port**: Verify port 8070 is not in use
3. **Check Logs**: Run `docker logs grobid` to see container logs
4. **Manual Start**: `docker start grobid` to manually start container

---

## Testing Commands

**From Windows:**
```cmd
REM Test VBS launcher
F:\prog\research-tools\scripts\start_scanner_daemon.vbs

REM Check daemon status
wsl cat /mnt/i/FraScanner/papers/.daemon.pid

REM View daemon output
wsl tail -f /tmp/daemon.log

REM Stop daemon (Ctrl+C in daemon terminal)
```

**From WSL:**
```bash
# Start daemon manually
cd /mnt/f/prog/research-tools
python scripts/start_paper_processor.py

# Check if running
cat /mnt/i/FraScanner/papers/.daemon.pid
ps aux | grep paper_processor_daemon

# Stop daemon (Ctrl+C in daemon terminal)
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

