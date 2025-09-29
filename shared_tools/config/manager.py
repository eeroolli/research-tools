"""
Centralized configuration management for research-tools.
"""
import os
import configparser
from typing import Dict, Any, Optional
from pathlib import Path


class ConfigManager:
    """Centralized configuration management."""
    
    def __init__(self, config_file: Optional[str] = None):
        """
        Initialize configuration manager.
        
        Args:
            config_file: Path to configuration file. If None, uses default location.
        """
        self.config_file = config_file or self._get_default_config_path()
        self.config = configparser.ConfigParser()
        self._load_config()
    
    def _get_default_config_path(self) -> str:
        """Get default configuration file path."""
        # Look for config.conf in the research-tools root directory
        research_tools_root = Path(__file__).parent.parent.parent
        return str(research_tools_root / "config.conf")
    
    def _load_config(self):
        """Load configuration from file."""
        if os.path.exists(self.config_file):
            self.config.read(self.config_file)
        else:
            # Create default configuration
            self._create_default_config()
    
    def _create_default_config(self):
        """Create default configuration file."""
        # Create directories
        config_dir = Path(self.config_file).parent
        config_dir.mkdir(parents=True, exist_ok=True)
        
        # Default configuration
        self.config['PATHS'] = {
            'scan_folder': '/mnt/i/FraMobil/Camera/Books/',
            'output_folder': './output',
            'log_folder': './logs',
            'data_folder': './data'
        }
        
        self.config['APIS'] = {
            'zotero_api_key': '',
            'zotero_library_id': '',
            'zotero_library_type': 'user',
            'openlibrary_api': 'https://openlibrary.org/api/books',
            'google_books_api_key': '',
            'norwegian_library_api': 'https://api.nb.no/catalog/v1',
            'finnish_library_api': 'https://api.kirjastot.fi',
            'swedish_library_api': 'https://libris.kb.se/api',
            'danish_library_api': 'https://api.dbc.dk',
            'german_library_api': 'https://api.dnb.de',
            'french_library_api': 'https://api.bnf.fr',
            'openalex_api': 'https://api.openalex.org',
            'crossref_api': 'https://api.crossref.org'
        }
        
        self.config['PROCESSING'] = {
            'language_detection': 'true',
            'languages': 'EN,DE,NO,FI,SE',
            'intel_gpu_optimization': 'true',
            'batch_size': '10',
            'max_retries': '3'
        }
        
        self.config['ZOTERO'] = {
            'duplicate_checking': 'true',
            'smart_tag_management': 'true',
            'annotation_storage': 'true',
            'pdf_optimization': 'true'
        }
        
        # Save default configuration
        self.save_config()
    
    def get(self, section: str, key: str, fallback: Any = None) -> Any:
        """Get configuration value."""
        try:
            return self.config.get(section, key, fallback=fallback)
        except (configparser.NoSectionError, configparser.NoOptionError):
            return fallback
    
    def get_section(self, section: str) -> Dict[str, str]:
        """Get entire configuration section."""
        try:
            return dict(self.config[section])
        except KeyError:
            return {}
    
    def set(self, section: str, key: str, value: str):
        """Set configuration value."""
        if not self.config.has_section(section):
            self.config.add_section(section)
        self.config.set(section, key, value)
    
    def save_config(self):
        """Save configuration to file."""
        with open(self.config_file, 'w') as f:
            self.config.write(f)
    
    def get_api_key(self, service: str) -> str:
        """Get API key for a service."""
        return self.get('APIS', f'{service}_api_key', '')
    
    def get_path(self, path_type: str) -> str:
        """Get configured path."""
        return self.get('PATHS', path_type, '')
    
    def is_enabled(self, feature: str) -> bool:
        """Check if a feature is enabled."""
        return self.get('PROCESSING', feature, 'false').lower() == 'true'
