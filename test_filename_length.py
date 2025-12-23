#!/usr/bin/env python3
"""
Test script for filename length limit with Ollama shortening.
"""

import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))

from shared_tools.utils.filename_generator import create_filename_generator

def test_filename_length_limit():
    """Test filename length enforcement."""
    gen = create_filename_generator()
    
    print("Testing Filename Length Limit (100 chars without extension)")
    print("=" * 80)
    
    # Test case 1: Create a filename that will definitely exceed 100 chars
    # Using a very long author name and very long title
    print("\nTest 1: Extremely long filename (should trigger shortening/truncation)")
    print("-" * 80)
    metadata1 = {
        'title': 'A Very Long Academic Paper Title About Complex Topics in Multiple Disciplines Including Science Technology Engineering and Mathematics',
        'authors': ['VeryLongAuthorNameOne', 'VeryLongAuthorNameTwo', 'VeryLongAuthorNameThree'],
        'year': '2023',
        'document_type': 'journal_article'
    }
    
    filename1 = gen.generate_filename(metadata1)
    base1 = filename1.rsplit('.', 1)[0] if '.' in filename1 else filename1
    print(f"Original title: {metadata1['title'][:60]}...")
    print(f"Generated filename: {filename1}")
    print(f"Base length (without extension): {len(base1)} characters")
    print(f"Within limit (≤100): {'✅ YES' if len(base1) <= 100 else '❌ NO'}")
    if len(base1) > 100:
        print(f"❌ ERROR: Filename exceeds limit by {len(base1) - 100} characters!")
    
    # Test case 2: Test with _scan suffix
    print("\nTest 2: Extremely long filename with _scan suffix")
    print("-" * 80)
    metadata2 = {
        'title': 'A Very Long Academic Paper Title About Complex Topics in Multiple Disciplines Including Science Technology Engineering and Mathematics',
        'authors': ['VeryLongAuthorNameOne', 'VeryLongAuthorNameTwo', 'VeryLongAuthorNameThree'],
        'year': '2023',
        'document_type': 'journal_article'
    }
    
    filename2 = gen.generate_filename(metadata2, is_scan=True)
    base2 = filename2.rsplit('.', 1)[0] if '.' in filename2 else filename2
    print(f"Original title: {metadata2['title'][:60]}...")
    print(f"Generated filename (with _scan): {filename2}")
    print(f"Base length (without extension): {len(base2)} characters")
    print(f"Within limit (≤100): {'✅ YES' if len(base2) <= 100 else '❌ NO'}")
    if len(base2) > 100:
        print(f"❌ ERROR: Filename exceeds limit by {len(base2) - 100} characters!")
    
    # Test case 3: Short title (should not trigger shortening)
    print("\nTest 3: Short title (should not trigger shortening)")
    print("-" * 80)
    metadata3 = {
        'title': 'Short Title',
        'authors': ['Author'],
        'year': '2023',
        'document_type': 'journal_article'
    }
    
    filename3 = gen.generate_filename(metadata3)
    base3 = filename3.rsplit('.', 1)[0] if '.' in filename3 else filename3
    print(f"Original title: {metadata3['title']}")
    print(f"Generated filename: {filename3}")
    print(f"Base length (without extension): {len(base3)} characters")
    print(f"Within limit (≤100): {'✅ YES' if len(base3) <= 100 else '❌ FAIL'}")
    
    # Test case 4: Test Ollama connection directly
    print("\nTest 4: Testing Ollama connection directly")
    print("-" * 80)
    try:
        from shared_tools.ai.ollama_client import OllamaClient
        client = OllamaClient()
        print(f"Ollama host: {client.ollama_base_url}")
        print(f"Ollama model: {client.ollama_model}")
        test_title = "In_Search_of_the_Right_Spouse_Interracial_Marriage_among_Chinese_and_Japanese_Americans"
        print(f"Testing with title: {test_title}")
        shortened = client.shorten_title(test_title, preserve_first_n_words=4)
        if shortened:
            print(f"✅ Ollama is available and working!")
            print(f"   Shortened title: {shortened}")
            print(f"   Length: {len(shortened)} characters")
        else:
            print("⚠️  Ollama is unavailable or returned None (will use truncation fallback)")
    except Exception as e:
        print(f"❌ Ollama connection failed: {e}")
        print("   Will use truncation fallback")
    
    print("\n" + "=" * 80)
    print("Test Summary:")
    print(f"  Test 1 (very long): {len(base1)} chars - {'✅ PASS' if len(base1) <= 100 else '❌ FAIL'}")
    print(f"  Test 2 (very long + scan): {len(base2)} chars - {'✅ PASS' if len(base2) <= 100 else '❌ FAIL'}")
    print(f"  Test 3 (short): {len(base3)} chars - {'✅ PASS' if len(base3) <= 100 else '❌ FAIL'}")
    
    print("\nNote: If Ollama is available and working, Test 1 and 2 should show")
    print("      intelligently shortened titles (first 4 words preserved).")
    print("      If Ollama is unavailable, truncation fallback will be used.")

if __name__ == "__main__":
    test_filename_length_limit()
