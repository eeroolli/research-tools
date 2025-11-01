# Journal Validator Implementation Plan

**Status:** Planning  
**Created:** 2025-01-11  
**Related Files:** `shared_tools/utils/author_validator.py`, `scripts/paper_processor_daemon.py`

## Overview

Implement a `JournalValidator` class similar to `AuthorValidator` to:
- Validate extracted journal titles against Zotero collection
- Correct OCR errors in journal names
- Normalize journal name variations (abbreviations, full names)
- Ensure consistency across the Zotero library
- Speed up metadata entry with suggestions/autocomplete

## Goals

### Primary Goals
1. **OCR Error Correction**: Fix common scanning mistakes (e.g., "Joumal" → "Journal")
2. **Consistency**: Normalize variations like "J. Pol. Sci." → "Journal of Political Science"
3. **Speed**: Reduce manual typing and decision-making time
4. **Data Quality**: Prevent typos from propagating into Zotero

### Secondary Goals
1. **Learning**: System learns new journals as collection grows
2. **Integration**: Seamless integration with existing metadata editor
3. **Performance**: Fast lookup with caching (similar to AuthorValidator)

## Challenges & Solutions

### Challenge 1: Journal Name Variations (More Complex Than Authors)

**Problem:**
- Abbreviations: "J. Pol. Sci." vs "Journal of Political Science" vs "JPOLSCI"
- Acronyms: "PS" could be "Political Science" or "Psychology"
- Name changes: Journals rebrand over time
- Publisher variations: "Cambridge University Press" vs "CUP"

**Solution (Phased):**
- **Phase 1**: Exact match + simple fuzzy matching (like authors)
- **Phase 2**: Build abbreviation dictionary from actual Zotero data
- **Phase 3**: Advanced normalization if needed (expansion rules, context-aware)

### Challenge 2: Matching Ambiguity

**Problem:**
- "PS" could mean multiple journals
- Need better disambiguation than lastname-only matching

**Solution:**
- Show paper count for each match (like authors: "Journal X (15 papers)")
- Allow user to see alternatives and select
- Use context when available (ISSN, publisher from same paper)

### Challenge 3: Performance

**Problem:**
- Larger datasets than authors potentially (more unique journal names)
- Normalization overhead

**Solution:**
- Same caching strategy as AuthorValidator (JSON cache, 24h refresh)
- Index by normalized key words (like lastname index)
- Fast exact match first, then fuzzy if needed

## Architecture

### File Structure
```
shared_tools/utils/
├── author_validator.py      # Existing (reference implementation)
└── journal_validator.py      # New (similar pattern)

data/cache/
├── zotero_authors.json       # Existing
└── zotero_journals.json      # New
```

### Why a Class? (Not Just Functions)

**Question:** Should we use a class or module-level functions?

**Analysis:**
Looking at the codebase, `shared_tools/utils/` modules **all use classes**:
- `AuthorValidator` - class (maintains state: cache, indexes)
- `ISBNMatcher` - class (all `@staticmethod`, but still a class)
- `IdentifierExtractor` - class
- `FileManager` - class
- `CPUMonitor` - class

**Why AuthorValidator uses a class:**
- Maintains **state**: `self.zotero_authors` (cached list, loaded once, reused many times)
- Maintains **indexes**: `self.lastname_index` (fast lookup dictionary)
- Maintains **configuration**: `self.db_path`, `self.cache_file` (from config)
- **Performance**: Avoid re-querying database on every validation

**JournalValidator needs the same state management:**
- ✅ Cached journal list (avoid re-querying database)
- ✅ Normalized index (fast lookup for common case)
- ✅ Configuration (database path, cache location)

**Alternative (Module Functions):** Could use module-level cache variables, but:
- ❌ Breaks encapsulation (harder to test, reset state, thread safety)
- ❌ Doesn't follow existing codebase pattern
- ❌ Makes concurrent access issues possible
- ✅ Would work functionally, but inconsistent with codebase

**Decision:** Use class to:
1. **Match existing pattern** - `AuthorValidator` already uses a class
2. **Maintain state properly** - Cache and indexes need instance variables
3. **Follow codebase conventions** - All utilities in `shared_tools/utils/` use classes
4. **Enable testing** - Easier to test with isolated instances

**Note:** If you prefer functional style, we could refactor both `AuthorValidator` and `JournalValidator` to use module functions with module-level cache, but that would be a larger architectural change affecting existing code.

### Class Structure (Similar to AuthorValidator)

```python
class JournalValidator:
    """Validate extracted journals against Zotero collection."""
    
    # Core initialization (like AuthorValidator)
    def __init__(self, db_path=None, cache_file=None)
    def _get_db_path_from_config(self) -> Path
    def _load_journal_list(self)
    def _extract_from_database(self, silent=False)
    def _save_cache(self, silent=False)
    
    # Cache management (like AuthorValidator)
    def cache_age_hours(self) -> Optional[float]
    def needs_refresh(self, max_age_hours=24) -> bool
    def refresh_if_needed(self, max_age_hours=24, silent=True) -> bool
    def rebuild_cache(self)
    
    # Indexing (similar to lastname_index)
    def _normalize_journal_name(self, name: str) -> str
    def _build_normalized_index(self)
    
    # Validation methods
    def validate_journal(self, extracted_journal: str) -> Dict
    def suggest_ocr_correction(self, extracted_name: str, max_distance=2) -> Optional[Dict]
    def find_similar_journals(self, journal_name: str, max_results=5) -> List[Dict]
    
    # Helper methods
    def get_journal_info(self, journal_name: str) -> Optional[Dict]
    def _edit_distance(self, s1: str, s2: str) -> int
```

## Implementation Phases

### Phase 1: MVP - Basic Validation (Like AuthorValidator)

**Goal:** Get core functionality working with simple matching (no normalization yet)

#### 1.1 Core Infrastructure
- [ ] Create `shared_tools/utils/journal_validator.py`
- [ ] Implement `__init__()` with config loading (reuse pattern from AuthorValidator)
- [ ] Implement `_get_db_path_from_config()` (reuse from AuthorValidator)
- [ ] Set up cache file location (`data/cache/zotero_journals.json`)

#### 1.2 Database Extraction
- [ ] Write SQL query to extract journals from Zotero:
  ```sql
  SELECT itemDataValues.value, COUNT(*) as paper_count
  FROM itemData
  JOIN fields ON itemData.fieldID = fields.fieldID
  JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
  JOIN items ON itemData.itemID = items.itemID
  JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
  WHERE fields.fieldName = 'publicationTitle'
  AND itemTypes.typeName = 'journalArticle'
  AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
  AND itemDataValues.value IS NOT NULL
  AND itemDataValues.value != ''
  GROUP BY itemDataValues.value
  ORDER BY paper_count DESC
  ```
- [ ] Implement `_extract_from_database()` method
- [ ] Store results in format: `{'name': 'Journal Name', 'paper_count': 15, 'normalized': 'journal name'}`

#### 1.3 Cache Management
- [ ] Implement `_load_journal_list()` (load from cache or extract)
- [ ] Implement `_save_cache()` (JSON format, version '1.0')
- [ ] Implement cache age checking (`cache_age_hours()`, `needs_refresh()`)
- [ ] Implement `refresh_if_needed()` (silent refresh like AuthorValidator)

#### 1.4 Simple Indexing (No Normalization Yet)
- [ ] Implement `_build_normalized_index()`:
  - Normalize to lowercase
  - Remove leading/trailing whitespace
  - Index: `normalized_name → [full journal names]`
  - Similar to `lastname_index` in AuthorValidator

#### 1.5 Basic Validation Method
- [ ] Implement `validate_journal(journal_name: str) -> Dict`:
  ```python
  Returns:
  {
      'matched': bool,
      'journal_name': str or None,  # Normalized name if matched
      'paper_count': int or None,
      'match_type': 'exact' | 'fuzzy' | 'none',
      'confidence': int (0-100),
      'alternatives': List[str]  # If multiple matches
  }
  ```
- [ ] Exact match first (normalized lookup)
- [ ] Fuzzy match if no exact match (edit distance ≤ 2, similarity > 0.8)

#### 1.6 OCR Correction
- [ ] Reuse `_edit_distance()` from AuthorValidator (or copy implementation)
- [ ] Implement `suggest_ocr_correction()`:
  - Check all journals for similarity > 0.8
  - Calculate edit distance
  - Return best match if distance ≤ max_distance (default: 2)

#### 1.7 Integration Testing
- [ ] Add `if __name__ == "__main__"` test section (like AuthorValidator)
- [ ] Test with known journals from your collection
- [ ] Test OCR error correction
- [ ] Verify cache loading/saving works

**Estimated Time:** 2-3 hours  
**Complexity:** Low-Medium (straightforward port of AuthorValidator pattern)

---

### Phase 2: Integration with Paper Processor

**Goal:** Wire JournalValidator into the paper processing workflow

#### 2.1 Daemon Integration
- [ ] Add JournalValidator initialization in `PaperProcessorDaemon.__init__()`:
  ```python
  # Initialize journal validator
  try:
      from shared_tools.utils.journal_validator import JournalValidator
      self.journal_validator = JournalValidator()
      self.journal_validator.refresh_if_needed(max_age_hours=24, silent=True)
      self.logger.info("✅ Journal validator ready")
  except Exception as e:
      self.logger.error(f"❌ Failed to initialize journal validator: {e}")
      self.journal_validator = None
  ```

#### 2.2 Metadata Validation Hook
- [ ] Add journal validation in metadata processing workflow
- [ ] Validate extracted journal after GROBID/API extraction
- [ ] Show suggestions when journal is found/not found
- [ ] Display in metadata comparison (like author validation)

#### 2.3 Metadata Editor Integration
- [ ] Add journal validation in `edit_metadata_interactively()`:
  - When user edits journal field, show suggestions
  - Display: "Did you mean 'Journal of Political Science'? (15 papers in your collection)"
  - Allow user to accept suggestion or keep typing

#### 2.4 Display Integration
- [ ] Add journal validation display in metadata comparison screens
- [ ] Show recognized journals with checkmarks (like authors)
- [ ] Show unknown journals with "new" indicator
- [ ] Show OCR corrections with confidence score

**Estimated Time:** 1-2 hours  
**Complexity:** Low (wiring existing functionality)

---

### Phase 3: Simple Normalization (Abbreviation Handling)

**Goal:** Handle common abbreviation patterns found in actual Zotero data

#### 3.1 Build Abbreviation Dictionary
- [ ] Analyze actual journal names in Zotero to find patterns:
  - Extract all journal names
  - There is in Zotero also a field for short names that often contains the short version of the journal names.
  - Identify common abbreviation patterns ("J." → "Journal", "Rev." → "Review")
  - Build mapping from actual data (not hardcoded)
- [ ] Create `_build_abbreviation_dict()` method
- [ ] Store in cache file (add to JSON structure)

#### 3.2 Normalization Method
- [ ] Implement `_normalize_journal_name(name: str) -> str`:
  - Remove leading articles ("The", "A", "An")
  - Handle common abbreviations ("J." → "Journal")
  - Normalize punctuation and spacing
  - Convert to lowercase for comparison

#### 3.3 Enhanced Matching
- [ ] Update `validate_journal()` to use normalized names:
  - Try exact match first (normalized)
  - Try normalized match second
  - Fall back to fuzzy match

#### 3.4 Testing
- [ ] Test with real abbreviation examples from your collection
- [ ] Verify false positives are acceptable
- [ ] Ensure performance is still good

**Estimated Time:** 2-3 hours  
**Complexity:** Medium (requires analysis of actual data patterns)

---

### Phase 4: Advanced Features (Optional, Future)

**Goal:** Enhanced UX features if needed

#### 4.1 Autocomplete Support
- [ ] Add `find_similar_journals()` method for autocomplete
- [ ] Return top N matches with paper counts
- [ ] Integrate with metadata editor for typing suggestions

#### 4.2 Context-Aware Disambiguation
- [ ] Use ISSN from same paper to disambiguate
- [ ] Use publisher information when available
- [ ] Show context in suggestions

#### 4.3 Advanced Normalization
- [ ] Full abbreviation expansion rules
- [ ] Handle journal name changes over time
- [ ] Learn from user corrections

**Estimated Time:** 3-5 hours  
**Complexity:** Medium-High (nice-to-have, implement only if needed)

---

## Detailed Method Specifications

### Method: `__init__()`

**Purpose:** Initialize JournalValidator (same pattern as AuthorValidator)

**Parameters:**
- `db_path: Optional[Path] = None` - Zotero database path (reads from config if None)
- `cache_file: Optional[Path] = None` - Cache file path (uses default if None)

**Behavior:**
- Load config to get database path
- Validate database exists
- Set up cache file location (`data/cache/zotero_journals.json`)
- Load journal list from cache or extract from database
- Build normalized index

**Errors:**
- `FileNotFoundError` if database doesn't exist
- `ValueError` if config missing

---

### Method: `_extract_from_database(silent=False)`

**Purpose:** Extract all unique journals from Zotero database

**SQL Query:**
```sql
SELECT itemDataValues.value, COUNT(*) as paper_count
FROM itemData
JOIN fields ON itemData.fieldID = fields.fieldID
JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
JOIN items ON itemData.itemID = items.itemID
JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
WHERE fields.fieldName = 'publicationTitle'
AND itemTypes.typeName = 'journalArticle'
AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
AND itemDataValues.value IS NOT NULL
AND itemDataValues.value != ''
GROUP BY itemDataValues.value
ORDER BY paper_count DESC
```

**Returns:**
- Populates `self.zotero_journals` list
- Each entry: `{'name': 'Journal Name', 'paper_count': 15, 'normalized': 'journal name'}`

**Notes:**
- Excludes deleted items
- Only journal articles (not conference papers, books, etc.)
- Groups by exact name (case-sensitive grouping)
- Orders by frequency (most common first)

---

### Method: `_build_normalized_index()`

**Purpose:** Build fast lookup index for normalized journal names

**Behavior:**
- Creates `self.normalized_index: Dict[str, List[Dict]]`
- Key: normalized journal name (lowercase, trimmed)
- Value: List of journal entries with that normalized name

**Normalization (Phase 1 - Simple):**
```python
def _normalize_journal_name(self, name: str) -> str:
    """Simple normalization: lowercase, trim whitespace."""
    return name.strip().lower()
```

**Phase 3 Enhancement:**
- Remove articles ("The", "A", "An")
- Expand common abbreviations
- Normalize punctuation

**Usage:**
- Fast lookup: `if normalized_name in self.normalized_index:`
- Get alternatives: `self.normalized_index[normalized_name]`

---

### Method: `validate_journal(journal_name: str) -> Dict`

**Purpose:** Validate extracted journal against Zotero collection

**Parameters:**
- `journal_name: str` - Extracted journal name

**Returns:**
```python
{
    'matched': bool,              # True if match found
    'journal_name': str or None,  # Normalized name if matched
    'paper_count': int or None,    # Number of papers in Zotero
    'match_type': str,             # 'exact' | 'fuzzy' | 'normalized' | 'none'
    'confidence': int,             # 0-100 confidence score
    'alternatives': List[str],     # Alternative matches if multiple
    'original': str                # Original extracted name
}
```

**Matching Strategy (Phase 1):**
1. Normalize extracted name
2. Try exact match in `normalized_index`
3. If multiple matches, return first (most common), list others in `alternatives`
4. If no exact match, try fuzzy match (`suggest_ocr_correction()`)
5. Return best result or None

**Example:**
```python
# Input: "J. Pol. Sci."
# Step 1: Normalize → "j. pol. sci."
# Step 2: No exact match
# Step 3: Fuzzy match → "Journal of Political Science" (similarity 0.75)
# Returns: {'matched': True, 'journal_name': 'Journal of Political Science', ...}
```

---

### Method: `suggest_ocr_correction(extracted_name: str, max_distance: int = 2) -> Optional[Dict]`

**Purpose:** Suggest OCR correction for journal name (same pattern as AuthorValidator)

**Parameters:**
- `extracted_name: str` - Name with potential OCR errors
- `max_distance: int = 2` - Maximum edit distance to consider

**Returns:**
```python
{
    'corrected_name': str,      # Suggested correction
    'confidence': int,          # 0-100 confidence score
    'distance': int,           # Edit distance
    'paper_count': int,         # Papers in collection
    'original_name': str        # Original input
}
```

**Algorithm:**
1. Calculate similarity for all journals (using `SequenceMatcher`)
2. Filter: `similarity > 0.8` and `edit_distance <= max_distance`
3. Return best match (highest similarity)

**Example:**
```python
# Input: "Joumal of Political Science" (OCR: 'n' → 'm')
# Finds: "Journal of Political Science" (similarity: 0.96, distance: 1)
# Returns: {... 'corrected_name': 'Journal of Political Science', 'confidence': 96, ...}
```

---

### Method: `get_journal_info(journal_name: str) -> Optional[Dict]`

**Purpose:** Get information about a specific journal from collection

**Parameters:**
- `journal_name: str` - Journal name to look up

**Returns:**
```python
{
    'name': str,                # Full journal name
    'paper_count': int,         # Number of papers in Zotero
    'normalized': str           # Normalized name
}
```

**Usage:**
- Check if journal exists
- Get paper count for display
- Similar to `get_author_info()` in AuthorValidator

---

## Cache File Format

### Version 1.0 (Phase 1)

```json
{
  "version": "1.0",
  "extracted_from": "/path/to/zotero.sqlite",
  "timestamp": "2025-01-11T10:30:00",
  "zotero_journals": [
    {
      "name": "Journal of Political Science",
      "paper_count": 15,
      "normalized": "journal of political science"
    },
    {
      "name": "American Political Science Review",
      "paper_count": 8,
      "normalized": "american political science review"
    }
  ]
}
```

### Version 2.0 (Phase 3 - With Normalization)

```json
{
  "version": "2.0",
  "extracted_from": "/path/to/zotero.sqlite",
  "timestamp": "2025-01-11T10:30:00",
  "abbreviation_dict": {
    "j.": "journal",
    "rev.": "review",
    "pol.": "political",
    "sci.": "science"
  },
  "zotero_journals": [
    {
      "name": "Journal of Political Science",
      "paper_count": 15,
      "normalized": "journal of political science",
      "normalized_no_articles": "journal political science"
    }
  ]
}
```

---

## Integration Points

### 1. Paper Processor Daemon

**Location:** `scripts/paper_processor_daemon.py`

**Changes:**
```python
# In __init__():
self.journal_validator = JournalValidator()
self.journal_validator.refresh_if_needed(max_age_hours=24, silent=True)

# In metadata processing:
if self.journal_validator and metadata.get('journal'):
    validation = self.journal_validator.validate_journal(metadata['journal'])
    if validation['matched']:
        # Show suggestion or auto-correct
```

### 2. Metadata Editor

**Location:** `scripts/paper_processor_daemon.py` → `edit_metadata_interactively()`

**Changes:**
```python
# When editing journal field:
if self.journal_validator:
    suggestion = self.journal_validator.validate_journal(edited.get('journal', ''))
    if suggestion['matched']:
        print(f"✅ Recognized: {suggestion['journal_name']} ({suggestion['paper_count']} papers)")
        # Offer to use suggestion
```

### 3. Metadata Comparison Display

**Location:** `scripts/paper_processor_daemon.py` → metadata display methods

**Changes:**
- Show validation status for journals (like authors)
- Display recognized journals with checkmarks
- Show unknown journals with "new" indicator

---

## Testing Strategy

### Unit Tests (Phase 1)

**Test File:** `tests/test_journal_validator.py` (create if tests directory exists)

**Test Cases:**
1. **Initialization**
   - Test with config-provided database path
   - Test with explicit database path
   - Test error handling (missing database, missing config)

2. **Cache Management**
   - Test cache loading from file
   - Test cache saving
   - Test cache age checking
   - Test refresh_if_needed()

3. **Database Extraction**
   - Test SQL query returns expected format
   - Test excludes deleted items
   - Test only journal articles (not conferences, books)
   - Test grouping and ordering

4. **Validation**
   - Test exact match
   - Test fuzzy match (OCR errors)
   - Test no match
   - Test multiple matches (alternatives)

5. **OCR Correction**
   - Test common OCR errors ("Joumal" → "Journal")
   - Test edit distance threshold
   - Test confidence scoring

### Integration Tests (Phase 2)

1. **Daemon Integration**
   - Test initialization in PaperProcessorDaemon
   - Test silent refresh on startup
   - Test error handling when database unavailable

2. **Metadata Processing**
   - Test validation during paper processing
   - Test suggestions displayed correctly
   - Test user can accept/reject suggestions

3. **Editor Integration**
   - Test suggestions during manual editing
   - Test autocomplete (if Phase 4 implemented)

### Manual Testing (All Phases)

**Test Scenarios:**
1. Scan paper with known journal → verify recognized
2. Scan paper with OCR error → verify correction suggested
3. Scan paper with new journal → verify "new" indicator
4. Edit metadata manually → verify suggestions appear
5. Process multiple papers → verify cache persists

**Test Data:**
- Use actual journals from your Zotero collection
- Test with various formats: full names, abbreviations, OCR errors

---

## Performance Considerations

### Expected Performance (Similar to AuthorValidator)

**Cache Loading:**
- Load from JSON: ~10-50ms (depends on collection size)
- Extract from database: ~100-500ms (one-time or on refresh)

**Validation Lookup:**
- Exact match: <1ms (indexed lookup)
- Fuzzy match: 10-50ms (if needed, depends on collection size)

**Memory Usage:**
- Cache file: ~50-200KB (estimated for typical collection)
- In-memory index: ~100-500KB (estimated)

**Refresh Strategy:**
- Default: Refresh if cache > 24 hours old
- Silent refresh on daemon startup (like AuthorValidator)
- Fast enough to refresh often without user impact

---

## Error Handling

### Database Errors
- **Database not found**: Raise `FileNotFoundError` with helpful message
- **SQL query fails**: Log error, return empty list, allow daemon to continue
- **Database locked**: Retry once, then skip (daemon can continue)

### Cache Errors
- **Cache file corrupted**: Log warning, extract from database, rebuild cache
- **Cache save fails**: Log warning, continue with in-memory data

### Validation Errors
- **Invalid input**: Return empty validation result, don't crash
- **Index not built**: Auto-build on first validation call

---

## Future Enhancements (Backlog)

### Phase 5: Advanced Normalization
- [ ] Full abbreviation dictionary from actual data
- [ ] Handle journal name changes over time
- [ ] Learn from user corrections

### Phase 6: Autocomplete in Editor
- [ ] Real-time suggestions while typing
- [ ] Keyboard navigation (arrow keys, enter to select)
- [ ] Show paper counts in dropdown

### Phase 7: Context-Aware Disambiguation
- [ ] Use ISSN from same paper
- [ ] Use publisher information
- [ ] Use document type hints

### Phase 8: Publisher Validation
- [ ] Similar validator for publishers
- [ ] Reuse same infrastructure
- [ ] Handle publisher name variations

---

## Success Criteria

### Phase 1 Complete When:
- ✅ JournalValidator class created and tested
- ✅ Extracts journals from Zotero database
- ✅ Caching works (load/save/refresh)
- ✅ Basic validation works (exact + fuzzy match)
- ✅ OCR correction works
- ✅ Unit tests pass

### Phase 2 Complete When:
- ✅ Integrated into paper processor daemon
- ✅ Suggestions appear in metadata processing
- ✅ User can accept/reject suggestions
- ✅ No performance degradation

### Phase 3 Complete When:
- ✅ Abbreviation normalization working
- ✅ Handles common abbreviation patterns
- ✅ False positive rate acceptable (< 5%)
- ✅ Performance still good (< 50ms for validation)

### Overall Success:
- ✅ Reduces manual journal entry time by 50%+
- ✅ Prevents typos and inconsistencies
- ✅ Works seamlessly with existing workflow
- ✅ No regressions in existing functionality

---

## Implementation Notes

### Code Reuse
- **Copy `_edit_distance()` from AuthorValidator** (or import if refactored)
- **Reuse config loading pattern** (identical to AuthorValidator)
- **Reuse cache structure** (same JSON format, different data)

### Code Differences from AuthorValidator
- **Indexing**: Journals use normalized full name (not just last word)
- **Matching**: May need multiple strategies (exact, normalized, fuzzy)
- **Normalization**: More complex than author lastname extraction

### Dependencies
- Same as AuthorValidator:
  - `sqlite3` (standard library)
  - `json` (standard library)
  - `configparser` (standard library)
  - `difflib` (standard library)
  - `pathlib` (standard library)
  - `datetime` (standard library)

No new dependencies required.

---

## Timeline Estimate

**Phase 1 (MVP):** 2-3 hours
- Core infrastructure: 1 hour
- Database extraction: 30 minutes
- Cache management: 30 minutes
- Validation methods: 1 hour
- Testing: 30 minutes

**Phase 2 (Integration):** 1-2 hours
- Daemon integration: 30 minutes
- Metadata hooks: 30 minutes
- Editor integration: 30 minutes
- Testing: 30 minutes

**Phase 3 (Normalization):** 2-3 hours
- Abbreviation analysis: 1 hour
- Normalization implementation: 1 hour
- Enhanced matching: 30 minutes
- Testing: 30 minutes

**Total MVP (Phases 1-2):** 3-5 hours  
**With Normalization (Phases 1-3):** 5-8 hours

---

## Risk Assessment

### Low Risk
- ✅ Pattern proven with AuthorValidator
- ✅ Similar complexity to existing code
- ✅ Well-understood problem space

### Medium Risk
- ⚠️ Normalization complexity (Phase 3)
- ⚠️ False positives from fuzzy matching
- ⚠️ Performance with large collections

### Mitigation
- Start simple (Phase 1), add complexity incrementally
- User can always override suggestions
- Cache and indexing ensure good performance
- Test with actual data early

---

## Documentation Updates

After implementation, update:
- [ ] README.md - Add journal validation to features list
- [ ] implementation-plan.md - Mark journal validator as complete
- [ ] Code docstrings - Ensure all methods documented
- [ ] User guide - Document journal validation workflow (if user-facing docs exist)

---

## Questions to Resolve During Implementation

1. **Normalization Strategy**: Should we normalize on extract or on query? (Answer: Both - normalized stored in cache, re-normalize on query for flexibility)

2. **Case Sensitivity**: Should matching be case-insensitive? (Answer: Yes, normalize to lowercase)

3. **Punctuation**: How to handle punctuation differences? (Answer: Normalize in Phase 1, handle properly in Phase 3)

4. **Multiple Item Types**: Should we include conference proceedings, books? (Answer: Phase 1 - journals only, expand later if needed)

5. **Cache Refresh Frequency**: 24 hours like authors? (Answer: Yes, proven to work well)

---

## Conclusion

This implementation plan provides a clear, phased approach to building JournalValidator following the proven AuthorValidator pattern. Starting simple (Phase 1) allows quick delivery of core value (OCR correction, consistency), then adding sophistication (normalization) based on actual usage patterns.

The plan balances:
- **Speed to value**: Phase 1 delivers core functionality quickly
- **Incremental complexity**: Each phase builds on the previous
- **Risk management**: Start simple, add complexity only if needed
- **Maintainability**: Reuse proven patterns, keep code similar to AuthorValidator

**Next Steps:** Begin Phase 1 implementation, test with real data early, iterate based on findings.

