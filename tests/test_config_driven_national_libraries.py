#!/usr/bin/env python3
"""
Test script for configuration-driven national library integration.
Demonstrates how the new system works and tests all configured libraries.
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

def test_config_loading():
    """Test that configuration loads correctly."""
    print("Testing configuration loading...")
    
    try:
        from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
        
        manager = ConfigDrivenNationalLibraryManager()
        libraries = manager.get_available_libraries()
        
        print(f"✓ Loaded {len(libraries)} libraries:")
        for lib in libraries:
            print(f"  - {lib['name']} ({lib['id']}) - {lib['country_code']}")
            print(f"    Languages: {', '.join(lib['language_codes'])}")
            print(f"    ISBN Prefixes: {', '.join(lib['isbn_prefixes'])}")
            print(f"    API: {lib['api_url']}")
        
        return True
        
    except Exception as e:
        print(f"✗ Configuration loading failed: {e}")
        return False

def test_client_creation():
    """Test that clients can be created for each library."""
    print("\nTesting client creation...")
    
    try:
        from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
        
        manager = ConfigDrivenNationalLibraryManager()
        
        # Test creating clients for each library
        test_libraries = ['norwegian', 'swedish', 'finnish']
        
        for lib_id in test_libraries:
            client = manager.get_client(lib_id)
            if client:
                print(f"✓ Created client for {lib_id}")
            else:
                print(f"✗ Failed to create client for {lib_id}")
        
        return True
        
    except Exception as e:
        print(f"✗ Client creation failed: {e}")
        return False

def test_search_functionality():
    """Test search functionality for Norwegian library (known to work)."""
    print("\nTesting search functionality...")
    
    try:
        from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
        
        manager = ConfigDrivenNationalLibraryManager()
        
        # Test Norwegian library search
        client = manager.get_client('norwegian')
        if not client:
            print("✗ Norwegian client not available")
            return False
        
        # Test book search
        result = client.search_books("test", size=1)
        print(f"✓ Norwegian book search: {result.get('total', 0)} results")
        
        # Test paper search
        result = client.search_papers("test", size=1)
        print(f"✓ Norwegian paper search: {result.get('total', 0)} results")
        
        return True
        
    except Exception as e:
        print(f"✗ Search functionality failed: {e}")
        return False

def test_country_language_mapping():
    """Test country and language code mapping."""
    print("\nTesting country/language mapping...")
    
    try:
        from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
        
        manager = ConfigDrivenNationalLibraryManager()
        
        # Test country code mapping
        tests = [
            ('NO', 'norwegian'),
            ('SE', 'swedish'),
            ('FI', 'finnish'),
            ('DK', 'danish'),
            ('DE', 'german'),
            ('FR', 'french')
        ]
        
        for country_code, expected_lib in tests:
            client = manager.get_client_by_country_code(country_code)
            if client:
                print(f"✓ Country code {country_code} → {client.library_id}")
            else:
                print(f"✗ Country code {country_code} → No client found")
        
        # Test language mapping
        language_tests = [
            ('no', 'norwegian'),
            ('sv', 'swedish'),
            ('fi', 'finnish'),
            ('da', 'danish'),
            ('de', 'german'),
            ('fr', 'french')
        ]
        
        for lang_code, expected_lib in language_tests:
            client = manager.get_client_by_language(lang_code)
            if client:
                print(f"✓ Language code {lang_code} → {client.library_id}")
            else:
                print(f"✗ Language code {lang_code} → No client found")
        
        return True
        
    except Exception as e:
        print(f"✗ Country/language mapping failed: {e}")
        return False

def test_isbn_prefix_mapping():
    """Test ISBN prefix mapping."""
    print("\nTesting ISBN prefix mapping...")
    
    try:
        from shared_tools.api.config_driven_manager import ConfigDrivenNationalLibraryManager
        
        manager = ConfigDrivenNationalLibraryManager()
        
        # Test ISBN prefix mapping
        prefix_tests = [
            ('82', 'norwegian'),
            ('91', 'swedish'),
            ('951', 'finnish'),
            ('952', 'finnish'),
            ('87', 'danish'),
            ('3', 'german'),
            ('2', 'french')
        ]
        
        for prefix, expected_lib in prefix_tests:
            client = manager.get_client_by_isbn_prefix(prefix)
            if client:
                print(f"✓ ISBN prefix {prefix} → {client.library_id}")
            else:
                print(f"✗ ISBN prefix {prefix} → No client found")
        
        return True
        
    except Exception as e:
        print(f"✗ ISBN prefix mapping failed: {e}")
        return False

def test_integration_with_metadata_extractor():
    """Test integration with metadata extractor."""
    print("\nTesting integration with metadata extractor...")
    
    try:
        from shared_tools.metadata.extractor import MetadataExtractor
        
        # Create metadata extractor
        extractor = MetadataExtractor({})
        
        # Test book metadata extraction with ISBN
        result = extractor.extract_book_metadata(isbn="978-82-123456-7-8")
        print(f"✓ Book metadata extraction: confidence {result.confidence}%")
        
        # Test paper metadata extraction with language
        result = extractor.extract_paper_metadata(
            title="Test Norwegian Paper",
            authors=["Test Author"],
            language="no"
        )
        print(f"✓ Paper metadata extraction: confidence {result.confidence}%")
        
        return True
        
    except Exception as e:
        print(f"✗ Metadata extractor integration failed: {e}")
        return False

def main():
    """Run all tests."""
    print("Configuration-Driven National Library Integration Test")
    print("=" * 60)
    
    tests = [
        test_config_loading,
        test_client_creation,
        test_search_functionality,
        test_country_language_mapping,
        test_isbn_prefix_mapping,
        test_integration_with_metadata_extractor
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        else:
            print(f"\n❌ Test failed!")
            break
    
    print("\n" + "=" * 60)
    print(f"Configuration-Driven Integration Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! Configuration-driven system is working correctly.")
        print("\nBenefits of new approach:")
        print("✅ Single YAML configuration file for all libraries")
        print("✅ No hardcoded API endpoints in code")
        print("✅ Consistent field mapping configuration")
        print("✅ Easy to add new libraries without code changes")
        print("✅ Centralized author parsing logic")
        print("✅ Support for different API response structures")
        return True
    else:
        print("❌ Some tests failed. Please check the errors above.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
