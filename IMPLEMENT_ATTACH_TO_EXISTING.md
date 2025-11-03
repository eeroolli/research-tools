# Implementation: Attach Scanned PDF to Existing Zotero Item

## Recent Updates (Oct 2025)

- Publications-first path resolution implemented:
  - Before any copy, the daemon searches the `publications` directory for an existing identical PDF using size-then-hash (SHA-256).
  - If found, it reuses that file as the linked attachment and moves the new scan to `done/` without copying.
- Size-then-hash duplicate handling during collisions:
  - On name collisions (base vs `_scanned` vs `_scanned2`), identical files are detected and skipped.
  - Non-identical collisions follow the existing menu: keep both (→ `_scanned2`), replace base, or replace scanned.
- Windows path normalization for linked files:
  - All attachments use Windows absolute paths derived from WSL paths to ensure linked files open in Zotero desktop.
- Attachment title normalization:
  - Attachment titles now use the filename (not the paper title) so Zotero shows and resolves the path clearly.
- Optional “skip attachment” flow:
  - Users can choose to create the item or finish the attach flow without attaching the PDF; the scan is moved to `done/`.
- Graceful failure behavior:
  - If copy fails, the item is still created (when applicable) and the daemon reports the state clearly (created with/without attachment).

Implementation references:
- `scripts/paper_processor_daemon.py`
  - `_find_identical_in_publications`, `_are_files_identical`, `_sha256_file`, `_to_windows_path`
  - `_handle_pdf_attachment_step(...)` and `handle_create_new_item(...)` updated with publications-first reuse, skip-attach, and safer messaging
- `shared_tools/zotero/paper_processor.py`
  - `add_paper(...)` now cleanly reports when no attachment was requested
  - `attach_pdf(...)` and `attach_pdf_to_existing(...)` normalize path and attachment title

Status: Completed (Oct 2025)
Changelog:
- 2025-10-29: Publications-first identical reuse; Windows path normalization; filename-based attachment titles; skip-attach option; refined messaging and errors.

See overall roadmap and progress: `implementation-plan.md`.
Related plan section: "At a glance" and "Completed" in `implementation-plan.md`.

## Scope

Attach scanned PDFs to existing Zotero items and create new Zotero items with optional linked-file attachments, including duplicate handling and publications-first reuse.
When scanning a paper, you often already have the item in Zotero (90% of cases). The daemon must:
1. Find the existing Zotero item
2. Generate correct filename using Zotero metadata
3. Copy scan to publications directory
4. Attach as linked file in Zotero
5. **Never use "Unknown" or "P_et_al" in filenames**

## Workflow Details

### Task 1: Fix Author Display in handle_item_selected() ✅
**File:** `scripts/paper_processor_daemon.py` (lines 3196-3252)  
**Status:** Already implemented  
**What:** Displays authors from selected Zotero item

```python
# Extract authors from Zotero item (may be in 'authors' or 'creators' field)
zotero_authors = selected_item.get('authors', [])
if not zotero_authors and 'creators' in selected_item:
    # Extract authors from creators list
    ...
print(f"Authors: {author_str}")  # ✅ Added
```

---

### Filename generation uses Zotero metadata ✅
**File:** `scripts/paper_processor_daemon.py`
Uses selected Zotero metadata for filenames; avoids falling back to low-quality scan metadata.

---

### Optional metadata editing
**File:** `scripts/paper_processor_daemon.py`

**Flow:**
```python
elif action == 'edit':
    # Show current Zotero metadata
    print("Current Zotero metadata:")
    print(f"  Title: {selected_item.get('title')}")
    print(f"  Authors: {zotero_authors}")
    print(f"  Year: {selected_item.get('year')}")
    
    # Edit metadata interactively
    edited_metadata = self.edit_metadata_interactively(selected_item, metadata)
    
    # Use edited metadata for filename
    target_filename = filename_gen.generate(edited_metadata, is_scan=True) + '.pdf'
    
    # Proceed with attachment
    self._process_selected_item(pdf_path, selected_item, target_filename)
```

**Edit options:**
- Fix title
- Fix authors
- Fix year
- Add/remove tags
- Add notes

---

### Copy/placement
Copies to publications directory only when no identical file exists; otherwise reuses the existing file path.
```powershell
powershell.exe -File F:\prog\research-tools\scripts\copy_to_publications.ps1 `
  "F:\test\source.pdf" `
  "G:\My Drive\publications\Schultz_Oskamp_1995_Who_Recycles_scan.pdf"
```

**Expected:**
- ✅ File copied successfully
- ✅ Verified (size check)
- ✅ Prompt for confirmation

---

### Zotero API attachment
**Method:** `ZoteroPaperProcessor.attach_pdf_to_existing()`  
**File:** `shared_tools/zotero/paper_processor.py`

**Test:**
```python
# Test attachment
result = zotero_processor.attach_pdf_to_existing(
    item_key='5VZFSJSG',
    pdf_path='/mnt/g/My Drive/publications/Schultz_Oskamp_1995_Who_Recycles_scan.pdf'
)

assert result == True
```

**Expected:**
- ✅ PDF attached as linked file
- ✅ Can view in Zotero desktop app
- ✅ Opens correctly from Zotero

---

## Testing Checklist

### Test Case 1: Perfect Match (Most Common)
**Input:** Scan of "Who Recycles..." by Schultz & Oskamp (1995)
**Expected Filename:** `Schultz_Oskamp_1995_Who_Recycles_And_When_scan.pdf`

**Steps:**
1. Scan document
2. Daemon extracts metadata (poor quality)
3. User enters year: 1995
4. Select authors: Schultz, Oskamp (action 'ab')
5. Daemon finds Zotero item D
6. User selects item D
7. **DISPLAY:**
   ```
   ✅ Selected: Who Recycles And When...
   Authors: P. W. Schultz; S. Oskamp  ← FROM ZOTERO
   
   📝 Filename will use authors: Schultz_Oskamp
   
   PROPOSED ACTIONS:
   Will perform:
     1. Generate filename: Schultz_Oskamp_1995_Who_Recycles_And_When_scan.pdf ✅
     2. Copy to publications
     3. Attach to Zotero
     4. Move to done/
   
   Proceed? [y/n/skip]: y
   ```
8. ✅ Copy succeeds
9. ✅ Attachment succeeds
10. ✅ File in done/

### Test Case 2: Zotero Item Has Poor Metadata
**Input:** Zotero item with incomplete title
**Solution:** Option 2 (Edit metadata) before proceeding

### Test Case 3: No Authors in Zotero Item
**Input:** Zotero item missing author field  
**Expected:** Warning displayed, user can proceed or cancel

### Test Case 4: Copy Fails
**Input:** WSL/GoogleDrive  issue during copy
**Expected:** Error shown, PDF stays in papers/, moved to manual/

---

## Critical Code Locations

### Where Filename is Generated
**File:** `scripts/paper_processor_daemon.py`  
**Method:** `handle_item_selected()`  
**Lines:** 3196-3252  

**Key Variables:**
- `zotero_authors` - List of author names from Zotero item
- `merged_metadata` - Dict used for filename generation
- `target_filename` - The generated filename string
- `final_authors` - The authors that will be used (must be confirmed)

### Where Filename Preview is Shown
**Lines:** 3248-3252
```python
# Show what authors will be used in filename
if final_authors:
    author_display = '_'.join([a.split()[-1] if ' ' in a else a for a in final_authors[:2]])
    print(f"📝 Filename will use authors: {author_display}")
```

### Where Copy Happens
**Method:** `_process_selected_item()`  
**Lines:** 3268-3332  
**Calls:** `_copy_to_publications_via_windows()`

### Where Attachment Happens
**Method:** `_process_selected_item()`  
**Line:** 3295  
**Calls:** `zotero_processor.attach_pdf_to_existing(item_key, target_path)`

---

## Success Criteria

### Must Have (Critical)
1. ✅ Authors displayed from Zotero item (semicolon separated)
2. ✅ Filename shows Zotero authors, not extracted scrap
3. ✅ No "Unknown_Author" without warning
4. ✅ No "P_et_al" without user knowing
5. ✅ Publications-first identical reuse before any copy
6. ✅ PowerShell/WSL copy succeeds to Google Drive (when needed)
7. ✅ Zotero attachment succeeds with Windows absolute path
8. ✅ File moved to done/ after success (or after reuse/skip)

### Nice to Have
1. Metadata editing before attachment
2. Online verification (CrossRef lookup) if Zotero metadata incomplete
3. Persistent hash cache to avoid re-hashing unchanged files

---

## Files
- `scripts/paper_processor_daemon.py`
- `shared_tools/zotero/paper_processor.py`

---

## Notes
This feature is complete and stable. Future enhancements (e.g., persistent hash cache) are tracked in `implementation-plan.md`.

---

## Open Questions

1. What if Zotero item has no authors?
   → Warning + proceed with "Unknown_Author" or cancel?

2. What if authors format is wrong in Zotero?
   → Use edit metadata option (action 2)

3. What if copy to Google Drive fails?
   → Show error, move to manual/

4. What if Zotero API attachment fails?
   → Show error, PDF stays in publications/, scan to manual/

5. What about duplicate PDF detection?
   → ✅ **IMPLEMENTED** (Oct 2025) - Size-then-hash comparison for identical files in publications directory

---

## Next Steps

All implementation complete. Future enhancements below.

---

## Future Enhancements

### Improved Author Extraction
**Issue:** Ollama/GROBID sometimes extracts publisher/journal names as authors.

**Example:**
- Incorrect: "Ellis Westview" (publisher "Westview Press" misidentified as author)
- Correct: "Richard J. Ellis", "Dennis J. Coyle"

**Proposed Solution:**
1. Add guidance to Ollama prompts about distinguishing publishers from authors
2. Maintain knowledge base of common publishers to filter out
3. Use context clues: "Published by" vs "By [Name]"
4. Post-process extraction to validate against known publishers

**Priority:** Medium - Affects accuracy but workaround exists (user can correct)
**Status:** TODO - Needs research into common publisher patterns

---

### Institutional Header Issues
**Issue:** GROBID extracts institutional headers instead of paper metadata.

**Example from Lakoff PDF:**
```
OCR content clearly shows:
  Title: "Metaphor, Morality, and Politics, Or, Why Conservatives Have Left Liberals in the Dust"
  Author: "Lakoff, George"
  Journal: "Social Research, 62(2)"
  Date: "1995-07-01"

But GROBID extracts:
  Title: "UC Berkeley" (from institutional header "UC Berkeley Previously Published Works")
  Authors: "Uc, Berkeley", "Previously"
```

**Root Cause:** Repository pages often have institutional headers/footers that GROBID treats as primary metadata.

**Proposed Solutions:**
1. **Pre-processing:** Strip institutional headers before sending to GROBID
2. **GROBID Configuration:** Adjust GROBID parameters to prioritize abstract/title sections
3. **Post-processing:** Filter out common institutional phrases from titles/authors
4. **Multi-pass extraction:** Try different GROBID configurations and merge results

**Priority:** Medium-High - Affects metadata quality for repository PDFs
**Status:** TODO - Needs investigation of GROBID header detection mechanisms

---

*This plan focuses ONLY on attaching to existing Zotero items. Creating new items is deferred to a later phase.*

