# Data Folder Structure Explanation

## Current Data Directory Structure

```
data/
├── books/          # 📚 Book processing results and logs
├── papers/         # 📄 Paper processing results and logs  
├── logs/           # 📝 Application logs (all scripts)
├── cache/          # 💾 Temporary cache files
├── output/         # 📤 Final processed outputs
└── temp/           # 🗑️ Temporary files (can be deleted)
```

## Detailed Explanation of Each Folder

### 📚 `data/books/` - Book Processing Results
**Purpose**: Stores all data related to book ISBN extraction and processing

**Current Contents**: Empty (but should contain)
**Should Contain**:
- `book_processing_log.csv` - Main processing log with ISBN results
- `pending/` - Photos waiting to be processed
- `done/` - Successfully processed photos (moved here after ISBN found)
- `failed/` - Photos that failed processing (retryable)
- `permanently_failed/` - Photos that failed after max retries
- `metadata/` - Book metadata from ISBN lookups
- `backups/` - Backup copies of processing logs

**Example Files**:
```
data/books/
├── book_processing_log.csv
├── pending/
│   └── IMG_20250725_202203.jpg
├── done/
│   └── IMG_20250725_231424.jpg
├── failed/
│   └── IMG_20250725_205655.jpg
└── metadata/
    └── book_metadata_9788292622216.json
```

### 📄 `data/papers/` - Paper Processing Results
**Purpose**: Stores all data related to academic paper processing

**Current Contents**: Empty
**Should Contain**:
- `paper_processing_log.csv` - Main processing log with paper results
- `pending/` - PDFs waiting to be processed
- `done/` - Successfully processed papers
- `failed/` - Papers that failed processing
- `metadata/` - Paper metadata from API lookups
- `extracted_text/` - OCR text from papers
- `citations/` - Extracted citations

**Example Files**:
```
data/papers/
├── paper_processing_log.csv
├── pending/
│   └── scan_timestamp.pdf
├── done/
│   └── processed_paper_20241003.pdf
└── metadata/
    └── paper_metadata_doi_10.1234_abc.json
```

### 📝 `data/logs/` - Application Logs
**Purpose**: Stores all application logs from different scripts

**Current Contents**: 
- `processing_20251003_122311.log`
- `processing_20251003_132703.log`

**Should Contain**:
- `processing_YYYYMMDD_HHMMSS.log` - General processing logs
- `error_YYYYMMDD_HHMMSS.log` - Error logs
- `debug_YYYYMMDD_HHMMSS.log` - Debug logs
- `zotero_api_YYYYMMDD_HHMMSS.log` - Zotero API logs
- `isbn_lookup_YYYYMMDD_HHMMSS.log` - ISBN lookup logs

**Example Files**:
```
data/logs/
├── processing_20251003_122311.log
├── processing_20251003_132703.log
├── error_20251003_143000.log
└── zotero_api_20251003_150000.log
```

### 💾 `data/cache/` - Temporary Cache Files
**Purpose**: Stores temporary cache files for performance optimization

**Current Contents**: Empty
**Should Contain**:
- `isbn_lookups/` - Cached ISBN lookup results
- `api_responses/` - Cached API responses
- `image_thumbnails/` - Cached image thumbnails
- `ocr_results/` - Cached OCR results

**Example Files**:
```
data/cache/
├── isbn_lookups/
│   └── 9788292622216.json
├── api_responses/
│   └── openalex_work_12345.json
└── image_thumbnails/
    └── IMG_20250725_202203_thumb.jpg
```

### 📤 `data/output/` - Final Processed Outputs
**Purpose**: Stores final processed outputs ready for use

**Current Contents**: Empty
**Should Contain**:
- `zotero_imports/` - Files ready for Zotero import
- `bibliographies/` - Generated bibliographies
- `reports/` - Processing reports
- `exports/` - Data exports

**Example Files**:
```
data/output/
├── zotero_imports/
│   └── books_to_import_20251003.csv
├── bibliographies/
│   └── bibliography_20251003.bib
└── reports/
    └── processing_summary_20251003.pdf
```

### 🗑️ `data/temp/` - Temporary Files
**Purpose**: Stores temporary files that can be safely deleted

**Current Contents**: Empty
**Should Contain**:
- Temporary image processing files
- Temporary OCR files
- Temporary download files
- Any files that can be safely deleted

**Example Files**:
```
data/temp/
├── temp_image_12345.jpg
├── temp_ocr_67890.txt
└── temp_download_11111.pdf
```

## Key Differences Between Folders

| Folder | Purpose | Persistence | Auto-Cleanup | Examples |
|--------|---------|-------------|--------------|----------|
| `books/` | Book processing results | Permanent | No | ISBN logs, processed photos |
| `papers/` | Paper processing results | Permanent | No | Paper logs, extracted text |
| `logs/` | Application logs | Permanent | Manual | Processing logs, error logs |
| `cache/` | Performance optimization | Temporary | Yes | API responses, thumbnails |
| `output/` | Final deliverables | Permanent | No | Zotero imports, reports |
| `temp/` | Temporary files | Temporary | Yes | Temp images, downloads |

## File Naming Conventions

### Log Files
- `processing_YYYYMMDD_HHMMSS.log` - General processing
- `error_YYYYMMDD_HHMMSS.log` - Error logs
- `debug_YYYYMMDD_HHMMSS.log` - Debug logs
- `{script_name}_YYYYMMDD_HHMMSS.log` - Script-specific logs

### Data Files
- `{type}_processing_log.csv` - Processing logs (books, papers)
- `{type}_metadata_{id}.json` - Metadata files
- `{type}_backup_YYYYMMDD.csv` - Backup files

### Cache Files
- `{service}_{id}.json` - API responses
- `{type}_{id}_thumb.jpg` - Thumbnails
- `{type}_{id}_cache.dat` - Binary cache

## Current Issues

1. **Empty Folders**: Most folders are empty, indicating incomplete setup
2. **Scattered Logs**: Logs are in multiple locations instead of centralized
3. **Missing Structure**: No subfolders for organization within main folders
4. **No Cleanup**: No automatic cleanup of temp/cache files

## Recommended Next Steps

1. **Consolidate Logs**: Move all logs to `data/logs/`
2. **Create Subfolders**: Add proper subfolder structure
3. **Update Scripts**: Ensure all scripts write to correct locations
4. **Add Cleanup**: Implement automatic cleanup for temp/cache folders
5. **Documentation**: Update scripts to document where they write files
