#!/usr/bin/env python3
"""Quick script to check what attachment items are."""

import sqlite3
from pathlib import Path

db_path = Path("/mnt/f/prog/scanpapers/data/zotero.sqlite.bak")
conn = sqlite3.connect(db_path)
conn.row_factory = sqlite3.Row

cursor = conn.cursor()

# Get sample attachments
query = """
SELECT 
    items.itemID,
    items.key,
    itemAttachments.contentType,
    itemAttachments.path,
    itemAttachments.parentItemID
FROM items
JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
LEFT JOIN itemAttachments ON items.itemID = itemAttachments.itemID
WHERE itemTypes.typeName = 'attachment'
AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
LIMIT 20
"""

cursor.execute(query)
results = cursor.fetchall()

print("Sample of 20 'attachment' items:")
print("="*80)

for idx, row in enumerate(results, 1):
    print(f"\n{idx}. Item ID: {row['itemID']}")
    print(f"   Key: {row['key']}")
    print(f"   Content Type: {row['contentType']}")
    print(f"   Path: {row['path']}")
    print(f"   Parent Item: {row['parentItemID']}")

conn.close()
