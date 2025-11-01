# scripts/zotero_api_book_processor_enhanced.py

import cv2
from pyzbar import pyzbar
import pytesseract
import requests
import json
import time
import configparser
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass
from typing import Optional, List, Dict, Tuple
import re
import sys

# Add project root to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.utils.isbn_matcher import ISBNMatcher

@dataclass
class BookDecision:
    isbn: str
    filename: str
    keep: bool
    zotero_item_key: Optional[str] = None
    action_taken: Optional[str] = None

class DetailedISBNLookupService:
    """Enhanced ISBN lookup with detailed metadata"""
    
    def __init__(self):
        self.services = [
            self.lookup_openlibrary,
            self.lookup_google_books,
            self.lookup_norwegian_library,
        ]
        
        # Non-ISBN search services (title + editor/book title lookups)
        self.metadata_services = [
            self.lookup_google_books_by_title_editor,
            self.lookup_openlibrary_by_title_editor,
        ]
    
    def lookup_openlibrary(self, isbn: str) -> Optional[Dict]:
        """Lookup using OpenLibrary API with detailed info"""
        try:
            url = "https://openlibrary.org/api/books"
            params = {
                'bibkeys': f'ISBN:{isbn}',
                'format': 'json',
                'jscmd': 'data'
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                book_key = f'ISBN:{isbn}'
                
                if book_key in data:
                    book_info = data[book_key]
                    
                    # Convert authors
                    authors = book_info.get('authors', [])
                    creators = []
                    
                    for author in authors:
                        name_parts = author['name'].split()
                        if len(name_parts) >= 2:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': ' '.join(name_parts[:-1]),
                                'lastName': name_parts[-1]
                            })
                        else:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': '',
                                'lastName': author['name']
                            })
                    
                    publishers = book_info.get('publishers', [])
                    publisher = publishers[0]['name'] if publishers else ''
                    
                    # Extract subjects as tags  
                    subjects = book_info.get('subjects', [])
                    tags = []
                    for subject in subjects[:10]:  # Limit to 10 subjects
                        if isinstance(subject, dict):
                            tags.append({'tag': subject.get('name', '')})
                        else:
                            tags.append({'tag': str(subject)})
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('excerpts', [{}])[0].get('text', '') if book_info.get('excerpts') else '',
                        'publisher': publisher,
                        'date': book_info.get('publish_date', ''),
                        'numPages': str(book_info.get('number_of_pages', '')),
                        'ISBN': isbn,
                        'url': book_info.get('url', ''),
                        'tags': tags,
                        'extra': f"OpenLibrary: {book_info.get('key', '')}" if book_info.get('key') else '',
                        'place': book_info.get('publish_places', [{}])[0].get('name', '') if book_info.get('publish_places') else '',
                        'language': book_info.get('languages', [{}])[0].get('name', '') if book_info.get('languages') else '',
                        'edition': book_info.get('edition_name', ''),
                    }
                    
        except Exception as e:
            pass  # Silent fail, try next service
        
        return None
    
    # ------------------------------
    # Title + Editor lookups (for book chapters without ISBN)
    # ------------------------------
    def lookup_google_books_by_title_editor(self, book_title: str, editor: str = None) -> Optional[Dict]:
        """Lookup book metadata by book title and optional editor via Google Books.
        
        Args:
            book_title: Book title to search for
            editor: Optional editor name (can be empty for books without editors)
            
        Returns:
            Normalized dict similar to ISBN lookups (itemType 'book', creators, publisher, date, ISBN, tags).
        """
        try:
            url = "https://www.googleapis.com/books/v1/volumes"
            # Google Books doesn't distinguish editor from author, so use inauthor if editor provided
            q_parts = []
            if book_title:
                q_parts.append(f"intitle:{book_title}")
            if editor:
                # Editor is often just treated as an author in search
                q_parts.append(f"inauthor:{editor}")
            params = {
                'q': ' '.join(q_parts) if q_parts else book_title,
                'maxResults': 5,
                'printType': 'books'
            }
            response = requests.get(url, params=params, timeout=10)
            if response.status_code != 200:
                return None
            data = response.json()
            items = data.get('items', [])
            if not items:
                return None
            # Pick best match (first)
            info = items[0].get('volumeInfo', {})
            # Authors in Google Books are typically authors; we will set editors separately if we detect editor in query
            creators = []
            for name in info.get('authors', []) or []:
                parts = name.split()
                if len(parts) >= 2:
                    creators.append({'creatorType': 'author', 'firstName': ' '.join(parts[:-1]), 'lastName': parts[-1]})
                else:
                    creators.append({'creatorType': 'author', 'firstName': '', 'lastName': name})
            # Add editor as editor creator if provided
            if editor:
                parts = editor.split()
                if len(parts) >= 2:
                    creators.append({'creatorType': 'editor', 'firstName': ' '.join(parts[:-1]), 'lastName': parts[-1]})
                else:
                    creators.append({'creatorType': 'editor', 'firstName': '', 'lastName': editor})
            # Prefer ISBN_13
            isbn = ''
            for iden in info.get('industryIdentifiers', []) or []:
                if iden.get('type') == 'ISBN_13':
                    isbn = iden.get('identifier', '')
                    break
                if not isbn and iden.get('type') == 'ISBN_10':
                    isbn = iden.get('identifier', '')
            tags = [{'tag': c} for c in (info.get('categories') or [])[:10]]
            return {
                'itemType': 'book',
                'title': info.get('title', ''),
                'creators': creators,
                'publisher': info.get('publisher', ''),
                'date': info.get('publishedDate', ''),
                'ISBN': isbn,
                'language': info.get('language', ''),
                'tags': tags,
                'extra': f"Google Books ID: {items[0].get('id', '')}"
            }
        except Exception:
            return None
    
    def lookup_openlibrary_by_title_editor(self, book_title: str, editor: str = None) -> Optional[Dict]:
        """Lookup book metadata by title via OpenLibrary (optional editor for filtering).
        
        Args:
            book_title: Book title to search for
            editor: Optional editor name (can be empty for books without editors)
        """
        try:
            # OpenLibrary search API
            url = "https://openlibrary.org/search.json"
            params = {
                'title': book_title,
                'limit': 5
            }
            # Use editor as author filter if provided (OpenLibrary treats editors as authors in search)
            if editor:
                params['author'] = editor
            resp = requests.get(url, params=params, timeout=10)
            if resp.status_code != 200:
                return None
            data = resp.json()
            docs = data.get('docs', [])
            if not docs:
                return None
            d = docs[0]
            title = d.get('title', '')
            publishers = (d.get('publisher') or [])
            publisher = publishers[0] if publishers else ''
            year = str(d.get('first_publish_year', ''))
            # Try to get ISBN13
            isbn = ''
            for i in (d.get('isbn') or []):
                i_str = str(i)
                if len(i_str) == 13 and i_str.isdigit():
                    isbn = i_str
                    break
                if not isbn and len(i_str) == 10 and i_str.isdigit():
                    isbn = i_str
                    break
            creators = []
            for name in (d.get('author_name') or [])[:5]:
                parts = name.split()
                if len(parts) >= 2:
                    creators.append({'creatorType': 'author', 'firstName': ' '.join(parts[:-1]), 'lastName': parts[-1]})
                else:
                    creators.append({'creatorType': 'author', 'firstName': '', 'lastName': name})
            if editor:
                parts = editor.split()
                if len(parts) >= 2:
                    creators.append({'creatorType': 'editor', 'firstName': ' '.join(parts[:-1]), 'lastName': parts[-1]})
                else:
                    creators.append({'creatorType': 'editor', 'firstName': '', 'lastName': editor})
            return {
                'itemType': 'book',
                'title': title,
                'creators': creators,
                'publisher': publisher,
                'date': year,
                'ISBN': isbn,
                'tags': [],
                'extra': 'OpenLibrary search'
            }
        except Exception:
            return None
    
    def lookup_by_title_and_editor(self, book_title: str, editor: str = None) -> Optional[Dict]:
        """Try multiple services to find book metadata by title and optional editor.
        
        Args:
            book_title: Book title to search for
            editor: Optional editor name (can be empty for books without editors)
            
        Returns:
            Best matching book metadata dict or None if not found
        """
        if not book_title:
            return None
            
        all_results: List[Dict] = []
        for service in self.metadata_services:
            try:
                r = service(book_title, editor)
                if r and r.get('title'):
                    all_results.append(r)
            except Exception:
                continue
        if not all_results:
            return None
        # Prefer results with ISBN, else first
        best = None
        for r in all_results:
            if r.get('ISBN'):
                best = r
                break
        if not best:
            best = all_results[0]
        return best

    def lookup_google_books(self, isbn: str) -> Optional[Dict]:
        """Lookup using Google Books API with detailed info"""
        try:
            url = "https://www.googleapis.com/books/v1/volumes"
            params = {'q': f'isbn:{isbn}'}
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('totalItems', 0) > 0:
                    book_info = data['items'][0]['volumeInfo']
                    
                    # Convert authors
                    authors = book_info.get('authors', [])
                    creators = []
                    
                    for author in authors:
                        name_parts = author.split()
                        if len(name_parts) >= 2:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': ' '.join(name_parts[:-1]),
                                'lastName': name_parts[-1]
                            })
                        else:
                            creators.append({
                                'creatorType': 'author',
                                'firstName': '',
                                'lastName': author
                            })
                    
                    # Extract categories as tags
                    categories = book_info.get('categories', [])
                    tags = [{'tag': category} for category in categories[:10]]
                    
                    # Get page count
                    page_count = book_info.get('pageCount', '')
                    
                    return {
                        'itemType': 'book',
                        'title': book_info.get('title', ''),
                        'creators': creators,
                        'abstractNote': book_info.get('description', ''),
                        'publisher': book_info.get('publisher', ''),
                        'date': book_info.get('publishedDate', ''),
                        'numPages': str(page_count) if page_count else '',
                        'ISBN': isbn,
                        'language': book_info.get('language', ''),
                        'tags': tags,
                        'extra': f"Google Books ID: {data['items'][0].get('id', '')}"
                    }
                    
        except Exception as e:
            pass  # Silent fail, try next service
        
        return None
    
    def lookup_norwegian_library(self, isbn: str) -> Optional[Dict]:
        """Lookup using Norwegian National Library API"""
        try:
            # Norwegian National Library API
            url = "https://api.nb.no/catalog/v1/items"
            params = {
                'q': f'isbn:{isbn}',
                'size': 1
            }
            
            response = requests.get(url, params=params, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                if data.get('_embedded', {}).get('items'):
                    book_info = data['_embedded']['items'][0]
                    metadata = book_info.get('metadata', {})
                    
                    # Extract creators from metadata
                    creators = []
                    for creator in metadata.get('creators', []):
                        if creator and creator != "Likhetens paradokser":  # Skip non-author entries
                            name_parts = creator.split(', ')
                            if len(name_parts) >= 2:
                                # Handle "LastName, FirstName" format
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': name_parts[1] if len(name_parts) > 1 else '',
                                    'lastName': name_parts[0]
                                })
                            else:
                                # Handle single name
                                creators.append({
                                    'creatorType': 'author',
                                    'firstName': '',
                                    'lastName': creator
                                })
                    
                    # Extract content classes as tags (Norwegian-specific categories)
                    tags = []
                    content_classes = metadata.get('contentClasses', [])
                    for content_class in content_classes:
                        if content_class not in ['legaldeposit', 'jp2', 'bokhylla', 'bokhyllalisens']:
                            tags.append({'tag': content_class})
                    
                    # Add media type as tag
                    media_types = metadata.get('mediaTypes', [])
                    for media_type in media_types:
                        if media_type:
                            tags.append({'tag': media_type})
                    
                    return {
                        'itemType': 'book',
                        'title': metadata.get('title', ''),
                        'creators': creators,
                        'abstractNote': '',  # Norwegian API doesn't provide abstracts
                        'publisher': metadata.get('originInfo', {}).get('publisher', ''),
                        'date': metadata.get('originInfo', {}).get('issued', ''),
                        'numPages': str(metadata.get('pageCount', '')),
                        'ISBN': isbn,
                        'language': metadata.get('languages', [{}])[0].get('code', '') if metadata.get('languages') else '',
                        'tags': tags,
                        'extra': f"Norwegian Library: {book_info.get('id', '')}"
                    }
                    
        except Exception as e:
            pass  # Silent fail, try next service
        
        return None
    
    def score_result(self, result: Dict) -> int:
        """Score a result based on completeness"""
        score = 0
        if result.get('title'): score += 10
        if result.get('creators'): score += 10
        if result.get('publisher'): score += 5
        if result.get('date'): score += 5
        if result.get('abstractNote'): score += 15
        if result.get('tags'): score += 10
        if result.get('numPages'): score += 3
        if result.get('language'): score += 2
        return score
    
    def lookup_isbn(self, isbn: str) -> Optional[Dict]:
        """Try multiple services to find detailed book info and combine tags"""
        all_results = []
        all_tags = []
        
        # Collect results from all services
        for service in self.services:
            try:
                result = service(isbn)
                if result and result.get('title'):
                    all_results.append(result)
                    # Collect tags from this service
                    tags = result.get('tags', [])
                    for tag in tags:
                        if isinstance(tag, dict):
                            tag_name = tag.get('tag', '')
                        else:
                            tag_name = str(tag)
                        if tag_name and tag_name not in [t.get('tag', '') if isinstance(t, dict) else str(t) for t in all_tags]:
                            all_tags.append(tag)
                        
            except Exception as e:
                continue
        
        if not all_results:
            return None
        
        # Find the best result based on score
        best_result = None
        best_score = 0
        
        for result in all_results:
            score = self.score_result(result)
            if score > best_score:
                best_result = result
                best_score = score
        
        # Combine all tags into the best result
        if best_result:
            best_result['tags'] = all_tags
        
        return best_result

class ZoteroAPIBookProcessor:
    def __init__(self, 
                 config_file: str = "/mnt/f/prog/research-tools/config.personal.conf",
                 photo_folder: str = "/mnt/i/FraMobil/Camera/Books"):
        
        self.config_file = config_file
        self.photo_folder = Path(photo_folder)
        
        # Load configuration
        self.api_key, self.library_id, self.library_type = self.load_config()
        
        if not self.api_key or not self.library_id:
            raise ValueError("Missing Zotero API credentials in config file")
        
        # Use proper URL construction
        self.base_url = f"https://api.zotero.org/users/{self.library_id}"
        self.headers = {
            'Zotero-API-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        
        # Initialize enhanced lookup service
        self.isbn_lookup = DetailedISBNLookupService()
        
        # File paths
        self.isbn_log_file = "../data/books/book_processing_log.csv"
        
        # Load enhanced configuration
        self.tag_groups = self.load_tag_groups()
        self.actions = self.load_actions()
        self.menu_options = self.load_menu_options()
        
        # Initialize duplicate detection list
        self.duplicates_found = []
        
        print(f"Enhanced Zotero API Processor initialized")
        print(f"Library: {self.library_type}/{self.library_id}")
        print(f"Config loaded from: {config_file}")
        print(f"Loaded {len(self.tag_groups)} tag groups and {len(self.actions)} actions")

    def load_config(self) -> Tuple[str, str, str]:
        """Load configuration from config file with personal overrides"""
        # Load default config first  
        root_dir = Path(self.config_file).parent.parent
        default_config_path = root_dir / "config.conf"
        personal_config_path = Path(self.config_file)
        
        config = configparser.ConfigParser()
        
        # Load default config if it exists
        if default_config_path.exists():
            config.read(default_config_path)
        
        # Load personal config to override defaults
        if personal_config_path.exists():
            config.read(personal_config_path)
        else:
            raise FileNotFoundError(f"Personal config file not found: {self.config_file}")
        
        try:
            # Try new format first, fall back to legacy
            api_key = config.get('APIS', 'zotero_api_key', fallback='').strip()
            library_id = config.get('APIS', 'zotero_library_id', fallback='').strip()
            library_type = config.get('APIS', 'zotero_library_type', fallback='user').strip()
            
            # Fall back to legacy format if new format is empty
            if not api_key or not library_id:
                api_key = config.get('zotero', 'zotero_api_key', fallback='').strip()
                library_id = config.get('zotero', 'zotero_library_id', fallback='').strip()
                library_type = config.get('zotero', 'zotero_library_type', fallback='user').strip()
            
            if not api_key or not library_id:
                print(f"❌ Missing credentials in {self.config_file}")
                
            return api_key, library_id, library_type
            
        except Exception as e:
            print(f"❌ Error reading config file: {e}")
            return '', '', 'user'

    def load_tag_groups(self) -> Dict[str, List[str]]:
        """Load tag groups from configuration with personal overrides"""
        # Load default config first  
        root_dir = Path(self.config_file).parent.parent
        default_config_path = root_dir / "config.conf"
        personal_config_path = Path(self.config_file)
        
        config = configparser.ConfigParser()
        
        # Load default config if it exists
        if default_config_path.exists():
            config.read(default_config_path)
        
        # Load personal config to override defaults
        if personal_config_path.exists():
            config.read(personal_config_path)
        
        tag_groups = {}
        
        try:
            if config.has_section('TAG_GROUPS'):
                for key, value in config.items('TAG_GROUPS'):
                    # Parse enhanced syntax or simple comma-separated tags
                    group_ops = self._parse_tag_group_syntax(value)
                    tag_groups[key] = group_ops
                    
        except Exception as e:
            print(f"Warning: Could not load tag groups: {e}")
        
        return tag_groups

    def _parse_tag_group_syntax(self, value: str) -> Dict[str, List[str]]:
        """Parse tag group value with enhanced syntax support.
        
        Supports:
        - "tag1,tag2" - simple comma-separated list
        - "add:tag1,tag2" - explicit add
        - "add:tag1,tag2 remove:tag3" - add and remove
        - "remove:tag1,tag2" - explicit remove only
        
        Returns dict with 'add' and/or 'remove' keys containing lists of tags.
        """
        if not value:
            return {}
        
        operations = {'add': [], 'remove': []}
        
        # Check if we have add: or remove: prefixes
        if 'add:' in value or 'remove:' in value:
            # Parse enhanced syntax
            parts = value.split()
            
            for part in parts:
                if part.startswith('add:'):
                    tags_str = part[4:]  # Remove "add:" prefix
                    tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
                    operations['add'].extend(tags)
                elif part.startswith('remove:'):
                    tags_str = part[7:]  # Remove "remove:" prefix
                    tags = [tag.strip() for tag in tags_str.split(',') if tag.strip()]
                    operations['remove'].extend(tags)
        else:
            # Simple syntax: just comma-separated tags
            operations['add'] = [tag.strip() for tag in value.split(',') if tag.strip()]
        
        return operations

    def _format_tag_group_display(self, group_ops) -> str:
        """Format tag group operations for display.
        
        Args:
            group_ops: Dict with 'add' and/or 'remove' keys, or list for backward compatibility
            
        Returns:
            Formatted string like "tag1, tag2" or "add:tag1, tag2 | remove:tag3"
        """
        if not group_ops:
            return '(empty)'
        
        # Backward compatibility: if it's a list, display as-is
        if isinstance(group_ops, list):
            return ', '.join(group_ops) if group_ops else '(empty)'
        
        add_tags = group_ops.get('add', [])
        remove_tags = group_ops.get('remove', [])
        
        parts = []
        if add_tags:
            parts.append(', '.join(add_tags))
        if remove_tags:
            parts.append(f"remove: {', '.join(remove_tags)}")
        
        return ' | '.join(parts) if parts else '(empty)'

    def load_actions(self) -> Dict[int, Dict[str, str]]:
        """Load action definitions from configuration with personal overrides"""
        # Load default config first
        default_config_path = Path("/mnt/f/prog/research-tools/config.conf")
        personal_config_path = Path(self.config_file)
        
        config = configparser.ConfigParser()
        
        # Load default config if it exists
        if default_config_path.exists():
            config.read(default_config_path)
        
        # Load personal config to override defaults
        if personal_config_path.exists():
            config.read(personal_config_path)
        
        actions = {}
        
        try:
            if config.has_section('ACTIONS'):
                for key, value in config.items('ACTIONS'):
                    # Parse action format: action_name:description
                    if ':' in value:
                        action_name, description = value.split(':', 1)
                        # Extract action number from key (e.g., "action1" -> 1)
                        if key.startswith('action'):
                            try:
                                action_num = int(key[6:])  # Remove "action" prefix
                                actions[action_num] = {
                                    'name': action_name.strip(),
                                    'description': description.strip()
                                }
                            except ValueError:
                                continue
                                
        except Exception as e:
            print(f"Warning: Could not load actions: {e}")
        
        return actions

    def load_menu_options(self) -> Dict[str, bool]:
        """Load menu options from configuration with personal overrides"""
        # Load default config first
        default_config_path = Path("/mnt/f/prog/research-tools/config.conf")
        personal_config_path = Path(self.config_file)
        
        config = configparser.ConfigParser()
        
        # Load default config if it exists
        if default_config_path.exists():
            config.read(default_config_path)
        
        # Load personal config to override defaults
        if personal_config_path.exists():
            config.read(personal_config_path)
        
        menu_options = {}
        
        try:
            if config.has_section('MENU_OPTIONS'):
                for key, value in config.items('MENU_OPTIONS'):
                    # Convert string values to boolean
                    menu_options[key] = value.lower() in ['true', '1', 'yes', 'on']
                    
        except Exception as e:
            print(f"Warning: Could not load menu options: {e}")
        
        return menu_options

    def parse_multi_digit_choice(self, user_input: str) -> List[int]:
        """Parse multi-digit input like '17' into [1, 7], handle special cases"""
        if not user_input.isdigit():
            return []
        
        # Special case: 999 is a single action (remove item)
        if user_input == '999':
            return [999]
        
        # Special case: 0 is a single action (skip)
        if user_input == '0':
            return [0]
        
        # Convert each digit to integer
        return [int(digit) for digit in user_input]

    def show_enhanced_menu(self, isbn: str, book_title: str = "", author: str = "", 
                          is_existing: bool = False, zotero_item: Dict = None, 
                          online_metadata: Dict = None) -> str:
        """Show enhanced menu with action descriptions and differences"""
        print(f"\nISBN: {isbn}")
        print(f"Title: {book_title}")
        print(f"Author: {author}")
        print(f"Status: {'Already in Zotero' if is_existing else 'Not in Zotero'}")
        print()
        
        # Show differences if they exist
        if is_existing and zotero_item and online_metadata:
            self._show_differences(zotero_item, online_metadata)
        
        # Show tags
        if is_existing and zotero_item:
            zotero_tags = [tag.get('tag', '') for tag in zotero_item.get('data', {}).get('tags', [])]
            if zotero_tags:
                print(f"Zotero tags: {', '.join(zotero_tags)}")
        
        if online_metadata:
            online_tags = [tag.get('tag', '') if isinstance(tag, dict) else str(tag) 
                          for tag in online_metadata.get('tags', [])]
            if online_tags:
                print(f"Online metadata tags: {', '.join(online_tags)}")
        
        print()
        
        # Show available actions
        print(f"🎯 AVAILABLE ACTIONS:")
        for action_num in sorted(self.actions.keys()):
            action = self.actions[action_num]
            if action_num in [1, 2, 3]:
                # Show tag groups with spaces after commas
                group_key = f"group{action_num}"
                group_ops = self.tag_groups.get(group_key, {})
                tag_display = self._format_tag_group_display(group_ops)
                print(f"  {action_num}. Add tags: {tag_display}")
            else:
                print(f"  {action_num}. {action['description']}")
        
        return input(f"\nEnter your choice: ").strip()
    
    def _show_differences(self, zotero_item: Dict, online_metadata: Dict):
        """Show differences between Zotero and online metadata"""
        zotero_data = zotero_item.get('data', {})
        
        # Compare key fields
        fields_to_compare = ['title', 'ISBN', 'abstractNote']
        
        for field in fields_to_compare:
            zotero_value = zotero_data.get(field, '')
            online_value = online_metadata.get(field, '')
            
            if zotero_value != online_value:
                field_display = field.replace('abstractNote', 'Abstract')
                print(f"{field_display} in Zotero: {zotero_value or '(empty)'}")
                print(f"{field_display} in OpenLibrary: {online_value or '(empty)'}")
        
        # Compare authors
        zotero_creators = zotero_data.get('creators', [])
        online_creators = online_metadata.get('creators', [])
        
        if zotero_creators != online_creators:
            zotero_author = self._format_author(zotero_creators[0]) if zotero_creators else ''
            online_author = self._format_author(online_creators[0]) if online_creators else ''
            print(f"Author in Zotero: {zotero_author}")
            print(f"Author in OpenLibrary: {online_author}")
    
    def _format_author(self, creator: Dict) -> str:
        """Format author name from creator dict"""
        first_name = creator.get('firstName', '')
        last_name = creator.get('lastName', '')
        return f"{first_name} {last_name}".strip()

    def execute_actions(self, actions: List[int], item_key: Optional[str], 
                       book_template: Optional[Dict], isbn: str) -> Dict[str, any]:
        """Execute multiple actions in sequence"""
        results = {
            'success': True,
            'actions_taken': [],
            'errors': [],
            'tags_added': [],
            'metadata_updated': False,
            'item_removed': False
        }
        
        # If removal action (999) is present, skip all tag operations since item will be removed
        has_removal = 999 in actions
        if has_removal:
            results['actions_taken'].append("Skipping tag operations - item will be removed")
        
        for action_num in actions:
            if action_num not in self.actions:
                results['errors'].append(f"Unknown action: {action_num}")
                continue
            
            action = self.actions[action_num]
            action_name = action['name']
            
            try:
                if action_name == 'add_group1_tags':
                    if has_removal:
                        results['actions_taken'].append("Skipped group1 tags - item will be removed")
                        continue
                    group_ops = self.tag_groups.get('group1', {})
                    add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                    remove_tags = group_ops.get('remove', []) if isinstance(group_ops, dict) else []
                    if add_tags and item_key:
                        success = self.update_item_tags(item_key, add_tags=add_tags, remove_tags=remove_tags)
                        if success:
                            results['tags_added'].extend(add_tags)
                            msg = f"Added group1 tags: {', '.join(add_tags)}"
                            if remove_tags:
                                msg += f" | Removed: {', '.join(remove_tags)}"
                            results['actions_taken'].append(msg)
                        else:
                            results['errors'].append("Failed to add group1 tags")
                
                elif action_name == 'add_group2_tags':
                    if has_removal:
                        results['actions_taken'].append("Skipped group2 tags - item will be removed")
                        continue
                    group_ops = self.tag_groups.get('group2', {})
                    add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                    remove_tags = group_ops.get('remove', []) if isinstance(group_ops, dict) else []
                    if add_tags and item_key:
                        success = self.update_item_tags(item_key, add_tags=add_tags, remove_tags=remove_tags)
                        if success:
                            results['tags_added'].extend(add_tags)
                            msg = f"Added group2 tags: {', '.join(add_tags)}"
                            if remove_tags:
                                msg += f" | Removed: {', '.join(remove_tags)}"
                            results['actions_taken'].append(msg)
                        else:
                            results['errors'].append("Failed to add group2 tags")
                
                elif action_name == 'add_group3_tags':
                    if has_removal:
                        results['actions_taken'].append("Skipped group3 tags - item will be removed")
                        continue
                    group_ops = self.tag_groups.get('group3', {})
                    add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                    remove_tags = group_ops.get('remove', []) if isinstance(group_ops, dict) else []
                    if add_tags and item_key:
                        success = self.update_item_tags(item_key, add_tags=add_tags, remove_tags=remove_tags)
                        if success:
                            results['tags_added'].extend(add_tags)
                            msg = f"Added group3 tags: {', '.join(add_tags)}"
                            if remove_tags:
                                msg += f" | Removed: {', '.join(remove_tags)}"
                            results['actions_taken'].append(msg)
                        else:
                            results['errors'].append("Failed to add group3 tags")
                
                elif action_name == 'use_online_tags':
                    if has_removal:
                        results['actions_taken'].append("Skipped online tags - item will be removed")
                        continue
                    if book_template and item_key:
                        online_tags = [tag.get('tag', '') if isinstance(tag, dict) else str(tag) 
                                     for tag in book_template.get('tags', [])]
                        if online_tags:
                            success = self.update_item_tags(item_key, add_tags=online_tags)
                            if success:
                                results['tags_added'].extend(online_tags)
                                results['actions_taken'].append(f"Added online tags: {', '.join(online_tags)}")
                            else:
                                results['errors'].append("Failed to add online tags")
                        else:
                            results['actions_taken'].append("No online tags available")
                
                elif action_name == 'skip':
                    results['actions_taken'].append("Skipped - no changes made")
                    continue
                
                elif action_name == 'update_author':
                    if has_removal:
                        results['actions_taken'].append("Skipped author update - item will be removed")
                        continue
                    if book_template and item_key:
                        success = self.update_item_author(item_key, book_template)
                        if success:
                            results['actions_taken'].append("Updated author")
                        else:
                            results['errors'].append("Failed to update author")
                
                elif action_name == 'update_title':
                    if has_removal:
                        results['actions_taken'].append("Skipped title update - item will be removed")
                        continue
                    if book_template and item_key:
                        success = self.update_item_title(item_key, book_template)
                        if success:
                            results['actions_taken'].append("Updated title")
                        else:
                            results['errors'].append("Failed to update title")
                
                elif action_name == 'update_metadata':
                    if has_removal:
                        results['actions_taken'].append("Skipped metadata update - item will be removed")
                        continue
                    if book_template and item_key:
                        success = self.update_item_metadata(item_key, book_template)
                        if success:
                            results['metadata_updated'] = True
                            results['actions_taken'].append("Updated metadata fields")
                        else:
                            results['errors'].append("Failed to update metadata")
                
                elif action_name == 'remove_item':
                    if item_key:
                        # ALWAYS require confirmation for removal, regardless of config
                        confirm = input(f"⚠️  Are you sure you want to remove this item? (yes/no): ").strip().lower()
                        if confirm != 'yes':
                            results['actions_taken'].append("Item removal cancelled by user")
                            continue
                        
                        success = self.remove_item_from_zotero(item_key)
                        if success:
                            results['item_removed'] = True
                            results['actions_taken'].append("Item removed from Zotero")
                        else:
                            results['errors'].append("Failed to remove item")
                
                elif action_name == 'show_differences':
                    if item_key and book_template:
                        self.show_item_differences(item_key, book_template)
                        results['actions_taken'].append("Showed differences between Zotero and online metadata")
                
            except Exception as e:
                results['errors'].append(f"Error executing action {action_num}: {e}")
        
        if results['errors']:
            results['success'] = False
        
        return results

    def show_item_differences(self, item_key: str, online_metadata: Dict):
        """Show differences between Zotero item and online metadata"""
        try:
            # Get current Zotero item
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Could not retrieve Zotero item: {response.status_code}")
                return
            
            zotero_item = response.json()
            zotero_data = zotero_item['data']
            
            print(f"\n" + "=" * 60)
            print(f"📊 METADATA COMPARISON")
            print(f"=" * 60)
            
            # Compare fields
            fields_to_compare = [
                'title', 'publisher', 'date', 'language', 'numPages', 
                'abstractNote', 'place', 'edition'
            ]
            
            for field in fields_to_compare:
                zotero_value = zotero_data.get(field, '')
                online_value = online_metadata.get(field, '')
                
                if zotero_value != online_value:
                    print(f"\n🔍 {field.upper()}:")
                    print(f"  Zotero:  {zotero_value or '(empty)'}")
                    print(f"  Online:  {online_value or '(empty)'}")
                    if zotero_value and online_value:
                        print(f"  Status:  ⚠️  Different")
                    elif online_value and not zotero_value:
                        print(f"  Status:  ➕ Online has additional info")
                    elif zotero_value and not online_value:
                        print(f"  Status:  ➖ Zotero has additional info")
            
            # Compare creators
            zotero_creators = zotero_data.get('creators', [])
            online_creators = online_metadata.get('creators', [])
            
            if zotero_creators != online_creators:
                print(f"\n🔍 CREATORS:")
                print(f"  Zotero:  {len(zotero_creators)} creators")
                for i, creator in enumerate(zotero_creators, 1):
                    name = f"{creator.get('firstName', '')} {creator.get('lastName', '')}".strip()
                    print(f"    {i}. {name}")
                
                print(f"  Online:  {len(online_creators)} creators")
                for i, creator in enumerate(online_creators, 1):
                    name = f"{creator.get('firstName', '')} {creator.get('lastName', '')}".strip()
                    print(f"    {i}. {name}")
            
            # Compare tags
            zotero_tags = [tag.get('tag', '') for tag in zotero_data.get('tags', [])]
            online_tags = [tag.get('tag', '') if isinstance(tag, dict) else str(tag) for tag in online_metadata.get('tags', [])]
            
            if set(zotero_tags) != set(online_tags):
                print(f"\n🔍 TAGS:")
                print(f"  Zotero:  {len(zotero_tags)} tags")
                for tag in sorted(zotero_tags):
                    print(f"    • {tag}")
                
                print(f"  Online:  {len(online_tags)} tags")
                for tag in sorted(online_tags):
                    print(f"    • {tag}")
                
                # Show differences
                zotero_only = set(zotero_tags) - set(online_tags)
                online_only = set(online_tags) - set(zotero_tags)
                
                if zotero_only:
                    print(f"  Only in Zotero: {', '.join(sorted(zotero_only))}")
                if online_only:
                    print(f"  Only online: {', '.join(sorted(online_only))}")
            
            print(f"\n" + "=" * 60)
            
        except Exception as e:
            print(f"❌ Error showing differences: {e}")

    def update_item_metadata(self, item_key: str, new_metadata: Dict) -> bool:
        """Update specific metadata fields of an existing item"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_data = item_data['data']
            
            # Update fields that exist in new_metadata
            fields_to_update = [
                'title', 'publisher', 'date', 'language', 'numPages', 
                'abstractNote', 'place', 'edition', 'creators'
            ]
            
            updated = False
            for field in fields_to_update:
                if field in new_metadata and new_metadata[field]:
                    if current_data.get(field) != new_metadata[field]:
                        current_data[field] = new_metadata[field]
                        updated = True
            
            if not updated:
                print(f"  ℹ️  No metadata updates needed")
                return True
            
            # Update item
            update_data = {
                'key': item_key,
                'version': item_data['version'],
                **current_data
            }
            
            update_response = requests.put(f"{self.base_url}/items/{item_key}",
                                         headers=self.headers,
                                         json=update_data)
            
            if update_response.status_code == 204:
                print(f"  ✅ Updated metadata fields")
                return True
            else:
                print(f"  ❌ Failed to update metadata: {update_response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Update metadata error: {e}")
            return False

    def update_item_author(self, item_key: str, new_metadata: Dict) -> bool:
        """Update author information of an existing item"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_data = item_data['data']
            
            # Update creators field
            if 'creators' in new_metadata and new_metadata['creators']:
                current_data['creators'] = new_metadata['creators']
                
                # Update item
                update_data = {
                    'key': item_key,
                    'version': item_data['version'],
                    **current_data
                }
                
                update_response = requests.put(f"{self.base_url}/items/{item_key}",
                                             headers=self.headers,
                                             json=update_data)
                
                if update_response.status_code == 204:
                    print(f"  ✅ Updated author information")
                    return True
                else:
                    print(f"  ❌ Failed to update author: {update_response.status_code}")
                    return False
            else:
                print(f"  ℹ️  No author information to update")
                return True
                
        except Exception as e:
            print(f"  ❌ Update author error: {e}")
            return False

    def update_item_title(self, item_key: str, new_metadata: Dict) -> bool:
        """Update title of an existing item"""
        try:
            # Get current item data
            response = requests.get(f"{self.base_url}/items/{item_key}", headers=self.headers)
            if response.status_code != 200:
                print(f"❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_data = item_data['data']
            
            # Update title field
            if 'title' in new_metadata and new_metadata['title']:
                current_data['title'] = new_metadata['title']
                
                # Update item
                update_data = {
                    'key': item_key,
                    'version': item_data['version'],
                    **current_data
                }
                
                update_response = requests.put(f"{self.base_url}/items/{item_key}",
                                             headers=self.headers,
                                             json=update_data)
                
                if update_response.status_code == 204:
                    print(f"  ✅ Updated title")
                    return True
                else:
                    print(f"  ❌ Failed to update title: {update_response.status_code}")
                    return False
            else:
                print(f"  ℹ️  No title information to update")
                return True
                
        except Exception as e:
            print(f"  ❌ Update title error: {e}")
            return False

    def remove_item_from_zotero(self, item_key: str) -> bool:
        """Remove item from Zotero library"""
        try:
            response = requests.delete(f"{self.base_url}/items/{item_key}", headers=self.headers)
            
            if response.status_code == 204:
                print(f"  ✅ Item removed from Zotero")
                return True
            else:
                print(f"  ❌ Failed to remove item: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Remove item error: {e}")
            return False

    def test_api_connection(self) -> bool:
        """Test if API credentials work"""
        try:
            test_url = f"{self.base_url}/items"
            params = {'limit': 1}
            
            print(f"🔍 Testing library access: {test_url}")
            
            response = requests.get(test_url, headers=self.headers, params=params)
            
            if response.status_code == 200:
                items = response.json()
                print(f"✅ API connection successful")
                print(f"📚 Your library contains items")
                return True
            else:
                print(f"❌ API connection failed: {response.status_code}")
                return False
                
        except Exception as e:
            print(f"❌ API connection error: {e}")
            return False

    def search_item_by_isbn(self, isbn: str) -> Optional[Dict]:
        """Search for existing item by ISBN in your library with improved format handling"""
        try:
            # Clean the search ISBN
            clean_search_isbn = self.normalize_isbn(isbn)
            print(f"  🔍 Searching for ISBN: {isbn} (normalized: {clean_search_isbn})")
            
            # Try targeted search approaches in order of specificity
            search_params = [
                {'q': f'isbn:{isbn}', 'qmode': 'everything', 'format': 'json', 'limit': 10},
                {'q': isbn, 'qmode': 'everything', 'format': 'json', 'limit': 10}
            ]
            
            items = []
            for params in search_params:
                response = requests.get(f"{self.base_url}/items", 
                                      headers=self.headers,
                                      params=params)
                
                if response.status_code == 200:
                    search_items = response.json()
                    if search_items:  # If we found items, use this search
                        items = search_items
                        print(f"  📚 Search with '{params['q']}' returned {len(items)} items")
                        break  # Stop at first successful search with results
                    else:
                        print(f"  📚 Search with '{params['q']}' returned 0 items")
            
            if not items:
                print(f"  📚 No items found in any search")
            
            matching_items = []
            for item in items:
                item_isbn = item['data'].get('ISBN', '')
                if item_isbn:
                    # Extract clean ISBN from potentially complex text
                    clean_item_isbn = self.extract_clean_isbn(item_isbn)
                    if clean_item_isbn:
                        normalized_item_isbn = self.normalize_isbn(clean_item_isbn)
                        print(f"    Checking item ISBN: {item_isbn} -> {clean_item_isbn} (normalized: {normalized_item_isbn})")
                        
                        # Use enhanced ISBN matching
                        if ISBNMatcher.match_isbn(clean_search_isbn, clean_item_isbn):
                            print(f"    ✅ ISBN match found!")
                            matching_items.append(item)
                    else:
                        print(f"    ⚠️  Could not extract clean ISBN from: {item_isbn}")
                else:
                    print(f"    ⚠️  Item has no ISBN field")
            
            if matching_items:
                if len(matching_items) > 1:
                    # Multiple duplicates found - add to duplicate list
                    duplicate_info = {
                        'isbn': isbn,
                        'count': len(matching_items),
                        'items': matching_items,
                        'titles': [item['data'].get('title', 'Unknown') for item in matching_items],
                        'keys': [item['key'] for item in matching_items],
                        'zotero_codes': [item['key'] for item in matching_items]  # Same as keys, but explicit for deletion
                    }
                    self.duplicates_found.append(duplicate_info)
                    print(f"  ⚠️  Found {len(matching_items)} duplicates for ISBN {isbn}")
                    print(f"      Titles: {', '.join(duplicate_info['titles'])}")
                    print(f"      Zotero codes: {', '.join(duplicate_info['zotero_codes'])}")
                
                # Return the first match for now
                return matching_items[0]
            
            print(f"  ❌ No matching ISBN found in your Zotero library")
            return None
            
        except Exception as e:
            print(f"Error searching for ISBN {isbn}: {e}")
            return None

    def normalize_isbn(self, isbn: str) -> str:
        """Normalize ISBN to standard format for comparison"""
        return ISBNMatcher.normalize_isbn(isbn)
    
    def extract_clean_isbn(self, isbn_text: str) -> str:
        """Extract clean ISBN from text that might contain additional info like (pbk.) or (hardcover)"""
        return ISBNMatcher.extract_clean_isbn(isbn_text)
    
    def _convert_and_match(self, isbn1: str, isbn2: str) -> bool:
        """Enhanced ISBN matching using substring approach"""
        return ISBNMatcher.match_isbn(isbn1, isbn2)
    

    def get_item_template_by_isbn(self, isbn: str) -> Optional[Dict]:
        """Get item template using enhanced ISBN lookup services with item type detection"""
        print(f"  Looking up book information...")
        
        result = self.isbn_lookup.lookup_isbn(isbn)
        
        if result:
            # Determine correct item type
            result = self.determine_item_type(result)
            
            title = result.get('title', 'Unknown Title')
            creators = result.get('creators', [])
            author = creators[0].get('lastName', 'Unknown') if creators else 'Unknown'
            year = result.get('date', 'Unknown')
            item_type = result.get('itemType', 'book')
            
            # Determine which service found the book
            extra_info = result.get('extra', '')
            if 'OpenLibrary:' in extra_info:
                source = 'OpenLibrary'
            elif 'Google Books ID:' in extra_info:
                source = 'Google Books'
            elif 'Norwegian Library:' in extra_info:
                source = 'Norwegian Library'
            else:
                source = 'metadata service'
            
            print(f"  Found: {title}")
            print(f"      Author: {author}")
            print(f"      Year: {year}")
            print(f"      Item type: {item_type} (found in {source})")
            
            # Display metadata tags from online library
            metadata_tags = result.get('tags', [])
            if metadata_tags:
                print(f"\n   📚 Metadata tags (combined from all services):")
                for i, tag in enumerate(metadata_tags, 1):
                    tag_name = tag.get('tag', '') if isinstance(tag, dict) else str(tag)
                    if tag_name:
                        print(f"      {i:2d}. {tag_name}")
            else:
                print(f"\n   📚 No metadata tags found")
            
            if result.get('abstractNote'):
                abstract_preview = result['abstractNote'][:100] + "..." if len(result['abstractNote']) > 100 else result['abstractNote']
                print(f"      Abstract: {abstract_preview}")
            
        return result

    def determine_item_type(self, item_data: Dict) -> Dict:
        """Determine the correct Zotero item type based on metadata"""
        title = item_data.get('title', '').lower()
        publisher = item_data.get('publisher', '').lower()
        tags = item_data.get('tags', [])
        tag_texts = [tag.get('tag', '').lower() if isinstance(tag, dict) else str(tag).lower() for tag in tags]
        
        # Check for journal indicators
        journal_indicators = [
            'journal', 'proceedings', 'conference', 'symposium', 'workshop',
            'annual', 'quarterly', 'monthly', 'volume', 'issue', 'number'
        ]
        
        # Check for book section indicators
        book_section_indicators = [
            'chapter', 'section', 'part', 'contribution', 'paper in',
            'in proceedings', 'in conference', 'in symposium'
        ]
        
        # Check if it's a journal article
        for indicator in journal_indicators:
            if (indicator in title or 
                any(indicator in tag_text for tag_text in tag_texts) or
                indicator in publisher):
                print(f"      Detected as journal article (indicator: {indicator})")
                item_data['itemType'] = 'journalArticle'
                return item_data
        
        # Check if it's a book section
        for indicator in book_section_indicators:
            if indicator in title:
                print(f"      Detected as book section (indicator: {indicator})")
                item_data['itemType'] = 'bookSection'
                return item_data
        
        # Default to book
        print(f"      Detected as book")
        item_data['itemType'] = 'book'
        return item_data

    def add_item_to_library(self, item_template: Dict, user_tags: List[str]) -> Optional[str]:
        """Add new item to your Zotero library with enhanced metadata"""
        try:
            # Combine user tags with existing metadata tags
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
                print(f"  ✅ Added to library with key: {item_key}")
                
                # Show what was added
                metadata_tags = len(existing_tags)
                personal_tags = len(user_tags)
                print(f"      🏷️  Added {personal_tags} personal tags and {metadata_tags} metadata tags")
                
                # Log successful addition
                self.log_successful_addition(item_template.get('ISBN', ''), item_key)
                
                return item_key
            else:
                print(f"  ❌ Failed to add item: {response.status_code}")
                return None
                
        except Exception as e:
            print(f"  ❌ Add item error: {e}")
            return None

    def update_item_tags(self, item_key: str, add_tags: List[str], remove_tags: List[str] = None) -> bool:
        """Update tags on existing item"""
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
                    print(f"  ✅ Updated tags: added {added_count} personal tags, removed {removed_count} tags")
                elif added_count > 0:
                    print(f"  ✅ Updated tags: added {added_count} personal tags")
                elif removed_count > 0:
                    print(f"  ✅ Updated tags: removed {removed_count} tags")
                else:
                    print(f"  ✅ Updated tags successfully")
                return True
            else:
                print(f"  ❌ Failed to update tags: {update_response.status_code}")
                return False
                
        except Exception as e:
            print(f"  ❌ Update tags error: {e}")
            return False

    def get_found_isbns(self) -> List[Tuple[str, str]]:
        """Get ISBNs from previous processing that haven't been processed for Zotero yet"""
        isbn_list = []
        
        try:
            # Read from the book processing log
            log_file = self.isbn_log_file
            import csv
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
                    
        except FileNotFoundError:
            print("No previous ISBN processing found. Run the image processor first.")
        except Exception as e:
            print(f"Error loading ISBN data: {e}")
            import traceback
            traceback.print_exc()
        
        return isbn_list

    def load_skip_log(self, skip_log_file: str) -> set:
        """Load existing skip log to avoid duplicates"""
        existing_isbns = set()
        
        try:
            if Path(skip_log_file).exists():
                with open(skip_log_file, 'r') as f:
                    for line in f:
                        if line.strip() and not line.startswith('#') and '|' in line:
                            parts = line.strip().split('|')
                            if len(parts) >= 2:
                                isbn = parts[1].strip()
                                if isbn != 'ISBN':  # Skip header
                                    existing_isbns.add(isbn)
        except Exception as e:
            print(f"Warning: Could not read skip log: {e}")
        
        return existing_isbns

    def add_to_skip_log(self, skip_log_file: str, isbn: str, filename: str, reason: str = "no_metadata"):
        """Add item to skip log with timestamp"""
        try:
            # Create directory if needed
            Path(skip_log_file).parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists to add header
            file_exists = Path(skip_log_file).exists()
            
            with open(skip_log_file, 'a', encoding='utf-8') as f:
                if not file_exists:
                    f.write("# Items not added to Zotero\n")
                    f.write("# Format: Timestamp | ISBN | Filename | Reason\n")
                    f.write("#" + "="*70 + "\n")
                
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp} | {isbn} | {filename} | {reason}\n")
            
            print(f"   📝 Logged to skip file: {reason}")
            
        except Exception as e:
            print(f"   ⚠️  Could not write to skip log: {e}")

    def update_book_processing_log(self, decisions: List[BookDecision]):
        """Update the book processing log with Zotero decision information"""
        try:
            import csv
            
            # Read existing data if file exists
            existing_data = {}
            if Path(self.isbn_log_file).exists():
                with open(self.isbn_log_file, 'r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        # Use ISBN as key since that's the unique identifier for books
                        if row.get('isbn'):
                            existing_data[row['isbn']] = row
            
            # Update with new Zotero decisions
            for decision in decisions:
                if decision.isbn in existing_data:
                    # Update existing record with Zotero decision info
                    existing_data[decision.isbn]['zotero_decision'] = 'keep' if decision.keep else 'give_away'
                    existing_data[decision.isbn]['zotero_item_key'] = decision.zotero_item_key or ''
                    existing_data[decision.isbn]['zotero_action_taken'] = decision.action_taken or ''
                    existing_data[decision.isbn]['zotero_timestamp'] = datetime.now().isoformat()
                else:
                    # Create new record if ISBN not found (shouldn't happen normally)
                    print(f"Warning: ISBN {decision.isbn} not found in processing log")
            
            # Write updated data to CSV with extended fieldnames
            fieldnames = ['filename', 'status', 'isbn', 'method', 'confidence', 'attempts', 
                         'processing_time', 'retry_count', 'timestamp', 'error',
                         'zotero_decision', 'zotero_item_key', 'zotero_action_taken', 'zotero_timestamp']
            
            with open(self.isbn_log_file, 'w', encoding='utf-8', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
                writer.writeheader()
                for row in existing_data.values():
                    # Ensure all fields exist with empty string defaults
                    for field in fieldnames:
                        if field not in row:
                            row[field] = ''
                    writer.writerow(row)
                
            print(f"Zotero decisions updated in: {self.isbn_log_file}")
            
        except Exception as e:
            print(f"Error updating book processing log: {e}")

    def print_summary(self, decisions: List[BookDecision]):
        """Print processing summary with skip information"""
        if not decisions:
            return
        
        total = len(decisions)
        pending = len([d for d in decisions if d.action_taken == 'pending'])
        failed = len([d for d in decisions if d.action_taken == 'failed'])
        kept = len([d for d in decisions if d.keep and d.action_taken == 'pending'])
        discarded = len([d for d in decisions if not d.keep and d.action_taken == 'pending'])
        
        print(f"\n" + "=" * 50)
        print(f"ZOTERO DECISION SUMMARY")
        print(f"=" * 50)
        print(f"Total books processed: {total}")
        print(f"Decisions recorded: {pending}")
        print(f"Failed: {failed}")
        print(f"Books to keep: {kept}")
        print(f"Books to give away: {discarded}")
        print(f"\n⚠️  Note: No items were actually added to Zotero")
        print(f"   Use a separate command to add the pending items")
        
        # Show skip log info
        skip_log_file = "data/output/items_not_added_to_zotero.txt"
        if Path(skip_log_file).exists():
            try:
                with open(skip_log_file, 'r') as f:
                    lines = [line for line in f if line.strip() and not line.startswith('#')]
                print(f"Items in skip log: {len(lines)}")
                print(f"Skip log: {skip_log_file}")
            except:
                pass
        
        successful = len([d for d in decisions if d.action_taken in ['added', 'updated']])
        if successful > 0:
            print(f"\nSuccessful actions:")
            for decision in decisions:
                if decision.action_taken in ['added', 'updated']:
                    action = "📚 Keep" if decision.keep else "📦 Give away"
                    print(f"  {action} - {decision.isbn} ({decision.action_taken})")

    def log_successful_addition(self, isbn: str, item_key: str):
        """Log successfully added items to prevent reprocessing"""
        try:
            success_log_file = "data/output/successfully_added_to_zotero.txt"
            
            # Create directory if needed
            Path(success_log_file).parent.mkdir(parents=True, exist_ok=True)
            
            # Check if file exists to add header
            file_exists = Path(success_log_file).exists()
            
            with open(success_log_file, 'a', encoding='utf-8') as f:
                if not file_exists:
                    f.write("# Successfully added to Zotero\n")
                    f.write("# Format: Timestamp | ISBN | Zotero Key | Action\n")
                    f.write("#" + "="*70 + "\n")
                
                timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                f.write(f"{timestamp} | {isbn} | {item_key} | added\n")
            
            print(f"  📝 Logged successful addition to prevent reprocessing")
            
        except Exception as e:
            print(f"  ⚠️  Could not write to success log: {e}")

    def load_success_log(self) -> set:
        """Load successfully processed ISBNs to avoid reprocessing"""
        success_log_file = "data/output/successfully_added_to_zotero.txt"
        processed_isbns = set()
        
        try:
            if Path(success_log_file).exists():
                with open(success_log_file, 'r') as f:
                    for line in f:
                        if line.strip() and not line.startswith('#') and '|' in line:
                            parts = line.strip().split('|')
                            if len(parts) >= 2:
                                isbn = parts[1].strip()
                                if isbn != 'ISBN':  # Skip header
                                    processed_isbns.add(isbn)
                print(f"  📋 Loaded {len(processed_isbns)} previously processed ISBNs")
        except Exception as e:
            print(f"Warning: Could not read success log: {e}")
        
        return processed_isbns

    def show_help(self):
        """Show help information once at the beginning"""
        print("🚀 ENHANCED ZOTERO BOOK PROCESSOR")
        print("=" * 50)
        print("💡 MULTI-DIGIT INPUT:")
        print("  • Enter single digit: 1 (add keep tags)")
        print("  • Enter multiple digits: 17 (add keep tags + update metadata)")
        print("  • Enter 'q' to quit")
        print()
        print("⚠️  DESTRUCTIVE ACTIONS:")
        print("  • Action 999: Remove item from Zotero (ALWAYS CONFIRMED)")
        print("  • This action always requires confirmation")
        print("=" * 50)
        print()

    def interactive_book_processing(self):
        """Enhanced interactive processing with multi-digit input and smart item handling"""
        isbn_list = self.get_found_isbns()
        
        if not isbn_list:
            print("No ISBNs found. Please run the image processing first.")
            return
        
        # Show help once at the beginning
        self.show_help()
        
        print(f"Found {len(isbn_list)} books to process")
        decisions = []
        
        # Load existing skip log and success log to avoid duplicates
        skip_log_file = "data/output/items_not_added_to_zotero.txt"
        existing_skipped = self.load_skip_log(skip_log_file)
        successfully_processed = self.load_success_log()
        
        # Filter out already processed books
        unprocessed_isbns = []
        for isbn, filename in isbn_list:
            if isbn not in successfully_processed:
                unprocessed_isbns.append((isbn, filename))
            else:
                print(f"⏭️  Skipping {filename} (ISBN: {isbn}) - already processed")
        
        if not unprocessed_isbns:
            print("All books have already been processed!")
            return
        
        print(f"Processing {len(unprocessed_isbns)} new books...")
        
        for i, (isbn, filename) in enumerate(unprocessed_isbns, 1):
            print(f"\n" + "=" * 60)
            print(f"Book {i}/{len(unprocessed_isbns)}: {filename}")
            print(f"ISBN: {isbn}")
            print("=" * 60)
            
            # Check if already in Zotero
            existing_item = self.search_item_by_isbn(isbn)
            book_template = None
            
            if existing_item:
                # Book is already in Zotero
                book_title = existing_item['data'].get('title', 'Unknown')
                creators = existing_item['data'].get('creators', [])
                author = self._format_author(creators[0]) if creators else 'Unknown'
                
                # Get online metadata for comparison
                book_template = self.get_item_template_by_isbn(isbn)
                
                # Show enhanced menu for existing item
                while True:
                    user_input = self.show_enhanced_menu(isbn, book_title, author, 
                                                       is_existing=True, zotero_item=existing_item, 
                                                       online_metadata=book_template)
                    
                    if user_input.lower() == 'q':
                        print("⏭️  Skipped")
                        break
                    
                    # Parse multi-digit input
                    actions = self.parse_multi_digit_choice(user_input)
                    if not actions:
                        print("❌ Invalid input. Please enter numbers or 'q' to quit.")
                        continue
                    
                    # Execute actions
                    results = self.execute_actions(actions, existing_item['key'], book_template, isbn)
                    
                    # Show results
                    if results['success']:
                        print(f"\n✅ Actions completed successfully:")
                        for action in results['actions_taken']:
                            print(f"   • {action}")
                        
                        if results['tags_added']:
                            print(f"   📝 Tags added: {', '.join(results['tags_added'])}")
                        
                        if results['metadata_updated']:
                            print(f"   📊 Metadata updated")
                        
                        if results['item_removed']:
                            print(f"   🗑️  Item removed from Zotero")
                            # Log successful processing
                            self.log_successful_addition(isbn, existing_item['key'])
                            break
                    else:
                        print(f"\n❌ Some actions failed:")
                        for error in results['errors']:
                            print(f"   • {error}")
                        continue
                    
                    # Ask if user wants to do more actions
                    more_actions = input(f"\nDo more actions on this book? (y/n): ").strip().lower()
                    if more_actions != 'y':
                        break
                
                # Log successful processing
                if not results.get('item_removed', False):
                    self.log_successful_addition(isbn, existing_item['key'])
                
            else:
                # Book not in Zotero
                print(f"❌ Book not found in your Zotero library")
                
                # Check if already in skip log
                if isbn in existing_skipped:
                    print(f"   Previously skipped (no metadata available)")
                    continue
                
                # Try to get enhanced book info
                book_template = self.get_item_template_by_isbn(isbn)
                
                if not book_template or not book_template.get('title'):
                    # No metadata found - add to skip log
                    print(f"   No book metadata found - will not add to Zotero")
                    self.add_to_skip_log(skip_log_file, isbn, filename)
                    existing_skipped.add(isbn)  # Update local cache
                    continue
                
                # We have good metadata - show it and ask user
                book_title = book_template.get('title', 'Unknown')
                creators = book_template.get('creators', [])
                author = self._format_author(creators[0]) if creators else 'Unknown'
                print(f"✅ Book information found!")
                
                # Show enhanced menu for new item
                while True:
                    user_input = self.show_enhanced_menu(isbn, book_title, author, 
                                                       is_existing=False, zotero_item=None, 
                                                       online_metadata=book_template)
                    
                    if user_input.lower() == 'q':
                        print("⏭️  Skipped - not added to Zotero")
                        self.add_to_skip_log(skip_log_file, isbn, filename, reason="user_skipped")
                        existing_skipped.add(isbn)
                        break
                    
                    # Parse multi-digit input
                    actions = self.parse_multi_digit_choice(user_input)
                    if not actions:
                        print("❌ Invalid input. Please enter numbers or 'q' to quit.")
                        continue
                    
                    # Check if action 0 (skip) was selected
                    if 0 in actions:
                        print("⏭️  Skipped - not added to Zotero")
                        self.add_to_skip_log(skip_log_file, isbn, filename, reason="user_skipped")
                        existing_skipped.add(isbn)
                        break
                    
                    # For new items, we need to add them first before we can update them
                    # Check if any actions require an existing item
                    requires_existing = any(action in [7, 8, 999] for action in actions)  # update_metadata, show_differences, remove_item
                    
                    if requires_existing:
                        print("❌ Some actions require the item to be in Zotero first.")
                        print("   Please add the item first, then you can update/remove it.")
                        continue
                    
                    # Add the item first
                    print(f"\n📚 Adding new item to Zotero...")
                    
                    # Determine tags based on actions
                    tags_to_add = []
                    for action_num in actions:
                        if action_num == 1:  # add_group1_tags
                            group_ops = self.tag_groups.get('group1', {})
                            add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                            tags_to_add.extend(add_tags)
                        elif action_num == 2:  # add_group2_tags
                            group_ops = self.tag_groups.get('group2', {})
                            add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                            tags_to_add.extend(add_tags)
                        elif action_num == 3:  # add_group3_tags
                            group_ops = self.tag_groups.get('group3', {})
                            add_tags = group_ops.get('add', []) if isinstance(group_ops, dict) else group_ops
                            tags_to_add.extend(add_tags)
                        elif action_num == 4:  # use_online_tags
                            online_tags = [tag.get('tag', '') if isinstance(tag, dict) else str(tag) 
                                         for tag in book_template.get('tags', [])]
                            tags_to_add.extend(online_tags)
                    
                    # Add item to Zotero
                    item_key = self.add_item_to_library(book_template, tags_to_add)
                    
                    if item_key:
                        print(f"✅ Item added successfully with key: {item_key}")
                        
                        # Now execute any remaining actions that require an existing item
                        remaining_actions = [action for action in actions if action in [7, 8, 999]]
                        if remaining_actions:
                            print(f"🔄 Executing remaining actions...")
                            results = self.execute_actions(remaining_actions, item_key, book_template, isbn)
                            
                            if results['success']:
                                print(f"✅ All actions completed successfully:")
                                for action in results['actions_taken']:
                                    print(f"   • {action}")
                            else:
                                print(f"❌ Some actions failed:")
                                for error in results['errors']:
                                    print(f"   • {error}")
                        
                        # Log successful processing
                        self.log_successful_addition(isbn, item_key)
                        break
                    else:
                        print(f"❌ Failed to add item to Zotero")
                        continue
            
            # Small delay to be nice to APIs
            time.sleep(1)
        
        # Show duplicate summary
        self.show_duplicate_summary()
        
        print(f"\n✅ Processing completed!")
    
    def show_duplicate_summary(self):
        """Show summary of duplicates found during processing"""
        if self.duplicates_found:
            print(f"\n" + "=" * 60)
            print(f"📋 DUPLICATE DETECTION SUMMARY")
            print(f"=" * 60)
            print(f"Found {len(self.duplicates_found)} ISBNs with duplicates:")
            
            for i, dup in enumerate(self.duplicates_found, 1):
                print(f"\n{i}. ISBN: {dup['isbn']} ({dup['count']} copies)")
                for j, (title, key) in enumerate(zip(dup['titles'], dup['zotero_codes']), 1):
                    print(f"   {j}. {title} (Zotero code: {key})")
            
            print(f"\n💡 These duplicates will be handled by the deduplicator tool")
            print(f"   (To be implemented in future version)")
            print(f"=" * 60)
        else:
            print(f"\n✅ No duplicates found during processing")

    def get_additional_tags(self, last_tags: List[str], metadata_tags: List[str] = None) -> List[str]:
        """Get additional tags from user with memory of previous tags and interactive editing"""
        print(f"\n📝 Additional tags:")
        
        # Show metadata tags first if available
        if metadata_tags:
            print(f"   📚 Metadata tags: {', '.join(metadata_tags)}")
            print(f"   💡 Tip: No need to add tags that are already in metadata")
        
        if last_tags:
            print(f"   Previous tags: {', '.join(last_tags)}")
            print(f"   Options:")
            print(f"   1. Press Enter to add no tags")
            print(f"   2. Type new tags (comma-separated)")
            print(f"   3. Use numbers to select tags (e.g., '1,3' for tags 1 and 3)")
            print(f"   4. Type 'all' to use all previous tags")
            
            # Show numbered tags for selection
            print(f"\n   Select by number:")
            for i, tag in enumerate(last_tags, 1):
                # Ensure proper UTF-8 encoding for special characters
                print(f"     {i}. {tag}")
            
            user_input = input(f"Tags (or numbers): ").strip()
            
            if not user_input:
                # Return empty list - user doesn't want any new personal tags
                return []
            
            # Check if user entered numbers (mixed with other content is OK)
            # Look for number patterns in the input
            number_pattern = r'\b\d+\b'
            import re
            numbers_found = re.findall(number_pattern, user_input)
            
            if numbers_found:
                # Parse number selection (e.g., "1,3" or "1, 3" or "123, rasisme")
                try:
                    numbers = [int(n) for n in numbers_found]
                    selected_tags = []
                    for num in numbers:
                        if 1 <= num <= len(last_tags):
                            selected_tags.append(last_tags[num - 1])
                    
                    # Also check for any non-number text as new tags
                    non_number_parts = re.sub(r'\b\d+\b', '', user_input).replace(',', ' ').split()
                    new_tags = [part.strip() for part in non_number_parts if part.strip()]
                    
                    # Combine selected tags and new tags
                    all_tags = selected_tags + new_tags
                    if all_tags:
                        return all_tags
                    else:
                        return selected_tags
                        
                except ValueError:
                    print(f"   ⚠️  Invalid number format, treating as regular tags")
                    # Fall through to regular tag parsing
            
            # Check for "all" keyword
            if user_input.lower() == 'all':
                return last_tags
            
            # Parse comma-separated tags and filter out duplicates
            tags = [tag.strip() for tag in user_input.split(',') if tag.strip()]
            
            # Filter out tags that are already in metadata
            if metadata_tags:
                filtered_tags = []
                for tag in tags:
                    if tag.lower() not in [mt.lower() for mt in metadata_tags]:
                        filtered_tags.append(tag)
                    else:
                        print(f"   ⚠️  Skipped '{tag}' (already in metadata)")
                
                if filtered_tags != tags:
                    print(f"   📝 Final tags: {', '.join(filtered_tags)}")
                
                return filtered_tags
            else:
                return tags
        else:
            print(f"   Enter tags (comma-separated):")
            user_input = input("Tags: ").strip()
            
            if not user_input:
                return []
            
            # Parse comma-separated tags
            tags = [tag.strip() for tag in user_input.split(',') if tag.strip()]
            
            # Filter out tags that are already in metadata
            if metadata_tags:
                filtered_tags = []
                for tag in tags:
                    if tag.lower() not in [mt.lower() for mt in metadata_tags]:
                        filtered_tags.append(tag)
                    else:
                        print(f"   ⚠️  Skipped '{tag}' (already in metadata)")
                
                if filtered_tags != tags:
                    print(f"   📝 Final tags: {', '.join(filtered_tags)}")
                
                return filtered_tags
            else:
                return tags

if __name__ == "__main__":
    print("Enhanced Zotero API Book Processor")
    print("=" * 40)
    
    try:
        processor = ZoteroAPIBookProcessor()
        
        # Test connection first
        if not processor.test_api_connection():
            exit(1)
        
        # Process books interactively with enhanced metadata
        processor.interactive_book_processing()
        
    except Exception as e:
        print(f"Error: {e}")