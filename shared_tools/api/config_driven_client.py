"""
Configuration-driven national library client.
Uses YAML configuration to handle different API structures without hardcoded clients.
"""
import yaml
import logging
import json
import xml.etree.ElementTree as ET
from typing import Optional, Dict, Any, List
from pathlib import Path
from .base_client import BaseAPIClient


class ConfigDrivenNationalLibraryClient(BaseAPIClient):
    """Configuration-driven client for national library APIs."""
    
    def __init__(self, config_path: str, library_id: str, api_key: Optional[str] = None):
        """
        Initialize client using configuration file.
        
        Args:
            config_path: Path to national_library_config.yaml
            library_id: Library identifier (e.g., 'norwegian', 'swedish')
            api_key: Optional API key
        """
        self.library_id = library_id
        self.config = self._load_config(config_path)
        self.library_config = self._get_library_config(library_id)
        
        # Initialize base client with configured URL
        api_config = self.library_config['api']
        super().__init__(
            base_url=api_config['base_url'],
            api_key=api_key,
            rate_limit_delay=self.config.get('global_settings', {}).get('rate_limit_delay', 1.0)
        )
        
        self.logger = logging.getLogger(f"{__name__}.{library_id}")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """Load YAML configuration file."""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config from {config_path}: {e}")
            raise
    
    def _get_library_config(self, library_id: str) -> Dict[str, Any]:
        """Get configuration for specific library."""
        libraries = self.config.get('libraries', {})
        if library_id not in libraries:
            raise ValueError(f"Library '{library_id}' not found in configuration")
        return libraries[library_id]
    
    def search_papers(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for academic papers using configured API."""
        return self._search_items(query, item_type='papers', **kwargs)
    
    def search_books(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for books using configured API."""
        return self._search_items(query, item_type='books', **kwargs)
    
    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for items using configured API."""
        item_type = kwargs.get('item_type', 'both')
        
        # Remove item_type from kwargs to avoid passing it to _search_items
        search_kwargs = {k: v for k, v in kwargs.items() if k != 'item_type'}
        
        if item_type == 'papers':
            return self.search_papers(query, **search_kwargs)
        elif item_type == 'books':
            return self.search_books(query, **search_kwargs)
        else:
            # Search both and combine results
            papers_result = self.search_papers(query, **search_kwargs)
            books_result = self.search_books(query, **search_kwargs)
            
            return {
                'papers': papers_result.get('papers', []),
                'books': books_result.get('books', []),
                'total': papers_result.get('total', 0) + books_result.get('total', 0),
                'source': self.library_config['name']
            }
    
    def get_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item by ID using configured API."""
        try:
            api_config = self.library_config['api']
            endpoint = api_config['endpoints']['item'].format(id=item_id)
            return self._make_request_with_format_detection(endpoint, {})
        except Exception as e:
            self.logger.error(f"Failed to get item {item_id}: {e}")
            return {}
    
    def _search_items(self, query: str, item_type: str, **kwargs) -> Dict[str, Any]:
        """Generic search method for papers or books."""
        try:
            api_config = self.library_config['api']
            endpoint = api_config['endpoints']['search']
            
            # Build parameters based on configuration
            params = self._build_search_params(query, item_type, **kwargs)
            
            # Get headers from configuration
            headers = api_config.get('headers', {})
            
            # Make API request
            response = self._make_request_with_format_detection(endpoint, params, headers)
            
            # Parse response using configuration
            return self._parse_response(response, item_type, query)
            
        except Exception as e:
            self.logger.error(f"Search failed for {item_type}: {e}")
            return {'papers' if item_type == 'papers' else 'books': [], 'total': 0, 'source': self.library_config['name']}
    
    def _build_search_params(self, query: str, item_type: str, **kwargs) -> Dict[str, Any]:
        """Build search parameters based on configuration."""
        api_config = self.library_config['api']
        params = api_config.get('parameters', {}).copy()
        
        # Add query - only if neither 'q' nor 'query' are already configured
        if 'q' not in params and 'query' not in params:
            params['q'] = query
        
        # Handle parameter substitution (e.g., {query} in bibkeys)
        for key, value in params.items():
            if isinstance(value, str) and '{query}' in value:
                params[key] = value.format(query=query)
        
        # Add size if specified
        if 'size' in kwargs:
            params['size'] = kwargs['size']
        
        # Add content type based on item type
        if item_type == 'papers':
            content_classes = params.get('content_classes_papers')
            if content_classes:
                params['contentClasses'] = content_classes
            
            # Swedish API specific
            if 'type_papers' in params:
                params['type'] = params.pop('type_papers')
                
        elif item_type == 'books':
            content_classes = params.get('content_classes_books')
            if content_classes:
                params['contentClasses'] = content_classes
            
            # Swedish API specific
            if 'type_books' in params:
                params['type'] = params.pop('type_books')
        
        return params
    
    def _parse_response(self, response: Dict[str, Any], item_type: str, query: str = None) -> Dict[str, Any]:
        """Parse API response using configuration."""
        try:
            # Get parsing configuration
            parsing_config = self.library_config.get('response_parsing', {})
            results_path = parsing_config.get('results_path', 'results')
            total_path = parsing_config.get('total_path', 'total')
            is_direct_result = parsing_config.get('is_direct_result', False)
            
            # Handle parameter substitution in results_path (e.g., {isbn} -> actual ISBN)
            if query and '{isbn}' in results_path:
                results_path = results_path.format(isbn=query)
            
            # Extract results using dot notation path
            if is_direct_result:
                # For direct results (like OpenLibrary), the response IS the item
                item_data = self._get_nested_value(response, results_path, None)
                items = [item_data] if item_data else []
            else:
                items = self._get_nested_value(response, results_path, [])
                # Ensure items is always a list
                if not isinstance(items, list):
                    items = [items] if items else []
            
            total = self._get_nested_value(response, total_path, len(items) if is_direct_result else 0)
            
            # Parse each item using field mappings
            parsed_items = []
            field_mappings = self.library_config['field_mappings'][item_type]
            
            for item in items:
                parsed_item = self._parse_item(item, field_mappings, item_type)
                if parsed_item:
                    parsed_items.append(parsed_item)
            
            return {
                item_type: parsed_items,
                'total': total,
                'source': self.library_config['name']
            }
            
        except Exception as e:
            self.logger.error(f"Failed to parse response: {e}")
            return {item_type: [], 'total': 0, 'source': self.library_config['name']}

    def _parse_xml_response(self, xml_text: str) -> Dict[str, Any]:
        """Parse XML response into a dictionary structure."""
        try:
            root = ET.fromstring(xml_text)
            
            # Convert XML to dictionary recursively
            def xml_to_dict(element):
                result = {}
                
                # Add attributes
                if element.attrib:
                    result['@attributes'] = element.attrib
                
                # Add text content if present and no children
                if element.text and element.text.strip():
                    if len(element) == 0:  # No child elements
                        return element.text.strip()
                    else:  # Has both text and children
                        result['text'] = element.text.strip()
                
                # Process child elements
                for child in element:
                    child_data = xml_to_dict(child)
                    
                    # Remove namespace prefix from tag name for easier access
                    tag_name = child.tag
                    if '}' in tag_name:
                        tag_name = tag_name.split('}', 1)[1]
                    
                    # Handle multiple children with same tag
                    if tag_name in result:
                        if not isinstance(result[tag_name], list):
                            result[tag_name] = [result[tag_name]]
                        result[tag_name].append(child_data)
                    else:
                        result[tag_name] = child_data
                
                return result
            
            return xml_to_dict(root)
            
        except ET.ParseError as e:
            self.logger.error(f"Failed to parse XML: {e}")
            return {}
    
    def _make_request_with_format_detection(self, endpoint: str, params: Dict[str, Any], headers: Dict[str, str] = None) -> Dict[str, Any]:
        """Make request and handle both JSON and XML responses."""
        import requests
        
        if endpoint and endpoint.strip():
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
        else:
            url = self.base_url
        
        # Merge custom headers with session headers
        request_headers = {}
        if hasattr(self.session, 'headers'):
            request_headers.update(self.session.headers)
        if headers:
            request_headers.update(headers)
        
        try:
            response = self.session.get(url, params=params, headers=request_headers, timeout=30)
            response.raise_for_status()
            
            # Check content type to determine parsing method
            content_type = response.headers.get('content-type', '').lower()
            
            if 'application/json' in content_type:
                return response.json()
            elif 'application/xml' in content_type or 'text/xml' in content_type:
                return self._parse_xml_response(response.text)
            else:
                # Try JSON first, fall back to XML
                try:
                    return response.json()
                except (ValueError, json.JSONDecodeError):
                    return self._parse_xml_response(response.text)
                    
        except requests.RequestException as e:
            print(f"API request failed: {e}")
            raise
    
    def _parse_item(self, item: Dict[str, Any], field_mappings: Dict[str, str], item_type: str) -> Dict[str, Any]:
        """Parse individual item using field mappings."""
        try:
            parsed_item = {}
            
            # Parse each field using dot notation
            for field_name, field_path in field_mappings.items():
                value = self._extract_field_value(item, field_path)
                if value is not None:
                    parsed_item[field_name] = value
            
            # Special handling for authors
            if 'authors' in parsed_item:
                parsed_item['authors'] = self._parse_authors(parsed_item['authors'])
            
            # Add language if not specified
            if 'language' not in parsed_item:
                parsed_item['language'] = self.library_config['language_codes'][0]
            
            # Add source
            parsed_item['source'] = self.library_config['name']
            
            return parsed_item
            
        except Exception as e:
            self.logger.error(f"Failed to parse item: {e}")
            return None
    
    def _extract_field_value(self, data: Dict[str, Any], field_path: str) -> Any:
        """Extract value using dot notation path, supporting array indexing."""
        try:
            parts = field_path.split('.')
            current = data
            
            for part in parts:
                if '[' in part and ']' in part:
                    # Handle array indexing like "identifiers[type=DOI]"
                    field_name = part.split('[')[0]
                    index_expr = part.split('[')[1].split(']')[0]
                    
                    if field_name:
                        current = current.get(field_name, [])
                    
                    if '=' in index_expr:
                        # Handle conditional indexing like "type=DOI" or "role.code=aut"
                        key, value = index_expr.split('=', 1)
                        for item in current:
                            if isinstance(item, dict):
                                # Handle nested property access like "role.code"
                                if '.' in key:
                                    nested_parts = key.split('.')
                                    nested_value = item
                                    for nested_part in nested_parts:
                                        if isinstance(nested_value, dict):
                                            nested_value = nested_value.get(nested_part)
                                        else:
                                            nested_value = None
                                            break
                                    
                                    if nested_value == value:
                                        current = item
                                        break
                                else:
                                    # Handle simple property access
                                    if item.get(key) == value:
                                        current = item
                                        break
                        else:
                            return None
                    else:
                        # Handle numeric indexing
                        index = int(index_expr)
                        current = current[index]
                else:
                    current = current.get(part)
                    if current is None:
                        return None
            
            return current
            
        except (KeyError, IndexError, ValueError):
            return None
    
    def _parse_authors(self, authors_data: Any) -> List[str]:
        """Parse authors based on configuration."""
        try:
            author_config = self.library_config.get('author_parsing', {})
            format_type = author_config.get('format', 'name')
            separator = author_config.get('separator')
            clean_patterns = author_config.get('clean_patterns', [])
            
            if not authors_data:
                return []
            
            authors = []
            
            if isinstance(authors_data, list):
                for author in authors_data:
                    if isinstance(author, dict):
                        # Check if this is a BIBFRAME contribution with agent
                        if 'agent' in author:
                            # Check if this is an author contribution
                            role = author.get('role')
                            is_author = False
                            
                            if isinstance(role, list):
                                # Role is a list, check if any role has code 'aut'
                                for r in role:
                                    if isinstance(r, dict) and r.get('code') == 'aut':
                                        is_author = True
                                        break
                            elif isinstance(role, dict) and role.get('code') == 'aut':
                                is_author = True
                            
                            if is_author:
                                agent = author['agent']
                                if isinstance(agent, dict):
                                    # BIBFRAME agent structure
                                    family_name = agent.get('familyName', '')
                                    given_name = agent.get('givenName', '')
                                    if family_name and given_name:
                                        authors.append(f"{given_name} {family_name}")
                                    elif family_name:
                                        authors.append(family_name)
                        
                        # Handle Finna author structure
                        elif 'name' in author and 'type' in author:
                            # Finna author structure: {"name": "Liebkind, Karmela", "type": "Personal Name"}
                            name = author.get('name', '')
                            if name:
                                authors.append(name)
                        
                        # Handle OpenLibrary author structure
                        elif 'name' in author:
                            # OpenLibrary author structure: {"name": "James H. Austin"}
                            name = author.get('name', '')
                            if name:
                                authors.append(name)
                        
                        # Handle direct agent data (fallback)
                        elif 'familyName' in author and 'givenName' in author:
                            # Direct BIBFRAME agent structure
                            family_name = author.get('familyName', '')
                            given_name = author.get('givenName', '')
                            if family_name and given_name:
                                authors.append(f"{given_name} {family_name}")
                            elif family_name:
                                authors.append(family_name)
                        elif format_type == 'lastname_firstname':
                            # Legacy structure
                            last_name = author.get('lastName', '')
                            first_name = author.get('firstName', '')
                            if last_name and first_name:
                                authors.append(f"{first_name} {last_name}")
                            elif last_name:
                                authors.append(last_name)
                        else:
                            name = author.get('name', '')
                            if name:
                                authors.append(name)
                    elif isinstance(author, str):
                        # Handle string author data
                        if separator and separator in author:
                            # Parse "LastName, FirstName" format
                            parts = author.split(separator)
                            if len(parts) >= 2:
                                last_name = parts[0].strip()
                                first_name = parts[1].strip()
                                authors.append(f"{first_name} {last_name}")
                            else:
                                authors.append(author.strip())
                        else:
                            authors.append(author.strip())
            elif isinstance(authors_data, str):
                # Single author as string
                if separator and separator in authors_data:
                    parts = authors_data.split(separator)
                    if len(parts) >= 2:
                        last_name = parts[0].strip()
                        first_name = parts[1].strip()
                        authors.append(f"{first_name} {last_name}")
                    else:
                        authors.append(authors_data.strip())
                else:
                    authors.append(authors_data.strip())
            
            # Clean up authors
            cleaned_authors = []
            for author in authors:
                author = author.strip()
                if author and author not in clean_patterns:
                    cleaned_authors.append(author)
            
            return cleaned_authors[:10]  # Limit to reasonable number
            
        except Exception as e:
            self.logger.error(f"Failed to parse authors: {e}")
            return []
    
    def _get_nested_value(self, data: Dict[str, Any], path: str, default: Any = None) -> Any:
        """Get nested value using dot notation."""
        try:
            parts = path.split('.')
            current = data
            
            for part in parts:
                if isinstance(current, dict):
                    current = current.get(part)
                elif isinstance(current, list):
                    index = int(part)
                    current = current[index]
                else:
                    return default
                
                if current is None:
                    return default
            
            return current
            
        except (KeyError, IndexError, ValueError, TypeError):
            return default
