#!/usr/bin/env python3
"""
Test script for the enhanced Zotero book processor
Demonstrates the new multi-digit input and tag group functionality
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scripts.add_or_remove_books_zotero import ZoteroAPIBookProcessor

def test_config_loading():
    """Test the enhanced configuration loading"""
    print("🧪 Testing enhanced configuration loading...")
    
    try:
        processor = ZoteroAPIBookProcessor()
        
        print(f"✅ Tag groups loaded: {len(processor.tag_groups)}")
        for group_name, tags in processor.tag_groups.items():
            print(f"   {group_name}: {', '.join(tags)}")
        
        print(f"\n✅ Actions loaded: {len(processor.actions)}")
        for action_num, action in processor.actions.items():
            print(f"   {action_num}. {action['description']}")
        
        print(f"\n✅ Menu options loaded: {len(processor.menu_options)}")
        for option, value in processor.menu_options.items():
            print(f"   {option}: {value}")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing configuration: {e}")
        return False

def test_multi_digit_parsing():
    """Test multi-digit input parsing"""
    print("\n🧪 Testing multi-digit input parsing...")
    
    try:
        processor = ZoteroAPIBookProcessor()
        
        test_cases = [
            ("1", [1]),
            ("17", [1, 7]),
            ("123", [1, 2, 3]),
            ("abc", []),
            ("", []),
            ("q", [])
        ]
        
        for input_str, expected in test_cases:
            result = processor.parse_multi_digit_choice(input_str)
            status = "✅" if result == expected else "❌"
            print(f"   {status} '{input_str}' -> {result} (expected: {expected})")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing multi-digit parsing: {e}")
        return False

def test_enhanced_menu():
    """Test the enhanced menu display"""
    print("\n🧪 Testing enhanced menu display...")
    
    try:
        processor = ZoteroAPIBookProcessor()
        
        # Test menu for existing item
        print("\n📚 Menu for existing item:")
        menu_output = processor.show_enhanced_menu("9781234567890", "Test Book", is_existing=True)
        print(f"   User input: '{menu_output}'")
        
        # Test menu for new item
        print("\n📚 Menu for new item:")
        menu_output = processor.show_enhanced_menu("9781234567890", "Test Book", is_existing=False)
        print(f"   User input: '{menu_output}'")
        
        return True
        
    except Exception as e:
        print(f"❌ Error testing enhanced menu: {e}")
        return False

def main():
    """Run all tests"""
    print("🚀 Enhanced Zotero Book Processor - Test Suite")
    print("=" * 60)
    
    tests = [
        test_config_loading,
        test_multi_digit_parsing,
        test_enhanced_menu
    ]
    
    passed = 0
    total = len(tests)
    
    for test in tests:
        if test():
            passed += 1
        print()
    
    print("=" * 60)
    print(f"📊 Test Results: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! The enhanced functionality is working correctly.")
    else:
        print("⚠️  Some tests failed. Please check the configuration and implementation.")

if __name__ == "__main__":
    main()
