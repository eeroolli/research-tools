"""
Zotero local database matching for academic papers using fuzzy matching.

This module provides fuzzy matching capabilities against the local Zotero SQLite database
to find existing entries and avoid duplicates when processing academic papers.
"""
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
from fuzzywuzzy import fuzz, process
import sqlite3
from pathlib import Path

from ..models.paper import Paper, PaperMetadata


@dataclass
class ZoteroMatch:
    """Result of Zotero matching."""
    item_id: str
    title: str
    authors: List[str]
    year: Optional[int]
    confidence: float
    match_method: str
    zotero_item: Dict[str, Any]


class ZoteroLocalDatabaseMatcher:
    """Match papers to existing Zotero entries using local SQLite database."""
    
    def __init__(self, zotero_db_path: str):
        """
        Initialize Zotero local database matcher.
        
        Args:
            zotero_db_path: Path to Zotero SQLite database (usually zotero.sqlite)
        """
        self.zotero_db_path = zotero_db_path
        self.logger = logging.getLogger(__name__)
        self.db_connection = None
        
        # Fuzzy matching thresholds
        self.title_threshold = 80
        self.author_threshold = 70
        self.combined_threshold = 75
    
    def connect_database(self):
        """Connect to Zotero database."""
        try:
            self.db_connection = sqlite3.connect(self.zotero_db_path)
            self.logger.info("Connected to Zotero database")
        except Exception as e:
            self.logger.error(f"Failed to connect to Zotero database: {e}")
            raise
    
    def disconnect_database(self):
        """Disconnect from Zotero database."""
        if self.db_connection:
            self.db_connection.close()
            self.db_connection = None
    
    def find_matches(self, paper: Paper, max_matches: int = 5) -> List[ZoteroMatch]:
        """
        Find potential matches for a paper in Zotero.
        
        Args:
            paper: Paper to match
            max_matches: Maximum number of matches to return
            
        Returns:
            List of potential matches sorted by confidence
        """
        if not paper.metadata:
            return []
        
        if not self.db_connection:
            self.connect_database()
        
        matches = []
        
        # Try different matching strategies
        matches.extend(self._match_by_doi(paper))
        matches.extend(self._match_by_title_and_authors(paper))
        matches.extend(self._match_by_title_only(paper))
        
        # Remove duplicates and sort by confidence
        unique_matches = {}
        for match in matches:
            if match.item_id not in unique_matches or match.confidence > unique_matches[match.item_id].confidence:
                unique_matches[match.item_id] = match
        
        sorted_matches = sorted(unique_matches.values(), key=lambda x: x.confidence, reverse=True)
        return sorted_matches[:max_matches]
    
    def _match_by_doi(self, paper: Paper) -> List[ZoteroMatch]:
        """Match by DOI if available."""
        matches = []
        
        if not paper.metadata or not paper.metadata.doi:
            return matches
        
        try:
            cursor = self.db_connection.cursor()
            
            # Search for DOI in Zotero items
            query = """
            SELECT itemID, title, dateAdded, dateModified
            FROM items 
            WHERE itemID IN (
                SELECT itemID FROM itemData 
                WHERE fieldID = (SELECT fieldID FROM fields WHERE fieldName = 'DOI')
                AND value = ?
            )
            """
            
            cursor.execute(query, (paper.metadata.doi,))
            results = cursor.fetchall()
            
            for row in results:
                item_id, title, date_added, date_modified = row
                
                # Get authors for this item
                authors = self._get_item_authors(item_id)
                
                # Get full item data
                item_data = self._get_item_data(item_id)
                
                match = ZoteroMatch(
                    item_id=str(item_id),
                    title=title or "Unknown Title",
                    authors=authors,
                    year=self._extract_year_from_date(date_added),
                    confidence=95.0,  # DOI match is very reliable
                    match_method="DOI",
                    zotero_item=item_data
                )
                matches.append(match)
            
        except Exception as e:
            self.logger.error(f"Error matching by DOI: {e}")
        
        return matches
    
    def _match_by_title_and_authors(self, paper: Paper) -> List[ZoteroMatch]:
        """Match by title and authors using fuzzy matching."""
        matches = []
        
        if not paper.metadata or not paper.metadata.title:
            return matches
        
        try:
            cursor = self.db_connection.cursor()
            
            # Get all items with titles and authors
            query = """
            SELECT DISTINCT i.itemID, i.title, i.dateAdded, i.dateModified
            FROM items i
            WHERE i.title IS NOT NULL AND i.title != ''
            AND i.itemTypeID IN (2, 3, 4, 5, 6)  -- Journal Article, Book, Book Section, etc.
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            paper_title = paper.metadata.title.lower()
            paper_authors = [author.lower() for author in (paper.metadata.authors or [])]
            
            for row in results:
                item_id, title, date_added, date_modified = row
                
                if not title:
                    continue
                
                # Get authors for this item
                authors = self._get_item_authors(item_id)
                
                # Calculate title similarity
                title_similarity = fuzz.ratio(paper_title, title.lower())
                
                # Calculate author similarity
                author_similarity = 0.0
                if paper_authors and authors:
                    author_similarity = self._calculate_author_similarity(paper_authors, authors)
                
                # Calculate combined confidence
                if title_similarity >= self.title_threshold:
                    confidence = title_similarity
                    if author_similarity >= self.author_threshold:
                        confidence = (title_similarity + author_similarity) / 2
                    
                    if confidence >= self.combined_threshold:
                        item_data = self._get_item_data(item_id)
                        
                        match = ZoteroMatch(
                            item_id=str(item_id),
                            title=title,
                            authors=authors,
                            year=self._extract_year_from_date(date_added),
                            confidence=confidence,
                            match_method="Title+Authors",
                            zotero_item=item_data
                        )
                        matches.append(match)
            
        except Exception as e:
            self.logger.error(f"Error matching by title and authors: {e}")
        
        return matches
    
    def _match_by_title_only(self, paper: Paper) -> List[ZoteroMatch]:
        """Match by title only using fuzzy matching."""
        matches = []
        
        if not paper.metadata or not paper.metadata.title:
            return matches
        
        try:
            cursor = self.db_connection.cursor()
            
            # Get all items with titles
            query = """
            SELECT DISTINCT i.itemID, i.title, i.dateAdded, i.dateModified
            FROM items i
            WHERE i.title IS NOT NULL AND i.title != ''
            AND i.itemTypeID IN (2, 3, 4, 5, 6)  -- Journal Article, Book, Book Section, etc.
            """
            
            cursor.execute(query)
            results = cursor.fetchall()
            
            paper_title = paper.metadata.title.lower()
            
            for row in results:
                item_id, title, date_added, date_modified = row
                
                if not title:
                    continue
                
                # Calculate title similarity
                title_similarity = fuzz.ratio(paper_title, title.lower())
                
                if title_similarity >= 85:  # Higher threshold for title-only matching
                    # Get authors for this item
                    authors = self._get_item_authors(item_id)
                    
                    # Get full item data
                    item_data = self._get_item_data(item_id)
                    
                    match = ZoteroMatch(
                        item_id=str(item_id),
                        title=title,
                        authors=authors,
                        year=self._extract_year_from_date(date_added),
                        confidence=title_similarity * 0.8,  # Lower confidence for title-only
                        match_method="Title Only",
                        zotero_item=item_data
                    )
                    matches.append(match)
            
        except Exception as e:
            self.logger.error(f"Error matching by title only: {e}")
        
        return matches
    
    def _get_item_authors(self, item_id: int) -> List[str]:
        """Get authors for a Zotero item."""
        authors = []
        
        try:
            cursor = self.db_connection.cursor()
            
            query = """
            SELECT DISTINCT c.lastName, c.firstName
            FROM creators c
            JOIN itemCreators ic ON c.creatorID = ic.creatorID
            WHERE ic.itemID = ?
            ORDER BY ic.orderIndex
            """
            
            cursor.execute(query, (item_id,))
            results = cursor.fetchall()
            
            for last_name, first_name in results:
                if last_name:
                    author_name = f"{first_name or ''} {last_name}".strip()
                    if author_name:
                        authors.append(author_name)
            
        except Exception as e:
            self.logger.error(f"Error getting authors for item {item_id}: {e}")
        
        return authors
    
    def _get_item_data(self, item_id: int) -> Dict[str, Any]:
        """Get full item data for a Zotero item."""
        item_data = {}
        
        try:
            cursor = self.db_connection.cursor()
            
            # Get basic item info
            query = """
            SELECT i.itemTypeID, i.title, i.dateAdded, i.dateModified, i.key
            FROM items i
            WHERE i.itemID = ?
            """
            
            cursor.execute(query, (item_id,))
            result = cursor.fetchone()
            
            if result:
                item_type_id, title, date_added, date_modified, key = result
                item_data.update({
                    'itemID': item_id,
                    'itemTypeID': item_type_id,
                    'title': title,
                    'dateAdded': date_added,
                    'dateModified': date_modified,
                    'key': key
                })
            
            # Get item data fields
            query = """
            SELECT f.fieldName, id.value
            FROM itemData id
            JOIN fields f ON id.fieldID = f.fieldID
            WHERE id.itemID = ?
            """
            
            cursor.execute(query, (item_id,))
            results = cursor.fetchall()
            
            for field_name, value in results:
                if value:
                    item_data[field_name] = value
            
        except Exception as e:
            self.logger.error(f"Error getting item data for item {item_id}: {e}")
        
        return item_data
    
    def _calculate_author_similarity(self, paper_authors: List[str], zotero_authors: List[str]) -> float:
        """Calculate similarity between author lists."""
        if not paper_authors or not zotero_authors:
            return 0.0
        
        # Normalize author names
        paper_authors_norm = [self._normalize_author_name(author) for author in paper_authors]
        zotero_authors_norm = [self._normalize_author_name(author) for author in zotero_authors]
        
        # Calculate pairwise similarities
        similarities = []
        for paper_author in paper_authors_norm:
            best_match = 0
            for zotero_author in zotero_authors_norm:
                similarity = fuzz.ratio(paper_author, zotero_author)
                best_match = max(best_match, similarity)
            similarities.append(best_match)
        
        # Return average similarity
        return sum(similarities) / len(similarities) if similarities else 0.0
    
    def _normalize_author_name(self, author_name: str) -> str:
        """Normalize author name for comparison."""
        # Convert to lowercase and remove extra spaces
        normalized = ' '.join(author_name.lower().split())
        
        # Remove common suffixes
        suffixes = ['jr', 'sr', 'ii', 'iii', 'iv', 'phd', 'md', 'prof']
        for suffix in suffixes:
            if normalized.endswith(f' {suffix}'):
                normalized = normalized[:-len(suffix)-1]
        
        return normalized
    
    def _extract_year_from_date(self, date_string: str) -> Optional[int]:
        """Extract year from date string."""
        if not date_string:
            return None
        
        try:
            # Try to parse the date and extract year
            from datetime import datetime
            date_obj = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
            return date_obj.year
        except:
            return None
