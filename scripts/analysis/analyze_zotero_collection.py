#!/usr/bin/env python3
"""
Analyze Zotero collection to discover document classification patterns.

Extracts evidence-based patterns from your 8000+ Zotero items:
- Page count ranges by document type
- Common keywords by type
- URL patterns
- File availability

This data will be used to build smart preprocessing for Ollama.
"""

import sqlite3
import sys
import csv
from pathlib import Path
from collections import defaultdict, Counter
from typing import Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class ZoteroAnalyzer:
    """Analyze Zotero SQLite database for document patterns."""
    
    def __init__(self, db_path: Path):
        """Initialize analyzer.
        
        Args:
            db_path: Path to Zotero SQLite database
        """
        self.db_path = Path(db_path)
        self.conn = None
    
    def connect(self):
        """Connect to database."""
        if not self.db_path.exists():
            print(f"Error: Database not found: {self.db_path}")
            return False
        
        try:
            self.conn = sqlite3.connect(self.db_path)
            self.conn.row_factory = sqlite3.Row
            print(f"✅ Connected to: {self.db_path}")
            return True
        except Exception as e:
            print(f"Error connecting to database: {e}")
            return False
    
    def get_item_types(self) -> Dict:
        """Get count of items by type."""
        cursor = self.conn.cursor()
        
        query = """
        SELECT itemTypes.typeName, COUNT(*) as count
        FROM items
        JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
        WHERE items.itemID NOT IN (SELECT itemID FROM deletedItems)
        GROUP BY itemTypes.typeName
        ORDER BY count DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        type_counts = {row['typeName']: row['count'] for row in results}
        return type_counts
    
    def get_items_with_attachments(self, item_type: str = None, progress: bool = True) -> List[Dict]:
        """Get items with PDF attachments.
        
        Args:
            item_type: Filter by specific type (e.g., 'journalArticle')
            progress: Show progress indicator
            
        Returns:
            List of items with attachment info
        """
        import time
        cursor = self.conn.cursor()
        
        # Query to get items with PDF attachments
        query = """
        SELECT 
            items.itemID,
            itemTypes.typeName,
            items.key as itemKey
        FROM items
        JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
        WHERE items.itemID NOT IN (SELECT itemID FROM deletedItems)
        """
        
        if item_type:
            query += f" AND itemTypes.typeName = '{item_type}'"
        
        cursor.execute(query)
        all_rows = cursor.fetchall()
        total = len(all_rows)
        
        items = []
        start_time = time.time()
        
        for idx, row in enumerate(all_rows, 1):
            item = {
                'itemID': row['itemID'],
                'type': row['typeName'],
                'key': row['itemKey'],
                'title': self._get_field_value(row['itemID'], 'title'),
                'pages': self._get_field_value(row['itemID'], 'pages'),
                'url': self._get_field_value(row['itemID'], 'url'),
                'doi': self._get_field_value(row['itemID'], 'DOI'),
                'attachments': self._get_attachments(row['itemID'])
            }
            items.append(item)
            
            # Progress indicator every 100 items
            if progress and idx % 100 == 0:
                elapsed = time.time() - start_time
                rate = idx / elapsed if elapsed > 0 else 0
                eta = (total - idx) / rate if rate > 0 else 0
                print(f"    Progress: {idx}/{total} ({idx/total*100:.1f}%) - ETA: {eta:.0f}s", end='\r')
        
        if progress and total > 0:
            elapsed = time.time() - start_time
            print(f"    Completed: {total}/{total} in {elapsed:.1f}s" + " "*20)
        
        return items
    
    def _get_field_value(self, item_id: int, field_name: str) -> str:
        """Get field value for an item."""
        cursor = self.conn.cursor()
        
        query = """
        SELECT itemDataValues.value
        FROM itemData
        JOIN fields ON itemData.fieldID = fields.fieldID
        JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
        WHERE itemData.itemID = ? AND fields.fieldName = ?
        """
        
        cursor.execute(query, (item_id, field_name))
        result = cursor.fetchone()
        return result['value'] if result else None
    
    def _get_attachments(self, item_id: int) -> List[Dict]:
        """Get PDF attachments for an item."""
        cursor = self.conn.cursor()
        
        query = """
        SELECT 
            items.key,
            itemAttachments.path
        FROM itemAttachments
        JOIN items ON itemAttachments.itemID = items.itemID
        WHERE itemAttachments.parentItemID = ?
        AND itemAttachments.contentType = 'application/pdf'
        AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
        """
        
        cursor.execute(query, (item_id,))
        attachments = []
        
        for row in cursor.fetchall():
            attachments.append({
                'key': row['key'],
                'path': row['path']
            })
        
        return attachments
    
    def analyze_collection(self):
        """Perform comprehensive analysis."""
        print("\n" + "="*80)
        print("ZOTERO COLLECTION ANALYSIS")
        print("="*80)
        
        # 1. Item type counts
        print("\n📊 Item Types Distribution:")
        print("-"*80)
        type_counts = self.get_item_types()
        total = sum(type_counts.values())
        print(f"Total items: {total}")
        
        # Estimate time
        est_time = total * 0.05  # ~0.05 seconds per item for database queries
        print(f"⏱️  Estimated time: {est_time:.0f} seconds ({est_time/60:.1f} minutes)\n")
        
        for type_name, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
            pct = (count / total * 100) if total > 0 else 0
            print(f"  {type_name:25s}: {count:5d} ({pct:5.1f}%)")
        
        # 2. Analyze specific types of interest
        types_to_analyze = [
            'journalArticle', 'book', 'bookSection', 'report', 
            'thesis', 'newspaperArticle', 'webpage'
        ]
        
        print("\n" + "="*80)
        print("DETAILED ANALYSIS BY TYPE")
        print("="*80)
        
        analysis_results = []
        
        for item_type in types_to_analyze:
            if item_type not in type_counts:
                continue
            
            print(f"\n📄 Analyzing {item_type}...")
            items = self.get_items_with_attachments(item_type)
            
            if not items:
                continue
            
            # Statistics
            has_doi = sum(1 for i in items if i['doi'])
            has_url = sum(1 for i in items if i['url'])
            has_pages = sum(1 for i in items if i['pages'])
            has_attachments = sum(1 for i in items if i['attachments'])
            
            result = {
                'type': item_type,
                'count': len(items),
                'has_doi_pct': (has_doi / len(items) * 100) if items else 0,
                'has_url_pct': (has_url / len(items) * 100) if items else 0,
                'has_pages_pct': (has_pages / len(items) * 100) if items else 0,
                'has_pdf_pct': (has_attachments / len(items) * 100) if items else 0,
            }
            
            analysis_results.append(result)
            
            print(f"  Items analyzed: {len(items)}")
            print(f"  Has DOI: {has_doi} ({result['has_doi_pct']:.1f}%)")
            print(f"  Has URL: {has_url} ({result['has_url_pct']:.1f}%)")
            print(f"  Has pages field: {has_pages} ({result['has_pages_pct']:.1f}%)")
            print(f"  Has PDF attachments: {has_attachments} ({result['has_pdf_pct']:.1f}%)")
        
        # 3. Save analysis results
        output_dir = Path("/mnt/f/prog/research-tools/data/analysis")
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Save summary to CSV
        summary_file = output_dir / "zotero_type_summary.csv"
        with open(summary_file, 'w', newline='', encoding='utf-8') as f:
            if analysis_results:
                writer = csv.DictWriter(f, fieldnames=analysis_results[0].keys())
                writer.writeheader()
                writer.writerows(analysis_results)
        
        # Save detailed type counts
        counts_file = output_dir / "zotero_type_counts.csv"
        with open(counts_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['document_type', 'count', 'percentage'])
            for type_name, count in sorted(type_counts.items(), key=lambda x: x[1], reverse=True):
                pct = (count / total * 100) if total > 0 else 0
                writer.writerow([type_name, count, f"{pct:.1f}"])
        
        print(f"\n💾 Analysis saved:")
        print(f"  Summary: {summary_file}")
        print(f"  Type counts: {counts_file}")
        
        return analysis_results
    
    def close(self):
        """Close database connection."""
        if self.conn:
            self.conn.close()


def main():
    """Main analysis function."""
    db_path = Path("/mnt/f/prog/scanpapers/data/zotero.sqlite.bak")
    pdf_base_path = Path("/mnt/i/publications")  # May 2025 backup
    
    if not db_path.exists():
        print(f"Error: Database not found: {db_path}")
        print("Please provide the correct path to zotero.sqlite.bak")
        return
    
    print(f"Zotero database: {db_path}")
    print(f"PDF base path: {pdf_base_path}")
    print(f"PDF path exists: {pdf_base_path.exists()}")
    
    analyzer = ZoteroAnalyzer(db_path)
    
    if analyzer.connect():
        try:
            analyzer.analyze_collection()
        finally:
            analyzer.close()


if __name__ == "__main__":
    main()
