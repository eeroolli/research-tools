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
    
    @staticmethod
    def _sanitize_unicode(text: str) -> str:
        """Sanitize Unicode string by removing invalid surrogates.
        
        Args:
            text: Input string that may contain invalid Unicode surrogates
            
        Returns:
            Cleaned string safe for UTF-8 encoding
        """
        if not isinstance(text, str):
            return text
        
        # Remove UTF-16 surrogates (invalid in UTF-8)
        # Surrogates are in range U+D800 to U+DFFF
        # Use encode/decode with errors='replace' to handle any encoding issues
        try:
            # Try to encode to UTF-8 - this will fail if there are surrogates
            text.encode('utf-8')
            return text
        except (UnicodeEncodeError, UnicodeDecodeError) as e:
            # If encoding fails, log diagnostic info and sanitize
            import logging
            logger = logging.getLogger(__name__)
            logger.warning(
                f"Unicode encoding issue detected: {e}. "
                f"Text length: {len(text)}, "
                f"First 100 chars: {repr(text[:100])}"
            )
            # If encoding fails, use encode/decode with error handling
            # This will replace invalid characters with replacement character
            sanitized = text.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
            logger.info(f"Sanitized text (first 100 chars): {repr(sanitized[:100])}")
            return sanitized
    
    @staticmethod
    def _sanitize_dict(data: Dict) -> Dict:
        """Recursively sanitize all string values in a dictionary.
        
        Args:
            data: Dictionary that may contain strings with invalid Unicode
            
        Returns:
            Dictionary with sanitized strings
        """
        if isinstance(data, dict):
            return {k: ZoteroPaperProcessor._sanitize_dict(v) for k, v in data.items()}
        elif isinstance(data, list):
            return [ZoteroPaperProcessor._sanitize_dict(item) for item in data]
        elif isinstance(data, str):
            return ZoteroPaperProcessor._sanitize_unicode(data)
        else:
            return data
    
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
            language = metadata.get('language', '').strip()
            
            if doi:
                existing = self.search_by_doi(doi)
                if existing:
                    result['action'] = 'duplicate_skipped'
                    result['item_key'] = existing['key']
                    # Update language if provided and missing in existing item
                    if language:
                        self.update_item_field_if_missing(existing['key'], 'language', language)
                    result['success'] = True
                    return result
            
            if title:
                existing = self.search_by_title(title)
                if existing:
                    result['action'] = 'duplicate_skipped'
                    result['item_key'] = existing['key']
                    # Update language if provided and missing in existing item
                    if language:
                        self.update_item_field_if_missing(existing['key'], 'language', language)
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
        # Handle both 'tags' and 'keywords' fields
        tags_to_add = []
        
        # Process 'tags' field (can be list of strings or list of dicts)
        if metadata.get('tags'):
            for tag in metadata['tags']:
                if isinstance(tag, dict):
                    tag_name = tag.get('tag', '')
                else:
                    tag_name = str(tag)
                if tag_name:
                    tags_to_add.append(tag_name)
        
        # Process 'keywords' field (for backward compatibility)
        if metadata.get('keywords'):
            for keyword in metadata['keywords']:
                keyword_str = str(keyword) if not isinstance(keyword, dict) else keyword.get('tag', '')
                if keyword_str and keyword_str not in tags_to_add:
                    tags_to_add.append(keyword_str)
        
        # Add unique tags to item
        for tag_name in tags_to_add:
            # Sanitize tag names to prevent encoding errors
            sanitized_tag = self._sanitize_unicode(tag_name)
            item['tags'].append({'tag': sanitized_tag})
        
        # Sanitize all string fields in the item to prevent UTF-8 encoding errors
        return self._sanitize_dict(item)
    
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
            # Sanitize Unicode to prevent encoding errors
            sanitized_template = self._sanitize_dict(item_template)
            
            response = requests.post(
                f"{self.base_url}/items",
                headers=self.headers,
                json=[sanitized_template],
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
            
            # Sanitize attachment title to prevent encoding errors
            attach_title = self._sanitize_unicode(attach_title)

            # Create attachment item with Windows path
            attachment = {
                'itemType': 'attachment',
                'linkMode': 'linked_file',
                'title': attach_title,
                'path': windows_path,
                'parentItem': item_key
            }
            
            # Sanitize entire attachment dict
            attachment = self._sanitize_dict(attachment)
            
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
            normalized_field = self._normalize_field_name(field_name)

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
            current_value = str(item_data.get(normalized_field, '') or '').strip()
            if current_value:
                # Field already has a value, don't update
                # #region agent log
                try:
                    import time as _time, json as _json, os as _os
                    log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                    with open(log_path, "a", encoding="utf-8") as _f:
                        _f.write(_json.dumps({
                            "sessionId": "debug-session",
                            "runId": "run-enrich2",
                            "hypothesisId": "A2",
                            "location": "zotero/paper_processor.py:update_item_field_if_missing",
                            "message": "skip_update_field_already_present",
                            "data": {
                                "item_key": item_key,
                                "field_name": field_name,
                                "normalized_field": normalized_field,
                                "current_value_preview": current_value[:120],
                            },
                            "timestamp": int(_time.time() * 1000)
                        }) + "\n")
                except Exception:
                    pass
                # #endregion
                return True
            
            # Update field with new value
            item_data[normalized_field] = field_value
            
            # Write changes back
            response = requests.patch(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                json=item_data,
                timeout=10
            )
            # Zotero commonly returns 204 No Content for successful PATCH.
            ok = response.status_code in (200, 204)
            # #region agent log
            try:
                import time as _time, json as _json, os as _os
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run-enrich2",
                        "hypothesisId": "A3",
                        "location": "zotero/paper_processor.py:update_item_field_if_missing",
                        "message": "patch_attempt",
                        "data": {
                            "item_key": item_key,
                            "field_name": field_name,
                            "normalized_field": normalized_field,
                            "sent_value_preview": str(field_value)[:120],
                            "status_code": response.status_code,
                            "ok_200_or_204": ok,
                            "resp_text_preview": (response.text or "")[:200],
                        },
                        "timestamp": int(_time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            return ok
            
        except Exception as e:
            print(f"Error updating item field: {e}")
            # #region agent log
            try:
                import time as _time, json as _json, os as _os
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run-enrich2",
                        "hypothesisId": "A3",
                        "location": "zotero/paper_processor.py:update_item_field_if_missing",
                        "message": "exception",
                        "data": {
                            "item_key": item_key,
                            "field_name": field_name,
                            "normalized_field": normalized_field,
                            "error": str(e),
                        },
                        "timestamp": int(_time.time() * 1000)
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            return False

    def update_item_field(self, item_key: str, field_name: str, field_value) -> bool:
        """Update (overwrite) a Zotero item field regardless of existing value.

        This is used for explicitly user-approved enrichment overwrites.

        Args:
            item_key: Zotero item key
            field_name: Field name (Zotero API key or normalized metadata key)
            field_value: Value to set

        Returns:
            True if successful, False otherwise
        """
        try:
            normalized_field = self._normalize_field_name(field_name)

            # Get current item (need version for safe patch)
            response = requests.get(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                timeout=10
            )
            if response.status_code != 200:
                return False

            item_json = response.json()
            item_data = item_json.get('data', {})
            version = item_json.get('version')
            if not version:
                # Fallback: try header-based version if present
                version = response.headers.get('Last-Modified-Version')

            item_data[normalized_field] = field_value

            update_headers = {**self.headers}
            if version is not None:
                update_headers['If-Unmodified-Since-Version'] = str(version)

            # Patch only the fields we intend to update plus key/version if available
            patch_data = {'key': item_key, normalized_field: field_value}
            if version is not None:
                patch_data['version'] = int(version) if str(version).isdigit() else version

            update_response = requests.patch(
                f"{self.base_url}/items/{item_key}",
                headers=update_headers,
                json=patch_data,
                timeout=10
            )
            # Zotero returns 204 No Content on success for key-based writes
            return update_response.status_code in (200, 204)
        except Exception as e:
            print(f"Error overwriting item field: {e}")
            return False

    def _normalize_field_name(self, field_name: str) -> str:
        """Map common metadata field names to Zotero API item data keys.

        Accepts either already-correct Zotero keys (e.g., 'DOI', 'abstractNote')
        or normalized metadata keys (e.g., 'doi', 'abstract', 'journal').
        """
        if not field_name:
            return field_name

        # Preserve exact Zotero keys commonly used elsewhere in this repo
        passthrough = {
            'url',
            'abstractNote',
            'publicationTitle',
            'DOI',
            'ISBN',
            'ISSN',
            'language',
            'title',
            'date',
            'volume',
            'issue',
            'pages',
            'publisher',
        }
        if field_name in passthrough:
            return field_name

        key = str(field_name)
        lower = key.lower()
        mapping = {
            'doi': 'DOI',
            'isbn': 'ISBN',
            'issn': 'ISSN',
            'journal': 'publicationTitle',
            'abstract': 'abstractNote',
            'year': 'date',
        }
        return mapping.get(lower, field_name)
    
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
            # #region agent log
            try:
                import time as _time, json as _json, os
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'T2',
                        'location': 'paper_processor.py:update_item_tags',
                        'message': 'Update tags entry',
                        'data': {
                            'item_key': item_key,
                            'add_count': len(add_tags) if add_tags else 0,
                            'remove_count': len(remove_tags) if remove_tags else 0
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion

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
            # #region agent log
            try:
                import time as _time, json as _json, os
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'T3',
                        'location': 'paper_processor.py:update_item_tags',
                        'message': 'Fetched item for tag update',
                        'data': {
                            'item_key': item_key,
                            'status_code': response.status_code,
                            'version': item_data.get('version'),
                            'current_tag_count': len(current_tags)
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
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
            
            # Prepare headers with If-Unmodified-Since-Version for key-based writes
            update_headers = {
                **self.headers,
                'If-Unmodified-Since-Version': str(item_data['version'])
            }
            
            # Update item
            update_response = requests.patch(
                f"{self.base_url}/items/{item_key}",
                headers=update_headers,
                json=update_data,
                timeout=10
            )
            
            # #region agent log
            try:
                import time as _time, json as _json, os
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(_json.dumps({
                        'sessionId': 'debug-session',
                        'runId': 'run1',
                        'hypothesisId': 'T4',
                        'location': 'paper_processor.py:update_item_tags',
                        'message': 'Tag update response',
                        'data': {
                            'item_key': item_key,
                            'status_code': update_response.status_code,
                            'response_text_len': len(update_response.text or ''),
                            'response_text_preview': (update_response.text or '')[:200]
                        },
                        'timestamp': int(_time.time() * 1000)
                    }) + '\n')
            except Exception:
                pass
            # #endregion
            
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
    
    def add_note_to_item(self, item_key: str, note_text: str) -> bool:
        """Add a note to an existing Zotero item as a child note.
        
        Args:
            item_key: Zotero item key (parent item)
            note_text: Text content of the note
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Sanitize note text to prevent encoding errors
            sanitized_note = self._sanitize_unicode(note_text)
            
            # Create note item with parent reference
            note_item = {
                'itemType': 'note',
                'parentItem': item_key,
                'note': sanitized_note
            }
            
            # Sanitize entire note item dict
            note_item = self._sanitize_dict(note_item)
            
            response = requests.post(
                f"{self.base_url}/items",
                headers=self.headers,
                json=[note_item],
                timeout=10
            )
            
            if response.status_code in (200, 201):
                return True
            else:
                print(f"❌ Failed to add note: {response.status_code}")
                print(f"Response: {response.text}")
                return False
                
        except Exception as e:
            print(f"Error adding note: {e}")
            return False
    
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
            
            # Sanitize attachment title to prevent encoding errors
            title = self._sanitize_unicode(title)

            # Create attachment item with Windows path
            attachment = {
                'itemType': 'attachment',
                'linkMode': 'linked_file',
                'title': title,
                'path': windows_path,
                'parentItem': item_key
            }
            
            # Sanitize entire attachment dict
            attachment = self._sanitize_dict(attachment)
            
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

    def delete_item(self, item_key: str) -> bool:
        """Delete a Zotero item (e.g., an attachment) by key via Zotero API.
        
        Args:
            item_key: Zotero item key to delete
        
        Returns:
            True if deleted successfully
        """
        try:
            response = requests.delete(
                f"{self.base_url}/items/{item_key}",
                headers=self.headers,
                timeout=10
            )
            return response.status_code in (200, 204)
        except Exception as e:
            print(f"Error deleting Zotero item {item_key}: {e}")
            return False


if __name__ == "__main__":
    # Test
    processor = ZoteroPaperProcessor()
    print("Zotero Paper Processor initialized")
    print(f"Library: {processor.library_type}/{processor.library_id}")

