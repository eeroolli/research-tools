"""
Configuration-driven national library manager.
Uses YAML configuration to manage all national library clients dynamically.
"""
import logging
from typing import Optional, Dict, Any, List
from pathlib import Path
import yaml
from .config_driven_client import ConfigDrivenNationalLibraryClient


class ConfigDrivenNationalLibraryManager:
    """Manager for national library clients using YAML configuration."""
    
    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize manager with configuration file.
        
        Args:
            config_path: Path to national_library_config.yaml. If None, uses default path.
        """
        if config_path is None:
            # Use default path relative to this file
            config_path = Path(__file__).parent / "national_library_config.yaml"
        
        self.config_path = str(config_path)
        self.config = self._load_config()
        self.clients = {}
        self._initialize_clients()
        
        self.logger = logging.getLogger(__name__)
    
    def _load_config(self) -> Dict[str, Any]:
        """Load YAML configuration file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            logging.error(f"Failed to load national library config from {self.config_path}: {e}")
            return {'libraries': {}}
    
    def _initialize_clients(self):
        """Initialize clients for all configured libraries."""
        libraries = self.config.get('libraries', {})
        
        for library_id, library_config in libraries.items():
            try:
                # Create client using configuration
                client = ConfigDrivenNationalLibraryClient(
                    config_path=self.config_path,
                    library_id=library_id,
                    api_key=self._get_api_key(library_id)
                )
                self.clients[library_id] = client
                
                # Also add by country code for convenience
                country_code = library_config.get('country_code', '').upper()
                if country_code:
                    self.clients[country_code] = client
                
            except Exception as e:
                self.logger.error(f"Failed to initialize client for {library_id}: {e}")
    
    def _get_api_key(self, library_id: str) -> Optional[str]:
        """Get API key for library from environment or config."""
        # Try environment variable first
        import os
        env_key = f"{library_id.upper()}_LIBRARY_API_KEY"
        api_key = os.getenv(env_key)
        
        if api_key:
            return api_key
        
        # Try config file
        library_config = self.config.get('libraries', {}).get(library_id, {})
        return library_config.get('api_key')
    
    def get_client(self, identifier: str) -> Optional[ConfigDrivenNationalLibraryClient]:
        """
        Get client by library ID or country code.
        
        Args:
            identifier: Library ID (e.g., 'norwegian') or country code (e.g., 'NO')
            
        Returns:
            Client instance or None if not found
        """
        return self.clients.get(identifier.lower()) or self.clients.get(identifier.upper())
    
    def get_client_by_country_code(self, country_code: str) -> Optional[ConfigDrivenNationalLibraryClient]:
        """Get client by ISO country code."""
        return self.get_client(country_code.upper())
    
    def get_client_by_language(self, language_code: str) -> Optional[ConfigDrivenNationalLibraryClient]:
        """Get client by language code."""
        libraries = self.config.get('libraries', {})
        
        for library_id, library_config in libraries.items():
            language_codes = library_config.get('language_codes', [])
            if language_code.lower() in [code.lower() for code in language_codes]:
                return self.get_client(library_id)
        
        # If no specific library found, return first default library
        default_libraries = self.get_default_libraries()
        if default_libraries:
            return default_libraries[0]
        
        return None
    
    def get_client_by_isbn_prefix(self, isbn_prefix: str) -> Optional[ConfigDrivenNationalLibraryClient]:
        """Get client by ISBN prefix."""
        libraries = self.config.get('libraries', {})
        
        for library_id, library_config in libraries.items():
            prefixes = library_config.get('isbn_prefixes', [])
            if isbn_prefix in prefixes:
                return self.get_client(library_id)
        
        return None
    
    def search_by_country(self, query: str, country_code: str, item_type: str = 'both') -> Dict[str, Any]:
        """Search national library for specific country."""
        results = {}
        client = self.get_client_by_country_code(country_code)
        
        if not client:
            self.logger.warning(f"No client found for country code: {country_code}")
            return results
        
        try:
            search_result = client.search(query, item_type=item_type)
            
            if item_type in ['papers', 'both']:
                results['papers'] = search_result.get('papers', [])
            
            if item_type in ['books', 'both']:
                results['books'] = search_result.get('books', [])
            
            results['source'] = search_result.get('source', '')
            results['total'] = search_result.get('total', 0)
            
        except Exception as e:
            self.logger.error(f"Search failed for country {country_code}: {e}")
        
        return results
    
    def search_by_language(self, query: str, language: str, item_type: str = 'both') -> Dict[str, Any]:
        """Search national libraries based on language."""
        results = {}
        client = self.get_client_by_language(language)
        
        if not client:
            self.logger.warning(f"No client found for language: {language}")
            return results
        
        try:
            search_result = client.search(query, item_type=item_type)
            
            if item_type in ['papers', 'both']:
                results['papers'] = search_result.get('papers', [])
            
            if item_type in ['books', 'both']:
                results['books'] = search_result.get('books', [])
            
            results['source'] = search_result.get('source', '')
            results['total'] = search_result.get('total', 0)
            
        except Exception as e:
            self.logger.error(f"Search failed for language {language}: {e}")
        
        return results
    
    def search_by_isbn_prefix(self, query: str, isbn_prefix: str, item_type: str = 'both') -> Dict[str, Any]:
        """Search national library based on ISBN prefix."""
        results = {}
        client = self.get_client_by_isbn_prefix(isbn_prefix)
        
        if not client:
            self.logger.warning(f"No client found for ISBN prefix: {isbn_prefix}")
            return results
        
        try:
            search_result = client.search(query, item_type=item_type)
            
            if item_type in ['papers', 'both']:
                results['papers'] = search_result.get('papers', [])
            
            if item_type in ['books', 'both']:
                results['books'] = search_result.get('books', [])
            
            results['source'] = search_result.get('source', '')
            results['total'] = search_result.get('total', 0)
            
        except Exception as e:
            self.logger.error(f"Search failed for ISBN prefix {isbn_prefix}: {e}")
        
        return results
    
    def get_available_libraries(self) -> List[Dict[str, Any]]:
        """Get list of all available libraries with their configurations."""
        libraries = []
        
        for library_id, library_config in self.config.get('libraries', {}).items():
            library_info = {
                'id': library_id,
                'name': library_config.get('name', ''),
                'country_code': library_config.get('country_code', ''),
                'language_codes': library_config.get('language_codes', []),
                'isbn_prefixes': library_config.get('isbn_prefixes', []),
                'api_url': library_config.get('api', {}).get('base_url', '')
            }
            libraries.append(library_info)
        
        return libraries
    
    def reload_config(self):
        """Reload configuration and reinitialize clients."""
        self.config = self._load_config()
        self.clients = {}
        self._initialize_clients()
        self.logger.info("National library configuration reloaded")
    
    def test_connection(self, library_id: str) -> bool:
        """Test connection to a specific library."""
        client = self.get_client(library_id)
        if not client:
            return False
        
        try:
            # Try a simple search to test connection
            result = client.search("test", item_type='books')
            return True
        except Exception as e:
            self.logger.error(f"Connection test failed for {library_id}: {e}")
            return False
    
    def test_all_connections(self) -> Dict[str, bool]:
        """Test connections to all configured libraries."""
        results = {}
        
        for library_id in self.config.get('libraries', {}).keys():
            results[library_id] = self.test_connection(library_id)
        
        return results
    
    def get_default_libraries(self) -> List[ConfigDrivenNationalLibraryClient]:
        """Get all libraries marked as default."""
        default_clients = []
        libraries = self.config.get('libraries', {})
        
        for library_id, library_config in libraries.items():
            if library_config.get('is_default', False):
                if library_id in self.clients:
                    default_clients.append(self.clients[library_id])
        
        return default_clients
    
