# Research-Tools Migration Plan

**Date:** September 2025  
**Purpose:** Migrate existing hardcoded national library system to configuration-driven approach  
**Status:** Ready for implementation

## 🎯 **Migration Overview**

### **Goal**
Replace the hardcoded national library client system with the new configuration-driven approach while maintaining all existing functionality.

### **Current State**
- ✅ Configuration-driven system implemented and tested
- ✅ Norwegian National Library API working (1M+ results)
- ✅ All 6 library configurations defined in YAML
- ❌ Existing code still uses hardcoded clients
- ❌ Old and new systems running in parallel

### **Target State**
- ✅ All components use configuration-driven system
- ✅ Single YAML configuration for all libraries
- ✅ No hardcoded API endpoints in code
- ✅ Easy to add new libraries without code changes

## 📋 **Migration Tasks**

### **Phase 1: Shared Components Migration**

#### **Task 1.1: Update Shared Metadata Extractor**
- **File:** `shared_tools/metadata/extractor.py`
- **Current:** Uses old `NationalLibraryManager`
- **Target:** Use `ConfigDrivenNationalLibraryManager`
- **Changes:**
  - Replace import statement
  - Update client initialization
  - Test integration works

#### **Task 1.2: Update Shared Config Manager**
- **File:** `shared_tools/config/manager.py`
- **Current:** Hardcoded national library API URLs
- **Target:** Remove hardcoded URLs, rely on YAML config
- **Changes:**
  - Remove hardcoded API URLs from default config
  - Add comments directing to YAML config
  - Test config loading still works

#### **Task 1.3: Test Shared Components**
- **Files:** `test_integration.py`, `test_config_driven_national_libraries.py`
- **Goal:** Ensure shared components work with new system
- **Tests:**
  - Metadata extractor can load config-driven manager
  - Country/language detection works
  - ISBN prefix mapping works

### **Phase 2: Book Processing Migration**

#### **Task 2.1: Update Book Processing Scripts**
- **Files:**
  - `process_books/scripts/enhanced_isbn_lookup_detailed.py`
  - `process_books/scripts/zotero_api_book_processor_enhanced.py`
  - `process_books/src/integrations/legacy_zotero_processor.py`
- **Current:** Use hardcoded `DetailedISBNLookupService`
- **Target:** Use config-driven national library manager
- **Changes:**
  - Replace hardcoded service with config-driven manager
  - Update method calls to use new interface
  - Maintain backward compatibility for existing workflows

#### **Task 2.2: Update Book Processing Configuration**
- **Files:**
  - `process_books/config/process_books.conf`
  - `process_books/config/scanpapers.conf`
- **Changes:**
  - Remove hardcoded national library URLs
  - Add references to YAML configuration
  - Update documentation comments

#### **Task 2.3: Test Book Processing**
- **Goal:** Ensure book processing still works with Norwegian library
- **Tests:**
  - ISBN prefix detection works
  - Norwegian library search returns results
  - Metadata extraction works
  - Zotero integration works

### **Phase 3: Paper Processing Migration**

#### **Task 3.1: Update Paper Processing Metadata Extractor**
- **File:** `process_papers/src/core/metadata_extractor.py`
- **Current:** Uses old shared metadata extractor
- **Target:** Use updated config-driven shared extractor
- **Changes:**
  - Update import paths
  - Test language-based library selection
  - Ensure national library enhancement works

#### **Task 3.2: Update Paper Processing Configuration**
- **File:** `process_papers/config/process_papers.conf`
- **Changes:**
  - Add national library configuration references
  - Update language detection settings
  - Add API key configuration options

#### **Task 3.3: Test Paper Processing**
- **Goal:** Ensure paper processing can use national libraries
- **Tests:**
  - Language detection works
  - Norwegian paper search works
  - Metadata enhancement works
  - Integration with shared components works

### **Phase 4: Cleanup and Documentation**

#### **Task 4.1: Remove Old Hardcoded Clients**
- **Files to Remove:**
  - `shared_tools/api/national_libraries.py` (old hardcoded clients)
- **Files to Update:**
  - All import statements throughout codebase
  - Documentation references
- **Changes:**
  - Remove old client files
  - Update all imports to use new system
  - Clean up unused code

#### **Task 4.2: Update Documentation**
- **Files to Update:**
  - `README.md`
  - `process_books/README.md`
  - `process_papers/README.md`
  - `NATIONAL_LIBRARY_INTEGRATION.md`
- **Changes:**
  - Update to reflect new configuration-driven approach
  - Add YAML configuration documentation
  - Update usage examples
  - Add migration notes

#### **Task 4.3: Final Integration Testing**
- **Goal:** Ensure entire system works end-to-end
- **Tests:**
  - Book processing with Norwegian library
  - Paper processing with language detection
  - Shared components integration
  - Configuration management
  - Error handling and fallbacks

## 🔧 **Implementation Strategy**

### **Approach: Incremental Migration**
1. **Test each phase** before proceeding to next
2. **Maintain backward compatibility** during migration
3. **Keep old system** until new system fully tested
4. **Document changes** at each step

### **Risk Mitigation**
- **Backup current working system** before changes
- **Test with known working data** (Norwegian library)
- **Rollback plan** if issues arise
- **Incremental testing** after each change

### **Success Criteria**
- ✅ All existing functionality preserved
- ✅ Norwegian library integration working
- ✅ Configuration-driven system fully implemented
- ✅ No hardcoded API endpoints remaining
- ✅ Easy to add new libraries via YAML

## 📊 **Migration Checklist**

### **Phase 1: Shared Components**
- [ ] Update shared metadata extractor
- [ ] Update shared config manager
- [ ] Test shared components integration
- [ ] Verify Norwegian library works

### **Phase 2: Book Processing**
- [ ] Update enhanced ISBN lookup script
- [ ] Update Zotero processor script
- [ ] Update legacy Zotero processor
- [ ] Update book processing configs
- [ ] Test book processing end-to-end

### **Phase 3: Paper Processing**
- [ ] Update paper metadata extractor
- [ ] Update paper processing config
- [ ] Test paper processing with language detection
- [ ] Test national library integration

### **Phase 4: Cleanup**
- [ ] Remove old hardcoded clients
- [ ] Update all import statements
- [ ] Update documentation
- [ ] Final integration testing
- [ ] Performance validation

## 🚨 **Potential Issues and Solutions**

### **Issue 1: API Response Format Differences**
- **Problem:** Different libraries may have different response formats
- **Solution:** Use flexible field mapping in YAML configuration
- **Mitigation:** Test each library configuration thoroughly

### **Issue 2: Breaking Changes in Method Signatures**
- **Problem:** New system may have different method signatures
- **Solution:** Maintain backward compatibility during migration
- **Mitigation:** Create adapter methods if needed

### **Issue 3: Configuration Loading Issues**
- **Problem:** YAML configuration may not load correctly
- **Solution:** Add configuration validation and error handling
- **Mitigation:** Test configuration loading in different environments

### **Issue 4: Performance Impact**
- **Problem:** New system may be slower than hardcoded approach
- **Solution:** Profile and optimize as needed
- **Mitigation:** Benchmark before and after migration

## 📈 **Expected Benefits After Migration**

### **Maintainability**
- Single YAML file for all library configurations
- No code changes needed to add new libraries
- Consistent interface across all libraries

### **Flexibility**
- Easy to modify API endpoints without code changes
- Flexible field mapping for different API structures
- Support for various response formats

### **Scalability**
- Easy to add new countries/languages
- Support for different API authentication methods
- Extensible configuration system

### **Reliability**
- Centralized error handling
- Consistent fallback mechanisms
- Better testing capabilities

## 🎯 **Next Steps for Implementation**

1. **Review this plan** and approve approach
2. **Start with Phase 1** (shared components)
3. **Test thoroughly** after each phase
4. **Document changes** as we go
5. **Complete migration** incrementally
6. **Validate entire system** works end-to-end

## 📝 **Notes for Implementation**

- **Always test** after each change
- **Keep backups** of working versions
- **Document issues** and solutions
- **Ask for approval** before major changes
- **Focus on Norwegian library** as known working example
- **Maintain existing functionality** throughout migration

---

**Ready for implementation when approved!** 🚀
