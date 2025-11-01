#!/usr/bin/env python3
"""
Journal validation using Zotero collection.

Validates extracted journal titles against ALL journals in Zotero collection:
- OCR error correction (edit distance)
- Journal recognition for matching
- Session cache for consecutive scans

Simple approach: If a journal is in Zotero, it's recognized.
No thresholds, no complexity - just all journals in your collection.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Dict, Optional
import configparser
from difflib import SequenceMatcher
from datetime import datetime


class JournalValidator:
    """Validate extracted journals against Zotero collection."""
    
    def __init__(self, db_path: Optional[Path] = None, cache_file: Optional[Path] = None):
        """
        Initialize journal validator.
        
        Args:
            db_path: Path to Zotero SQLite database. If None, reads from config.
            cache_file: Path to cache file for journal lists. If None, uses default.
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
            cache_file = cache_dir / 'zotero_journals.json'
        
        self.cache_file = Path(cache_file)
        
        # Load ALL journals from Zotero (no thresholds)
        self.zotero_journals = []  # All journals in your Zotero collection
        self._load_journal_list()
        
        # Build simple normalized index
        # "journal of political science" → ["Journal of Political Science"]
        self.normalized_index = {}  # normalized_name -> list of full names
        self._build_normalized_index()
    
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
        
        Very fast, safe to call anytime.
        
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
                    print(f"🔄 Refreshing journal cache ({age:.1f}h old)...")
                else:
                    print("🔄 Building journal cache...")
            self._extract_from_database(silent=silent)
            self._save_cache(silent=silent)
            if not silent:
                print("✅ Journal cache updated")
            return True
        return False

    def _load_journal_list(self):
        """Load journal list from cache or extract from database."""
        # Try loading from cache first
        if self.cache_file.exists():
            try:
                with open(self.cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                    self.zotero_journals = cache_data.get('zotero_journals', [])
                    
                    if self.zotero_journals:
                        age = self.cache_age_hours()
                        age_str = f" ({age:.1f}h old)" if age else ""
                        print(f"✅ Loaded {len(self.zotero_journals)} journals from Zotero cache{age_str}")
                        return
            except Exception as e:
                print(f"⚠️  Cache read failed: {e}")
        
        # Extract from database if cache failed
        print("🔄 Extracting ALL journals from Zotero database...")
        self._extract_from_database()
        self._save_cache()
    
    def _extract_from_database(self, silent: bool = False):
        """Extract ALL journals from Zotero database (journal articles only)."""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Extract ALL journals from journal articles
        query = """
        SELECT itemDataValues.value, COUNT(*) as paper_count
        FROM itemData
        JOIN fields ON itemData.fieldID = fields.fieldID
        JOIN itemDataValues ON itemData.valueID = itemDataValues.valueID
        JOIN items ON itemData.itemID = items.itemID
        JOIN itemTypes ON items.itemTypeID = itemTypes.itemTypeID
        WHERE fields.fieldName = 'publicationTitle'
        AND itemTypes.typeName = 'journalArticle'
        AND items.itemID NOT IN (SELECT itemID FROM deletedItems)
        AND itemDataValues.value IS NOT NULL
        AND itemDataValues.value != ''
        GROUP BY itemDataValues.value
        ORDER BY paper_count DESC
        """
        
        cursor.execute(query)
        results = cursor.fetchall()
        
        self.zotero_journals = []
        for journal_name, count in results:
            normalized = self._normalize_journal_name(journal_name)
            
            self.zotero_journals.append({
                'name': journal_name,
                'paper_count': count,
                'normalized': normalized
            })
        
        conn.close()
        
        if not silent:
            print(f"✅ Extracted {len(self.zotero_journals)} journals from Zotero")
    
    def _save_cache(self, silent: bool = False):
        """Save journal list to cache file."""
        try:
            cache_data = {
                'zotero_journals': self.zotero_journals,
                'extracted_from': str(self.db_path),
                'version': '1.0',
                'timestamp': datetime.now().isoformat()
            }
            
            with open(self.cache_file, 'w', encoding='utf-8') as f:
                json.dump(cache_data, f, indent=2, ensure_ascii=False)
            
            if not silent:
                print(f"💾 Cached {len(self.zotero_journals)} journals to: {self.cache_file}")
        except Exception as e:
            if not silent:
                print(f"⚠️  Cache save failed: {e}")
    
    def _normalize_journal_name(self, name: str) -> str:
        """
        Normalize journal name for comparison.
        
        Simple approach: lowercase, trim whitespace.
        Phase 3 will add abbreviation expansion.
        
        Args:
            name: Journal name in any format
            
        Returns:
            Normalized name (lowercase, trimmed)
        """
        return name.strip().lower()
    
    def _build_normalized_index(self):
        """Build simple normalized index for all Zotero journals."""
        self.normalized_index = {}
        
        for journal in self.zotero_journals:
            full_name = journal['name']
            normalized = journal['normalized']
            
            if normalized not in self.normalized_index:
                self.normalized_index[normalized] = []
            
            self.normalized_index[normalized].append(full_name)
    
    def suggest_ocr_correction(self, extracted_name: str, max_distance: int = 2) -> Optional[Dict]:
        """
        Suggest OCR correction for an extracted journal name using edit distance.
        
        Checks all Zotero journals for potential OCR errors.
        
        Args:
            extracted_name: The journal name extracted from OCR/AI
            max_distance: Maximum edit distance to consider (default: 2)
            
        Returns:
            Dict with correction info or None if no good match found:
                - corrected_name: Suggested correction
                - confidence: Match confidence (0-100)
                - distance: Edit distance
                - paper_count: Number of papers in this journal
        """
        best_match = None
        best_similarity = 0
        
        extracted_lower = extracted_name.lower()
        
        for journal in self.zotero_journals:
            journal_name = journal['name']
            journal_lower = journal_name.lower()
            
            # Calculate similarity ratio
            similarity = SequenceMatcher(None, extracted_lower, journal_lower).ratio()
            
            # Calculate Levenshtein-like distance
            if similarity > 0.8:  # Only consider good matches
                distance = self._edit_distance(extracted_lower, journal_lower)
                
                if distance <= max_distance and similarity > best_similarity:
                    best_similarity = similarity
                    best_match = {
                        'corrected_name': journal_name,
                        'confidence': int(similarity * 100),
                        'distance': distance,
                        'paper_count': journal['paper_count'],
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
    
    def validate_journal(self, extracted_journal: str) -> Dict:
        """
        Validate extracted journal against Zotero collection.
        
        Args:
            extracted_journal: Journal name from extraction
            
        Returns:
            Dict with validation results:
                - matched: bool
                - journal_name: str or None (normalized name if matched)
                - paper_count: int or None
                - match_type: 'exact' | 'fuzzy' | 'none'
                - confidence: int (0-100)
                - alternatives: List[str] (alternative matches if multiple)
                - original: str (original extracted name)
        """
        if not extracted_journal:
            return {
                'matched': False,
                'journal_name': None,
                'paper_count': None,
                'match_type': 'none',
                'confidence': 0,
                'alternatives': [],
                'original': extracted_journal
            }
        
        original = extracted_journal.strip()
        normalized = self._normalize_journal_name(original)
        
        # Try exact match first (normalized lookup)
        if normalized in self.normalized_index:
            matches = self.normalized_index[normalized]
            
            # Find the journal entry with this name to get paper_count
            journal_entry = None
            for journal in self.zotero_journals:
                if journal['normalized'] == normalized:
                    journal_entry = journal
                    break
            
            if journal_entry:
                if len(matches) == 1:
                    # Single exact match
                    return {
                        'matched': True,
                        'journal_name': matches[0],
                        'paper_count': journal_entry['paper_count'],
                        'match_type': 'exact',
                        'confidence': 100,
                        'alternatives': [],
                        'original': original
                    }
                else:
                    # Multiple matches with same normalized name (shouldn't happen, but handle it)
                    return {
                        'matched': True,
                        'journal_name': matches[0],
                        'paper_count': journal_entry['paper_count'],
                        'match_type': 'exact',
                        'confidence': 100,
                        'alternatives': matches[1:],
                        'original': original
                    }
        
        # Try fuzzy match if no exact match
        ocr_correction = self.suggest_ocr_correction(original)
        if ocr_correction:
            return {
                'matched': True,
                'journal_name': ocr_correction['corrected_name'],
                'paper_count': ocr_correction['paper_count'],
                'match_type': 'fuzzy',
                'confidence': ocr_correction['confidence'],
                'alternatives': [],
                'original': original
            }
        
        # No match found
        return {
            'matched': False,
            'journal_name': None,
            'paper_count': None,
            'match_type': 'none',
            'confidence': 0,
            'alternatives': [],
            'original': original
        }
    
    def get_journal_info(self, journal_name: str) -> Optional[Dict]:
        """
        Get information about a journal from Zotero collection.
        
        Args:
            journal_name: Journal name to look up
            
        Returns:
            Dict with journal info or None if not found
        """
        journal_lower = journal_name.lower().strip()
        
        # Check Zotero journals
        for journal in self.zotero_journals:
            if journal['normalized'] == journal_lower or journal['name'].lower() == journal_lower:
                return journal
        
        return None
    
    def rebuild_cache(self):
        """Force rebuild of journal cache from database (blocking)."""
        print("🔄 Rebuilding journal cache...")
        self._extract_from_database()
        self._save_cache()
        print("✅ Cache rebuilt successfully")


if __name__ == "__main__":
    # Test the validator
    print("Testing JournalValidator")
    print("=" * 80)
    
    try:
        validator = JournalValidator()
        
        print(f"\nLoaded {len(validator.zotero_journals)} journals from Zotero")
        
        # Test cache age
        age = validator.cache_age_hours()
        if age:
            print(f"Cache age: {age:.2f} hours")
            print(f"Needs refresh (24h): {validator.needs_refresh()}")
        
        # Test validation
        print("\n" + "=" * 80)
        print("TEST 1: Validate known journals")
        print("=" * 80)
        
        if validator.zotero_journals:
            # Test with first few journals from collection
            test_journals = [journal['name'] for journal in validator.zotero_journals[:3]]
        else:
            test_journals = ["Journal of Political Science", "Nature", "Science"]
        
        for journal_name in test_journals:
            result = validator.validate_journal(journal_name)
            if result['matched']:
                print(f"\n✅ '{journal_name}' → '{result['journal_name']}'")
                print(f"   Match type: {result['match_type']}, Confidence: {result['confidence']}%")
                print(f"   Papers in Zotero: {result['paper_count']}")
            else:
                print(f"\n❌ '{journal_name}' → No match found")
        
        # Test OCR correction
        print("\n" + "=" * 80)
        print("TEST 2: OCR error correction")
        print("=" * 80)
        
        if validator.zotero_journals:
            # Create OCR error version of first journal
            original = validator.zotero_journals[0]['name']
            # Create a typo (replace 'r' with 'n')
            ocr_version = original.replace('r', 'n', 1) if 'r' in original else original.replace('o', '0', 1)
            
            test_ocr_names = [ocr_version]
        else:
            test_ocr_names = [
                "Joumal of Political Science",  # Should correct to "Journal"
                "Natuve",  # Should correct to "Nature"
            ]
        
        for name in test_ocr_names:
            correction = validator.suggest_ocr_correction(name)
            if correction:
                print(f"\n'{name}' → '{correction['corrected_name']}'")
                print(f"  Confidence: {correction['confidence']}%")
                print(f"  Distance: {correction['distance']}")
                print(f"  Journal has {correction['paper_count']} papers in Zotero")
            else:
                print(f"\n'{name}' → No correction found")
        
        # Test case insensitivity and whitespace
        print("\n" + "=" * 80)
        print("TEST 3: Case insensitivity and whitespace")
        print("=" * 80)
        
        if validator.zotero_journals:
            test_variations = [
                validator.zotero_journals[0]['name'].upper(),
                validator.zotero_journals[0]['name'].lower(),
                f"  {validator.zotero_journals[0]['name']}  ",  # Extra whitespace
            ]
        else:
            test_variations = ["JOURNAL OF POLITICAL SCIENCE", "journal of political science", "  Journal of Political Science  "]
        
        for variation in test_variations:
            result = validator.validate_journal(variation)
            if result['matched']:
                print(f"  '{variation}' → '{result['journal_name']}' ({result['match_type']})")
            else:
                print(f"  '{variation}' → No match")
        
        print("\n" + "=" * 80)
        print("✅ All tests completed")
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

