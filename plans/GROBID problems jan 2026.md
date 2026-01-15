
This information is clearly visible and should be extractable by GROBID.

## Possible Root Causes

### 1. GROBID Parsing Logic Issue

**Location**: `shared_tools/api/grobid_client.py` - `_parse_grobid_xml()` method (lines 250-385)

**Possible Issues**:
- XPath queries may not match the actual GROBID XML structure
- Author filtering logic (lines 282-328) may be too aggressive, filtering out valid authors
- Title extraction logic (lines 262-280) may miss multi-line titles
- Namespace handling for TEI XML may be incorrect

**Investigation**: Inspect the saved TEI XML file to see if GROBID actually extracted the metadata but our parsing missed it.

### 2. GROBID Server Configuration

**Possible Issues**:
- GROBID server version mismatch
- Consolidation settings interfering with extraction
- GROBID model quality issues

**Configuration Locations**:
- Consolidation settings: `shared_tools/api/grobid_client.py` lines 132-138
- GROBID server URL: Config file `[GROBID]` section

### 3. PDF Preprocessing Issue

**Possible Issues**:
- PDF structure not recognized by GROBID
- Font encoding issues
- PDF metadata interfering with GROBID processing

**Note**: Fix 4 (rotation retry logic) has been fixed, so rotation handling is no longer a likely cause.

### 4. GROBID XML Structure Change

**Possible Issue**: GROBID server may have changed its XML output format, making our parsing logic obsolete.

## Investigation Steps

### Step 1: Inspect Saved TEI XML File

**File Location**: `data/temp/grobid_tei/EN_20260109-131419_003_double.tei.xml`

**What to Check**:
1. Does the XML file exist and contain data?
2. Are there `<author>` elements in the XML?
3. What namespace is used? (Should be `{http://www.tei-c.org/ns/1.0}`)
4. Is the title present in the XML?
5. Is the year/date present in the XML?
6. Are authors in unwanted contexts (footnotes, citations) that our filtering excludes?

**Tools**: 
- Use a text editor or XML viewer to inspect the file
- Compare with a known-good GROBID XML output
- Use `tests/show_grobid_xml.py` if available

### Step 2: Test with Known-Good PDF

**Action**: Test GROBID with a PDF that previously worked correctly.

**Purpose**: Determine if this is a PDF-specific issue or a general GROBID problem.

### Step 3: Check GROBID Consolidation Settings

**Location**: `shared_tools/api/grobid_client.py` lines 132-138

**Action**: Temporarily disable consolidation to see if it's interfering:
- Set `enable_consolidation=False` in the call to `extract_metadata()`
- Or test with different consolidation header/citations levels

### Step 4: Verify GROBID Server Version

**Action**: Check GROBID server version and compare with expected version.

**Command**: Check GROBID server logs or API endpoint for version information.

### Step 5: Test Parsing Logic with Saved XML

**Action**: 
1. Load the saved TEI XML file
2. Run `_parse_grobid_xml()` on it
3. Check what metadata is extracted
4. Compare with what's actually in the XML

**Code Location**: `shared_tools/api/grobid_client.py` - `_parse_grobid_xml()` method

### Step 6: Check Author Filtering Logic

**Location**: `shared_tools/api/grobid_client.py` lines 282-328

**What to Check**:
- Are authors being filtered out incorrectly?
- Are authors in `<sourceDesc>` being excluded?
- Is the filtering logic excluding main document authors?

## Code Locations

### GROBID Client
- **File**: `shared_tools/api/grobid_client.py`
- **Main extraction method**: `extract_metadata()` (line 75)
- **Parsing method**: `_parse_grobid_xml()` (line 250)
- **Author filtering**: Lines 282-328
- **Title extraction**: Lines 262-280
- **Year extraction**: Lines 372-377

### Daemon Integration
- **File**: `scripts/paper_processor_daemon.py`
- **GROBID call**: Line 3872
- **Result handling**: Lines 3874-4023

## Next Steps (Priority Order)

1. **Inspect TEI XML file** (Highest Priority)
   - Check if GROBID actually extracted the metadata
   - Compare XML structure with parsing logic
   - This will determine if it's a parsing issue or GROBID server issue

2. **Test parsing logic**
   - Use saved XML file to test `_parse_grobid_xml()` method
   - Add debug logging to see what's being extracted vs. filtered

3. **Test with consolidation disabled**
   - See if consolidation settings are interfering
   - Try different consolidation levels

4. **Check GROBID server**
   - Verify server version
   - Check server logs for errors
   - Test with a known-good PDF

5. **Review author filtering logic**
   - Verify filtering isn't too aggressive
   - Check if main document authors are being excluded

## Related Issues

- **Fix 4**: Rotation retry logic has been fixed (no longer a potential cause)
- **Previous GROBID issues**: See `docs/BUG_ANALYSIS_REPORT.md` for related GROBID author filtering issues
- **GROBID setup**: See `GROBID_SETUP.md` for configuration documentation

## Status

**Status**: Deferred - Requires investigation

**Reason**: Needs inspection of TEI XML files to determine root cause before implementing fix.

**Date**: 2025-01-09

**Related Commits**: 
- `6046e95` - fix: resolve communication issues after modularization (Fix 1, 2, 4)