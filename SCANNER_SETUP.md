# Epson Scanner Configuration Guide

## Overview

This guide explains how to configure your Epson scanner to automatically trigger the paper processing daemon when you scan documents.

---

## Prerequisites

- ✅ Epson Capture Pro installed on Windows
- ✅ WSL2 with research-tools repo installed
- ✅ Paper processor daemon implemented (done)
- ✅ Batch/PowerShell launcher scripts created (done)
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
3. **Use Quiet Launcher (Recommended):**
   ```
   F:\prog\research-tools\scripts\start_scanner_daemon_quiet.vbs
   ```
   - Epson compatible
   - Runs silently (no popup windows)
   - Works on any Windows computer
   - Best for automated post-scan triggering

4. **Save settings**

---

## Step 3: Create Scanner Buttons/Profiles

### Button Configuration

Create separate jobs/profiles for each language and orientation:

**English Portrait:**
- Name: "Papers - English Portrait"
- Language prefix: EN_
- Scan settings:
  - Scan double-sided
  - Scan language: English
  - Remove empty pages (in case it is only one-sided scan)
- Save settings:
   - Filename pattern: Starts with `EN_`
   - PDF - Options - Language: English
   - Location: I:\FraScanner\papers\ (or what every you defined in config.conf)
- Index settings off
- Send Settings
   - Destination: Application - Setting name - Edit
           `[add path]\research-tools\scripts\start_scanner_daemon_quiet.vbs`

**English Landscape:**
- Name: "Papers - English Landscape"
- Description: To be used when there are two pages next to each other like in a book
- All the same settings as English Portait but add:
   Filename pattern: Starts with `EN_` and ends with `_double`

**Other Languages:**
You can create similar profiles for other languages (Norwegian, German, etc.):
- Each with: exactly same settings as the English ones, except: 
- Norwegian Portrait: Prefix `NO_`
- German Portrait: Prefix `DE_`
- And so on...

---

## Step 4: Starting the Daemon Before Scanning

### Initial Startup

**Before you start scanning, do a full restart of the daemon:**

1. **Run the restart script:**
   ```
   F:\prog\research-tools\scripts\start_scanner_daemon_restart.vbs
   ```
   - This ensures a clean start
   - Stops any existing daemon instance
   - Starts fresh daemon process
   - Recommended: Run this when you begin your scanning session or if you have any problems.

2. **Verify daemon is running:**
   ```cmd
   wsl cat /mnt/i/FraScanner/papers/.daemon.pid
   wsl ps aux | findstr paper_processor_daemon
   ```
   You should see the PID file and process running.

---

## Step 5: Test the Setup

### Test Sequence

1. **Start with restart (if not already running):**
   ```cmd
   F:\prog\research-tools\scripts\start_scanner_daemon_restart.vbs
   ```

2. **Scan a test document:**
   - Press your configured scanner button
   - Watch for:
     - PDF saved to I:\FraScanner\papers\
     - Quiet VBS script runs silently (no popup)
     - Daemon processes the file automatically

3. **Verify daemon is running:**
   ```cmd
   wsl cat /mnt/i/FraScanner/papers/.daemon.pid
   wsl ps aux | findstr paper_processor_daemon
   ```

4. **Check processing:**
   - Check daemon logs or terminal for activity
   - Should show: "New scan detected: EN_..."
   - Should process automatically

5. **Test second scan:**
   - Scan another document
   - Quiet VBS script runs silently (daemon already running)
   - New PDF processed automatically

---

## Workflow After Setup

```
┌─────────────────┐
│ Start Daemon    │
│ Run restart     │
│ script          │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Turn on         │
│ Scanner         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Put the Paper   │
│ in Scanner      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Open Epson      │
│ Capture Pro     │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Click Job       │
│ (Language/      │
│  Orientation)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Scan            │
│ Document        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Save            │
│ Document        │
│ (to scanner     │
│  folder)        │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Epson triggers  │
│ quiet.vbs       │
│ (silently)      │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Terminal       │
│ Opens with     │
│ PDF Info       │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Make Choices   │
│ & Edit         │
│ Metadata       │
│ (see           │
│  PAPER_        │
│  PROCESSOR_    │
│  UX_FLOW.md)   │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Metadata       │
│ (tags etc)     │
│ Saved to       │
│ Zotero         │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ PDF Saved      │
│ to             │
│ Publications   │
│ Folder         │
│ (with new      │
│  name or not)  │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ PDF Linked     │
│ to Zotero      │
│ Item           │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ ✅ Done        │
│ Recycle Paper  │
│ Ready for Next │
└─────────────────┘
```

---

## Troubleshooting

### VBS script doesn't run

**Check Epson Capture Pro settings:**
- Verify path is correct: `F:\prog\research-tools\scripts\start_scanner_daemon_quiet.vbs`
- Try absolute path without spaces
- Check "Run as administrator" if needed

**Test manually:**
```cmd
F:\prog\research-tools\scripts\start_scanner_daemon_quiet.vbs
```

**Or test the restart script:**
```cmd
F:\prog\research-tools\scripts\start_scanner_daemon_restart.vbs
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
| Quiet VBS launcher (post-scan) | `F:\prog\research-tools\scripts\start_scanner_daemon_quiet.vbs` | `/mnt/f/prog/research-tools/scripts/start_scanner_daemon_quiet.vbs` |
| Restart VBS launcher (startup) | `F:\prog\research-tools\scripts\start_scanner_daemon_restart.vbs` | `/mnt/f/prog/research-tools/scripts/start_scanner_daemon_restart.vbs` |
| Python launcher | `F:\prog\research-tools\scripts\start_paper_processor.py` | `/mnt/f/prog/research-tools/scripts/start_paper_processor.py` |
| Daemon script | `F:\prog\research-tools\scripts\paper_processor_daemon.py` | `/mnt/f/prog/research-tools/scripts/paper_processor_daemon.py` |
| Scanner destination | `I:\FraScanner\papers\` | `/mnt/i/FraScanner/papers/` |
| Final PDFs | `G:\My Drive\publications\` | `/mnt/g/My Drive/publications/` |

---

## GROBID Configuration

The paper processor daemon uses **GROBID** (GeneRation Of BIbliographic Data) for advanced academic paper metadata extraction.

### Automatic Setup
- ✅ **Auto-start**: GROBID Docker container starts automatically when daemon launches (local GROBID only)
- ✅ **Auto-stop**: Container stops when daemon shuts down (configurable, local GROBID only)
- ✅ **Remote Support**: Can connect to GROBID running on another machine
- ✅ **Smart Processing**: Extracts metadata from first 2 pages only (prevents citation pollution)
- ✅ **Document Type Detection**: Automatically identifies journal articles, books, conferences, etc.

### Configuration Options
Edit `config.conf` to customize GROBID behavior:

```ini
[GROBID]
# GROBID server host (localhost or remote hostname/IP)
# For local GROBID: host = localhost
# For remote GROBID: host = p1
host = localhost
# GROBID server port (default is 8070)
port = 8070
# Automatically start GROBID Docker container if not running (only if host=localhost)
auto_start = true
# Stop GROBID container when daemon shuts down (if we started it, only if host=localhost)
auto_stop = true
# Docker container name for GROBID
container_name = grobid
# Maximum pages to process for metadata extraction (prevents extracting authors from references)
max_pages = 2
```

### Distributed Processing Setup

For distributed processing where GROBID runs on one machine (P1) and the daemon runs on another (blacktower):

**On P1 (GROBID server):**
1. Start GROBID Docker container:
   ```bash
   docker start grobid
   # Or create if needed:
   docker run -d --name grobid -p 8070:8070 lfoppiano/grobid:0.8.2
   ```
2. Ensure GROBID is accessible on port 8070 (check firewall if needed)

**On blacktower (daemon machine):**
1. Edit `config.personal.conf`:
   ```ini
   [GROBID]
   host = p1
   # Or use IP address: host = 192.168.1.100
   port = 8070
   auto_start = false
   auto_stop = false
   ```
2. Configure daemon lock checking (optional, prevents multiple daemons):
   ```ini
   [DAEMON]
   remote_check_host = p1
   ```
3. Start daemon - it will connect to remote GROBID automatically

**Daemon Locking:**
- Only one daemon should run at a time across all machines
- Local daemon checks prevent duplicate instances on same machine
- Remote daemon check (if configured) prevents conflicts when daemon is running on another machine
- If remote daemon is detected, startup will exit with clear error message

### GROBID Features
- **Smart Author Extraction** - Only processes first 2 pages to avoid extracting authors from references
- **Document Type Detection** - Identifies journal articles, books, conferences, theses, reports, preprints
- **Enhanced Metadata** - Extracts keywords, publisher, volume, issue, pages, language, conference info
- **Fallback Support** - Falls back to Ollama 7B if GROBID is unavailable
- **Remote Access** - Can connect to GROBID on another machine over network

### Troubleshooting GROBID
If GROBID fails to start:
1. **Check Docker**: Ensure Docker is running on Windows (for local GROBID)
2. **Check Port**: Verify port 8070 is not in use
3. **Check Logs**: Run `docker logs grobid` to see container logs
4. **Manual Start**: `docker start grobid` to manually start container

If remote GROBID is unreachable:
1. **Test Connectivity**: `curl http://p1:8070/api/isalive` (should return "true")
2. **Check Firewall**: Ensure port 8070 is open on GROBID machine
3. **Check Network**: Verify machines can reach each other (ping, SSH)
4. **Check GROBID Status**: Ensure GROBID container is running on remote machine

---

## Testing Commands

**From Windows:**
```cmd
REM Start/restart daemon before scanning
F:\prog\research-tools\scripts\start_scanner_daemon_restart.vbs

REM Test quiet launcher (post-scan action)
F:\prog\research-tools\scripts\start_scanner_daemon_quiet.vbs

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

