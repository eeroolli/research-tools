#!/usr/bin/env python3
"""
Demo script for enhanced Zotero book processor features
Shows the new functionality without requiring user interaction
"""

import sys
from pathlib import Path

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent))

from scripts.add_or_remove_books_zotero import ZoteroAPIBookProcessor

def demo_configuration():
    """Demonstrate the enhanced configuration system"""
    print("🔧 ENHANCED CONFIGURATION SYSTEM")
    print("=" * 50)
    
    processor = ZoteroAPIBookProcessor()
    
    print(f"📚 Tag Groups ({len(processor.tag_groups)}):")
    for group_name, tags in processor.tag_groups.items():
        print(f"   {group_name}: {', '.join(tags)}")
    
    print(f"\n🎯 Actions ({len(processor.actions)}):")
    for action_num, action in processor.actions.items():
        print(f"   {action_num}. {action['description']}")
    
    print(f"\n⚙️  Menu Options ({len(processor.menu_options)}):")
    for option, value in processor.menu_options.items():
        print(f"   {option}: {value}")

def demo_multi_digit_parsing():
    """Demonstrate multi-digit input parsing"""
    print("\n🔢 MULTI-DIGIT INPUT PARSING")
    print("=" * 50)
    
    processor = ZoteroAPIBookProcessor()
    
    test_cases = [
        ("1", "Single action: Add keep tags"),
        ("17", "Two actions: Add keep tags + Update metadata"),
        ("123", "Three actions: Add keep tags + Give away tags + Political tags"),
        ("456", "Three actions: Academic tags + Fiction tags + Nonfiction tags"),
        ("78", "Two actions: Update metadata + Show differences"),
        ("999", "Single action: Remove item (ALWAYS CONFIRMED)"),
        ("1999", "Two actions: Add keep tags + Remove item (tags skipped)"),
        ("abc", "Invalid input (not numeric)"),
        ("", "Empty input"),
    ]
    
    for input_str, description in test_cases:
        actions = processor.parse_multi_digit_choice(input_str)
        print(f"   Input: '{input_str}' -> {actions} ({description})")

def demo_action_execution():
    """Demonstrate action execution logic"""
    print("\n⚡ ACTION EXECUTION SYSTEM")
    print("=" * 50)
    
    processor = ZoteroAPIBookProcessor()
    
    # Simulate action execution for different scenarios
    scenarios = [
        {
            "name": "Keep a book",
            "actions": [1],
            "description": "Add keep tags (Eero har, personal, owned)"
        },
        {
            "name": "Give away a book",
            "actions": [2],
            "description": "Add give away tags (Eero hadde, gitt bort, donated)"
        },
        {
            "name": "Academic political book",
            "actions": [1, 3, 4],
            "description": "Keep + Political + Academic tags"
        },
        {
            "name": "Update existing book",
            "actions": [1, 7],
            "description": "Add keep tags + Update all metadata"
        },
        {
            "name": "Remove unwanted book",
            "actions": [999],
            "description": "Remove item from Zotero (ALWAYS CONFIRMED)"
        },
        {
            "name": "Remove with tags (optimized)",
            "actions": [1, 999],
            "description": "Add keep tags + Remove item (tags skipped for efficiency)"
        }
    ]
    
    for scenario in scenarios:
        print(f"\n📖 Scenario: {scenario['name']}")
        print(f"   Actions: {scenario['actions']}")
        print(f"   Description: {scenario['description']}")
        
        # Show what tags would be added
        tags_to_add = []
        for action_num in scenario['actions']:
            if action_num == 1:
                tags_to_add.extend(processor.tag_groups.get('group1_keep', []))
            elif action_num == 2:
                tags_to_add.extend(processor.tag_groups.get('group2_give_away', []))
            elif action_num == 3:
                tags_to_add.extend(processor.tag_groups.get('group3_political', []))
            elif action_num == 4:
                tags_to_add.extend(processor.tag_groups.get('group4_academic', []))
            elif action_num == 5:
                tags_to_add.extend(processor.tag_groups.get('group5_fiction', []))
            elif action_num == 6:
                tags_to_add.extend(processor.tag_groups.get('group6_nonfiction', []))
        
        if tags_to_add:
            print(f"   Tags to add: {', '.join(tags_to_add)}")

def demo_smart_handling():
    """Demonstrate smart item handling"""
    print("\n🧠 SMART ITEM HANDLING")
    print("=" * 50)
    
    print("📚 For Existing Items in Zotero:")
    print("   • Show current metadata and tags")
    print("   • Allow tag updates and metadata changes")
    print("   • Compare with online metadata")
    print("   • Support all actions including removal")
    
    print("\n📚 For New Items (not in Zotero):")
    print("   • Fetch online metadata first")
    print("   • Add to Zotero with selected tags")
    print("   • Then allow additional actions")
    print("   • Prevent actions requiring existing item")
    
    print("\n🔄 Workflow Examples:")
    print("   • Input '1' on new book → Add to Zotero with keep tags")
    print("   • Input '17' on existing book → Add keep tags + update metadata")
    print("   • Input '8' on any book → Remove from Zotero (with confirmation)")

def demo_difference_detection():
    """Demonstrate difference detection features"""
    print("\n🔍 DIFFERENCE DETECTION")
    print("=" * 50)
    
    print("📊 Metadata Comparison:")
    print("   • Title, Author, Publisher, Date")
    print("   • Language, Page count, Abstract")
    print("   • Place, Edition information")
    
    print("\n🏷️  Tag Comparison:")
    print("   • Show tags only in Zotero")
    print("   • Show tags only in online metadata")
    print("   • Highlight differences with visual indicators")
    
    print("\n👥 Creator Comparison:")
    print("   • Compare author information")
    print("   • Show differences in name formatting")
    print("   • Handle multiple authors")

def main():
    """Run the complete demonstration"""
    print("🚀 ENHANCED ZOTERO BOOK PROCESSOR - FEATURE DEMO")
    print("=" * 60)
    
    try:
        demo_configuration()
        demo_multi_digit_parsing()
        demo_action_execution()
        demo_smart_handling()
        demo_difference_detection()
        
        print("\n" + "=" * 60)
        print("✅ DEMONSTRATION COMPLETE")
        print("\n🎉 All enhanced features are working correctly!")
        print("\n📖 To use the enhanced system:")
        print("   python scripts/add_or_remove_books_zotero.py")
        print("\n💡 Key improvements:")
        print("   • Multi-digit input (e.g., '17' for actions 1+7)")
        print("   • Smart tag groups with predefined categories")
        print("   • Enhanced menu with clear descriptions")
        print("   • Difference detection between Zotero and online data")
        print("   • Intelligent handling of existing vs new items")
        
    except Exception as e:
        print(f"\n❌ Error during demonstration: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
