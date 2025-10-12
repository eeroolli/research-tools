# Development Session Summary - October 11, 2025

## Scanner-to-Zotero Integration Implementation

### Session Goals
Implement automated paper scanning workflow connecting Epson scanner to Zotero with interactive user control.

---

## ✅ Completed Today

### 1. Environment Setup
- **Added watchdog** to `environment.yml` for file system monitoring
- **Fixed pdfplumber** installation (was missing)
- **Configured G: drive** permanent mount in WSL2 via `/etc/fstab`
- **Fixed psutil API** compatibility issues (pid_exists removed in newer versions)

### 2. Core Daemon System
Created complete daemon infrastructure following specification in `daemon_implementation_spec.md`:

**Files Created:**
- `scripts/paper_processor_daemon.py` (363 lines)
  - Watches `/mnt/i/FraScanner/papers/` for new PDFs
  - Processes papers with NO_/EN_/DE_ prefixes
  - PID file management for singleton pattern
  - Clean shutdown with signal handling
  - Moves processed files to `done/` or `failed/`

- `scripts/start_paper_processor.py` (120 lines)
  - Smart idempotent launcher
  - Fast exit if already running (< 1 second)
  - PID validation with process checking
  - Scanner can trigger repeatedly without issues

- `scripts/stop_paper_processor.py` (71 lines)
  - Graceful shutdown via SIGTERM
  - 10-second timeout with SIGKILL fallback
  - PID file cleanup

### 3. Zotero Integration - Dual Approach

**A. API-Based (for updates):**
- `shared_tools/zotero/paper_processor.py` (376 lines)
  - Creates new Zotero items
  - Attaches PDFs as linked files
  - Duplicate detection by DOI and title
  - Item type detection (journal, conference, book chapter, etc.)
  - Metadata format conversion

**B. Database-Based (for searching):**
- `shared_tools/zotero/local_search.py` (372 lines) ✨ NEW
  - Read-only access to local Zotero SQLite database
  - Fast fuzzy matching (title: 80%, author: 70%, combined: 75%)
  - Multi-field search (DOI, title+authors, title only)
  - Returns top 5 matches with similarity scores
  - Checks for existing PDF attachments

**Architecture Decision:** 
- 📖 Read from local DB (fast, no API limits)
- ✏️ Write through API (safe, proper sync)

### 4. Conference Presentation Detection
- `shared_tools/metadata/conference_detector.py` (144 lines) ✨ NEW
  - Detects unpublished conference presentations
  - Heuristics: sparse first page (< 100 words), conference keywords, location/date
  - Identifies papers lacking DOI/ISBN/ISSN
  - Confidence scoring system

### 5. Configuration Updates
Updated both `config.conf` and `config.personal.conf`:
```ini
[PATHS]
scanner_papers_dir = /mnt/i/FraScanner/papers
publications_dir = /mnt/g/My Drive/publications
zotero_db_path = /mnt/f/prog/scanpapers/data/zotero.sqlite.bak  # NEW
```

### 6. Testing & Validation
- ✅ Daemon starts and stops cleanly
- ✅ PID management working
- ✅ Metadata extraction tested (DOI, CrossRef API working)
- ✅ Zotero API connection verified
- ✅ Local database search tested
- ✅ G: drive mount permanent and working

---

## 🚧 Remaining Work

### Interactive User Interface
The final piece is enhancing `scripts/process_scanned_papers.py` with interactive workflow:

**Needed (~200-300 lines of code):**

1. **Import new modules**
   ```python
   from shared_tools.zotero.local_search import ZoteroLocalSearch
   from shared_tools.metadata.conference_detector import ConferenceDetector
   from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
   ```

2. **Interactive menu function** (following `add_or_remove_books_zotero.py` pattern)
   ```
   Display:
   - Extracted metadata (title, authors, year, DOI)
   - Zotero matches from local DB (with similarity %)
   - Whether matches have PDFs attached
   
   Options:
   [1-5] Attach PDF to match #N
   [n] Create new Zotero item
   [s] Skip (don't add to Zotero)
   [f] Move to failed/ for manual review
   [q] Quit
   ```

3. **Conference presentation handling**
   - Detect using `ConferenceDetector`
   - Search Zotero more aggressively (lower threshold: 75%)
   - If found: offer to attach PDF
   - If not found: offer Ollama extraction + create new item

4. **Zotero operations**
   - Search local DB (fast)
   - Show matches to user
   - Execute chosen action via API
   - Log all operations

5. **Batch processing**
   - Process all PDFs in scanner directory
   - Interactive prompt for each
   - Continue until done or user quits

---

## Known Issues & Limitations

### File Watcher Not Working
**Issue:** `watchdog` doesn't detect new files on WSL2/DrvFS mounts (Google Drive)

**Workarounds:**
1. **PollingObserver** (recommended) - change in `paper_processor_daemon.py`:
   ```python
   from watchdog.observers.polling import PollingObserver as Observer
   ```
   Scans directory every few seconds instead of OS events.

2. **Manual trigger** - Scanner calls batch processing script instead of daemon

3. **Move to Linux filesystem** - If scanner can save to native Linux path

**Current Status:** Daemon infrastructure complete but file detection needs workaround.

---

## File Structure Created

```
scripts/
├── paper_processor_daemon.py          ✨ NEW - File watcher
├── start_paper_processor.py           ✨ NEW - Smart launcher  
├── stop_paper_processor.py            ✨ NEW - Clean shutdown
└── process_scanned_papers.py          📝 NEEDS ENHANCEMENT

shared_tools/zotero/
├── __init__.py                        ✨ NEW
├── paper_processor.py                 ✨ NEW - API integration
└── local_search.py                    ✨ NEW - Database search

shared_tools/metadata/
├── conference_detector.py             ✨ NEW - Presentation detection
├── paper_processor.py                 ✅ Existing - Metadata extraction
└── identifier_extractor.py            ✅ Existing

/mnt/i/FraScanner/papers/
├── .daemon.pid                        (created when daemon runs)
├── done/                              ✅ Existing
├── failed/                            ✅ Existing
└── paper_processing_log.csv           ✅ Existing

/mnt/g/My Drive/publications/          ✅ Mounted and accessible
```

---

## Next Session Plan

### Priority 1: Complete Interactive Workflow
Enhance `scripts/process_scanned_papers.py`:
1. Add interactive menu system
2. Integrate local Zotero search
3. Add conference presentation workflow
4. Test with real PDFs

**Estimated time:** 30-45 minutes

### Priority 2: Fix File Watching (Optional)
- Implement PollingObserver workaround
- Test automatic detection
- Configure scanner trigger

**Estimated time:** 15 minutes

### Priority 3: Documentation
- Update user guide
- Add scanner configuration instructions
- Create workflow diagrams

---

## Dependencies Installed

```yaml
# environment.yml additions
- watchdog  # File system monitoring
- pdfplumber  # PDF text extraction (was missing, now fixed)

# Already installed:
- psutil
- requests
- pyzotero
- pdfplumber (after fix)
```

---

## Configuration Reference

### Scanner Setup (Not Yet Done)
Configure Epson scanner to:
1. Save PDFs to: `/mnt/i/FraScanner/papers/`
2. Filename pattern: `<LANG>_YYYYMMDD_HHMMSS_<PAGES>.pdf`
   - Where `<LANG>` = NO, EN, or DE
3. Trigger: `python /mnt/f/prog/research-tools/scripts/start_paper_processor.py`

### Zotero Database Path
Located at: `/mnt/f/prog/scanpapers/data/zotero.sqlite.bak`
- Read-only access for searching
- All updates via API

### Publications Directory
Final PDFs stored at: `/mnt/g/My Drive/publications/`
- Permanently mounted via WSL2 fstab
- Accessible to both Windows and Linux

---

## Testing Commands

```bash
# Test Zotero API connection
cd /mnt/f/prog/research-tools
python shared_tools/zotero/paper_processor.py

# Test local database search
python shared_tools/zotero/local_search.py

# Test conference detection  
python shared_tools/metadata/conference_detector.py

# Test metadata extraction
python -c "from shared_tools.metadata.paper_processor import PaperMetadataProcessor; print('OK')"

# Start daemon (when ready)
python scripts/start_paper_processor.py

# Stop daemon
python scripts/stop_paper_processor.py

# Batch processing (current working method)
python scripts/process_scanned_papers.py
```

---

## Key Design Decisions Made

1. **Dual Zotero Access Pattern**
   - Local SQLite DB for fast searching (read-only)
   - API for all modifications (safe, synced)
   - Best of both worlds: speed + safety

2. **Interactive vs Automatic**
   - User confirms all Zotero additions
   - System assists with search and suggestions
   - Follows existing book processor pattern
   - Prevents accidental duplicates

3. **Conference Presentation Workflow**
   - Detect via heuristics (sparse first page, keywords, no identifiers)
   - Search Zotero for existing entry
   - If found: attach PDF
   - If not found: extract metadata + create new
   - Special handling for items lacking DOI/ISBN

4. **Daemon Architecture**
   - PID-based singleton pattern
   - Idempotent launcher (scanner can trigger multiple times)
   - Clean signal handling
   - Foreground terminal output (see activity)

5. **File Organization**
   - Original PDFs: `scanner_dir/done/` (with scanner filename)
   - Renamed PDFs: `publications_dir/` (Author_Year_Title.pdf)
   - Failed: `scanner_dir/failed/` (manual review)
   - Linked in Zotero (not uploaded)

---

## References

- **Main Spec:** `daemon_implementation_spec.md` (1053 lines)
- **Overall Plan:** `implementation-plan.md` (Phase 4, lines 259-299)
- **Book Processor Pattern:** `scripts/add_or_remove_books_zotero.py`
- **User Preferences:** `programming_preferences.md`

---

## Git Status

**Modified:**
- `config.conf`
- `config.personal.conf`
- `environment.yml`
- `implementation-plan.md` (will be updated)

**New Files (Untracked):**
- `scripts/paper_processor_daemon.py`
- `scripts/start_paper_processor.py`
- `scripts/stop_paper_processor.py`
- `shared_tools/zotero/__init__.py`
- `shared_tools/zotero/paper_processor.py`
- `shared_tools/zotero/local_search.py`
- `shared_tools/metadata/conference_detector.py`
- `daemon_implementation_spec.md`

**Recommendation:** Commit in logical chunks:
1. Config and dependencies
2. Daemon system
3. Zotero integration
4. Conference detection
5. Documentation

---

## Success Metrics

When complete, the system will:
- ✅ Detect new scanned papers automatically (or manually triggered)
- ✅ Extract metadata in 1-2 seconds (DOI/API) or 60-120 seconds (Ollama)
- ✅ Search local Zotero database for matches
- ✅ Show interactive menu with suggestions
- ✅ Execute user's choice via API
- ✅ Organize files properly
- ✅ Handle conference presentations intelligently
- ✅ Process 1 paper every 1-3 minutes
- ✅ Prevent duplicates
- ✅ Keep user in control

---

**Session End: October 11, 2025**
**Status: 85% Complete - Interactive menu is final piece**
**Next Session: Implement interactive workflow in process_scanned_papers.py**

