# Next Session: Complete Interactive Workflow

**Status:** 85% Complete  
**Remaining:** Interactive menu in `process_scanned_papers.py`

---

## Quick Start for Next Session

### What's Done ✅
- Daemon system (3 scripts)
- Zotero API integration
- Local database search
- Conference detection
- All configurations
- All dependencies

### What's Needed 🚧
Enhance `scripts/process_scanned_papers.py` with interactive workflow

---

## Implementation Checklist

### 1. Add Imports (5 minutes)
```python
from shared_tools.zotero.local_search import ZoteroLocalSearch
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor  
from shared_tools.metadata.conference_detector import ConferenceDetector
```

### 2. Add Interactive Menu Function (15 minutes)
**Pattern:** Follow `scripts/add_or_remove_books_zotero.py`

```python
def show_paper_menu(metadata, zotero_matches, pdf_path, is_conference=False):
    """
    Show interactive menu for paper processing.
    
    Returns:
        User choice: '1'-'5' (attach to match), 'n' (new), 's' (skip), 'f' (failed), 'q' (quit)
    """
    # Display metadata
    # Display Zotero matches
    # Display options
    # Get user input
    # Return choice
```

### 3. Add Conference Workflow (10 minutes)
```python
def process_conference_presentation(pdf_path, metadata):
    """
    Special handling for conference presentations.
    
    1. Search Zotero with lower threshold (75%)
    2. Show matches
    3. If found: offer to attach
    4. If not: use Ollama + create new
    """
```

### 4. Update Main Processing Loop (10 minutes)
```python
def process_pdf_interactive(self, pdf_path):
    """
    Process single PDF with user interaction.
    
    1. Extract metadata
    2. Detect if conference presentation
    3. Search local Zotero database
    4. Show interactive menu
    5. Execute user choice via API
    6. Move file to done/failed
    """
```

### 5. Add Zotero Operations (10 minutes)
```python
# Initialize processors
local_search = ZoteroLocalSearch()
zotero_api = ZoteroPaperProcessor()

# Search local DB
matches = local_search.search_by_metadata(metadata)

# Execute based on user choice
if choice in ['1', '2', '3', '4', '5']:
    # Attach to existing item
    item_key = matches[int(choice)-1]['item_key']
    zotero_api.attach_pdf_to_existing(item_key, pdf_path)
elif choice == 'n':
    # Create new item
    zotero_api.add_paper(metadata, pdf_path)
```

### 6. Test (15 minutes)
```bash
# Test with existing PDFs
cd /mnt/f/prog/research-tools
python scripts/process_scanned_papers.py

# Test cases:
# 1. Paper with DOI (should find in Zotero)
# 2. Conference presentation (special workflow)
# 3. News article (should use Ollama)
# 4. Paper not in Zotero (create new)
```

---

## Code Locations Reference

**Main file to edit:**
- `scripts/process_scanned_papers.py` (lines 200-388 are good insertion points)

**Reference patterns:**
- Interactive menu: `scripts/add_or_remove_books_zotero.py` (lines 1465-1631)
- ISBN lookup menu: `scripts/manual_isbn_metadata_search.py` (lines 768-950)

**New modules to use:**
- `shared_tools/zotero/local_search.py` - ZoteroLocalSearch class
- `shared_tools/zotero/paper_processor.py` - ZoteroPaperProcessor class
- `shared_tools/metadata/conference_detector.py` - ConferenceDetector class

---

## Testing Commands

```bash
# 1. Test local search
python shared_tools/zotero/local_search.py

# 2. Test conference detection  
python shared_tools/metadata/conference_detector.py

# 3. Test interactive processing
python scripts/process_scanned_papers.py

# 4. Check for errors
python -m pylint scripts/process_scanned_papers.py
```

---

## Expected Behavior

```
$ python scripts/process_scanned_papers.py

============================================================
Processing: Doerig_et_al_2025.pdf
============================================================

Extracting metadata...
✅ Got metadata from CrossRef in 1.0s

Title: High-level visual representations in the human brain...
Authors: Doerig, Kietzmann
Year: 2025
DOI: 10.1038/s42256-025-01072-0

🔍 Searching local Zotero database...
Found 1 potential match:

[1] High-level visual representations... (100% match) - HAS PDF
    Authors: Doerig, Kietzmann
    Year: 2025

Options:
[1] Attach PDF to item #1 (replace existing)
[n] Create new Zotero item
[s] Skip (don't add to Zotero)
[f] Move to failed/ for manual review
[q] Quit

Your choice: _
```

---

## Known Issues to Address

### 1. File Watcher (Optional Fix)
If you want automatic detection, change line 449 in `paper_processor_daemon.py`:
```python
# FROM:
from watchdog.observers import Observer

# TO:
from watchdog.observers.polling import PollingObserver as Observer
```

### 2. Duplicate Attachment Handling
Decision needed: If Zotero item already has PDF, should we:
- Replace it?
- Skip attachment?
- Ask user?

**Recommendation:** Check `match['has_attachment']` and show in menu:
- "Attach PDF (replace existing)" vs "Attach PDF"

---

## Files to Commit After Completion

**Modified:**
```
config.conf
config.personal.conf
environment.yml
implementation-plan.md
scripts/process_scanned_papers.py  ← MAIN CHANGE
```

**New:**
```
scripts/paper_processor_daemon.py
scripts/start_paper_processor.py
scripts/stop_paper_processor.py
shared_tools/zotero/__init__.py
shared_tools/zotero/paper_processor.py
shared_tools/zotero/local_search.py
shared_tools/metadata/conference_detector.py
SESSION_SUMMARY_2025-10-11.md
daemon_implementation_spec.md
```

**Suggested commit messages:**
```bash
git add environment.yml config.conf config.personal.conf
git commit -m "feature: add dependencies and config for paper scanning workflow"

git add scripts/paper_processor_daemon.py scripts/start_paper_processor.py scripts/stop_paper_processor.py
git commit -m "feature: implement paper processor daemon with smart launcher"

git add shared_tools/zotero/
git commit -m "feature: add Zotero integration (API + local DB search)"

git add shared_tools/metadata/conference_detector.py
git commit -m "feature: add conference presentation detection"

# After completing interactive menu:
git add scripts/process_scanned_papers.py
git commit -m "feature: add interactive workflow to paper processor"

git add implementation-plan.md SESSION_SUMMARY_2025-10-11.md
git commit -m "docs: update implementation plan and session summary"
```

---

## Questions to Consider

1. **Conference presentations** - If no Zotero match, should we:
   - Always use Ollama to extract full metadata?
   - Ask user if they want to search manually first?
   - Just skip and move to failed/?

2. **Batch processing** - Should script:
   - Process all PDFs then exit?
   - Stay running and watch for more?
   - Ask after each paper?

3. **Duplicate PDFs** - If publications_dir already has this filename:
   - Auto-rename (append number)?
   - Ask user?
   - Skip?

**Current behavior:** Auto-rename (append 2, 3, 4, etc.)

---

## Estimated Time: 45-60 minutes
- Implementation: 30-45 minutes
- Testing: 15 minutes
- Documentation: 5 minutes (already done)

---

**Ready to implement when you return!**
All infrastructure is complete and tested.

