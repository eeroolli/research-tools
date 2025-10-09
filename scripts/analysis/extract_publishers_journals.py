#!/usr/bin/env python3
"""
Extract common publishers and journals from Zotero database.

This creates a reference list for preprocessing - detecting these names
helps classify documents before sending to Ollama.
"""

import sqlite3
from pathlib import Path
from collections import Counter


def get_field_values(db_path: Path, field_name: str, item_type: str = None) -> Counter:
    """Get all values for a field, optionally filtered by item type.
    
    Args:
        db_path: Path to Zotero database
        field_name: Field to extract (e.g., 'publicationTitle', 'publisher')
        item_type: Optional filter by type (e.g., 'journalArticle')
        
    Returns:
        Counter object with value frequencies
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    query = """
    SELECT itemDataValues.value
    FROM itemData
    JOIN fields ON itemData.fieldID = fields.fieldID
    JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
    JOIN items ON itemData.itemID = items.itemID
    """
    
    if item_type:
        query += """
        JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
        WHERE fields.fieldName = ? AND itemTypes.typeName = ?
        """
        cursor.execute(query, (field_name, item_type))
    else:
        query += "WHERE fields.fieldName = ?"
        cursor.execute(query, (field_name,))
    
    values = [row['value'] for row in cursor.fetchall() if row['value']]
    conn.close()
    
    return Counter(values)


def main():
    db_path = Path("/mnt/f/prog/scanpapers/data/zotero.sqlite.bak")
    
    print("="*80)
    print("EXTRACTING PUBLISHERS & JOURNALS FROM ZOTERO")
    print("="*80)
    
    # 1. Journal names (from journal articles)
    print("\n📰 Top 30 Journals:")
    print("-"*80)
    journals = get_field_values(db_path, 'publicationTitle', 'journalArticle')
    for name, count in journals.most_common(30):
        print(f"  {count:4d}x  {name}")
    
    # 2. Publishers (from all items)
    print("\n🏢 Top 30 Publishers:")
    print("-"*80)
    publishers = get_field_values(db_path, 'publisher')
    for name, count in publishers.most_common(30):
        print(f"  {count:4d}x  {name}")
    
    # 3. Newspaper names
    print("\n📄 Newspapers:")
    print("-"*80)
    newspapers = get_field_values(db_path, 'publicationTitle', 'newspaperArticle')
    for name, count in newspapers.most_common():
        print(f"  {count:4d}x  {name}")
    
    # 4. Save to reference files
    output_dir = Path("/mnt/f/prog/research-tools/data/analysis")
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Save journals
    journals_file = output_dir / "common_journals.txt"
    with open(journals_file, 'w', encoding='utf-8') as f:
        f.write("# Common journal names for document classification\n")
        f.write("# Format: count | journal_name\n\n")
        for name, count in journals.most_common(100):
            f.write(f"{count:4d} | {name}\n")
    
    # Save publishers
    publishers_file = output_dir / "common_publishers.txt"
    with open(publishers_file, 'w', encoding='utf-8') as f:
        f.write("# Common publishers for document classification\n")
        f.write("# Format: count | publisher_name\n\n")
        for name, count in publishers.most_common(100):
            f.write(f"{count:4d} | {name}\n")
    
    # Save newspapers
    newspapers_file = output_dir / "common_newspapers.txt"
    with open(newspapers_file, 'w', encoding='utf-8') as f:
        f.write("# Common newspapers for document classification\n")
        f.write("# Format: count | newspaper_name\n\n")
        for name, count in newspapers.most_common():
            f.write(f"{count:4d} | {name}\n")
    
    print(f"\n💾 Reference lists saved:")
    print(f"  Journals (top 100): {journals_file}")
    print(f"  Publishers (top 100): {publishers_file}")
    print(f"  Newspapers (all): {newspapers_file}")
    
    # Summary statistics
    print(f"\n📊 Statistics:")
    print(f"  Unique journals: {len(journals)}")
    print(f"  Unique publishers: {len(publishers)}")
    print(f"  Unique newspapers: {len(newspapers)}")


if __name__ == "__main__":
    main()
