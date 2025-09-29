#!/usr/bin/env python3
"""
Integration test for research-tools modules.
Tests that all components can be imported and basic functionality works.
"""

import sys
import os
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_shared_tools():
    """Test shared-tools components."""
    print("Testing shared-tools components...")
    
    try:
        from shared_tools.utils.isbn_matcher import ISBNMatcher
        print("✓ ISBNMatcher imported successfully")
        
        # Test ISBN matching
        matcher = ISBNMatcher()
        result = matcher.match_isbn("9781234567890", "1234567890")
        print(f"✓ ISBN matching test: {result}")
        
    except Exception as e:
        print(f"✗ ISBNMatcher test failed: {e}")
        return False
    
    try:
        from shared_tools.config.manager import ConfigManager
        config = ConfigManager()
        print("✓ ConfigManager imported and initialized")
        
        # Test config access
        scan_folder = config.get_path('scan_folder')
        print(f"✓ Config access test: scan_folder = {scan_folder}")
        
    except Exception as e:
        print(f"✗ ConfigManager test failed: {e}")
        return False
    
    try:
        from shared_tools.metadata.extractor import MetadataExtractor
        extractor = MetadataExtractor({})
        print("✓ MetadataExtractor imported successfully")
        
    except Exception as e:
        print(f"✗ MetadataExtractor test failed: {e}")
        return False
    
    return True

def test_process_books():
    """Test process_books components."""
    print("\\nTesting process_books components...")
    
    try:
        from process_books.src.processors.smart_integrated_processor_v3 import SmartIntegratedProcessorV3
        print("✓ SmartIntegratedProcessorV3 imported successfully")
        
    except Exception as e:
        print(f"✗ SmartIntegratedProcessorV3 test failed: {e}")
        return False
    
    try:
        from process_books.src.extractors.isbn_extractor import ISBNExtractor
        extractor = ISBNExtractor()
        print("✓ ISBNExtractor imported successfully")
        
    except Exception as e:
        print(f"✗ ISBNExtractor test failed: {e}")
        return False
    
    return True

def test_process_papers():
    """Test process_papers components."""
    print("\\nTesting process_papers components...")
    
    try:
        from process_papers.src.models.paper import Paper, PaperMetadata, ProcessingStatus
        print("✓ Paper models imported successfully")
        
        # Test paper creation
        paper = Paper(id="test_001", file_path="/test/path.pdf")
        print(f"✓ Paper creation test: {paper.id}")
        
    except Exception as e:
        print(f"✗ Paper models test failed: {e}")
        return False
    
    try:
        from process_papers.src.core.metadata_extractor import MetadataExtractor
        extractor = MetadataExtractor()
        print("✓ MetadataExtractor imported successfully")
        
    except Exception as e:
        print(f"✗ MetadataExtractor test failed: {e}")
        return False
    
    try:
        from process_papers.src.core.ocr_engine import OCREngine
        engine = OCREngine({})
        print("✓ OCREngine imported successfully")
        
    except Exception as e:
        print(f"✗ OCREngine test failed: {e}")
        return False
    
    return True

def test_directory_structure():
    """Test that directory structure is correct."""
    print("\\nTesting directory structure...")
    
    required_dirs = [
        'shared_tools',
        'process_books',
        'process_papers',
        'config.conf',
        'environment.yml'
    ]
    
    for dir_name in required_dirs:
        path = Path(dir_name)
        if path.exists():
            print(f"✓ {dir_name} exists")
        else:
            print(f"✗ {dir_name} missing")
            return False
    
    return True

def main():
    """Run all integration tests."""
    print("Research-Tools Integration Test")
    print("=" * 40)
    
    tests = [
        test_directory_structure,
        test_shared_tools,
        test_process_books,
        test_process_papers
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        else:
            print("\\n❌ Test failed!")
            break
    
    print("\\n" + "=" * 40)
    print(f"Integration Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Research-tools is ready to use.")
        return True
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
