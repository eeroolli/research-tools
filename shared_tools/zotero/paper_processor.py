#!/usr/bin/env python3
"""
Zotero integration for academic papers.
Similar to book_processor.py but for papers.

Handles:
- Adding papers to Zotero
- Duplicate detection (by DOI and title)
- PDF linking (linked files, not uploaded)
- Item type detection (journal article, conference paper, etc.)
- Metadata conversion from internal format to Zotero format
"""

import sys
import requests
import configparser
from pathlib import Path
from typing import Dict, Optional, Union
import ntpath
from difflib import SequenceMatcher

sys.path.insert(0, str(Path(__file__).parent.parent.parent))


class ZoteroPaperProcessor:
    """Zotero integration for academic papers."""
    
    def __init__(self, config_file: str = None):
        """Initialize processor.
        
        Args:
            config_file: Path to config file (uses default if None)
        """
        if config_file is None:
            root_dir = Path(__file__).parent.parent.parent
            config_file = root_dir / "config.personal.conf"
        
        self.config_file = config_file
        self.load_config()
        
        # Zotero API setup
        self.base_url = f"https://api.zotero.org/users/{self.library_id}"
        self.headers = {
            'Zotero-API-Key': self.api_key,
            'Content-Type': 'application/json'
        }
    
    def load_config(self):
        """Load Zotero configuration."""
        config = configparser.ConfigParser()
        
        # Read both config files (personal overrides main)
        root_dir = Path(__file__).parent.parent.parent
        config.read([
            root_dir / 'config.conf',
            root_dir / 'config.personal.conf'
        ])
        
        # Try new format first, fall back to legacy
        self.api_key = config.get('APIS', 'zotero_api_key', fallback='').strip()
        self.library_id = config.get('APIS', 'zotero_library_id', fallback='').strip()
        self.library_type = config.get('APIS', 'zotero_library_type', fallback='user').strip()
        
        if not self.api_key or not self.library_id:
            # Fall back to legacy format
            self.api_key = config.get('zotero', 'zotero_api_key', fallback='').strip()
            self.library_id = config.get('zotero', 'zotero_library_id', fallback='').strip()
            self.library_type = config.get('zotero', 'zotero_library_type', fallback='user').strip()
        
        if not self.api_key or not self.library_id:
            raise ValueError("Missing Zotero API credentials in config")
    
    def add_paper(self, metadata: Dict, pdf_path: Union[str, Path, None]) -> Dict:
        """Add paper to Zotero library.
        
        Args:
            metadata: Paper metadata from extraction
            pdf_path: Path to PDF file (in publications directory)
            
        Returns:
            Result dict with success status and item key
        """
        result = {
            'success': False,
            'item_key': None,
            'error': None,
            'action': None
        }
        
        try:
            # Step 1: Check for duplicates
            doi = metadata.get('doi')
            title = metadata.get('title')
            
            if doi:
                existing = self.search_by_doi(doi)
                if existing:
                    result['action'] = 'duplicate_skipped'
                    result['item_key'] = existing['key']
                    result['success'] = True
                    return result
            
            if title:
                existing = self.search_by_title(title)
                if existing:
                    result['action'] = 'duplicate_skipped'
                    result['item_key'] = existing['key']
                    result['success'] = True
                    return result
            
            # Step 2: Create Zotero item
            item_template = self.metadata_to_zotero(metadata)
            item_key = self.create_item(item_template)
            
            if not item_key:
                result['error'] = "Failed to create Zotero item"
                return result
            
            # Step 3: Attach PDF
            pdf_attached = False
            skipped_attachment = pdf_path is None
            if not skipped_attachment:
                pdf_attached = self.attach_pdf(item_key, pdf_path, title)
            
            if pdf_attached:
                result['success'] = True
                result['item_key'] = item_key
                result['action'] = 'added_with_pdf'
            else:
                result['success'] = True
                result['item_key'] = item_key
                result['action'] = 'added_without_pdf'
                if not skipped_attachment:
                    result['error'] = "PDF attachment failed"
            
            return result
            
        except Exception as e:
            result['error'] = str(e)
            return result
    
    def metadata_to_zotero(self, metadata: Dict) -> Dict:
        """Convert our metadata format to Zotero item format.
        
        Args:
            metadata: Our internal metadata format
            
        Returns:
            Zotero item template
        """
        # Determine item type
        item_type = self.determine_item_type(metadata)
        
        # Build creators list
        creators = []
        for author in metadata.get('authors', []):
            # Split "LastName, FirstName" or "FirstName LastName"
            if ',' in author:
                parts = author.split(',', 1)
                last_name = parts[0].strip()
                first_name = parts[1].strip() if len(parts) > 1 else ''
            else:
                parts = author.rsplit(' ', 1)
                first_name = parts[0].strip() if len(parts) > 1 else ''
                last_name = parts[-1].strip()
            
            creators.append({
                'creatorType': 'author',
                'firstName': first_name,
                'lastName': last_name
            })
        
        # Build item template
        item = {
            'itemType': item_type,
            'title': metadata.get('title', ''),
            'creators': creators,
            'abstractNote': metadata.get('abstract', ''),
            'date': str(metadata.get('year', '')),
            'language': metadata.get('language', ''),
            'DOI': metadata.get('doi', ''),
            'url': metadata.get('url', ''),
            'tags': []
        }
        
        # Add type-specific fields
        if item_type == 'journalArticle':
            item['publicationTitle'] = metadata.get('journal', '')
            item['volume'] = metadata.get('volume', '')
            item['issue'] = metadata.get('issue', '')
            item['pages'] = metadata.get('pages', '')
            item['ISSN'] = metadata.get('issn', '')
        
        elif item_type == 'conferencePaper':
            item['proceedingsTitle'] = metadata.get('journal', '')  # Journal field often contains conference
            item['pages'] = metadata.get('pages', '')
        
        elif item_type == 'bookSection':
            item['bookTitle'] = metadata.get('book_title', '')
            item['publisher'] = metadata.get('publisher', '')
            item['pages'] = metadata.get('pages', '')
            item['ISBN'] = metadata.get('isbn', '')
        
        # Add tags from metadata
        if metadata.get('keywords'):
            for keyword in metadata['keywords']:
                item['tags'].append({'tag': keyword})
        
        return item
    
    def determine_item_type(self, metadata: Dict) -> str:
        """Determine Zotero item type from metadata.
        
        Args:
            metadata: Paper metadata
            
        Returns:
            Zotero item type string
        """
        doc_type = metadata.get('document_type', '').lower()
        
        # Map our types to Zotero types
        type_mapping = {
            'journal_article': 'journalArticle',
            'conference_paper': 'conferencePaper',
            'book_chapter': 'bookSection',
            'preprint': 'preprint',
            'working_paper': 'preprint',  # Working papers map to preprint in Zotero
            'manuscript': 'manuscript',    # True manuscripts (no institution)
            'report': 'report',
            'thesis': 'thesis',
            'news_article': 'newspaperArticle',
            'web_article': 'webpage'
        }
        
        zotero_type = type_mapping.get(doc_type, 'journalArticle')
        
        # Additional heuristics if type unclear
        if zotero_type == 'journalArticle':
            if metadata.get('book_title'):
                zotero_type = 'bookSection'
            elif metadata.get('url') and not metadata.get('doi'):
                zotero_type = 'webpage'
        
        return zotero_type
    
    def search_by_doi(self, doi: str) -> Optional[Dict]:
        """Search Zotero library for item by DOI.
        
        Args:
            doi: DOI to search for
            
        Returns:
            Zotero item or None
        """
        try:
            response = requests.get(
                f"{self.base_url}/items",
                headers=self.headers,
                params={
                    'q': doi,
                    'qmode': 'everything',
                    'format': 'json',
                    'limit': 10
                },
                timeout=10
            )
            
            if response.status_code == 200:
                items = response.json()
                for item in items:
                    item_doi = item['data'].get('DOI', '').strip()
                    if item_doi.lower() == doi.lower():
                        return item
            
            return None
            
        except Exception:
            return None
    
    def search_by_title(self, title: str, threshold: float = 0.85) -> Optional[Dict]:
        """Search Zotero library for item by title similarity.
        
        Args:
            title: Title to search for
            threshold: Similarity threshold (0-1)
            
        Returns:
            Zotero item or None
        """
        try:
            response = requests.get(
                f"{self.base_url}/items",
                headers=self.headers,
                params={
                    'q': title,
                    'qmode': 'everything',
                    'format': 'json',
                    'limit': 20
                },
                timeout=10
            )
            
            if response.status_code == 200:
                items = response.json()
                for item in items:
                    item_title = item['data'].get('title', '')
                    similarity = SequenceMatcher(None, title.lower(), item_title.lower()).ratio()
                    if similarity >= threshold:
                        return item
            
            return None
            
        except Exception:
            return None
    
    def create_item(self, item_template: Dict) -> Optional[str]:
        """Create new item in Zotero library.
        
        Args:
            item_template: Zotero item template
            
        Returns:
            Item key or None
        """
        try:
            response = requests.post(
                f"{self.base_url}/items",
                headers=self.headers,
                json=[item_template],
                timeout=10
            )
            
            if response.status_code == 200:
                result = response.json()
                return result['successful']['0']['key']
            
            return None
            
        except Exception:
            return None
    
    def attach_pdf(self, item_key: str, pdf_path: Union[str, Path], title: str) -> bool:
        """Attach PDF to Zotero item as linked file.
        
        Args:
            item_key: Zotero item key
            pdf_path: Path to PDF file
            title: PDF title
            
        Returns:
            True if successful
        """
        try:
            # Convert WSL path to Windows path for Zotero (runs on Windows)
            path_str = str(pdf_path)
            windows_path = self._convert_wsl_to_windows_path(path_str)
            
            filename = ntpath.basename(windows_path)
            attach_title = filename or (title or 'PDF')

            # Create attachment item with Windows path
            attachment = {
                'itemType': 'attachment',
                'linkMode': 'linked_file',
                'title': attach_title,
                'path': windows_path,
                'parentItem': item_key
            }
            
            response = requests.post(
                f"{self.base_url}/items",
                headers=self.headers,
                json=[attachment],
                timeout=10
            )
            
            return response.status_code == 200
            
        except Exception:
            return False

    def update_item_field_if_missing(self, item_key: str, field_name: str, field_value: str) -> bool:
        """Update a Zotero item field if it's currently empty/missing.
        
        Args:
            item_key: Zotero item key
            field_name: Name of the field to update (e.g., 'url', 'abstractNote')
            field_value: Value to set
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current item
            response = requests.get(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code != 200:
                return False
            
            item_data = response.json().get('data', {})
            
            # Check if field is empty/missing
            current_value = item_data.get(field_name, '').strip()
            if current_value:
                # Field already has a value, don't update
                return True
            
            # Update field with new value
            item_data[field_name] = field_value
            
            # Write changes back
            response = requests.patch(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                json=item_data,
                timeout=10
            )
            
            return response.status_code == 200
            
        except Exception as e:
            print(f"Error updating item field: {e}")
            return False
    
    def update_item_tags(self, item_key: str, add_tags: list = None, remove_tags: list = None) -> bool:
        """Update tags on an existing Zotero item.
        
        Args:
            item_key: Zotero item key
            add_tags: List of tag names to add (optional)
            remove_tags: List of tag names to remove (optional)
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Get current item data
            response = requests.get(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                timeout=10
            )
            
            if response.status_code != 200:
                print(f"❌ Failed to get item: {response.status_code}")
                return False
            
            item_data = response.json()
            current_tags = item_data['data'].get('tags', [])
            
            # Convert current tags to list of tag names for easier manipulation
            current_tag_names = [tag['tag'] if isinstance(tag, dict) else str(tag) for tag in current_tags]
            
            # Remove specified tags
            if remove_tags:
                current_tag_names = [tag for tag in current_tag_names if tag not in remove_tags]
            
            # Add new tags (avoid duplicates)
            if add_tags:
                existing_tag_names_lower = [t.lower() for t in current_tag_names]
                for tag_name in add_tags:
                    if tag_name and tag_name.lower() not in existing_tag_names_lower:
                        current_tag_names.append(tag_name)
            
            # Convert back to Zotero format (list of dicts)
            updated_tags = [{'tag': tag_name} for tag_name in current_tag_names if tag_name]
            
            # Prepare update data
            update_data = {
                'key': item_data['data']['key'],
                'version': item_data['version'],
                'tags': updated_tags
            }
            
            # Update item
            update_response = requests.patch(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                json=update_data,
                timeout=10
            )
            
            if update_response.status_code == 204:
                return True
            else:
                print(f"❌ Failed to update tags: {update_response.status_code}")
                print(f"Response: {update_response.text}")
                return False
                
        except Exception as e:
            print(f"❌ Error updating tags: {e}")
            return False
    
    def _convert_wsl_to_windows_path(self, path_str: str) -> str:
        """Convert WSL path to Windows path format.
        
        Zotero runs on Windows, so it needs Windows paths (G:\...) not WSL paths (/mnt/g/...).
        
        Args:
            path_str: Path string in WSL format (/mnt/g/...) or Windows format (G:\...)
            
        Returns:
            Windows path string (G:\My Drive\...) or original if already Windows format
        """
        path_str = str(path_str)
        
        # If already Windows path (contains : or starts with letter drive), return as-is
        if ':' in path_str or (len(path_str) > 1 and path_str[1] == ':'):
            # Normalize Windows path separators
            return path_str.replace('/', '\\')
        
        # If WSL path (starts with /mnt/), convert to Windows
        if path_str.startswith('/mnt/'):
            # Extract drive letter: /mnt/g/... -> g
            parts = path_str.split('/')
            if len(parts) >= 4 and parts[1] == 'mnt':
                drive_letter = parts[2].upper()
                # Get remainder after /mnt/drive/
                remainder = '/'.join(parts[3:])
                # Convert to Windows format: G:\remainder
                windows_path = f"{drive_letter}:\\{remainder}"
                # Normalize separators
                windows_path = windows_path.replace('/', '\\')
                return windows_path
        
        # If not recognized format, return as-is (might be relative path)
        return path_str
    
    def attach_pdf_to_existing(self, item_key: str, pdf_path: Union[str, Path]) -> bool:
        """Attach PDF to existing Zotero item.
        
        This is used when user selects an existing Zotero item from local search
        and wants to attach the scanned PDF to it.
        
        Args:
            item_key: Zotero item key
            pdf_path: Path to PDF file (can be WSL or Windows format)
            
        Returns:
            True if successful
        """
        try:
            # Convert WSL path to Windows path for Zotero (runs on Windows)
            path_str = str(pdf_path)
            windows_path = self._convert_wsl_to_windows_path(path_str)
            
            filename = ntpath.basename(windows_path)
            title = filename.rsplit('.', 1)[0] if '.' in filename else filename

            # Create attachment item with Windows path
            attachment = {
                'itemType': 'attachment',
                'linkMode': 'linked_file',
                'title': title,
                'path': windows_path,
                'parentItem': item_key
            }
            
            response = requests.post(
                f"{self.base_url}/items",
                headers=self.headers,
                json=[attachment],
                timeout=10
            )
            
            if response.status_code == 200:
                return True
            else:
                # Log error for debugging
                print(f"Zotero API error: {response.status_code}")
                print(f"Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"Error attaching PDF: {e}")
            return False


if __name__ == "__main__":
    # Test
    processor = ZoteroPaperProcessor()
    print("Zotero Paper Processor initialized")
    print(f"Library: {processor.library_type}/{processor.library_id}")

