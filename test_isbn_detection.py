#!/usr/bin/env python3
"""
Test script to verify ISBN detection from CSV
"""

import csv
from pathlib import Path

def test_get_found_isbns():
    """Test the ISBN detection logic"""
    isbn_list = []
    
    try:
        # Read from the book processing log
        log_file = "data/books/book_processing_log.csv"
        data = []
        if Path(log_file).exists():
            with open(log_file, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                data = list(reader)
        
        for result in data:
            if (result.get('status') == 'success' and 
                result.get('isbn') and 
                not result.get('zotero_decision', '').strip()):  # Only get ISBNs not yet processed for Zotero
                # Extract filename from result
                filename = result.get('filename', '')
                isbn = result['isbn']
                isbn_list.append((isbn, filename))
                
    except Exception as e:
        print(f"Error loading ISBN data: {e}")
        import traceback
        traceback.print_exc()
    
    return isbn_list

if __name__ == "__main__":
    print("Testing ISBN detection...")
    isbns = test_get_found_isbns()
    print(f"Found {len(isbns)} ISBNs ready for Zotero processing:")
    for isbn, filename in isbns:
        print(f"  {isbn} - {filename}")
