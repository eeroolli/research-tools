### Debug/Implementation Plan: GROBID, Online Search, File Copy

#### Scope
Address multiple issues end-to-end:
- GROBID extracting 0 authors on simple layouts.
- Online search (CrossRef/OpenAlex) returning nothing; CrossRef 400.
- File copy "Operation not permitted" even when file exists.
- DOI extraction failing due to OCR errors (DO!, DO1, DOl).
- ISSN extraction not preferring online over print ISSN.
- Match display missing journal, DOI, and abstract information.
- GROBID abstract not being added to Zotero items.
- DOI not shown or used when extracted via OCR.
- Manual DOI entry needed in metadata editor (independent of Zotero items).
- DOI cleaning/normalization duplicated across multiple API clients.
- JSTOR URLs misclassified as arXiv IDs (e.g., stable/2289064).
- Missing backward navigation in final confirmation step.
- Insufficient Zotero item information during selection for reviewing metadata.

---

## 1) GROBID: 0 authors despite readable text

- Diagnostics
  - Enable temporary TEI/XML dump when authors list is empty:
    - Save TEI to `./data/temp/grobid_tei/<basename>.tei.xml`.
    - Log GROBID URL, status code, body snippet on failure.
  - Verify container health:
    - `docker logs grobid`
    - `curl -s http://localhost:8070/api/isalive`
  - Confirm we call GROBID on the split file (we do) and that page count/rotation looks normal.

- Likely root causes
  - First 2 pages (max_pages=2) do not contain proper author metadata after split.
  - Split halves introduce unusual bounding boxes or require rotation retry.
  - TEI parsing path too strict or missing fallback.

- Implementation
  - Add debug TEI dump when authors=0.
  - Retry strategy:
    - If authors=0 → re-run with `max_pages=4`.
    - If still 0 → try rotated variants (90/270) on a temp copy, call again with `max_pages=2`.
  - Harden TEI parsing:
    - Log first seen author block fields; handle missing tags without aborting.

- Acceptance criteria
  - On your test PDF, GROBID yields at least the first author correctly.
  - Debug TEI present for failures, and removed on success runs.

---

## 2) Online search: CrossRef 400 / no results

- Diagnostics
  - Log outgoing queries (sanitized) for CrossRef/OpenAlex:
    - Endpoint, query params (title, author, year, container-title).
    - Response code and first 200 chars of body on failure.
  - Confirm `crossref_email` is set in config for polite pool and that all params are URL-encoded.

- Likely root causes
  - OCR noise in title (e.g., “racoial” for “racial”), diacritics (“Dædalus”) causing bad queries or 400.
  - Over-constrained queries (title+author+journal) without tolerant variants.

- Implementation
  - Add `normalize_ocr_artifacts(text)`:
    - Fix common OCR substitutions; collapse repeated letters; remove stray punctuation; NFKD normalize and generate both “Daedalus” and “Dædalus” forms.
    - Limit title to top 8–10 high-signal tokens.
  - Multi-variant search:
    - Variant A: title-only simplified.
    - Variant B: author+year.
    - Variant C: author+year+journal (both Daedalus/Dædalus).
  - If CrossRef returns 400 or 429:
    - Retry with simpler query.
    - Fallback to OpenAlex with equivalent variants.
  - Ensure polite-pool email set in `config.personal.conf` and log a warning if missing.

- Acceptance criteria
  - For “Looking ahead: racial trends in the United States” with Hochschild/2005, at least one library returns candidates.

---

## 3) File copy: EPERM though file exists or is identical

- Diagnostics
  - Before copy:
    - If a file with the same name exists: compare size and SHA-256.
    - If identical: treat as success; skip copy.
  - After copy failure:
    - Re-check destination; if exists and identical → treat as success.
  - Log resolved Windows paths:
    - Source (converted via `wslpath -w`).
    - Target dir and final full path.

- Likely root causes
  - Destination exists (Google Drive) and returns EPERM on overwrite.
  - Minor path quirks with drvfs timing or name collision.

- Implementation
  - Pre-copy identical check (size+hash).
  - On name collision with different content: try `_scanned2`, `_scanned3` suffix, then copy again.
  - Post-failure recovery:
    - If file exists and is identical → success.
    - Else retry with `Move-Item -Force` or `Copy-Item -Force` in PowerShell; if still failing, suggest manual recovery.
  - Keep logs concise but actionable.

- Acceptance criteria
  - No false failures when the file is already present and identical.
  - When different file exists, a suffixed copy is created successfully.

---

## 4) Identifier Extraction: OCR Errors and Display Improvements

### 4.1 DOI Extraction: Handle OCR Errors ✅ COMPLETED

- Diagnostics ✅
  - OCR often misreads "DOI:" as "DO!", "DO1", or "DOl" (especially at page bottoms).
  - Current regex patterns only match "DOI:" exactly, missing OCR variants.

- Implementation ✅
  - ✅ Added OCR error patterns to `DOI_PATTERNS` in `shared_tools/utils/identifier_extractor.py`:
    - Pattern: `r'DO[!1lI]:\s*(10\.\d{4,}/[^\s\)]+)'` (case-insensitive)
    - Standalone variant: `r'\bDO[!1lI]\s*:\s*(10\.\d{4,}/[^\s\)]+)'`
  - ✅ Normalized extracted DOIs by cleaning OCR artifacts before validation.
  - ✅ Tested with actual OCR text: "DO!: 10.1080/13501780701394094" - working correctly.

- Acceptance criteria ✅
  - ✅ DOI detected in text with "DO!", "DO1", or "DOl" variants.
  - ✅ Normalized DOI passes validation.

---

### 4.2 ISSN Extraction: Prefer Online Over Print ✅ COMPLETED

- Diagnostics ✅
  - Many journals have both print ISSN (e.g., 1350-178X) and online ISSN (e.g., 1469-9427).
  - Current extraction returns all ISSNs without preference.
  - Online ISSN is more useful for digital documents.

- Implementation ✅
  - ✅ Enhanced `extract_issns()` in `shared_tools/utils/identifier_extractor.py`:
    - ✅ Detects context markers within 20 characters after ISSN: "print", "online", "electronic", etc.
    - ✅ Uses distance-based classification: when both "online" and "print" markers found, prefers closer one.
    - ✅ Returns list with online ISSN first when both exist.
    - ✅ Only checks immediate context (20 chars) to avoid noise from distant keywords.
  - ✅ Tested with actual OCR text: "ISSN 1350-178X print/ISSN 1469-9427 online" - correctly returns `['1469-9427', '1350-178X']`.

- Acceptance criteria ✅
  - ✅ Documents with both print and online ISSN: online ISSN is returned first.
  - ✅ Single ISSN (either type) still extracted correctly.
  - ✅ Markers too far away (>20 chars) are ignored to prevent misclassification.

---

### 4.3 Enhanced Match Display: Journal, DOI, Abstract ✅ COMPLETED

- Diagnostics ✅
  - Current match display shows: title, authors, year, PDF status.
  - Missing useful fields: journal name, DOI, abstract.
  - Users need this info to make informed selection decisions.

- Implementation ✅

  **A. Add fields to search results** (`shared_tools/zotero/local_search.py`) ✅:
  - ✅ Modified `_search_by_doi()` and `_search_by_title_fuzzy()` to query additional fields.
  - ✅ Added helper methods `_get_item_type()`, `_get_container_info()`, `_get_journal()`, `_get_doi()`, `_get_abstract()`.
  - ✅ Created type-aware `_get_container_info()` method that returns correct field based on document type:
    - `journalArticle` → `publicationTitle` (labeled as "Journal")
    - `conferencePaper` → `proceedingsTitle` (labeled as "Conference")
    - `bookSection` → `bookTitle` (labeled as "Book")
  - ✅ Updated `search_by_authors_ordered()` to include these fields.

  **B. Enhance match display** (`scripts/paper_processor_daemon.py`) ✅:
  - ✅ Updated `display_and_select_zotero_matches()` to show:
    - Container info: `{Label}: {value}` (e.g., "Journal: Nature", "Book: Title of Book", "Conference: ICML 2023")
    - DOI: `DOI: {doi}` (if available)
    - Abstract: `Abstract: {preview}...` (first 150 chars if available, truncated with "..." if longer)
  - ✅ Display uses document-type-aware labels instead of always showing "Journal".

  **C. Normalize additional fields** (`scripts/paper_processor_daemon.py`) ✅:
  - ✅ Updated `_normalize_search_result()` to pass through `container_info`, `item_type`, `doi`, `abstract`.
  - ✅ Handles both `publicationTitle`/`journal` and `abstractNote`/`abstract` field name variants.
  - ✅ Maintains backward compatibility with existing `journal` field.

- Acceptance criteria ✅
  - ✅ Journal articles show "Journal: {name}" in match list.
  - ✅ Book chapters show "Book: {book title}" in match list.
  - ✅ Conference papers show "Conference: {conference name}" in match list.
  - ✅ Items with DOI show DOI in match list.
  - ✅ Items with abstract show preview in match list.
  - ✅ Display remains readable and not cluttered.
  - ✅ Display is document-type aware, showing appropriate labels for each type.

---

### 4.4 Extraction Flow Optimization: GREP-First Approach ✅ COMPLETED

- Diagnostics ✅
  - GROBID-first approach was slower (5-10+ seconds) even when identifiers were available.
  - GREP (regex identifier extraction) is much faster (1-2 seconds).
  - API lookups with valid identifiers are also fast (1-2 seconds).
  - Combined: GREP + API lookup = 2-4 seconds vs. GROBID 5-10+ seconds.

- Implementation ✅
  - ✅ Restructured `process_paper()` in `scripts/paper_processor_daemon.py`:
    - ✅ Step 1: Always try GREP first (identifier extraction + API lookup) - 2-4 seconds
    - ✅ Step 2: Fallback to GROBID only if no identifiers found or API lookup failed
    - ✅ Step 3: Last resort - Ollama if GROBID also failed
  - ✅ Leverages existing `metadata_processor.process_pdf()` optimized workflow.
  - ✅ Maintains all existing error handling and user workflow.

- Acceptance criteria ✅
  - ✅ Papers with DOIs process in 2-4 seconds (vs. 5-10+ seconds with GROBID-first).
  - ✅ DOI extraction happens first and is visible/used immediately.
  - ✅ GROBID still used when needed (no identifiers found).
  - ✅ Preserves existing error handling and user workflow.

---

### 4.5 Centralized DOI Normalization ✅ COMPLETED

- Diagnostics ✅
  - DOI cleaning code was duplicated in multiple places:
    - `PubMedClient.get_metadata_by_doi()`
    - `OpenAlexClient.get_metadata_by_doi()`
    - `CrossRefClient.get_metadata()`
    - `IdentifierValidator.validate_doi()` (internal)
  - Violates DRY principle - changes need to be made in multiple places.
  - Risk of inconsistency between implementations.

- Implementation ✅
  - ✅ Added `normalize_doi()` static method in `IdentifierValidator`:
    - Cleans common prefixes (`https://doi.org/`, `doi:`, `http://dx.doi.org/`, etc.)
    - Case-insensitive handling
    - Returns None if input is empty/None
    - Does NOT validate (use `validate_doi()` for validation)
  - ✅ Updated `validate_doi()` to use `normalize_doi()` internally.
  - ✅ Updated all API clients to use centralized `normalize_doi()`:
    - `PubMedClient.get_metadata_by_doi()`
    - `OpenAlexClient.get_metadata_by_doi()`
    - `CrossRefClient.get_metadata()`

- Acceptance criteria ✅
  - ✅ Single source of truth for DOI normalization.
  - ✅ All API clients use same normalization logic.
  - ✅ Consistent behavior across codebase.

---

### 4.6 Manual DOI Entry in Metadata Editor ✅ COMPLETED

- Diagnostics ✅
  - DOI entry was only available when online/local metadata sources existed.
  - Early return blocked manual editing when no Zotero items or online metadata found.
  - No validation feedback when entering DOI manually.
  - Could not fetch metadata after manually entering a DOI.

- Implementation ✅
  - ✅ Removed early return in `edit_metadata_interactively()` that blocked manual editing.
  - ✅ DOI entry section always available, regardless of metadata sources.
  - ✅ Added validation with `IdentifierValidator.validate_doi()`:
    - Shows validation feedback (valid/invalid messages)
    - Auto-normalizes common prefixes
    - Supports multiple formats: `10.1234/example`, `https://doi.org/10.1234/...`, `doi:10.1234/...`
  - ✅ Optional metadata fetching: If valid DOI entered and no metadata exists, offers to fetch from APIs.
  - ✅ User can choose to merge fetched metadata with existing fields.
  - ✅ Retry mechanism if validation fails.

- Acceptance criteria ✅
  - ✅ Manual DOI entry works independently of Zotero items.
  - ✅ Validation provides clear feedback.
  - ✅ Optional metadata fetching integrates seamlessly.
  - ✅ Supports all common DOI input formats.

---

### 4.7 Tags Display in Zotero Item Selection ✅ COMPLETED

- Diagnostics ✅
  - Tags not fetched from local Zotero database during search.
  - Tags not displayed when selecting existing Zotero items.
  - Tags are useful for quick identification of items.

- Implementation ✅
  - ✅ Added `_get_tags()` method in `ZoteroLocalSearch` to fetch tags from SQLite database.
  - ✅ Included tags in all search methods:
    - `_search_by_doi()`
    - `_search_by_title_fuzzy()`
    - `search_by_authors_ordered()`
  - ✅ Tags displayed first in `handle_item_selected()` (right after title, before authors).
  - ✅ Added tags to normalization in `_normalize_search_result()`.

- Acceptance criteria ✅
  - ✅ Tags fetched and displayed when selecting Zotero items.
  - ✅ Tags appear first for quick reference.
  - ✅ Tags available in all search result types.

---

### 4.8 JSTOR Identifier Extraction and Classification ✅ COMPLETED

- Diagnostics ✅
  - JSTOR URLs were being extracted as generic URLs but not handled specially.
  - JSTOR stable URLs (e.g., http://www.jstor.org/stable/2289064) indicate journal articles by definition.
  - No dedicated JSTOR identifier extraction existed.

- Implementation ✅
  - ✅ Added `extract_jstor_ids()` method in `shared_tools/utils/identifier_extractor.py`:
    - Pattern: `r'https?://(?:www\.)?jstor\.org/stable/(\d+)'`
    - Extracts JSTOR stable URL IDs separately from generic URLs.
  - ✅ Integrated into `extract_all()` and `extract_first_page_identifiers()` methods.
  - ✅ Added reporting in paper processor logs.
  - ✅ JSTOR URLs automatically classified as journal articles.
  - ✅ JSTOR URLs excluded from generic URL extraction to prevent confusion.

- Acceptance criteria ✅
  - ✅ JSTOR stable URLs extracted correctly (e.g., "2289064" from full URL).
  - ✅ Documents with JSTOR IDs automatically classified as journal articles.
  - ✅ No confusion with generic URL handling.
  - ✅ Proper logging and reporting in extraction flow.

---

### 4.9 arXiv URL Misclassification Fix ✅ COMPLETED

- Diagnostics ✅
  - JSTOR stable URLs like "stable/2289064" were being misclassified as arXiv IDs (old format pattern).
  - Generic subject patterns like "stable/" matched arXiv old format regex.
  - No validation to distinguish real arXiv IDs from similar patterns.

- Implementation ✅
  - ✅ Enhanced `extract_arxiv_ids()` with proximity checks:
    - Requires "arxiv" within 20 characters of potential arXiv ID.
    - Prevents false positives from random subject/number patterns.
  - ✅ Added comprehensive arXiv subject whitelist:
    - Valid subjects: cs, math, physics, astro-ph, etc.
    - Only accepts known arXiv subject categories for old format.
  - ✅ Fixed validation logic to properly check subject against whitelist.

- Acceptance criteria ✅
  - ✅ "stable/2289064" no longer misclassified as arXiv ID.
  - ✅ Real arXiv IDs (e.g., "cs.AI/0001001") still extracted correctly.
  - ✅ New format arXiv IDs (e.g., "2301.12345") still work.
  - ✅ Valid arXiv IDs with "arxiv" nearby still detected.

---

### 4.10 Backward Navigation in Final Confirmation ✅ COMPLETED

- Diagnostics ✅
  - Final "Proceed with these actions?" confirmation had no way to go back.
  - Users who wanted to reconsider their Zotero item selection were stuck or had to cancel.
  - No navigation control at final step.

- Implementation ✅
  - ✅ Added (z) option to "go back to item selection" in final confirmation prompt.
  - ✅ Updated confirmation prompt to show all options clearly.
  - ✅ Proper handling when user chooses (z) - moves to manual review.

- Acceptance criteria ✅
  - ✅ (z) option available in final confirmation.
  - ✅ User can navigate back to reconsider item selection.
  - ✅ Clear documentation of all options in prompt.

---

### 4.11 Enhanced Zotero Item Selection UX ✅ COMPLETED

- Diagnostics ✅
  - After selecting a Zotero item, system jumped directly to attachment without showing full metadata.
  - Users couldn't review or edit metadata before attaching PDF.
  - No way to see tags, abstract, journal details that might need correction.
  - Duplicate code displaying same information multiple times.

- Implementation ✅
  - ✅ Added comprehensive metadata review display with `_display_zotero_item_details()`:
    - Shows: title, journal/conference/book, authors, year, DOI, abstract preview, tags
    - Tags displayed in multi-column format for readability.
  - ✅ Added review prompt with three options:
    - (y/Enter): Proceed with attachment
    - (e): Edit metadata in Zotero first
    - (z): Go back to item selection
  - ✅ Eliminated duplicate code:
    - Removed redundant title/tags/authors display.
    - Consolidated author extraction logic.
    - Streamlined flow by ~25 lines of code.

- Acceptance criteria ✅
  - ✅ Full metadata displayed before attachment decision.
  - ✅ User can choose to edit, proceed, or go back.
  - ✅ Code is cleaner without duplication.
  - ✅ Better user experience with informed decision-making.

---

### 4.12 GROBID Abstract Addition to Zotero Items

- Diagnostics
  - GROBID successfully extracts abstracts (visible in TEI dumps).
  - Abstracts are parsed and included in metadata dict.
  - When attaching PDF to existing Zotero item, abstract is not added if Zotero field is empty.

- Implementation
  - In `_process_selected_item()` (`scripts/paper_processor_daemon.py`, starting line 4883):
    - After PDF attachment step (around line 4962-4980):
      - Check if Zotero item's `abstractNote` field is empty or missing.
      - If `metadata` contains `abstract` from GROBID and Zotero field is empty:
        - Update item via Zotero API to add abstract.
        - Use `zotero_processor.update_item()` or direct API call.
        - Log: "Added abstract from GROBID extraction"
      - Only update if Zotero field is truly empty (not just whitespace).
  - Ensure update happens after PDF attachment but before moving to done.

- Acceptance criteria
  - Zotero item with empty abstract gets abstract from GROBID.
  - Zotero item with existing abstract is not overwritten.
  - Operation is logged for debugging.

---

## Code Touchpoints

- GROBID handling
  - File: `scripts/paper_processor_daemon.py`
  - Functions: `process_paper`, the GROBID client hook, and TEI parsing path.
  - Add TEI dump and retry logic (max_pages/rotation).

- Online library search
  - File: `shared_tools/metadata/paper_processor.py` (and any API wrappers used)
  - Add `normalize_ocr_artifacts` and variant query builder.
  - Improve request logging and error handling for CrossRef/OpenAlex.

- File copy logic
  - File: `scripts/paper_processor_daemon.py`
  - Function(s): `_copy_to_publications_via_windows`, `copy_to_publications`, and the identical-file helpers.
  - Add pre/post checks and conflict suffix strategy.

- Identifier extraction
  - File: `shared_tools/utils/identifier_extractor.py`
  - Functions: `extract_dois()`, `extract_issns()`, `extract_jstor_ids()`, `extract_arxiv_ids()`, `extract_urls()`.
  - ✅ Added OCR error handling patterns and ISSN preference logic.
  - ✅ Added JSTOR identifier extraction with automatic classification.
  - ✅ Enhanced arXiv extraction with proximity checks and subject whitelist.
  - ✅ JSTOR URLs excluded from generic URL extraction.

- Identifier validation and normalization
  - File: `shared_tools/utils/identifier_validator.py`
  - Functions: `normalize_doi()`, `validate_doi()`.
  - ✅ Added centralized `normalize_doi()` method for consistent DOI cleaning across codebase.

- API clients
  - Files: `shared_tools/api/pubmed_client.py`, `shared_tools/api/openalex_client.py`, `shared_tools/api/crossref_client.py`
  - Functions: `get_metadata_by_doi()` in each client.
  - ✅ Updated to use centralized `IdentifierValidator.normalize_doi()`.

- Processing flow
  - File: `scripts/paper_processor_daemon.py`
  - Function: `process_paper()`
  - ✅ Restructured to GREP-first (fast identifier extraction + API lookup before GROBID fallback).
  - ✅ Automatic document type classification for JSTOR IDs.
  - File: `shared_tools/metadata/paper_processor.py`
  - Function: `process_pdf()`
  - ✅ JSTOR ID handling with automatic journal article classification.

- Zotero search and display
  - File: `shared_tools/zotero/local_search.py`
  - Functions: `_search_by_doi()`, `_search_by_title_fuzzy()`, `search_by_authors_ordered()`, `_get_tags()`.
  - ✅ Added tag fetching and inclusion in all search results.
  - File: `scripts/paper_processor_daemon.py`
  - Functions: `display_and_select_zotero_matches()`, `_normalize_search_result()`, `handle_item_selected()`, `_display_zotero_item_details()`, `edit_metadata_interactively()`.
  - ✅ Enhanced display with tags shown first, manual DOI entry with validation.
  - ✅ Added comprehensive metadata review step with edit/proceed/back options.
  - ✅ Eliminated duplicate code in item selection flow.
  - ✅ Added backward navigation (z) option in final confirmation.

---

## Test Procedure

- GROBID
  - Run the same split PDF.
  - Expect ≥1 author from GROBID or successful fallback logic; if not, find TEI dump under `./data/temp/grobid_tei/`.

- Online search
  - With `title=Looking ahead: racial trends in the United States`, `author=Hochschild`, `year=2005`, `journal=Dædalus/Daedalus`:
    - Confirm at least one match from CrossRef or OpenAlex.
    - Verify logs show queries and handled 400 gracefully.

- File copy
  - Case A: identical file already exists → skip copy, success.
  - Case B: different file exists → suffixed copy created; Zotero attach succeeds.
  - Case C: first copy fails, but destination is present and identical → treated as success.

- Identifier extraction
  - Test DOI extraction with OCR errors: "DO!:", "DO1:", "DOl:" variants.
  - Test ISSN extraction: Document with both print (1350-178X) and online (1469-9427) ISSN.
  - Verify online ISSN is returned first.
  - Test JSTOR URL extraction: http://www.jstor.org/stable/2289064 should extract "2289064".
  - Test arXiv URL fix: "stable/2289064" should NOT be misclassified as arXiv ID.
  - Test arXiv extraction: Valid arXiv IDs (cs.AI/0001001 or 2301.12345) with "arxiv" nearby should still work.

- Match display
  - Search for journal article: Verify journal name, DOI, and abstract preview appear.
  - Display format remains readable and not cluttered.
  - Note displayed: "All items shown below already exist in your Zotero library."

- UX flow
  - After selecting a Zotero item: Verify detailed metadata review appears with all fields.
  - Verify three options available: (y) proceed, (e) edit, (z) go back.
  - Verify (z) option works in final confirmation to navigate back.
  - Verify code has no duplication in item selection flow.

- Abstract addition
  - Zotero item with empty abstract: Verify abstract from GROBID is added.
  - Zotero item with existing abstract: Verify it is not overwritten.

---

## Rollout Steps

1. Implement GROBID debug+retry.
2. Implement normalized, multi-variant online search with improved logging.
3. Implement idempotent file copy with identical checks and suffixing.
4. ✅ **COMPLETED** - Implement DOI OCR error handling patterns.
5. ✅ **COMPLETED** - Implement ISSN preference logic (online over print).
6. ✅ **COMPLETED** - Enhance Zotero search to include journal/DOI/abstract fields with document-type awareness.
7. ✅ **COMPLETED** - Enhance match display to show journal/book/conference, DOI, and abstract.
8. ✅ **COMPLETED** - Optimize extraction flow: GREP-first (identifier extraction + API lookup) before GROBID fallback.
9. ✅ **COMPLETED** - Tags displayed first when selecting existing Zotero items.
10. ✅ **COMPLETED** - Centralized DOI normalization function (`normalize_doi()`) in IdentifierValidator.
11. ✅ **COMPLETED** - Manual DOI entry in metadata editor (works independently of Zotero items).
12. ✅ **COMPLETED** - JSTOR identifier extraction with automatic journal article classification.
13. ✅ **COMPLETED** - arXiv URL misclassification fix with proximity checks and subject whitelist.
14. ✅ **COMPLETED** - Identifier separation: JSTOR URLs excluded from generic URL extraction.
15. ✅ **COMPLETED** - Backward navigation added to final confirmation step.
16. ✅ **COMPLETED** - Enhanced Zotero item selection UX with metadata review step.
17. ✅ **COMPLETED** - UX code optimization: Eliminated duplicate code in item selection flow.
18. Add GROBID abstract update logic for existing Zotero items.
19. Re-run your test PDF and validate logs + outcomes.

- GROBID produces authors or a robust fallback handles the case.
- At least one online metadata candidate shown for the test.
- File copy reports success (either detected identical or successful copy/suffix) and attaches to Zotero.
- ✅ **COMPLETED** - DOI extracted from OCR text with "DO!", "DO1", or "DOl" errors.
- ✅ **COMPLETED** - Online ISSN preferred when both print and online ISSN exist.
- ✅ **COMPLETED** - Match display shows document-type-aware container info (Journal/Book/Conference), DOI, and abstract preview for better decision-making.
- ✅ **COMPLETED** - Tags displayed first when selecting Zotero items for quick reference.
- ✅ **COMPLETED** - GREP-first approach: Fast identifier extraction (2-4 seconds) before GROBID fallback.
- ✅ **COMPLETED** - DOI normalization centralized: All API clients now use `IdentifierValidator.normalize_doi()`.
- ✅ **COMPLETED** - Manual DOI entry always available in metadata editor, with validation and optional metadata fetching.
- ✅ **COMPLETED** - JSTOR identifier extraction: JSTOR stable URL IDs extracted separately, automatically classified as journal articles.
- ✅ **COMPLETED** - arXiv URL misclassification fix: Proximity checks (20 chars) and subject whitelist prevent JSTOR URLs from being misclassified as arXiv IDs.
- ✅ **COMPLETED** - Identifier separation: JSTOR URLs excluded from generic URL extraction to prevent confusion and double-counting.
- ✅ **COMPLETED** - Backward navigation: Added (z) option to go back from final confirmation step.
- ✅ **COMPLETED** - Enhanced Zotero item selection UX: Added detailed metadata review step before attachment with options to edit, proceed, or go back.
- ✅ **COMPLETED** - UX code optimization: Eliminated duplicate code in item selection, streamlined metadata display.
- GROBID abstract automatically added to Zotero items when field is empty.