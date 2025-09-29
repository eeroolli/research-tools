#!/usr/bin/env python3
"""
Interactive ISBN Lookup and Zotero Integration Script

This script provides an interactive command-line interface for:
1. Manual ISBN input and lookup using country-specific libraries
2. Zotero library search and item management
3. Metadata enhancement and tag editing
4. Smart library selection based on ISBN prefixes

Uses the enhanced DetailedISBNLookupService with multiple national libraries
and comprehensive Zotero integration capabilities.
"""

import sys
import requests
import json
import time
import configparser
import re
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
from difflib import SequenceMatcher

# Add project root to path for imports
project_root = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(project_root))

from shared_tools.utils.isbn_matcher import ISBNMatcher
from process_books.scripts.enhanced_isbn_lookup_detailed import DetailedISBNLookupService

@dataclass
class SearchResult:
    """Result of Zotero search"""
    item_key: str
    title: str
    authors: List[str]
    year: str
    isbn: str
    similarity_score: float = 0.0

class InteractiveISBNLookup:
    """Interactive ISBN lookup with enhanced Zotero integration"""
    
    def __init__(self, 
                 config_file: str = "/mnt/f/prog/research-tools/config.personal.conf",
                 zotero_config_file: str = "/mnt/f/prog/research-tools/config.personal.conf"):
        
        self.config_file = config_file
        self.zotero_config_file = zotero_config_file
        
        # Load configuration
        self.load_config()
        
        # Initialize enhanced lookup service
        self.isbn_lookup = DetailedISBNLookupService()
        
        # Initialize Zotero connection
        self.api_key, self.library_id, self.library_type = self.load_zotero_config()
        
        if not self.api_key or not self.library_id:
            raise ValueError("Missing Zotero API credentials in config file")
        
        # Zotero API setup
        self.base_url = f"https://api.zotero.org/users/{self.library_id}"
        self.headers = {
            'Zotero-API-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        
        # File paths
        self.decisions_file = str(self.data_dir / "interactive_isbn_decisions.json")
        
        print(f"Interactive ISBN Lookup initialized")
        print(f"Library: {self.library_type}/{self.library_id}")
        print(f"Enhanced lookup service with country-specific libraries ready")

    def load_config(self):
        """Load main configuration from config file"""
        config = configparser.ConfigParser()
        config.read(self.config_file)
        
        # Get data directory
        self.data_dir = Path(config.get('PATHS', 'data_folder', fallback='/mnt/f/prog/research-tools/data'))
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # API settings
        self.api_delay = config.getfloat('PROCESSING', 'api_delay', fallback=1.0)

    def load_zotero_config(self) -> Tuple[str, str, str]:
        """Load Zotero configuration from config file"""
        config_path = Path(self.zotero_config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Zotero config file not found: {self.zotero_config_file}")
        
        try:
            config = configparser.ConfigParser()
            config.read(self.zotero_config_file)
            
            api_key = config.get('zotero', 'zotero_api_key', fallback='').strip()
            library_id = config.get('zotero', 'zotero_library_id', fallback='').strip()
            library_type = config.get('zotero', 'zotero_library_type', fallback='user').strip()
            
            if not api_key or not library_id:
                print(f"❌ Missing credentials in {self.zotero_config_file}")
                
            return api_key, library_id, library_type
            
        except Exception as e:
            print(f"❌ Error reading Zotero config file: {e}")
            return '', '', 'user'

    def test_api_connection(self) -> bool:
        """Test if Zotero API credentials work"""
        try:
            test_url = f"{self.base_url}/items"
            params = {'limit': 1}
            
            print(f"🔍 Testing Zotero library access...")
            
            response = requests.get(test_url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                items = response.json()
                print(f"✅ Zotero API connection successful")
                return True
            else:
                print(f"❌ Zotero API connection failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ Zotero API connection error: {e}")
            return False

    def normalize_isbn(self, isbn: str) -> str:
        """Normalize ISBN to standard format for comparison"""
        return ISBNMatcher.normalize_isbn(isbn)

    def extract_clean_isbn(self, isbn_text: str) -> str:
        """Extract clean ISBN from text that might contain additional info"""
        return ISBNMatcher.extract_clean_isbn(isbn_text)

    def search_zotero_by_isbn(self, isbn: str) -> Optional[Dict]:
        """Search for existing item by ISBN in Zotero library"""
        try:
            clean_search_isbn = self.normalize_isbn(isbn)
            print(f"  🔍 Searching Zotero for ISBN: {isbn}")
            print(f"  ⏳ Searching...", end="", flush=True)
            
            response = requests.get(f"{self.base_url}/items", 
                                  headers=self.headers,
                                  params={
                                      'q': isbn,
                                      'qmode': 'everything',
                                      'format': 'json',
                                      'limit': 50  # Limit results for speed
                                  },
                                  timeout=15)  # 15s timeout for reliability
            
            print(" ✅")
            
            if response.status_code == 200:
                items = response.json()
                
                for item in items:
                    item_isbn = item['data'].get('ISBN', '')
                    if item_isbn:
                        clean_item_isbn = self.extract_clean_isbn(item_isbn)
                        if clean_item_isbn:
                            normalized_item_isbn = self.normalize_isbn(clean_item_isbn)
                            
                            if normalized_item_isbn == clean_search_isbn:
                                print(f"  ✅ Found existing item")
                                return item
                            
                            # Try ISBN-10/ISBN-13 conversion matching
                            if self._convert_and_match(clean_search_isbn, clean_item_isbn):
                                print(f"  ✅ Found existing item")
                                return item
            
            print(f"  ❌ No such ISBN found")
            return None
            
        except requests.exceptions.Timeout:
            print(" ❌ Timeout")
            return None
        except Exception as e:
            if "timeout" in str(e).lower() or "read timeout" in str(e).lower():
                print(" ❌ Timeout")
            else:
                print(f" ❌ Error: {e}")
            return None

    def _convert_and_match(self, isbn1: str, isbn2: str) -> bool:
        """Enhanced ISBN matching using substring approach"""
        return ISBNMatcher.match_isbn(isbn1, isbn2)


    def search_zotero_by_metadata(self, book_data: Dict) -> List[SearchResult]:
        """Search Zotero by author+title or title+year combinations with faster, targeted searches"""
        results = []
        
        title = book_data.get('title', '')
        creators = book_data.get('creators', [])
        date = book_data.get('date', '')
        
        if not title:
            return results
        
        # Extract year from date
        year = ''
        if date:
            year_match = re.search(r'\d{4}', date)
            if year_match:
                year = year_match.group(0)
        
        # Get author names
        authors = []
        for creator in creators:
            if creator.get('creatorType') == 'author':
                first_name = creator.get('firstName', '')
                last_name = creator.get('lastName', '')
                full_name = f"{first_name} {last_name}".strip()
                if full_name:
                    authors.append(full_name)
        
        print(f"  🔍 Searching Zotero by metadata:")
        print(f"    Title: {title}")
        print(f"    Authors: {', '.join(authors)}")
        print(f"    Year: {year}")
        
        # Optimized search strategies - fewer, more targeted queries
        search_queries = []
        
        # Strategy 1: Primary author + Title (most likely to match)
        if authors:
            primary_author = authors[0]  # Use first author only for speed
            search_queries.append(f"{primary_author} {title}")
        
        # Strategy 2: Title + Year (if we have year)
        if year:
            search_queries.append(f"{title} {year}")
        
        # Strategy 3: Title only (fallback)
        search_queries.append(title)
        
        print(f"  📡 Executing {len(search_queries)} targeted searches...")
        
        for i, query in enumerate(search_queries, 1):
            print(f"    {i}/{len(search_queries)}: Searching for '{query[:50]}...'", end="", flush=True)
            
            try:
                response = requests.get(f"{self.base_url}/items", 
                                      headers=self.headers,
                                      params={
                                          'q': query,
                                          'qmode': 'everything',
                                          'format': 'json',
                                          'limit': 20  # Limit results for speed
                                      },
                                      timeout=15)  # 15s timeout for reliability
                
                print(" ✅")
                
                if response.status_code == 200:
                    items = response.json()
                    
                    for item in items:
                        item_data = item['data']
                        item_title = item_data.get('title', '')
                        
                        # Calculate similarity score
                        similarity = SequenceMatcher(None, title.lower(), item_title.lower()).ratio()
                        
                        if similarity > 0.8:  # Increased threshold for better matches
                            # Extract item metadata
                            item_creators = item_data.get('creators', [])
                            item_authors = []
                            for creator in item_creators:
                                if creator.get('creatorType') == 'author':
                                    first_name = creator.get('firstName', '')
                                    last_name = creator.get('lastName', '')
                                    full_name = f"{first_name} {last_name}".strip()
                                    if full_name:
                                        item_authors.append(full_name)
                            
                            item_year = item_data.get('date', '')
                            item_isbn = item_data.get('ISBN', '')
                            
                            result = SearchResult(
                                item_key=item['key'],
                                title=item_title,
                                authors=item_authors,
                                year=item_year,
                                isbn=item_isbn,
                                similarity_score=similarity
                            )
                            results.append(result)
                            print(f"      ✅ Match found: {similarity:.1%} similarity")
                            
                            # Stop after finding a few good matches
                            if len(results) >= 3:
                                print(f"      Stopping search after {len(results)} good matches")
                                break
                    
                    # If we found good matches, don't continue with more searches
                    if results and max(r.similarity_score for r in results) > 0.9:
                        print(f"      High-quality match found, skipping remaining searches")
                        break
                            
            except requests.exceptions.Timeout:
                print(" ❌ Timeout")
                continue
            except Exception as e:
                if "timeout" in str(e).lower() or "read timeout" in str(e).lower():
                    print(" ❌ Timeout")
                else:
                    print(" ❌ Error")
                continue
        
        # Sort by similarity score
        results.sort(key=lambda x: x.similarity_score, reverse=True)
        
        if not results:
            print(f"  ❌ No such title found")
        else:
            print(f"  📊 Found {len(results)} potential matches")
        
        return results

    def enhance_metadata(self, item_data: Dict, online_data: Dict) -> Dict:
        """Enhance Zotero item metadata with online data"""
        enhanced = item_data.copy()
        enhancements_made = []
        
        # Define fields to enhance (with their display names)
        enhancement_fields = {
            'abstractNote': 'abstract',
            'language': 'language',
            'numPages': 'page count',
            'publisher': 'publisher',
            'place': 'publication place',
            'edition': 'edition',
            'extra': 'additional notes'
        }
        
        # Check for missing or empty fields
        for field, display_name in enhancement_fields.items():
            current_value = item_data.get(field, '')
            online_value = online_data.get(field, '')
            
            # Only enhance if current field is missing/empty and online has data
            if (not current_value or current_value.strip() == '') and online_value and online_value.strip():
                enhanced[field] = online_value
                enhancements_made.append(display_name)
        
        # Special handling for tags
        online_tags = online_data.get('tags', [])
        if online_tags:
            current_tags = [tag['tag'] for tag in item_data.get('tags', [])]
            
            # Add new tags that aren't already present
            new_tags = []
            for tag in online_tags:
                tag_name = tag.get('tag', '') if isinstance(tag, dict) else str(tag)
                if tag_name and tag_name not in current_tags:
                    new_tags.append(tag_name)
            
            if new_tags:
                # Add new tags to existing ones
                existing_tags = item_data.get('tags', [])
                for tag_name in new_tags:
                    existing_tags.append({'tag': tag_name})
                enhanced['tags'] = existing_tags
                enhancements_made.append(f"{len(new_tags)} tags")
        
        # Report enhancements
        if enhancements_made:
            print(f"  📝 Enhanced metadata with: {', '.join(enhancements_made)}")
        else:
            print(f"  ℹ️  No metadata enhancements needed")
        
        return enhanced

    def update_zotero_item(self, item_key: str, enhanced_data: Dict) -> bool:
        """Update Zotero item with enhanced metadata"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            
            if response.status_code != 200:
                print(f"  ❌ Failed to get item: {response.status_code}")
                return False
            
            current_item = response.json()
            current_data = current_item['data']
            
            # Merge enhanced data with current data
            for key, value in enhanced_data.items():
                if key != 'key' and value:  # Don't overwrite the key
                    current_data[key] = value
            
            # Update item
            update_response = requests.put(f"{self.base_url}/items/{item_key}",
                                         headers=self.headers,
                                         json=current_data)
            
            if update_response.status_code == 204:
                print(f"  ✅ Successfully updated Zotero item")
                return True
            else:
                print(f"  ❌ Failed to update item: {update_response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Update error: {e}")
            return False

    def add_item_to_zotero(self, item_template: Dict, user_tags: List[str]) -> Optional[str]:
        """Add new item to Zotero library"""
        try:
            # Combine user tags with existing subject tags
            existing_tags = item_template.get('tags', [])
            combined_tags = existing_tags.copy()
            
            # Add user decision tags
            for tag in user_tags:
                combined_tags.append({'tag': tag})
            
            item_template['tags'] = combined_tags
            
            # Create item in library
            response = requests.post(f"{self.base_url}/items",
                                   headers=self.headers,
                                   json=[item_template])
            
            if response.status_code == 200:
                result = response.json()
                item_key = result['successful']['0']['key']
                print(f"  ✅ Added to Zotero library with key: {item_key}")
                
                # Show what was added
                metadata_tags = len(existing_tags)
                personal_tags = len(user_tags)
                print(f"      🏷️  Added {personal_tags} personal tags and {metadata_tags} metadata tags")
                
                return item_key
            else:
                print(f"  ❌ Failed to add item: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Add item error: {e}")
            return None

    def update_item_tags(self, item_key: str, add_tags: List[str], remove_tags: List[str] = None) -> bool:
        """Update tags on existing Zotero item"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            
            if response.status_code != 200:
                print(f"  ❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_tags = item_data['data'].get('tags', [])
            
            # Remove specified tags
            if remove_tags:
                current_tags = [tag for tag in current_tags if tag['tag'] not in remove_tags]
            
            # Add new tags (avoid duplicates)
            existing_tag_names = [tag['tag'] for tag in current_tags]
            for tag_name in add_tags:
                if tag_name not in existing_tag_names:
                    current_tags.append({'tag': tag_name})
            
            # Update item
            update_data = {
                'key': item_key,
                'version': item_data['version'],
                'tags': current_tags
            }
            
            update_response = requests.put(f"{self.base_url}/items/{item_key}",
                                         headers=self.headers,
                                         json=update_data)
            
            if update_response.status_code == 204:
                # Count the changes
                added_count = len(add_tags) if add_tags else 0
                removed_count = len(remove_tags) if remove_tags else 0
                
                if added_count > 0 and removed_count > 0:
                    print(f"  ✅ Updated tags: added {added_count}, removed {removed_count}")
                elif added_count > 0:
                    print(f"  ✅ Updated tags: added {added_count}")
                elif removed_count > 0:
                    print(f"  ✅ Updated tags: removed {removed_count}")
                else:
                    print(f"  ✅ Updated tags successfully")
                return True
            else:
                print(f"  ❌ Failed to update tags: {update_response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Update tags error: {e}")
            return False

    def interactive_tag_management(self, item_key: str) -> bool:
        """Interactive tag management for Zotero item"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            
            if response.status_code != 200:
                print(f"  ❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_tags = [tag['tag'] for tag in item_data['data'].get('tags', [])]
            
            print(f"\n📝 Current tags: {', '.join(current_tags) if current_tags else 'None'}")
            
            while True:
                print(f"\nTag management options:")
                print(f"1. Add tags")
                print(f"2. Remove tags")
                print(f"3. Show all tags")
                print(f"4. Done")
                
                choice = input("Enter choice (1-4): ").strip()
                
                if choice == '1':
                    # Add tags
                    new_tags_input = input("Enter tags to add (comma-separated): ").strip()
                    if new_tags_input:
                        new_tags = [tag.strip() for tag in new_tags_input.split(',') if tag.strip()]
                        success = self.update_item_tags(item_key, new_tags)
                        if success:
                            current_tags.extend(new_tags)
                
                elif choice == '2':
                    # Remove tags
                    if not current_tags:
                        print("  No tags to remove")
                        continue
                    
                    print(f"  Current tags: {', '.join(current_tags)}")
                    remove_tags_input = input("Enter tags to remove (comma-separated): ").strip()
                    if remove_tags_input:
                        remove_tags = [tag.strip() for tag in remove_tags_input.split(',') if tag.strip()]
                        success = self.update_item_tags(item_key, [], remove_tags)
                        if success:
                            current_tags = [tag for tag in current_tags if tag not in remove_tags]
                
                elif choice == '3':
                    # Show all tags
                    print(f"  Current tags: {', '.join(current_tags) if current_tags else 'None'}")
                
                elif choice == '4':
                    # Done
                    break
                
                else:
                    print("  Invalid choice. Please enter 1-4.")
            
            return True
            
        except Exception as e:
            print(f"  ❌ Tag management error: {e}")
            return False


    def search_and_manage_zotero_item(self, book_data: Dict) -> bool:
        """Search for existing item in Zotero and manage it"""
        isbn = book_data.get('ISBN', '')
        title = book_data.get('title', '')
        
        print(f"\n🔍 Searching Zotero library...")
        
        # Strategy 1: Search by ISBN
        existing_item = None
        if isbn:
            existing_item = self.search_zotero_by_isbn(isbn)
        
        # Strategy 2: Search by metadata if no ISBN match
        metadata_results = []
        if not existing_item:
            metadata_results = self.search_zotero_by_metadata(book_data)
        
        if existing_item:
            # Found exact ISBN match
            print(f"\n✅ Found existing item in Zotero:")
            print(f"  Title: {existing_item['data'].get('title', 'Unknown')}")
            print(f"  Key: {existing_item['key']}")
            
            # Show current tags
            current_tags = [tag['tag'] for tag in existing_item['data'].get('tags', [])]
            print(f"  Current tags: {', '.join(current_tags) if current_tags else 'None'}")
            
            # Ask user what to do
            print(f"\nOptions:")
            print(f"1. Enhance metadata and tags")
            print(f"2. Edit tags only")
            print(f"3. Skip (no changes)")
            
            while True:
                choice = input("Enter choice (1-3): ").strip()
                if choice in ['1', '2', '3']:
                    break
                print("Please enter 1, 2, or 3")
            
            if choice == '1':
                # Enhance metadata
                enhanced_data = self.enhance_metadata(existing_item['data'], book_data)
                success = self.update_zotero_item(existing_item['key'], enhanced_data)
                if success:
                    # Also manage tags interactively
                    self.interactive_tag_management(existing_item['key'])
                return success
            
            elif choice == '2':
                # Edit tags only
                return self.interactive_tag_management(existing_item['key'])
            
            else:
                # Skip
                print("  ⏭️  No changes made")
                return True
        
        elif metadata_results:
            # Found potential matches by metadata
            print(f"\n📋 Found {len(metadata_results)} potential matches:")
            
            for i, result in enumerate(metadata_results[:5], 1):  # Show top 5
                print(f"  {i}. {result.title} ({result.similarity_score:.1%} match)")
                if result.authors:
                    print(f"     Authors: {', '.join(result.authors)}")
                if result.year:
                    print(f"     Year: {result.year}")
                if result.isbn:
                    print(f"     ISBN: {result.isbn}")
                print()
            
            print(f"Options:")
            print(f"0. None of these match - add new item")
            
            for i, result in enumerate(metadata_results[:5], 1):
                print(f"{i}. This is the same book (update existing)")
            
            while True:
                try:
                    choice = int(input("Enter choice (0-5): ").strip())
                    if 0 <= choice <= min(5, len(metadata_results)):
                        break
                except ValueError:
                    pass
                print("Please enter a number between 0 and 5")
            
            if choice == 0:
                # Add new item
                return self.add_new_item_to_zotero(book_data)
            else:
                # Update existing item
                selected_result = metadata_results[choice - 1]
                
                # Get full item data
                response = requests.get(f"{self.base_url}/items/{selected_result.item_key}", headers=self.headers)
                if response.status_code == 200:
                    existing_item_data = response.json()['data']
                    
                    # Enhance metadata
                    enhanced_data = self.enhance_metadata(existing_item_data, book_data)
                    success = self.update_zotero_item(selected_result.item_key, enhanced_data)
                    if success:
                        # Also manage tags interactively
                        self.interactive_tag_management(selected_result.item_key)
                    return success
                else:
                    print(f"  ❌ Failed to get item data")
                    return False
        
        else:
            # No existing item found - add new one
            print(f"\n❌ No existing item found in Zotero")
            return self.add_new_item_to_zotero(book_data)

    def add_new_item_to_zotero(self, book_data: Dict) -> bool:
        """Add new item to Zotero library"""
        print(f"\n📚 Adding new item to Zotero library...")
        
        # Get user decision
        print(f"Add this book to your Zotero library?")
        print(f"1. Yes - Keep it (add with tag: 'Eero har')")
        print(f"2. Yes - Give it away (add with tags: 'Eero hadde', 'gitt bort')")
        print(f"3. No - Don't add to Zotero")
        
        while True:
            choice = input("Enter choice (1-3): ").strip()
            if choice in ['1', '2', '3']:
                break
            print("Please enter 1, 2, or 3")
        
        if choice == '3':
            print("  ⏭️  Skipped - not added to Zotero")
            return True
        
        # Determine base tags
        keep = (choice == '1')
        base_tags = ['Eero har'] if keep else ['Eero hadde', 'gitt bort']
        
        # Get additional tags from user
        additional_tags = self.get_additional_tags_from_user(book_data)
        
        # Combine all tags
        all_tags = base_tags + additional_tags
        
        # Add item to Zotero
        item_key = self.add_item_to_zotero(book_data, all_tags)
        
        if item_key:
            print(f"  ✅ Successfully added to Zotero")
            return True
        else:
            print(f"  ❌ Failed to add to Zotero")
            return False

    def get_additional_tags_from_user(self, book_data: Dict) -> List[str]:
        """Get additional tags from user"""
        print(f"\n📝 Additional tags:")
        
        # Show metadata tags
        metadata_tags = book_data.get('tags', [])
        if metadata_tags:
            tag_names = [tag.get('tag', '') for tag in metadata_tags]
            print(f"  📚 Metadata tags: {', '.join(tag_names)}")
            print(f"  💡 Tip: No need to add tags that are already in metadata")
        
        print(f"  Enter additional tags (comma-separated, or press Enter for none):")
        user_input = input("Tags: ").strip()
        
        if not user_input:
            return []
        
        # Parse comma-separated tags
        tags = [tag.strip() for tag in user_input.split(',') if tag.strip()]
        
        # Filter out tags that are already in metadata
        if metadata_tags:
            metadata_tag_names = [tag.get('tag', '').lower() for tag in metadata_tags]
            filtered_tags = []
            for tag in tags:
                if tag.lower() not in metadata_tag_names:
                    filtered_tags.append(tag)
                else:
                    print(f"  ⚠️  Skipped '{tag}' (already in metadata)")
            
            return filtered_tags
        else:
            return tags

    def main_menu(self):
        """Main interactive menu with improved UX flow"""
        print(f"\n" + "="*60)
        print(f"📚 INTERACTIVE ISBN LOOKUP AND ZOTERO INTEGRATION")
        print("="*60)
        print(f"")
        print(f"🎯 What this script does:")
        print(f"   • Looks up book information using country-specific libraries")
        print(f"   • Searches your Zotero library to avoid duplicates")
        print(f"   • Adds new books to Zotero with enhanced metadata")
        print(f"   • Manages tags and enhances existing items")
        print(f"")
        print(f"🔧 Features:")
        print(f"   • Smart library selection based on ISBN prefixes")
        print(f"   • Comprehensive Zotero search and tag management")
        print(f"   • Metadata enhancement from multiple sources")
        print("="*60)
        
        # Check Zotero connection first
        print(f"\n🔍 Checking Zotero connection...")
        if not self.test_api_connection():
            print(f"\n❌ ZOTERO SETUP REQUIRED")
            print(f"="*40)
            print(f"This script requires Zotero API access to function.")
            print(f"")
            print(f"📋 Please ensure you have:")
            print(f"   1. Zotero API key")
            print(f"   2. Library ID")
            print(f"   3. Config file: {self.zotero_config_file}")
            print(f"")
            print(f"💡 See the documentation for setup instructions.")
            print(f"")
            input("Press Enter to exit...")
            return
        
        print(f"✅ Zotero connection successful!")
        
        # Main workflow loop
        while True:
            print(f"\n" + "="*60)
            print(f"📖 ISBN LOOKUP WORKFLOW")
            print("="*60)
            
            # Step 1: Get ISBN
            book_data = self.get_isbn_from_user()
            if not book_data:
                continue  # User wants to exit
            
            # Step 2: Display book information
            self.display_book_information(book_data)
            
            # Step 3: Ask about adding to Zotero
            add_to_zotero = self.ask_about_adding_to_zotero()
            
            if add_to_zotero:
                # Step 4: Process in Zotero
                success = self.search_and_manage_zotero_item(book_data)
                if success:
                    print(f"✅ Successfully processed book in Zotero")
                else:
                    print(f"❌ Failed to process book in Zotero")
            else:
                print(f"👋 Book information displayed - not added to Zotero")
            
            # Step 5: Ask if user wants to continue
            if not self.ask_to_continue():
                break
            
            # Small delay to be nice to APIs
            time.sleep(self.api_delay)
        
        print(f"\n👋 Thank you for using the ISBN Lookup tool!")

    def get_isbn_from_user(self) -> Optional[Dict]:
        """Get ISBN from user and lookup book information"""
        print(f"\n📝 Step 1: Enter ISBN")
        print("-" * 30)
        
        while True:
            isbn_input = input("Enter ISBN (or 'quit' to exit): ").strip()
            
            if isbn_input.lower() == 'quit':
                return None
            
            if not isbn_input:
                print("Please enter a valid ISBN")
                continue
            
            # Clean the ISBN
            clean_isbn = self.normalize_isbn(isbn_input)
            
            if len(clean_isbn) not in [10, 13]:
                print(f"❌ Invalid ISBN format. Please enter a 10 or 13 digit ISBN.")
                continue
            
            print(f"🔍 Looking up ISBN: {clean_isbn}")
            print(f"📡 Searching online libraries...")
            
            # Lookup book information using enhanced service
            book_data = self.isbn_lookup.lookup_isbn(clean_isbn)
            
            if not book_data or not book_data.get('title'):
                print(f"❌ No book information found for ISBN {clean_isbn}")
                print(f"Please check the ISBN or try again.")
                continue
            
            return book_data

    def display_book_information(self, book_data: Dict):
        """Display comprehensive book information"""
        print(f"\n📚 Step 2: Book Information Found")
        print("-" * 40)
        print(f"📖 Title: {book_data.get('title', 'Unknown')}")
        
        creators = book_data.get('creators', [])
        if creators:
            authors = []
            for creator in creators:
                if creator.get('creatorType') == 'author':
                    first_name = creator.get('firstName', '')
                    last_name = creator.get('lastName', '')
                    full_name = f"{first_name} {last_name}".strip()
                    if full_name:
                        authors.append(full_name)
            print(f"👤 Authors: {', '.join(authors)}")
        
        if book_data.get('publisher'):
            print(f"🏢 Publisher: {book_data['publisher']}")
        if book_data.get('date'):
            print(f"📅 Date: {book_data['date']}")
        if book_data.get('numPages'):
            print(f"📄 Pages: {book_data['numPages']}")
        if book_data.get('language'):
            print(f"🌐 Language: {book_data['language']}")
        if book_data.get('place'):
            print(f"📍 Place: {book_data['place']}")
        if book_data.get('edition'):
            print(f"📚 Edition: {book_data['edition']}")
        
        if book_data.get('abstractNote'):
            abstract = book_data['abstractNote']
            if len(abstract) > 200:
                abstract = abstract[:200] + "..."
            print(f"📝 Abstract: {abstract}")
        
        tags = book_data.get('tags', [])
        if tags:
            tag_names = [tag.get('tag', '') for tag in tags[:5]]  # Show first 5 tags
            print(f"🏷️  Tags: {', '.join(tag_names)}")

    def ask_about_adding_to_zotero(self) -> bool:
        """Ask user if they want to add the book to Zotero"""
        print(f"\n📚 Step 3: Add to Zotero?")
        print("-" * 30)
        print(f"Would you like to add this book to your Zotero library?")
        print(f"1. Yes - Add item or new metadata to Zotero")
        print(f"2. No - Just view information")
        
        while True:
            choice = input("Enter choice (1-2): ").strip()
            if choice == '1':
                return True
            elif choice == '2':
                return False
            else:
                print("Please enter 1 or 2")

    def ask_to_continue(self) -> bool:
        """Ask user if they want to process another ISBN"""
        print(f"\n🔄 Continue?")
        print("-" * 20)
        print(f"Would you like to lookup another ISBN?")
        print(f"1. Yes - Lookup another ISBN")
        print(f"2. No - Exit")
        
        while True:
            choice = input("Enter choice (1-2): ").strip()
            if choice == '1':
                return True
            elif choice == '2':
                return False
            else:
                print("Please enter 1 or 2")

def main():
    """Main function"""
    try:
        processor = InteractiveISBNLookup()
        processor.main_menu()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
