# Metadata Extraction and Online Search Flow - Overview

## Overview

This document describes the complete flow of metadata extraction and online searches in the paper processor daemon, from initial PDF processing through final metadata display.

## Entry Point

**Method**: `process_paper(pdf_path: Path)` in `scripts/paper_processor_daemon.py` (line 3787)

**Initial Steps**:
1. Open PDF in viewer
2. Prompt for page offset (if document starts after page 1)
3. Create temporary PDF if page offset > 0

---

## Phase 1: Metadata Extraction

### Step 1: Fast GREP Identifier Extraction + API Lookup

**Location**: `scripts/paper_processor_daemon.py` line 3847  
**Module**: `shared_tools/metadata/paper_processor.py` → `process_pdf()`

**What Happens**:
1. **Step 0** (paper_processor.py line 442): Check if handwritten note (very little text)
2. **Step 1** (line 464): Extract identifiers from first page using regex:
   - DOIs
   - arXiv IDs
   - JSTOR IDs
   - ISSNs
   - ISBNs
   - URLs
   - Years (extracted from text)
3. **Step 2** (line 480): Validate identifiers
4. **Step 3** (line 522): Try API lookup based on identifiers found:

   **Priority Order**:
   - **DOIs**: Try CrossRef → OpenAlex → PubMed (in priority order)
   - **arXiv IDs**: Fetch from arXiv API
   - **JSTOR IDs**: 
     - Try to extract DOI from JSTOR page (using `JSTORClient.fetch_doi_from_url()`)
     - If DOI found: Use DOI for API lookup (CrossRef/OpenAlex/PubMed)
     - If no DOI: Store JSTOR ID, continue to GROBID
   - **ISBNs**: Return early (use book workflow)
   - **URLs**: Try regex extraction, then Ollama if enabled

**Returns**:
- `result` dict with:
  - `success`: True/False
  - `metadata`: Dict with extracted metadata (if successful)
  - `method`: Extraction method (e.g., 'crossref_api', 'arxiv_api', 'jstor+crossref_api')
  - `identifiers_found`: Dict with all identifiers found (years, JSTOR IDs, etc.)
  - `processing_time_seconds`: Time taken

**Fast Path**: If authors found, extraction is complete (line 3858-3860)

---

### Step 2: GROBID Extraction (Fallback)

**Location**: `scripts/paper_processor_daemon.py` line 3866-4023  
**Module**: `shared_tools/api/grobid_client.py` → `extract_metadata()`

**When It Runs**: If Step 1 didn't find authors (no API lookup success)

**What Happens**:
1. **Rotation Detection** (grobid_client.py line 111-124):
   - Check PDF for rotation issues
   - If all pages have machine-readable text: Skip rotation correction
   - If scanned pages detected: Apply rotation correction
   
2. **GROBID Extraction** (line 147):
   - Send PDF to GROBID server (first 2 pages, configurable)
   - Parse TEI XML response
   - Extract: title, authors, year, journal, abstract, DOI, keywords
   
3. **Retry Logic** (line 197-243):
   - If no authors found:
     - Try with 4 pages instead of 2
     - **Skip rotation retries if rotation detection already found PDF is correctly oriented** (Fix 4)
     - If still no authors: Return empty metadata

4. **JSTOR + CrossRef/OpenAlex Search** (daemon line 3928-4021):
   - **Only runs if**: GROBID found authors AND JSTOR ID exists
   - Extract search parameters from GROBID metadata: title, authors, year, journal
   - Search CrossRef with GROBID metadata
   - If CrossRef succeeds:
     - **Merge**: API data overwrites GROBID fields (`metadata.update(api_metadata)`)
     - **Combine**: Tags/keywords from both sources merged intelligently
     - Preserve JSTOR ID
   - If CrossRef fails: Try OpenAlex with same parameters
   - Result: `method = 'grobid+crossref'` or `'grobid+openalex'`

**Important Note**: If GROBID fails to find authors, CrossRef/OpenAlex search does NOT run (we removed the problematic search code in Fix 2).

---

### Step 3: Ollama Fallback (Last Resort)

**Location**: `scripts/paper_processor_daemon.py` line 4025-4046  
**Module**: `shared_tools/metadata/paper_processor.py` → `process_pdf()` with `use_ollama_fallback=True`

**When It Runs**: If Step 1 and Step 2 both failed to find authors

**What Happens**:
1. Call `process_pdf()` again with `use_ollama_fallback=True`
2. This triggers Ollama processing in `paper_processor.py` (line 718-806)
3. Ollama extracts metadata from PDF text using AI
4. Very slow (60-120 seconds)

**Returns**: Same structure as Step 1

---

## Phase 2: Metadata Processing and Display

### Step 2.1: Filter Garbage Authors

**Location**: `scripts/paper_processor_daemon.py` line 4058  
**Method**: `filter_garbage_authors()`

**What Happens**:
- Filters authors that aren't in Zotero database
- For GROBID: Also validates authors appear in document text (prevents hallucinations)
- Keeps only known/valid authors

---

### Step 2.2: Year Prompt/Confirmation

**Location**: `scripts/paper_processor_daemon.py` line 4060-4183

**When Year Prompt is Skipped**:
- Valid DOI found AND API lookup succeeded (line 4068-4074)
- API-provided year is reliable, no confirmation needed

**When Year Prompt Appears**:
- Year found by GREP (regex from scan text)
- Year found by GROBID/API
- Multiple year sources (show all, detect conflicts)
- User can: confirm, change, or enter manually

---

### Step 2.3: Document Type Confirmation

**Location**: `scripts/paper_processor_daemon.py` line 4185-4206

**When Type Prompt is Skipped**:
- API lookup succeeded AND document type provided (line 4196-4199)
- JSTOR ID detected (auto-set as journal_article)

**When Type Prompt Appears**:
- User selects from list of document types
- Sets `document_type` in metadata

---

### Step 2.4: Display Metadata

**Location**: `scripts/paper_processor_daemon.py` line 4208, 4225  
**Method**: `display_extracted_metadata()`

**What It Shows**:
- Extraction time
- **Data source**: From `metadata.get('source', 'OCR extraction')` 
- **Method**: From `metadata.get('method', 'unknown')`
- All metadata fields (title, authors, year, journal, etc.)

**Issue**: If metadata doesn't have 'source' field, defaults to "OCR extraction (unknown)" - this is why Zotero manual selections show wrong source.

---

## Phase 3: Failed Extraction (Manual Entry)

**Location**: `scripts/paper_processor_daemon.py` line 4210-4230  
**Method**: `handle_failed_extraction()`

**When It Runs**: If all extraction methods failed (no authors found)

**What Happens**:
1. Prompt for document type (line 2181-2217)
2. Prompt for DOI (optional, line 2219-2231)
3. **Manual Metadata Entry** (line 2233-2253):
   - Prompt for first author's last name
   - Search Zotero by author
   - If match found: User selects item → `convert_zotero_item_to_metadata()` → Returns metadata
   - If no match: Continue with manual entry (title, year, journal, etc.)

**Issue**: `convert_zotero_item_to_metadata()` doesn't set 'source' or 'method', so display shows wrong source.

---

## Phase 4: Zotero Search and Item Selection

**Location**: `scripts/paper_processor_daemon.py` line 4232-4308  
**Method**: `search_and_display_local_zotero()`

**What Happens**:
1. **Year Prompt** (line 1385-1393):
   - Prompt for year if missing (unless already confirmed)
   - **Fix 1**: If called with `force_prompt_year=True`, prompts even if year exists (allows changing)
   
2. **Author Selection** (line 1502-1536):
   - User selects which authors to search by
   - User can edit/add/remove authors
   
3. **Zotero Search** (line 1406-1600):
   - Search by author + year + document type
   - Component-based search strategy
   - Display matches with numbers
   
4. **Item Selection** (line 1602-1780):
   - User selects item from list
   - User can: select, edit search params, edit metadata, create new, skip, quit

---

## Data Flow Summary

### Identifiers → APIs Flow
