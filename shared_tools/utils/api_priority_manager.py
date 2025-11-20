#!/usr/bin/env python3
"""
API Priority Manager - Config-driven priority system for paper metadata APIs.

This module manages the order in which different APIs are tried when looking up
paper metadata. Priorities are read from config files, allowing users to customize
the order based on their needs (e.g., medical researchers prioritizing PubMed).
"""

import configparser
from typing import List, Dict, Tuple
from pathlib import Path


class APIPriorityManager:
    """Manages API priority order from configuration."""
    
    def __init__(self, config_file: str = None):
        """Initialize priority manager.
        
        Args:
            config_file: Path to config file. If None, uses default location.
        """
        self.config = configparser.ConfigParser()
        
        if config_file is None:
            # Use default config location
            root_dir = Path(__file__).parent.parent.parent
            config_file = root_dir / 'config.conf'
            personal_config = root_dir / 'config.personal.conf'
            
            # Read both configs
            self.config.read([
                str(config_file),
                str(personal_config)
            ])
        else:
            self.config.read(config_file)
        
        self.priorities = self._load_priorities()
    
    def _load_priorities(self) -> Dict[str, int]:
        """Load API priorities from config.
        
        Returns:
            Dictionary mapping API names to priority values
        """
        priorities = {}
        
        if 'API_PRIORITIES' in self.config:
            for api_name, priority_str in self.config['API_PRIORITIES'].items():
                try:
                    priority = int(priority_str)
                    priorities[api_name.lower()] = priority
                except ValueError:
                    print(f"Warning: Invalid priority value for {api_name}: {priority_str}")
        
        return priorities
    
    def get_ordered_apis(self, api_list: List[str]) -> List[str]:
        """Get list of APIs ordered by priority.
        
        Higher priority numbers are tried first.
        
        Args:
            api_list: List of API names to sort
            
        Returns:
            List of API names sorted by priority (highest first)
        """
        # Create tuples of (priority, api_name)
        api_priorities = []
        for api in api_list:
            priority = self.priorities.get(api.lower(), 0)
            api_priorities.append((priority, api))
        
        # Sort by priority (descending), then by name
        api_priorities.sort(key=lambda x: (-x[0], x[1]))
        
        return [api for _, api in api_priorities]
    
    def is_api_enabled(self, api_name: str) -> bool:
        """Check if an API is enabled (has a priority assigned).
        
        Args:
            api_name: Name of the API
            
        Returns:
            True if API has a priority, False otherwise
        """
        return api_name.lower() in self.priorities
    
    def get_priority(self, api_name: str) -> int:
        """Get priority value for an API.
        
        Args:
            api_name: Name of the API
            
        Returns:
            Priority value (0 if not set)
        """
        return self.priorities.get(api_name.lower(), 0)


if __name__ == "__main__":
    # Test the priority manager
    manager = APIPriorityManager()
    
    print("API Priority Manager Test")
    print("=" * 60)
    
    print("\nCurrent priorities:")
    for api, priority in sorted(manager.priorities.items(), key=lambda x: -x[1]):
        print(f"  {api}: {priority}")
    
    # Test ordering
    test_apis = ['crossref', 'openalex', 'pubmed', 'arxiv']
    ordered = manager.get_ordered_apis(test_apis)
    
    print(f"\nOrder for {test_apis}:")
    print(f"  -> {ordered}")
    
    # Test enabling
    print("\nAPIs enabled:")
    for api in test_apis:
        print(f"  {api}: {'Yes' if manager.is_api_enabled(api) else 'No'}")

