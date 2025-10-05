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
                 config_file: str = "/mnt/f/prog/scanpapers/config/zotero_api.conf",
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
        self.isbn_log_file = "data/books/book_processing_log.csv"
        self.decisions_file = "data/books/book_decisions.json"
        
        print(f"Enhanced Zotero API Processor initialized")
        print(f"Library: {self.library_type}/{self.library_id}")
        print(f"Config loaded from: {config_file}")

    def load_config(self) -> Tuple[str, str, str]:
        """Load configuration from config file"""
        config_path = Path(self.config_file)
        
        if not config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_file}")
        
        try:
            config = configparser.ConfigParser()
            config.read(self.config_file)
            
            api_key = config.get('zotero', 'zotero_api_key', fallback='').strip()
            library_id = config.get('zotero', 'zotero_library_id', fallback='').strip()
            library_type = config.get('zotero', 'zotero_library_type', fallback='user').strip()
            
            if not api_key or not library_id:
                print(f"❌ Missing credentials in {self.config_file}")
                
            return api_key, library_id, library_type
            
        except Exception as e:
            print(f"❌ Error reading config file: {e}")
            return '', '', 'user'

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
            
            response = requests.get(f"{self.base_url}/items", 
                                  headers=self.headers,
                                  params={
                                      'q': isbn,
                                      'qmode': 'everything',
                                      'format': 'json'
                                  })
            
            if response.status_code == 200:
                items = response.json()
                print(f"  📚 Found {len(items)} items in search results")
                
                for item in items:
                    item_isbn = item['data'].get('ISBN', '')
                    if item_isbn:
                        clean_item_isbn = self.normalize_isbn(item_isbn)
                        print(f"    Checking item ISBN: {item_isbn} (normalized: {clean_item_isbn})")
                        
                        if clean_item_isbn == clean_search_isbn:
                            print(f"    ✅ Match found!")
                            return item
                    else:
                        print(f"    ⚠️  Item has no ISBN field")
            
            print(f"  ❌ No matching ISBN found in library")
            return None
            
        except Exception as e:
            print(f"Error searching for ISBN {isbn}: {e}")
            return None

    def normalize_isbn(self, isbn: str) -> str:
        """Normalize ISBN to standard format for comparison"""
        if not isbn:
            return ""
        
        # Remove all non-alphanumeric characters except X
        cleaned = ''.join(c for c in isbn.upper() if c.isalnum() or c == 'X')
        
        # Handle different ISBN lengths
        if len(cleaned) == 10:
            # Convert 10-digit to 13-digit if needed
            # This is a simplified conversion - in practice, you might want a more robust algorithm
            if cleaned.startswith('0'):
                cleaned = '978' + cleaned[1:]
            else:
                cleaned = '978' + cleaned
        
        return cleaned

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
            
            print(f"  Found: {title}")
            print(f"      Author: {author}")
            print(f"      Year: {year}")
            print(f"      Type: {item_type}")
            
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
        """Get ISBNs from previous processing"""
        isbn_list = []
        
        try:
            # Read from the book processing log
            log_file = "data/books/book_processing_log.csv"
            import csv
            data = []
            if Path(log_file).exists():
                with open(log_file, 'r', encoding='utf-8', newline='') as f:
                    reader = csv.DictReader(f)
                    data = list(reader)
                
            for file_path, result in data.items():
                if result.get('status') == 'success' and result.get('isbn'):
                    # Extract filename from full path
                    filename = Path(file_path).name
                    isbn = result['isbn']
                    isbn_list.append((isbn, filename))
                    
        except FileNotFoundError:
            print("No previous ISBN processing found. Run the image processor first.")
        except Exception as e:
            print(f"Error loading ISBN data: {e}")
        
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

    def save_decisions(self, decisions: List[BookDecision]):
        """Save processing decisions"""
        try:
            data = []
            for decision in decisions:
                data.append({
                    'isbn': decision.isbn,
                    'filename': decision.filename,
                    'keep': decision.keep,
                    'zotero_item_key': decision.zotero_item_key,
                    'action_taken': decision.action_taken,
                    'timestamp': datetime.now().isoformat()
                })
            
            with open(self.decisions_file, 'w') as f:
                json.dump(data, f, indent=2)
                
            print(f"Decisions saved to: {self.decisions_file}")
            
        except Exception as e:
            print(f"Error saving decisions: {e}")

    def print_summary(self, decisions: List[BookDecision]):
        """Print processing summary with skip information"""
        if not decisions:
            return
        
        total = len(decisions)
        successful = len([d for d in decisions if d.action_taken in ['added', 'updated']])
        failed = len([d for d in decisions if d.action_taken == 'failed'])
        kept = len([d for d in decisions if d.keep and d.action_taken in ['added', 'updated']])
        discarded = len([d for d in decisions if not d.keep and d.action_taken in ['added', 'updated']])
        
        print(f"\n" + "=" * 50)
        print(f"ENHANCED ZOTERO PROCESSING SUMMARY")
        print(f"=" * 50)
        print(f"Total books processed: {total}")
        print(f"Successfully updated/added: {successful}")
        print(f"Failed: {failed}")
        print(f"Books to keep: {kept}")
        print(f"Books to give away: {discarded}")
        
        # Show skip log info
        skip_log_file = "/mnt/f/prog/research-tools/data/items_not_added_to_zotero.txt"
        if Path(skip_log_file).exists():
            try:
                with open(skip_log_file, 'r') as f:
                    lines = [line for line in f if line.strip() and not line.startswith('#')]
                print(f"Items in skip log: {len(lines)}")
                print(f"Skip log: {skip_log_file}")
            except:
                pass
        
        if successful > 0:
            print(f"\nSuccessful actions:")
            for decision in decisions:
                if decision.action_taken in ['added', 'updated']:
                    action = "📚 Keep" if decision.keep else "📦 Give away"
                    print(f"  {action} - {decision.isbn} ({decision.action_taken})")

    def log_successful_addition(self, isbn: str, item_key: str):
        """Log successfully added items to prevent reprocessing"""
        try:
            success_log_file = "/mnt/f/prog/research-tools/data/successfully_added_to_zotero.txt"
            
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
        success_log_file = "/mnt/f/prog/research-tools/data/successfully_added_to_zotero.txt"
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

    def interactive_book_processing(self):
        """Interactive processing of found ISBNs with enhanced metadata, skip logic, and advanced tagging"""
        isbn_list = self.get_found_isbns()
        
        if not isbn_list:
            print("No ISBNs found. Please run the image processing first.")
            return
        
        print(f"Found {len(isbn_list)} books to process")
        decisions = []
        
        # Load existing skip log and success log to avoid duplicates
        skip_log_file = "/mnt/f/prog/research-tools/data/items_not_added_to_zotero.txt"
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
        
        # Initialize tag memory for batch processing
        last_tags = []
        
        for i, (isbn, filename) in enumerate(unprocessed_isbns, 1):
            print(f"\n" + "=" * 60)
            print(f"Book {i}/{len(unprocessed_isbns)}: {filename}")
            print(f"ISBN: {isbn}")
            print("=" * 60)
            
            # Check if already in Zotero
            existing_item = self.search_item_by_isbn(isbn)
            
            if existing_item:
                print(f"ALREADY IN your Zotero library:")
                print(f"   Title: {existing_item['data'].get('title', 'Unknown')}")
                creators = existing_item['data'].get('creators', [])
                if creators:
                    print(f"   Author: {creators[0].get('lastName', 'Unknown')}")
                print(f"   Key: {existing_item['key']}")
                
                current_tags = [tag['tag'] for tag in existing_item['data'].get('tags', [])]
                print(f"   Current tags: {current_tags}")
                
                # Get user decision for existing item
                print(f"\nUpdate tags for this existing book?")
                print(f"1. Keep it (add tag: 'Eero har')")
                print(f"2. Give it away (add tags: 'Eero hadde', 'gitt bort')")
                print(f"3. Skip (leave unchanged)")
                
                while True:
                    choice = input("Enter choice (1-3): ").strip()
                    if choice in ['1', '2', '3']:
                        break
                    print("Please enter 1, 2, or 3")
                
                if choice == '3':
                    print("⏭️  Left unchanged")
                    # Log as processed even if unchanged
                    self.log_successful_addition(isbn, existing_item['key'])
                    continue
                
                # Process the decision for existing item
                keep = (choice == '1')
                decision = BookDecision(isbn=isbn, filename=filename, keep=keep)
                
                # Get additional tags for existing item
                additional_tags = self.get_additional_tags(last_tags)
                if additional_tags:
                    last_tags = additional_tags
                
                if keep:
                    base_tags = ['Eero har']
                    all_tags = base_tags + additional_tags
                    success = self.update_item_tags(existing_item['key'], 
                                                  add_tags=all_tags,
                                                  remove_tags=['Eero hadde', 'gitt bort'])
                else:
                    base_tags = ['Eero hadde', 'gitt bort']
                    all_tags = base_tags + additional_tags
                    success = self.update_item_tags(existing_item['key'],
                                                  add_tags=all_tags,
                                                  remove_tags=['Eero har'])
                
                decision.zotero_item_key = existing_item['key']
                decision.action_taken = 'updated' if success else 'failed'
                decisions.append(decision)
                
                # Log successful processing
                if success:
                    self.log_successful_addition(isbn, existing_item['key'])
                
            else:
                # Book not in Zotero - try to get metadata
                print(f"NOT FOUND in your Zotero library")
                
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
                print(f"   Book information found!")
                
                # Get user decision for new item
                print(f"\nAdd this book to your Zotero library?")
                print(f"1. Keep it (add with tag: 'Eero har')")
                print(f"2. Give it away (add with tags: 'Eero hadde', 'gitt bort')")
                print(f"3. Skip (don't add to Zotero)")
                
                while True:
                    choice = input("Enter choice (1-3): ").strip()
                    if choice in ['1', '2', '3']:
                        break
                    print("Please enter 1, 2, or 3")
                
                if choice == '3':
                    print("⏭️  Skipped - not added to Zotero")
                    self.add_to_skip_log(skip_log_file, isbn, filename, reason="user_skipped")
                    existing_skipped.add(isbn)
                    continue
                
                # Add new item with metadata
                keep = (choice == '1')
                decision = BookDecision(isbn=isbn, filename=filename, keep=keep)
                
                # Get additional tags for new item
                metadata_tags = [tag.get('tag', '') if isinstance(tag, dict) else str(tag) for tag in book_template.get('tags', [])]
                additional_tags = self.get_additional_tags(last_tags, metadata_tags)
                if additional_tags:
                    last_tags = additional_tags
                
                base_tags = ['Eero har'] if keep else ['Eero hadde', 'gitt bort']
                all_tags = base_tags + additional_tags
                
                item_key = self.add_item_to_library(book_template, all_tags)
                
                decision.zotero_item_key = item_key
                decision.action_taken = 'added' if item_key else 'failed'
                
                if not item_key:
                    # Failed to add - log it
                    self.add_to_skip_log(skip_log_file, isbn, filename, reason="add_failed")
                    existing_skipped.add(isbn)
                
                decisions.append(decision)
            
            # Small delay to be nice to APIs
            time.sleep(1)
        
        # Save decisions and show summary
        self.save_decisions(decisions)
        self.print_summary(decisions)

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
            
            # Check if user entered numbers
            if user_input.replace(',', '').replace(' ', '').isdigit():
                # Parse number selection (e.g., "1,3" or "1, 3")
                try:
                    numbers = [int(n.strip()) for n in user_input.split(',') if n.strip().isdigit()]
                    selected_tags = []
                    for num in numbers:
                        if 1 <= num <= len(last_tags):
                            selected_tags.append(last_tags[num - 1])
                    return selected_tags
                except ValueError:
                    print(f"   ⚠️  Invalid number format, using all previous tags")
                    return last_tags
            
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