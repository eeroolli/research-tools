# Data Structure Cleanup Plan

## Current Problem
The project has scattered data directories and log files across multiple locations, creating confusion and maintenance issues.

## Current Data Structure Issues

### **Scattered Data Directories:**
```
./data/                          # ✅ Main data directory (correct)
├── books/                       # ✅ For book processing results
├── papers/                      # ✅ For paper processing results  
├── logs/                        # ✅ For application logs
├── cache/                       # ✅ For temporary cache
├── output/                      # ✅ For processed outputs
└── temp/                        # ✅ For temporary files

./process_books/data/            # ❌ Duplicate - should be removed
└── logs/                        # ❌ Duplicate logs

./process_papers/data/           # ❌ Empty - should be removed

./scripts/data/                  # ❌ Duplicate - should be removed
└── logs/                        # ❌ Duplicate logs

./shared_tools/metadata/         # ✅ Code directory - keep as is
└── extractor.py                 # ✅ Code file - keep as is
```

### **Scattered Log Files:**
```
./data/logs/processing_20251003_122311.log     # ✅ Main logs
./data/logs/processing_20251003_132703.log     # ✅ Main logs

./process_books/data/logs/processing_20251003_122311.log  # ❌ Duplicate
./scripts/data/logs/processing_20251003_124507.log        # ❌ Duplicate
./scripts/data/logs/processing_20251003_125842.log        # ❌ Duplicate
./scripts/data/logs/processing_20251003_134853.log        # ❌ Duplicate
./scripts/data/logs/processing_20251003_140328.log        # ❌ Duplicate
./scripts/data/logs/processing_20251003_141215.log        # ❌ Duplicate
./scripts/data/logs/processing_20251003_143120.log        # ❌ Duplicate
```

## Cleanup Plan

### **Phase 1: Consolidate Logs** 🧹
1. **Move all logs to main data/logs directory**
   - Copy unique logs from scattered locations
   - Remove duplicate log files
   - Update logging configuration to use only `data/logs/`

2. **Update logging configuration**
   - Ensure all scripts write to `data/logs/`
   - Remove hardcoded paths to old log locations
   - Standardize log file naming

### **Phase 2: Remove Duplicate Data Directories** 🗑️
1. **Remove `process_books/data/`**
   - Move any unique files to main `data/` directory
   - Remove empty directory

2. **Remove `process_papers/data/`**
   - Directory is empty, safe to remove

3. **Remove `scripts/data/`**
   - Move any unique files to main `data/` directory
   - Remove empty directory

### **Phase 3: Update Code References** 🔧
1. **Update all hardcoded paths**
   - Search for references to old data directories
   - Update to use centralized `data/` directory
   - Ensure all scripts use relative paths from project root

2. **Update configuration files**
   - Update any config files that reference old paths
   - Ensure consistent path structure

### **Phase 4: Verify and Test** ✅
1. **Test all scripts**
   - Ensure they can find data files in new locations
   - Verify logging works correctly
   - Check that no functionality is broken

2. **Document new structure**
   - Update README with clear data structure
   - Document where different types of files are stored

## Target Data Structure

### **Final Clean Structure:**
```
research-tools/
├── data/                        # 🎯 Single data directory
│   ├── books/                   # Book processing results
│   │   └── book_processing_log.csv
│   ├── papers/                  # Paper processing results
│   │   └── paper_processing_log.csv
│   ├── logs/                    # All application logs
│   │   ├── processing_YYYYMMDD_HHMMSS.log
│   │   └── error_YYYYMMDD_HHMMSS.log
│   ├── cache/                   # Temporary cache files
│   ├── output/                  # Processed outputs
│   └── temp/                    # Temporary files
├── scripts/                     # All executable scripts
├── process_books/               # Book processing code (no data/)
├── process_papers/              # Paper processing code (no data/)
└── shared_tools/                # Shared utilities
    └── metadata/                # Code only
```

## Implementation Steps

### **Step 1: Backup Current State**
```bash
# Create backup before cleanup
cp -r data data_backup_$(date +%Y%m%d_%H%M%S)
```

### **Step 2: Consolidate Logs**
```bash
# Move all logs to main data/logs directory
find . -name "*.log" -not -path "./data/logs/*" -exec cp {} data/logs/ \;
find . -name "*.log" -not -path "./data/logs/*" -delete
```

### **Step 3: Remove Duplicate Directories**
```bash
# Remove empty duplicate data directories
rm -rf process_books/data
rm -rf process_papers/data  
rm -rf scripts/data
```

### **Step 4: Update Code References**
- Search for hardcoded paths to old data directories
- Update all references to use centralized `data/` directory
- Update logging configuration

### **Step 5: Test and Verify**
- Run all scripts to ensure they work
- Verify logs are written to correct location
- Check that data files are found correctly

## Benefits of Clean Structure

1. **Single Source of Truth**: All data in one place
2. **Easier Maintenance**: No confusion about where files are
3. **Better Organization**: Clear separation of concerns
4. **Simpler Backups**: Only need to backup `data/` directory
5. **Cleaner Code**: No hardcoded paths to multiple locations
6. **Better Documentation**: Clear structure is easier to document

## Files to Update

### **Code Files with Hardcoded Paths:**
- `scripts/find_isbn_from_photos.py` - Update log path
- `process_books/src/utils/file_manager.py` - Update log path
- Any other scripts that reference old data directories

### **Configuration Files:**
- `process_books/config/process_books.conf` - Update paths
- Any other config files with data directory references

## Risk Mitigation

1. **Backup First**: Always backup before making changes
2. **Test Incrementally**: Test after each step
3. **Update Code First**: Update code references before removing directories
4. **Verify Functionality**: Ensure all scripts still work after cleanup

---

**Priority**: High - This cleanup will significantly improve project maintainability and reduce confusion.
