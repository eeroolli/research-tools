# Paper Processor UX Flow

## Terminal User Experience Flowchart

This document shows the complete user flow through the paper processor daemon's terminal interface.

---

## Main Flow

```
START: New PDF scanned
│
├─► Extract Metadata (Automatic)
│   ├─► STEP 1: GREP preprocessing (1-2s)
│   │   └─► Try APIs if identifiers found (2-4s total)
│   │
│   ├─► STEP 2: GROBID (if Step 1 failed)
│   │
│   └─► STEP 3: Ollama (if Step 2 failed) (60-180s)
│
├─► Filter Authors (Automatic)
│   └─► Remove garbage authors from poor extractions
│
┌─────────────────────────────────────────────────────────┐
│  YEAR CONFIRMATION PAGE                                 │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  Case 1: Year Found                                     │
│  ─────────────────────────────────────────────────────  │
│  📅 Year found by GREP (scan): 2023                     │
│  Press Enter to confirm (2023) or type a different year:│
│  _                                                       │
│                                                          │
│  Case 2: Conflict Detected                              │
│  ─────────────────────────────────────────────────────  │
│  ⚠️  Year conflict detected:                            │
│     GREP (scan):      2023                               │
│     GROBID/API:       2024                               │
│  Press Enter to confirm (2023) or type a different year:│
│  _                                                       │
│                                                          │
│  Case 3: No Year Found                                  │
│  ─────────────────────────────────────────────────────  │
│  📅 Publication year not found in scan                   │
│  Enter publication year (or press Enter to skip):       │
│  _                                                       │
└─────────────────────────────────────────────────────────┘
│
├─► [User Input]
│   ├─► Press Enter: Use suggested year (or skip if none)
│   ├─► Type year: Use custom year
│   └─► Conflict resolution: Choose one source's year
│
┌─────────────────────────────────────────────────────────┐
│  DOCUMENT TYPE PAGE                                     │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  Auto-detected type: journal_article                    │
│  [1] Use detected type (journal_article)                │
│  [2] Select different type                              │
│                                                          │
│  (or if type menu appears):                             │
│  [1] Journal Article                                    │
│  [2] Conference Paper                                   │
│  [3] Book Chapter                                       │
│  [4] Book                                               │
│  [5] Report                                             │
│  [6] ... (more types)                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Input]
│   ├─► [1]: Use detected type
│   └─► [2]: Show type menu and select
│
┌─────────────────────────────────────────────────────────┐
│  METADATA DISPLAY PAGE                                  │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  EXTRACTED METADATA                                     │
│  ────────────────────────                               │
│  Title:      Understanding Bias in Neural Networks      │
│  Authors:    Smith, John; Johnson, Mary                 │
│  Year:       2023                                       │
│  Journal:    Journal of AI Research                     │
│  Type:       journal_article                            │
│  DOI:        10.1234/example.2023.567                   │
│  Abstract:   This paper examines...                     │
│                                                          │
│  File:       scan_20250103_143022.pdf                   │
│  Time:       3.2 seconds                                │
└─────────────────────────────────────────────────────────┘
│
├─► Continue to Zotero Search
│
┌─────────────────────────────────────────────────────────┐
│  AUTHOR SELECTION PAGE                                  │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  Found 3 authors in your library:                       │
│                                                          │
│  [✓] Smith, John                   123 papers           │
│  [✓] Johnson, Mary                  45 papers           │
│  [✓] Williams, Bob                   8 papers           │
│                                                          │
│  Select authors to search (Enter to confirm, 'a'=all):  │
│  _                                                       │
│                                                          │
│  OR if no authors recognized:                           │
│                                                          │
│  No recognized authors found.                           │
│  [1] Use all authors: Smith, John; Johnson, Mary        │
│  [2] Select specific authors                            │   
│  [3] Enter authors manually                             │
│  [z] Back                                               │
└─────────────────────────────────────────────────────────┘
│
├─► [User Input]
│   ├─► Press Enter: Use selected authors
│   ├─► Toggle checkmarks: [ ] or [✓]
│   ├─► 'a': Select all
│   └─► 'z': Back
│
┌─────────────────────────────────────────────────────────┐
│  ZOTERO SEARCH PAGE                                     │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  ✅ Found 3 potential match(es) by Smith → Johnson:     │
│                                                          │
│  [A] Understanding Bias in Neural Networks              │
│      Authors: Smith, John; Johnson, Mary                │
│      Year: 2023  |  Type: journalArticle  |  PDF: ✅   │
│      Journal: Journal of AI Research                    │
│      DOI: 10.1234/example.2023.567                      │
│      Match: Perfect order                               │
│                                                          │
│  [B] A Different Paper on Bias                          │
│      Authors: Smith, John; Johnson, Mary                │
│      Year: 2022  |  Type: journalArticle  |  PDF: ❌   │
│                                                          │
│  [C] Neural Network Research                            │
│      Authors: Smith, John; Brown, Alice                 │
│      Year: 2023  |  Type: journalArticle  |  PDF: ❌   │
│                                                          │
│  ACTIONS:                                               │
│    [A-Z] Select item from list above                    │
│  [1]   🔍 Search again (different authors/year)         │
│  [2]   ✏️  Edit metadata                                │
│  [3]   None of these items - create new                 │
│  [4]   ❌ Skip document                                 │
│    (z) ⬅️  Back to author selection                     │
│    (r) 🔄 Restart from beginning                        │
│    (q) Quit daemon                                      │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► [A-Z]: SELECT ITEM ──────────────────────────────►┐
│   │                                                      │
│   ├─► [1]: SEARCH AGAIN ────────────────────────────────┤
│   │                                                      │
│   ├─► [2]: EDIT METADATA ───────────────────────────────┤
│   │                                                      │
│   ├─► [3]: CREATE NEW ──────────────────────────────────┤
│   │                                                      │
│   ├─► [4]: SKIP ────────────────────────────────────────┤
│   │                                                      │
│   ├─► [z]: BACK ────────────────────────────────────────┤
│   │                                                      │
│   └─► [r]: RESTART ─────────────────────────────────────┤
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Branch 1: SELECT ITEM (A-Z)

**Context:** You selected a matching item from the Zotero search results. This item already exists in your library.

**Purpose:** Attach the scanned PDF and/or update metadata for the selected Zotero item.

```
┌─────────────────────────────────────────────────────────┐
│  SELECTED ITEM REVIEW PAGE                              │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  SELECTED ITEM                                          │
│  ─────────────                                          │
│  Title:      Understanding Bias in Neural Networks      │
│  Authors:    Smith, John; Johnson, Mary                 │
│  Year:       2023                                       │
│  Journal:    Journal of AI Research                     │
│  DOI:        10.1234/example.2023.567                   │
│                                                          │
│  EXTRACTED METADATA                                     │
│  ────────────────                                       │
│  Title:      Understanding Bias in Neural Networks      │
│  Authors:    Smith, John; Johnson, Mary                 │
│  Year:       2023                                       │
│  Journal:    Journal of AI Research                     │
│  DOI:        10.1234/example.2023.567                   │
│                                                          │
│  🔀 These appear to be the SAME item                    │
│                                                          │
│  ACTIONS:                                               │
│  [1] Use extracted metadata (Replace, keep tags)        │
│  [2] Use Zotero metadata as-is                          │
│  [3] Merge metadata (field-by-field)                    │
│  [4] ✏️  Edit metadata                                  │
│  [5] 🔍 Search for more metadata online                 │
│  [6] 📝 Manual processing later                         │
│  [7] Create new item instead                            │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► [1]: USE EXTRACTED ──────────────────────────────► Sub-Branch 1.1
│   │   (Replace Zotero with extracted, keep tags)        │
│   │                                                      │
│   ├─► [2]: USE ZOTERO ──────────────────────────────────┤ Sub-Branch 1.2
│   │   (Keep Zotero item unchanged)                      │
│   │                                                      │
│   ├─► [3]: MERGE METADATA ──────────────────────────────┤ Sub-Branch 1.3
│   │   (Field-by-field comparison and merge)             │
│   │                                                      │
│   ├─► [4]: EDIT METADATA ───────────────────────────────┤ Sub-Branch 1.4
│   │   (Edit metadata before attaching)                  │
│   │                                                      │
│   ├─► [5]: SEARCH ONLINE ───────────────────────────────┤ Sub-Branch 1.5
│   │   (Search CrossRef, arXiv, PubMed, OpenAlex)        │
│   │                                                      │
│   ├─► [6]: MANUAL PROCESSING ───────────────────────────┤ Sub-Branch 1.6
│   │   (Defer to manual review later)                    │
│   │                                                      │
│   └─► [7]: CREATE NEW ──────────────────────────────────┤ Sub-Branch 1.7
│       (Create new item instead of attaching)             │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

---

## Sub-Branches of Branch 1: SELECT ITEM (A-Z)

### Sub-Branch 1.1: USE EXTRACTED METADATA

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Replace the selected Zotero item's metadata with the extracted scan metadata; keep existing tags.

### Sub-Branch 1.2: USE ZOTERO METADATA AS-IS

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Keep the Zotero item unchanged and attach the scanned PDF.

### Sub-Branch 1.3: MERGE METADATA FIELDS

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Compare metadata field-by-field between the scan and Zotero; choose which value to keep for each field.

### Sub-Branch 1.4: EDIT METADATA BEFORE ATTACHING

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Edit extracted metadata before attaching the PDF.

### Sub-Branch 1.5: SEARCH FOR MORE METADATA ONLINE

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Search CrossRef, arXiv, PubMed, OpenAlex for enhanced metadata; choose how to merge with existing sources.

```
┌─────────────────────────────────────────────────────────┐
│  ONLINE SEARCH RESULTS                                  │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  🔍 Searching CrossRef, arXiv, PubMed, OpenAlex...     │
│                                                          │
│  Extracted (from scan):                                 │
│    Title:    Understanding Bias in Neural Networks      │
│    Authors:  Smith, John                                │
│    Year:     2023                                       │
│                                                          │
│  Zotero (existing item):                                │
│    Title:    Understanding Bias in Neural Networks      │
│    Authors:  Smith, John                                │
│    Year:     2022                                       │
│                                                          │
│  Online (CrossRef/arXiv/etc):                           │
│    Title:    Understanding Bias in Neural Networks      │
│    Authors:  Smith, John; Johnson, Mary                 │
│    Year:     2023                                       │
│    DOI:      10.1234/example.2023.567                   │
│    Abstract: This paper examines...                     │
│                                                          │
│  Which metadata to use?                                 │
│  [1] Use online metadata                                │
│  [2] Use online + merge with Zotero                     │
│  [3] Use online + merge with extracted                  │
│  [4] Edit manually with online as reference             │
│  [5] Cancel (use Zotero metadata)                       │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► [1]: Use Online ───────────────────────────────►┐
│   ├─► [2]: Merge Online+Zotero ────────────────────────┤
│   ├─► [3]: Merge Online+Extracted ─────────────────────┤
│   ├─► [4]: Edit Manually ──────────────────────────────┤
│   └─► [5]: Cancel ────────────────────────────────────►┘
│       Use Zotero metadata as-is                        │
└──────────────────────────────────────────────────────────► Continue to PDF attachment
```

### Sub-Branch 1.6: MANUAL PROCESSING LATER

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Defer attaching the scan to a selected item; move to manual review.

### Sub-Branch 1.7: CREATE NEW ITEM INSTEAD

**Context:** You selected an existing item from Zotero search results.

**Purpose:** Do not use the selection; create a new Zotero item with the scan instead.

---

## Branch 2: SEARCH AGAIN (1)

**Context:** Matches were found, but you want to search Zotero with different criteria.

**Purpose:** Change search parameters (authors, year) to find better matches.

```
┌─────────────────────────────────────────────────────────┐
│  SEARCH AGAIN PAGE                                      │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  Try searching with different criteria:                 │
│                                                          │
│  [1] Search with all authors                            │
│  [2] Search with fewer authors                          │
│  [3] Edit metadata first                                │
│  [z] Back                                               │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► Returns to AUTHOR SELECTION PAGE
```

---

## Branch 3: EDIT METADATA (2)

**Context:** You want to correct or modify extracted metadata before searching Zotero or creating a new item.

**Purpose:** Edit title, authors, year, journal, DOI, etc., from the scan. Available before Zotero search, after matches, or before creating new items.

```
┌─────────────────────────────────────────────────────────┐
│  EDIT METADATA PAGE                                     │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  [Current metadata fields shown]                        │
│                                                          │
│  Authors:                                               │
│    [Current] Smith, John; Johnson, Mary; ...            │
│    [Online]  Smith, John; Johnson, Mary                 │
│    [Local]   Smith, John; Johnson, Mary                 │
│                                                          │
│  ⚠️  Found 30 authors. Quick options:                   │
│    (clear)  Delete all authors                          │
│    (first)  Use only first author                       │
│    (last)   Use only last author                        │
│                                                          │
│  New authors (comma-separated, Enter to keep,           │
│              'clear', 'first', or 'last'): _            │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► Enter: Keep current authors
│   ├─► Type: Replace with new authors
│   ├─► 'clear': Delete all authors
│   ├─► 'first': Keep only first author
│   └─► 'last': Keep only last author
│
┌─────────────────────────────────────────────────────────┐
│  RE-SEARCH WITH EDITED METADATA                         │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  🔍 Searching Zotero with edited metadata...            │
│                                                          │
│  (Returns to ZOTERO SEARCH PAGE)                        │
└─────────────────────────────────────────────────────────┘
```

---

## Branch 4: CREATE NEW ITEM (3)

**Context:** No matching items in your Zotero library, or you chose "None of these items" from the search results.

**Purpose:** Create a new Zotero item from the extracted metadata and attach the scanned PDF.

```
┌─────────────────────────────────────────────────────────┐
│  CREATE NEW ITEM - ONLINE CHECK                         │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  📄 Creating new Zotero item...                         │
│                                                          │
│  Should we search online libraries for enhanced         │
│  metadata? (DOI, OpenAlex, PubMed, CrossRef)            │
│                                                          │
│  [1] Yes - search and merge results                     │
│  [2] No - use extracted metadata as-is                  │
│  [3] Cancel                                             │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► [1]: Yes ───────────────────────────────────────►┐
│   │   Search online libraries for enhanced metadata    │
│   │   Merge with extracted metadata                    │
│   │   Confirm final metadata                           │
│   │                                                    │
│   ├─► [2]: No ────────────────────────────────────────►┤
│   │   Use extracted metadata as-is                     │
│   │                                                    │
│   └─► [3]: Cancel ────────────────────────────────────►┘
│       Don't create item                                │
│                                                       │
└───────────────────────────────────────────────────────► Create Item
                                                          Attach PDF
                                                          Move to done/
```

---

## Branch 5: SKIP (4)

**Context:** You want to skip this document and continue with the next one.

**Purpose:** Defer this document and move to the next scan; save this PDF for later processing.

```
┌─────────────────────────────────────────────────────────┐
│  SKIP DOCUMENT                                          │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  ⏭️  Skipping this document                             │
│                                                          │
│  PDF will be moved to skipped/ directory                │
└─────────────────────────────────────────────────────────┘
│
├─► Move PDF to skipped/
└─► END
```

---

## Branch 6: BACK (z)

**Context:** You want to go back to the previous step to change something.

**Purpose:** Return to the last step (author selection) without losing extracted metadata.

```
┌─────────────────────────────────────────────────────────┐
│  GOING BACK                                             │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  ⬅️  Going back to author selection...                   │
└─────────────────────────────────────────────────────────┘
│
├─► Returns to AUTHOR SELECTION PAGE
```

---

## Branch 7: RESTART (r)

**Context:** You want to start over from the beginning of the workflow.

**Purpose:** Reset extraction metadata and start fresh.

```
┌─────────────────────────────────────────────────────────┐
│  RESTARTING                                             │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  🔄 Restarting from beginning...                        │
└─────────────────────────────────────────────────────────┘
│
├─► Returns to AUTHOR SELECTION PAGE with fresh metadata
```

---

## Special Case: NO MATCHES FOUND

**Context:** Zotero search returned no matches for the extracted metadata.

**Purpose:** Handle cases where the document isn’t in your library.

```
┌─────────────────────────────────────────────────────────┐
│  NO MATCHES FOUND                                       │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  No matches found in your Zotero library                │
│                                                          │
│  Options:                                               │
│  [1] Proceed to create new Zotero item                  │
│  [2] Move to manual review                              │
│    (z) Back to previous step                            │
│                                                          │
│  Enter your choice: _                                   │
└─────────────────────────────────────────────────────────┘
│
├─► [User Choice]
│   │
│   ├─► [1]: CREATE NEW ────────────────────────────────► Branch 4
│   │
│   ├─► [2]: MANUAL REVIEW ──────────────────────────────► Move to manual/
│   │
│   └─► [z]: BACK ──────────────────────────────────────► AUTHOR SELECTION
```

---

## Special Case: EXTRACTION FAILED

**Context:** Automatic metadata extraction failed.

**Purpose:** Manually enter year, document type, title, and authors.

```
┌─────────────────────────────────────────────────────────┐
│  EXTRACTION FAILED - GUIDED WORKFLOW                    │
│  ─────────────────────────────────────────────────────  │
│                                                          │
│  ❌ Metadata extraction failed                          │
│                                                          │
│  You have the physical paper in front of you.           │
│  Let's manually enter the key information:              │
│                                                          │
│  📅 Enter publication year: _                           │
│                                                          │
│  (This follows similar flow but starts from scratch)    │
└─────────────────────────────────────────────────────────┘
│
├─► Prompts for: Year, Document Type, Title, Authors
├─► Then proceeds to ZOTERO SEARCH PAGE
```

---

## Navigation Summary

### From Any Page:
- **Ctrl+C**: Cancel current operation → Move PDF to failed/
- **'q'**: Quit daemon (only available on certain pages)
- **'z'**: Back to previous step (only available on certain pages)
- **'r'**: Restart from beginning (only available on certain pages)

### Page Sequence:
1. YEAR CONFIRMATION PAGE (always shown)
2. DOCUMENT TYPE PAGE (once after year)
3. METADATA DISPLAY PAGE (once after type)
4. AUTHOR SELECTION PAGE (once before search)
5. ZOTERO SEARCH PAGE (with branching)
6. Various action pages (based on choices)
7. Final result (done/, skipped/, failed/, manual/)

---

## Key Design Principles

1. **Always show context**: User sees extracted metadata at each decision point
2. **Conflict resolution**: Year conflicts shown with both sources
3. **Author intelligence**: Recognizes authors from your library
4. **Flexible navigation**: Back/restart options where applicable
5. **Smart defaults**: Suggested values based on extraction
6. **Physical paper reference**: User has paper in hand for verification
7. **Safe operations**: PDF conflicts detected and resolved
8. **Online enhancement**: Search CrossRef, arXiv, OpenAlex to supplement any Zotero item with enhanced metadata

---

## End States

- **done/**: PDF processed successfully, attached to Zotero item
- **skipped/**: User chose to skip this document
- **failed/**: Processing error or cancellation
- **manual/**: Needs manual review later

