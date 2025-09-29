#!/usr/bin/env python3
"""
Simplified parameterized test for any national library
Usage: python test_library_by_params.py <country_code> <isbn> [language_code]
Example: python test_library_by_params.py NO 978-82-02-48434-7 no
"""

import sys
from pathlib import Path

# Add shared_tools to path
shared_tools_path = Path(__file__).parent.parent / "shared_tools"
sys.path.insert(0, str(shared_tools_path))

from api.config_driven_manager import ConfigDrivenNationalLibraryManager
from utils.isbn_matcher import ISBNMatcher

def test_library(country_code, isbn, language_code=None):
    """Test any national library with given parameters."""
    
    print(f"🔍 Testing {country_code} National Library")
    print("=" * 50)
    print(f"📚 ISBN: {isbn}")
    print(f"🌍 Country: {country_code}")
    if language_code:
        print(f"🗣️ Language: {language_code}")
    print()
    
    try:
        # Initialize manager
        manager = ConfigDrivenNationalLibraryManager()
        
        # Get client by country code
        client = manager.get_client_by_country_code(country_code)
        if not client:
            print(f"❌ No client found for country code: {country_code}")
            return False
        
        print(f"✅ Client: {client.library_config['name']}")
        print(f"   URL: {client.library_config['api']['base_url']}")
        
        # Test book search by ISBN
        print(f"\n📖 Testing book search...")
        book_results = client.search_books(query=isbn)
        print(f"   Results: {book_results.get('total', 0)}")
        
        if book_results.get('books'):
            book = book_results['books'][0]
            print(f"   ✅ Found: {book.get('title', 'No title')}")
            print(f"   Authors: {book.get('authors', 'No authors')}")
            print(f"   Publisher: {book.get('publisher', 'No publisher')}")
            print(f"   Year: {book.get('year', 'No year')}")
            print(f"   ISBN: {book.get('isbn', 'No ISBN')}")
        else:
            print(f"   ⚠️ No books found")
        
        # Test general search if language provided
        if language_code:
            print(f"\n🔍 Testing general search for '{language_code}'...")
            general_results = client.search(query=language_code)
            print(f"   Total results: {general_results.get('total', 0)}")
            print(f"   Books: {len(general_results.get('books', []))}")
            print(f"   Papers: {len(general_results.get('papers', []))}")
        
        # Test ISBN prefix detection
        print(f"\n🏷️ Testing ISBN prefix detection...")
        
        # Validate ISBN first
        is_valid, error_msg = ISBNMatcher.validate_isbn(isbn)
        if not is_valid:
            print(f"   ❌ Invalid ISBN: {error_msg}")
            return True
        
        # Extract prefixes from ISBN using robust utility
        prefix_2, prefix_3 = ISBNMatcher.extract_isbn_prefix(isbn)
        if prefix_2 and prefix_3:
            print(f"   ✅ {error_msg}")
            print(f"   Extracted prefixes: {prefix_2} (2-digit), {prefix_3} (3-digit)")
        else:
            print(f"   ⚠️ Cannot extract prefix from ISBN: {isbn}")
            return True
        
        # Try both prefix lengths
        prefix_client = manager.get_client_by_isbn_prefix(prefix_2)
        if not prefix_client:
            prefix_client = manager.get_client_by_isbn_prefix(prefix_3)
        
        if prefix_client:
            print(f"   ✅ Prefix detected: {prefix_client.library_config['name']}")
        else:
            print(f"   ⚠️ No prefix match found for {prefix_2} or {prefix_3}")
        
        print(f"\n✅ Test completed successfully!")
        return True
        
    except Exception as e:
        print(f"❌ Test failed: {e}")
        return False

def main():
    """Main function with command line argument parsing."""
    
    if len(sys.argv) < 3:
        print("Usage: python test_library_by_params.py <country_code> <isbn> [language_code]")
        print("\nAvailable country codes:")
        print("  NO - Norwegian National Library")
        print("  SE - Swedish National Library (Libris)")
        print("  FI - Finnish National Library")
        print("  DK - Danish National Library")
        print("  DE - German National Library")
        print("  FR - French National Library")
        print("\nExamples:")
        print("  python test_library_by_params.py NO 978-82-02-48434-7 no")
        print("  python test_library_by_params.py SE 978-91-44-07769-7 sv")
        print("  python test_library_by_params.py FI 978-951-1-12345-6 fi")
        sys.exit(1)
    
    country_code = sys.argv[1].upper()
    isbn = sys.argv[2]
    language_code = sys.argv[3] if len(sys.argv) > 3 else None
    
    success = test_library(country_code, isbn, language_code)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
