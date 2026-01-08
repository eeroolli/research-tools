#!/usr/bin/env python3
"""
Secure configuration loader for daemon operations.

Provides secure loading of configuration with environment variable support
and proper file permission checking.
"""

import configparser
import os
import stat
import logging
from pathlib import Path
from typing import Optional, Dict, Any

from shared_tools.daemon.exceptions import ConfigurationError


class SecureConfigLoader:
    """Secure configuration loader with environment variable support."""
    
    def __init__(self, logger: Optional[logging.Logger] = None):
        """Initialize secure config loader.
        
        Args:
            logger: Optional logger instance
        """
        self.logger = logger or logging.getLogger(__name__)
    
    def load_config(
        self,
        config_path: Path,
        personal_config_path: Optional[Path] = None,
        check_permissions: bool = True
    ) -> configparser.ConfigParser:
        """Load configuration from files with environment variable override.
        
        Configuration values are loaded in this order (later overrides earlier):
        1. Main config file (config.conf)
        2. Personal config file (config.personal.conf) if exists
        3. Environment variables (highest priority)
        
        Args:
            config_path: Path to main configuration file
            personal_config_path: Optional path to personal configuration file
            check_permissions: If True, check file permissions for personal config
        
        Returns:
            ConfigParser instance with loaded configuration
            
        Raises:
            ConfigurationError: If configuration cannot be loaded
        """
        config = configparser.ConfigParser()
        
        # Load main config file
        if not config_path.exists():
            raise ConfigurationError(f"Configuration file not found: {config_path}")
        
        try:
            config.read(config_path)
            self.logger.debug(f"Loaded main config from: {config_path}")
        except Exception as e:
            raise ConfigurationError(f"Failed to load config from {config_path}: {e}") from e
        
        # Load personal config file if it exists
        if personal_config_path and personal_config_path.exists():
            if check_permissions:
                self._check_config_permissions(personal_config_path)
            
            try:
                config.read(personal_config_path)
                self.logger.debug(f"Loaded personal config from: {personal_config_path}")
            except Exception as e:
                raise ConfigurationError(f"Failed to load personal config from {personal_config_path}: {e}") from e
        
        # Override with environment variables
        self._apply_environment_overrides(config)
        
        return config
    
    def _check_config_permissions(self, config_path: Path) -> None:
        """Check that personal config file has restrictive permissions.
        
        Warns if file is readable by others (permissions too open).
        
        Args:
            config_path: Path to configuration file
            
        Raises:
            ConfigurationError: If file permissions are too open
        """
        try:
            file_stat = config_path.stat()
            mode = file_stat.st_mode
            
            # Check if file is readable by group or others
            if mode & (stat.S_IRGRP | stat.S_IROTH):
                self.logger.warning(
                    f"Configuration file {config_path} is readable by group or others. "
                    f"Consider setting permissions to 600 (chmod 600 {config_path})"
                )
        except OSError as e:
            self.logger.warning(f"Could not check permissions for {config_path}: {e}")
    
    def _apply_environment_overrides(self, config: configparser.ConfigParser) -> None:
        """Apply environment variable overrides to configuration.
        
        Environment variables take the form: SECTION_KEY (e.g., APIS_ZOTERO_API_KEY)
        or use underscores: SECTION_KEY (e.g., APIS_ZOTERO_API_KEY)
        
        Args:
            config: ConfigParser instance to modify
        """
        # Map of environment variable names to (section, key) tuples
        env_mappings = {
            'ZOTERO_API_KEY': ('APIS', 'zotero_api_key'),
            'ZOTERO_LIBRARY_ID': ('APIS', 'zotero_library_id'),
            'ZOTERO_LIBRARY_TYPE': ('APIS', 'zotero_library_type'),
            'GROBID_HOST': ('GROBID', 'host'),
            'GROBID_PORT': ('GROBID', 'port'),
            'OLLAMA_HOST': ('OLLAMA', 'host'),
            'OLLAMA_PORT': ('OLLAMA', 'port'),
            'OLLAMA_MODEL': ('OLLAMA', 'model'),
        }
        
        for env_var, (section, key) in env_mappings.items():
            env_value = os.getenv(env_var)
            if env_value:
                # Ensure section exists
                if not config.has_section(section):
                    config.add_section(section)
                
                config.set(section, key, env_value)
                self.logger.debug(f"Overrode {section}.{key} from environment variable {env_var}")
    
    def get_secure_value(
        self,
        config: configparser.ConfigParser,
        section: str,
        key: str,
        env_var: Optional[str] = None,
        fallback: Optional[str] = None,
        required: bool = False
    ) -> Optional[str]:
        """Get configuration value with environment variable override.
        
        Checks environment variable first, then config file, then fallback.
        
        Args:
            config: ConfigParser instance
            section: Configuration section name
            key: Configuration key name
            env_var: Optional environment variable name (if None, uses section_key format)
            fallback: Optional fallback value
            required: If True, raises ConfigurationError if value is missing
            
        Returns:
            Configuration value or fallback
            
        Raises:
            ConfigurationError: If required value is missing
        """
        # Check environment variable first
        if env_var is None:
            env_var = f"{section.upper()}_{key.upper()}"
        
        env_value = os.getenv(env_var)
        if env_value:
            return env_value
        
        # Check config file
        try:
            config_value = config.get(section, key, fallback=fallback)
            if config_value:
                return config_value
        except (configparser.NoSectionError, configparser.NoOptionError):
            pass
        
        # Use fallback if provided
        if fallback is not None:
            return fallback
        
        # Raise error if required
        if required:
            raise ConfigurationError(
                f"Required configuration value missing: [{section}]{key} "
                f"(or set environment variable {env_var})"
            )
        
        return None
    
    def get_secure_api_key(
        self,
        config: configparser.ConfigParser,
        service_name: str,
        env_var: Optional[str] = None
    ) -> str:
        """Get API key securely from environment or config.
        
        Args:
            config: ConfigParser instance
            service_name: Name of service (e.g., 'zotero', 'grobid')
            env_var: Optional environment variable name
            
        Returns:
            API key string
            
        Raises:
            ConfigurationError: If API key is not found
        """
        if env_var is None:
            env_var = f"{service_name.upper()}_API_KEY"
        
        # Try environment variable first (most secure)
        api_key = os.getenv(env_var)
        if api_key:
            return api_key
        
        # Try config file
        section = 'APIS'
        key = f"{service_name}_api_key"
        
        try:
            api_key = config.get(section, key)
            if api_key and api_key.strip() and api_key != f"YOUR_{service_name.upper()}_API_KEY_HERE":
                return api_key
        except (configparser.NoSectionError, configparser.NoOptionError):
            pass
        
        raise ConfigurationError(
            f"API key for {service_name} not found. "
            f"Set environment variable {env_var} or configure [{section}]{key} in config file."
        )

