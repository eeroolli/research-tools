#!/usr/bin/env python3
"""
Zotero local database search for fast fuzzy matching.
Read-only access to local Zotero SQLite database.

Use this for SEARCHING only - all updates go through API.
"""

import sqlite3
import logging
import re
from pathlib import Path
from typing import List, Dict, Optional
from difflib import SequenceMatcher
import configparser


class ZoteroLocalSearch:
    """Search local Zotero database for matching items."""
    
    def __init__(self, db_path: str = None):
        """
        Initialize local database searcher.
        
        Args:
            db_path: Path to Zotero SQLite database.
                     If None, reads from config.
        """
        self.logger = logging.getLogger(__name__)
        
        if db_path is None:
            db_path = self._get_db_path_from_config()
        
        self.db_path = Path(db_path)
        
        if not self.db_path.exists():
            raise FileNotFoundError(f"Zotero database not found: {self.db_path}")
        
        self.db_connection = None
        
        # Fuzzy matching thresholds
        self.title_threshold = 80
        self.author_threshold = 70
        self.combined_threshold = 75
    
    def _get_db_path_from_config(self) -> str:
        """Get Zotero database path from config files."""
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent.parent
        
        # Try process_papers config first
        process_papers_config = root_dir / 'process_papers' / 'config' / 'process_papers.conf'
        if process_papers_config.exists():
            config.read(process_papers_config)
            if config.has_option('PATHS', 'zotero_db_path'):
                db_path = config.get('PATHS', 'zotero_db_path')
                if db_path:
                    return db_path
        
        # Fallback to main config
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        if config.has_option('PATHS', 'zotero_db_path'):
            return config.get('PATHS', 'zotero_db_path')
        
        raise ValueError("zotero_db_path not found in any config file")
    
    def connect(self):
        """Connect to Zotero database (read-only)."""
        if not self.db_connection:
            # Open in read-only mode for safety
            uri = f"file:{self.db_path}?mode=ro"
            self.db_connection = sqlite3.connect(uri, uri=True)
            self.logger.debug(f"Connected to Zotero database: {self.db_path}")
    
    def disconnect(self):
        """Disconnect from database."""
        if self.db_connection:
            self.db_connection.close()
            self.db_connection = None
    
    def search_by_metadata(self, metadata: Dict, max_matches: int = 5) -> List[Dict]:
        """
        Search Zotero for items matching the metadata.
        
        Args:
            metadata: Paper metadata dict with title, authors, doi, year, etc.
            max_matches: Maximum number of matches to return
            
        Returns:
            List of match dicts with keys:
                - item_key: Zotero item key
                - title: Item title
                - authors: List of author names
                - year: Publication year
                - similarity: Match confidence (0-100%)
                - method: How it was matched
                - has_attachment: Whether item has PDF attachment
        """
        if not self.db_connection:
            self.connect()
        
        matches = []
        
        # Try DOI match first (most reliable)
        if metadata.get('doi'):
            matches.extend(self._search_by_doi(metadata['doi']))
        
        # Try title + author match
        if metadata.get('title'):
            matches.extend(self._search_by_title_fuzzy(
                metadata['title'],
                metadata.get('authors', []),
                metadata.get('year')
            ))
        
        # Remove duplicates and sort by confidence
        unique_matches = {}
        for match in matches:
            key = match['item_key']
            if key not in unique_matches or match['similarity'] > unique_matches[key]['similarity']:
                unique_matches[key] = match
        
        sorted_matches = sorted(
            unique_matches.values(),
            key=lambda x: x['similarity'],
            reverse=True
        )
        
        return sorted_matches[:max_matches]
    
    def _search_by_doi(self, doi: str) -> List[Dict]:
        """Search by DOI (exact match)."""
        matches = []
        
        try:
            cursor = self.db_connection.cursor()
            
            # Query to find items with this DOI
            query = """
            SELECT i.itemID, i.key, 
                   (SELECT value FROM itemDataValues WHERE valueID = id_title.valueID) as title,
                   (SELECT value FROM itemDataValues WHERE valueID = id_year.valueID) as year
            FROM items i
            LEFT JOIN itemData id_doi ON i.itemID = id_doi.itemID 
                AND id_doi.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'DOI')
            LEFT JOIN itemData id_title ON i.itemID = id_title.itemID
                AND id_title.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
            LEFT JOIN itemData id_year ON i.itemID = id_year.itemID
                AND id_year.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'date')
            WHERE id_doi.valueID IN (
                SELECT valueID FROM itemDataValues WHERE value = ?
            )
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            """
            
            cursor.execute(query, (doi,))
            results = cursor.fetchall()
            
            for row in results:
                item_id, item_key, title, year = row
                authors = self._get_authors(item_id)
                has_attachment = self._has_attachment(item_id)
                
                matches.append({
                    'item_key': item_key,
                    'title': title or "Unknown",
                    'authors': authors,
                    'year': self._extract_year(year),
                    'similarity': 100.0,  # Perfect DOI match
                    'method': 'DOI',
                    'has_attachment': has_attachment
                })
        
        except Exception as e:
            self.logger.error(f"Error searching by DOI: {e}")
        
        return matches
    
    def _search_by_title_fuzzy(self, title: str, authors: List[str] = None, 
                                year: int = None) -> List[Dict]:
        """Search by title with fuzzy matching."""
        matches = []
        
        try:
            cursor = self.db_connection.cursor()
            
            # Get all paper items with titles
            query = """
            SELECT i.itemID, i.key,
                   (SELECT value FROM itemDataValues WHERE valueID = id_title.valueID) as title,
                   (SELECT value FROM itemDataValues WHERE valueID = id_year.valueID) as year
            FROM items i
            INNER JOIN itemData id_title ON i.itemID = id_title.itemID
                AND id_title.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
            LEFT JOIN itemData id_year ON i.itemID = id_year.itemID
                AND id_year.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'date')
            WHERE i.itemTypeID IN (
                SELECT itemTypeID FROM itemTypes 
                WHERE typeName IN ('journalArticle', 'conferencePaper', 'preprint', 'report', 'thesis')
            )
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            # Fuzzy match titles
            for row in results:
                item_id, item_key, db_title, db_year = row
                
                if not db_title:
                    continue
                
                # Calculate title similarity
                title_similarity = SequenceMatcher(
                    None,
                    title.lower(),
                    db_title.lower()
                ).ratio() * 100
                
                if title_similarity < self.title_threshold:
                    continue
                
                # Get authors for this item
                item_authors = self._get_authors(item_id)
                
                # Boost score if authors match
                author_boost = 0
                if authors and item_authors:
                    author_match = any(
                        auth.lower() in ' '.join(item_authors).lower()
                        for auth in authors
                    )
                    if author_match:
                        author_boost = 10
                
                # Boost score if year matches
                year_boost = 0
                if year and db_year:
                    item_year = self._extract_year(db_year)
                    if item_year == year:
                        year_boost = 5
                
                combined_similarity = min(
                    title_similarity + author_boost + year_boost,
                    100.0
                )
                
                if combined_similarity >= self.combined_threshold:
                    has_attachment = self._has_attachment(item_id)
                    
                    matches.append({
                        'item_key': item_key,
                        'title': db_title,
                        'authors': item_authors,
                        'year': self._extract_year(db_year),
                        'similarity': combined_similarity,
                        'method': 'Title+Authors',
                        'has_attachment': has_attachment
                    })
        
        except Exception as e:
            self.logger.error(f"Error in fuzzy title search: {e}")
        
        return matches
    
    def _get_authors(self, item_id: int) -> List[str]:
        """Get authors for an item."""
        authors = []
        
        try:
            cursor = self.db_connection.cursor()
            
            query = """
            SELECT c.lastName, c.firstName
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            WHERE ic.itemID = ?
            AND ic.creatorTypeID = (SELECT creatorTypeID FROM creatorTypes WHERE creatorType = 'author')
            ORDER BY ic.orderIndex
            """
            
            cursor.execute(query, (item_id,))
            results = cursor.fetchall()
            
            for last_name, first_name in results:
                if first_name:
                    authors.append(f"{first_name} {last_name}")
                else:
                    authors.append(last_name)
        
        except Exception as e:
            self.logger.error(f"Error getting authors: {e}")
        
        return authors
    
    def _has_attachment(self, item_id: int) -> bool:
        """Check if item has PDF attachment."""
        try:
            cursor = self.db_connection.cursor()
            
            query = """
            SELECT COUNT(*)
            FROM items i
            JOIN itemAttachments ia ON i.itemID = ia.itemID
            WHERE ia.parentItemID = ?
            AND ia.contentType = 'application/pdf'
            """
            
            cursor.execute(query, (item_id,))
            count = cursor.fetchone()[0]
            
            return count > 0
        
        except Exception as e:
            self.logger.error(f"Error checking attachments: {e}")
            return False
    
    def _extract_year(self, date_str: Optional[str]) -> Optional[int]:
        """Extract year from date string."""
        if not date_str:
            return None
        
        # Try to find 4-digit year
        import re
        match = re.search(r'\b(19|20)\d{2}\b', str(date_str))
        if match:
            return int(match.group())
        
        return None
    
    def __enter__(self):
        """Context manager entry."""
        self.connect()
        return self
    
    def search_by_author(self, author_name: str, limit: int = 10) -> list:
        """Search local Zotero database by author name.
        
        Args:
            author_name: Author's last name or full name
            limit: Maximum number of results
            
        Returns:
            List of matching items with metadata
        """
        if not self.db_connection:
            self.connect()
        
        try:
            cursor = self.db_connection.cursor()
            
            # Search in creators table
            query = """
            SELECT DISTINCT i.itemID, i.key, 
                   COALESCE(fv_title.value, '') as title,
                   COALESCE(fv_date.value, '') as date,
                   it.typeName as itemType
            FROM items i
            JOIN itemTypes it ON i.itemTypeID = it.itemTypeID
            JOIN itemCreators ic ON i.itemID = ic.itemID
            JOIN creators c ON ic.creatorID = c.creatorID
            LEFT JOIN itemData id_title ON i.itemID = id_title.itemID 
                AND id_title.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'title')
            LEFT JOIN itemDataValues fv_title ON id_title.valueID = fv_title.valueID
            LEFT JOIN itemData id_date ON i.itemID = id_date.itemID 
                AND id_date.fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'date')
            LEFT JOIN itemDataValues fv_date ON id_date.valueID = fv_date.valueID
            WHERE (c.lastName LIKE ? OR c.firstName LIKE ?)
            AND i.itemID NOT IN (SELECT itemID FROM deletedItems)
            ORDER BY fv_date.value DESC
            LIMIT ?
            """
            
            search_pattern = f"%{author_name}%"
            cursor.execute(query, (search_pattern, search_pattern, limit))
            
            results = []
            for row in cursor.fetchall():
                item = {
                    'itemID': row[0],
                    'key': row[1],
                    'title': row[2],
                    'date': row[3],
                    'itemType': row[4]
                }
                
                # Get full author list
                item['creators'] = self._get_item_creators(cursor, item['itemID'])
                
                # Extract year from date
                date_str = item.get('date', '')
                year_match = re.search(r'\b(19|20)\d{2}\b', date_str)
                item['year'] = year_match.group(0) if year_match else ''
                
                # Check for attachments
                item['hasAttachment'] = self._has_attachment(item['itemID'])
                
                results.append(item)
            
            return results
            
        except Exception as e:
            self.logger.error(f"Error searching by author: {e}")
            return []
    
    def _get_item_creators(self, cursor, item_id: int) -> list:
        """Get creators for an item."""
        creators = []
        
        try:
            query = """
            SELECT c.lastName, c.firstName, ct.creatorType
            FROM itemCreators ic
            JOIN creators c ON ic.creatorID = c.creatorID
            JOIN creatorTypes ct ON ic.creatorTypeID = ct.creatorTypeID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """
            
            cursor.execute(query, (item_id,))
            results = cursor.fetchall()
            
            for last_name, first_name, creator_type in results:
                creators.append({
                    'lastName': last_name,
                    'firstName': first_name,
                    'creatorType': creator_type
                })
        
        except Exception as e:
            self.logger.error(f"Error getting creators: {e}")
        
        return creators
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.disconnect()


if __name__ == "__main__":
    # Test
    try:
        with ZoteroLocalSearch() as searcher:
            # Test search
            test_metadata = {
                'title': 'High-level visual representations',
                'authors': ['Doerig', 'Kietzmann'],
                'year': 2025,
                'doi': '10.1038/s42256-025-01072-0'
            }
            
            matches = searcher.search_by_metadata(test_metadata)
            
            print(f"Found {len(matches)} matches:")
            for i, match in enumerate(matches, 1):
                print(f"\n{i}. {match['title']}")
                print(f"   Authors: {', '.join(match['authors'][:2])}")
                print(f"   Year: {match['year']}")
                print(f"   Similarity: {match['similarity']:.1f}%")
                print(f"   Method: {match['method']}")
                print(f"   Has PDF: {match['has_attachment']}")
    
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure zotero_db_path is configured in process_papers.conf")

