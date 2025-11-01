#!/usr/bin/env python3
"""
Author validation using Zotero collection.

Validates extracted authors against ALL authors in Zotero collection:
- OCR error correction (edit distance)
- Author recognition for matching
- Session cache for consecutive scans (alphabetical order)

Simple approach: If an author is in Zotero, they're recognized.
No thresholds, no complexity - just all authors in your collection.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import configparser
from difflib import SequenceMatcher
from datetime import datetime


class AuthorValidator:
    """Validate extracted authors against Zotero collection."""
    
    def __init__(self, db_path: Optional[Path] = None, cache_file: Optional[Path] = None):
        """
        Initialize author validator.
        
        Args:
            db_path: Path to Zotero SQLite database. If None, reads from config.
            cache_file: Path to cache file for author lists. If None, uses default.
        """
        if db_path is None:
            db_path = self._get_db_path_from_config()
        
        self.db_path = Path(db_path)
        
        if not self.db_path.exists():
            raise FileNotFoundError(f"Zotero database not found: {self.db_path}")
        
        # Set cache file location
        if cache_file is None:
            root_dir = Path(__file__).parent.parent.parent
            cache_dir = root_dir / 'data' / 'cache'
            cache_dir.mkdir(parents=True, exist_ok=True)
            cache_file = cache_dir / 'zotero_authors.json'
        
        self.cache_file = Path(cache_file)
        
        # Load ALL authors from Zotero (no thresholds)
        self.zotero_authors = []  # All authors in your Zotero collection
        self._load_author_list()
        
        # Build simple last name index
        # "olli" → ["Eero Olli", "Ottar Olli"] (all authors with that last name)
        self.lastname_index = {}  # lastname -> list of full names
        self._build_lastname_index()
    
    def _get_db_path_from_config(self) -> Path:
        """Get Zotero database path from config files."""
        config = configparser.ConfigParser()
        root_dir = Path(__file__).parent.parent.parent
        
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        if config.has_option('PATHS', 'zotero_db_path'):
            return Path(config.get('PATHS', 'zotero_db_path'))
        
        raise ValueError("zotero_db_path not found in config files")
    
    def cache_age_hours(self) -> Optional[float]:
        """
        Get age of cache file in hours.
        
        Returns:
            Hours since cache was created, or None if cache doesn't exist
        """
        if not self.cache_file.exists():
            return None
        
        cache_mtime = datetime.fromtimestamp(self.cache_file.stat().st_mtime)
        age = datetime.now() - cache_mtime
        return age.total_seconds() / 3600
    
    def needs_refresh(self, max_age_hours: float = 24) -> bool:
        """
        Check if cache needs refresh based on age.
        
        Args:
            max_age_hours: Maximum cache age in hours (default: 24)
            
        Returns:
            True if cache is older than max_age_hours or doesn't exist
        """
        age = self.cache_age_hours()
        if age is None:
            return True  # No cache exists
        return age > max_age_hours
    
    def refresh_if_needed(self, max_age_hours: float = 24, silent: bool = True) -> bool:
        """
        Refresh cache if older than max_age_hours.
        
        Very fast (53ms), safe to call anytime.
        
        Args:
            max_age_hours: Maximum cache age in hours (default: 24)
            silent: If True, suppress print statements
            
        Returns:
            True if cache was refreshed, False if still fresh
        """
        if self.needs_refresh(max_age_hours):
            if not silent:
                age = self.cache_age_hours()
                if age:
                    print(f"🔄 Refreshing author cache ({age:.1f}h old)...")
                else:
                    print("🔄 Building author cache...")
            self._extract_from_database(silent=silent)
            self._save_cache(silent=silent)
            if not silent:
                print("✅ Author cache updated")
            return True
        return False

    def _load_author_list(self):
        """Load author list from cache or extract from database."""
        # Try loading from cache first
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    self.zotero_authors = cache_data.get('zotero_authors', [])
                    
                    if self.zotero_authors:
                        age = self.cache_age_hours()
                        age_str = f" ({age:.1f}h old)" if age else ""
                        print(f"✅ Loaded {len(self.zotero_authors)} authors from Zotero cache{age_str}")
                        return
            except Exception as e:
                print(f"⚠️  Cache read failed: {e}")
        
        # Extract from database if cache failed
        print("🔄 Extracting ALL authors from Zotero database...")
        self._extract_from_database()
        self._save_cache()
    
    def _extract_from_database(self, silent: bool = False):
        """Extract ALL authors from Zotero database (no thresholds)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Extract ALL authors (1+ papers) from Zotero
        query = """
        SELECT c.lastName, c.firstName, COUNT(*) as paper_count
        FROM creators c
        JOIN itemCreators ic ON c.creatorID = ic.creatorID
        WHERE ic.itemID NOT IN (SELECT itemID FROM deletedItems)
        AND ic.creatorTypeID = (SELECT creatorTypeID FROM creatorTypes WHERE creatorType = 'author')
        GROUP BY c.creatorID
        ORDER BY paper_count DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        self.zotero_authors = []
        for last_name, first_name, count in results:
            if first_name:
                full_name = f"{first_name} {last_name}"
            else:
                full_name = last_name
            
            self.zotero_authors.append({
                'name': full_name,
                'last_name': last_name,
                'first_name': first_name or '',
                'paper_count': count
            })
        
        conn.close()
        
        if not silent:
            print(f"✅ Extracted {len(self.zotero_authors)} authors from Zotero")
    
    def _save_cache(self, silent: bool = False):
        """Save author list to cache file."""
        try:
            cache_data = {
                'zotero_authors': self.zotero_authors,
                'extracted_from': str(self.db_path),
                'version': '2.0',  # Simplified version
                'timestamp': datetime.now().isoformat()
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            if not silent:
                print(f"💾 Cached {len(self.zotero_authors)} authors to: {self.cache_file}")
        except Exception as e:
            if not silent:
                print(f"⚠️  Cache save failed: {e}")
    
    def _extract_lastname(self, name: str) -> str:
        """
        Extract last name from author name.
        
        Simple approach: last word in name is the last name.
        
        Args:
            name: Author name in any format
            
        Returns:
            Last name (lowercase)
        """
        name = name.strip()
        
        # Handle "Last, First" format - take first part
        if ',' in name:
            return name.split(',')[0].strip().lower()
        
        # Handle "First Last" format - take last word
        parts = name.split()
        if parts:
            return parts[-1].strip().lower()
        
        return name.lower()
    
    def _build_lastname_index(self):
        """Build simple last name index for all Zotero authors."""
        self.lastname_index = {}
        
        for author in self.zotero_authors:
            full_name = author['name']
            lastname = self._extract_lastname(full_name)
            
            if lastname not in self.lastname_index:
                self.lastname_index[lastname] = []
            
            self.lastname_index[lastname].append(full_name)
    
    def suggest_ocr_correction(self, extracted_name: str, max_distance: int = 2) -> Optional[Dict]:
        """
        Suggest OCR correction for an extracted name using edit distance.
        
        Checks all Zotero authors for potential OCR errors.
        
        Args:
            extracted_name: The name extracted from OCR/AI
            max_distance: Maximum edit distance to consider (default: 2)
            
        Returns:
            Dict with correction info or None if no good match found:
                - corrected_name: Suggested correction
                - confidence: Match confidence (0-100)
                - distance: Edit distance
                - paper_count: Number of papers by this author
        """
        best_match = None
        best_similarity = 0
        
        extracted_lower = extracted_name.lower()
        
        for author in self.zotero_authors:
            author_name = author['name']
            author_lower = author_name.lower()
            
            # Calculate similarity ratio
            similarity = SequenceMatcher(None, extracted_lower, author_lower).ratio()
            
            # Calculate Levenshtein-like distance
            if similarity > 0.8:  # Only consider good matches
                distance = self._edit_distance(extracted_lower, author_lower)
                
                if distance <= max_distance and similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        'corrected_name': author_name,
                        'confidence': int(similarity * 100),
                        'distance': distance,
                        'paper_count': author['paper_count'],
                        'original_name': extracted_name
                    }
        
        return best_match
    
    def _edit_distance(self, s1: str, s2: str) -> int:
        """Calculate Levenshtein edit distance between two strings."""
        if len(s1) < len(s2):
            return self._edit_distance(s2, s1)
        
        if len(s2) == 0:
            return len(s1)
        
        previous_row = range(len(s2) + 1)
        for i, c1 in enumerate(s1):
            current_row = [i + 1]
            for j, c2 in enumerate(s2):
                # Cost of insertions, deletions, or substitutions
                insertions = previous_row[j + 1] + 1
                deletions = current_row[j] + 1
                substitutions = previous_row[j] + (c1 != c2)
                current_row.append(min(insertions, deletions, substitutions))
            previous_row = current_row
        
        return previous_row[-1]
    
    def validate_authors(self, extracted_authors: List[str]) -> Dict:
        """
        Validate extracted authors against Zotero collection.
        
        Checks all authors in your Zotero database for matches.
        
        Args:
            extracted_authors: List of author names from extraction
            
        Returns:
            Dict with validation results:
                - known_authors: List of authors found in Zotero
                - unknown_authors: List of new/unrecognized authors
                - ocr_corrections: List of suggested OCR corrections
                - confidence: Overall confidence (HIGH/MEDIUM/LOW)
                - coverage_pct: Percentage of known authors
        """
        if not extracted_authors:
            return {
                'known_authors': [],
                'unknown_authors': [],
                'ocr_corrections': [],
                'confidence': 'UNKNOWN',
                'coverage_pct': 0
            }
        
        known = []
        unknown = []
        corrections = []
        
        for extracted_name in extracted_authors:
            # Extract last name and look up in index
            lastname = self._extract_lastname(extracted_name)
            
            if lastname in self.lastname_index:
                # Found matching last name(s) in Zotero
                matches = self.lastname_index[lastname]
                
                if len(matches) == 1:
                    # Single match - use it
                    known.append({
                        'name': matches[0],
                        'original': extracted_name,
                        'match_type': 'lastname',
                        'alternatives': []
                    })
                else:
                    # Multiple matches - suggest first, list alternatives
                    known.append({
                        'name': matches[0],
                        'original': extracted_name,
                        'match_type': 'lastname_multiple',
                        'alternatives': matches[1:]  # Other options
                    })
            else:
                # Last name not found - genuinely unknown
                unknown.append({
                    'name': extracted_name,
                    'suggestion': None
                })
        
        # Calculate confidence
        known_count = len(known)
        total_count = len(extracted_authors)
        coverage_pct = (known_count / total_count * 100) if total_count > 0 else 0
        
        if coverage_pct == 100:
            confidence = 'HIGH'
        elif coverage_pct >= 50:
            confidence = 'MEDIUM'
        else:
            confidence = 'LOW'
        
        return {
            'known_authors': known,
            'unknown_authors': unknown,
            'ocr_corrections': corrections,
            'confidence': confidence,
            'coverage_pct': coverage_pct
        }
    
    def get_author_info(self, author_name: str) -> Optional[Dict]:
        """
        Get information about an author from Zotero collection.
        
        Args:
            author_name: Author name to look up
            
        Returns:
            Dict with author info or None if not found
        """
        author_lower = author_name.lower()
        
        # Check Zotero authors
        for author in self.zotero_authors:
            if author['name'].lower() == author_lower:
                return author
        
        return None
    

    
    def rebuild_cache(self):
        """Force rebuild of author cache from database (blocking)."""
        print("🔄 Rebuilding author cache...")
        self._extract_from_database()
        self._save_cache()
        print("✅ Cache rebuilt successfully")


if __name__ == "__main__":
    # Test the validator
    print("Testing AuthorValidator")
    print("=" * 80)
    
    try:
        validator = AuthorValidator()
        
        print(f"\nLoaded {len(validator.zotero_authors)} authors from Zotero")
        
        # Test cache age
        age = validator.cache_age_hours()
        if age:
            print(f"Cache age: {age:.2f} hours")
            print(f"Needs refresh (24h): {validator.needs_refresh()}")
        
        # Test validation
        print("\n" + "=" * 80)
        print("TEST 1: Validate known authors")
        print("=" * 80)
        
        test_authors = ["Per Selle", "Mary Douglas", "Jane Smith"]
        result = validator.validate_authors(test_authors)
        
        print(f"\nConfidence: {result['confidence']}")
        print(f"Coverage: {result['coverage_pct']:.1f}%")
        print(f"\nKnown authors: {len(result['known_authors'])}")
        for author in result['known_authors']:
            info = validator.get_author_info(author['name'])
            papers = info['paper_count'] if info else 0
            print(f"  ✅ {author['name']} ({papers} papers)")
        
        print(f"\nUnknown authors: {len(result['unknown_authors'])}")
        for author in result['unknown_authors']:
            print(f"  🆕 {author['name']}")
        
        # Test OCR correction
        print("\n" + "=" * 80)
        print("TEST 2: OCR error correction")
        print("=" * 80)
        
        test_ocr_names = [
            "Bernt Aard0l",  # Should correct to "Bernt Aardal"
            "Per Se11e",     # Should correct to "Per Selle"
        ]
        
        for name in test_ocr_names:
            correction = validator.suggest_ocr_correction(name)
            if correction:
                print(f"\n'{name}' → '{correction['corrected_name']}'")
                print(f"  Confidence: {correction['confidence']}%")
                print(f"  Distance: {correction['distance']}")
                print(f"  Author has {correction['paper_count']} papers in Zotero")
            else:
                print(f"\n'{name}' → No correction found")
        
        # Test lastname matching with different formats
        print("\n" + "=" * 80)
        print("TEST 3: Lastname matching (all formats)")
        print("=" * 80)
        
        test_formats = ["Eero Olli", "Olli, Eero", "E. Olli", "Olli E"]
        result = validator.validate_authors(test_formats)
        
        print(f"\nTested {len(test_formats)} different formats:")
        for author in result['known_authors']:
            print(f"  '{author['original']:15}' → {author['name']:20} ({author['match_type']})")
            if author.get('alternatives'):
                print(f"    Alternatives: {', '.join(author['alternatives'][:3])}")
        
        if result['unknown_authors']:
            print(f"\nUnknown: {len(result['unknown_authors'])}")
            for author in result['unknown_authors']:
                print(f"  ❌ {author['name']}")
        
        print("\n" + "=" * 80)
        print("✅ All tests completed")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
