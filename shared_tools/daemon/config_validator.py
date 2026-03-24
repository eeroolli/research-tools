#!/usr/bin/env python3
"""
Configuration validation module for daemon operations.

This module provides validation for configuration values, ensuring
that configuration is correct before daemon startup.
"""

import configparser
import os
from pathlib import Path
from typing import List, Optional

from shared_tools.daemon.exceptions import ConfigurationError


class ConfigValidator:
    """Validate configuration values for daemon operations."""
    
    @staticmethod
    def validate_path(path_str: str, must_exist: bool = False) -> Path:
        """Validate and normalize path.
        
        Args:
            path_str: Path string to validate
            must_exist: If True, path must exist
            
        Returns:
            Validated Path object
            
        Raises:
            ConfigurationError: If path is invalid or doesn't exist (when required)
        """
        if not path_str:
            raise ConfigurationError("Path cannot be empty")
        
        try:
            path = Path(path_str)
            
            if must_exist and not path.exists():
                raise ConfigurationError(f"Path does not exist: {path}")
            
            return path
        except (OSError, ValueError) as e:
            raise ConfigurationError(f"Invalid path '{path_str}': {e}") from e
    
    @staticmethod
    def validate_port(port: int) -> int:
        """Validate port number.
        
        Args:
            port: Port number to validate
            
        Returns:
            Validated port number
            
        Raises:
            ConfigurationError: If port is out of valid range
        """
        if not isinstance(port, int):
            try:
                port = int(port)
            except (ValueError, TypeError):
                raise ConfigurationError(f"Port must be an integer: {port}")
        
        if not 1 <= port <= 65535:
            raise ConfigurationError(f"Port must be between 1 and 65535: {port}")
        
        return port
    
    @staticmethod
    def validate_config(config: configparser.ConfigParser) -> List[str]:
        """Validate configuration and return list of errors.
        
        Args:
            config: Configuration parser to validate
            
        Returns:
            List of error messages (empty if no errors)
        """
        errors = []
        
        # Validate GROBID configuration
        try:
            grobid_host = config.get('GROBID', 'host', fallback='localhost').strip()
            grobid_port = config.getint('GROBID', 'port', fallback=8070)
            ConfigValidator.validate_port(grobid_port)
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
            errors.append(f"GROBID configuration error: {e}")
        
        # Validate Ollama configuration
        try:
            ollama_host = config.get('OLLAMA', 'host', fallback='localhost').strip()
            ollama_port = config.getint('OLLAMA', 'port', fallback=11434)
            ConfigValidator.validate_port(ollama_port)
            
            # Validate Ollama timeouts
            startup_timeout = config.getint('OLLAMA', 'startup_timeout', fallback=30)
            if startup_timeout <= 0:
                errors.append("OLLAMA startup_timeout must be positive")
            
            shutdown_timeout = config.getint('OLLAMA', 'shutdown_timeout', fallback=10)
            if shutdown_timeout <= 0:
                errors.append("OLLAMA shutdown_timeout must be positive")
        except (configparser.NoSectionError, configparser.NoOptionError, ValueError) as e:
            errors.append(f"OLLAMA configuration error: {e}")
        
        # Validate paths (if sections exist)
        if config.has_section('PATHS'):
            try:
                scanner_papers_dir = config.get('PATHS', 'scanner_papers_dir', fallback='')
                if scanner_papers_dir:
                    ConfigValidator.validate_path(scanner_papers_dir, must_exist=True)
            except ConfigurationError as e:
                errors.append(f"PATHS.scanner_papers_dir error: {e}")
            
            try:
                publications_dir = config.get('PATHS', 'publications_dir', fallback='')
                if publications_dir:
                    ConfigValidator.validate_path(publications_dir, must_exist=True)
            except ConfigurationError as e:
                errors.append(f"PATHS.publications_dir error: {e}")
        
        # Validate SERVICE_RESILIENCE configuration (if section exists)
        if config.has_section('SERVICE_RESILIENCE'):
            try:
                health_check_timeout = config.getint('SERVICE_RESILIENCE', 'health_check_timeout', fallback=5)
                if health_check_timeout <= 0:
                    errors.append("SERVICE_RESILIENCE health_check_timeout must be positive")
                
                health_check_retries = config.getint('SERVICE_RESILIENCE', 'health_check_retries', fallback=3)
                if health_check_retries <= 0:
                    errors.append("SERVICE_RESILIENCE health_check_retries must be positive")
                
                backoff_multiplier = config.getint('SERVICE_RESILIENCE', 'health_check_backoff_multiplier', fallback=2)
                if backoff_multiplier <= 0:
                    errors.append("SERVICE_RESILIENCE health_check_backoff_multiplier must be positive")
            except (configparser.NoOptionError, ValueError) as e:
                errors.append(f"SERVICE_RESILIENCE configuration error: {e}")
        
        return errors
    
    @staticmethod
    def validate_and_raise(config: configparser.ConfigParser):
        """Validate configuration and raise exception if invalid.
        
        Args:
            config: Configuration parser to validate
            
        Raises:
            ConfigurationError: If configuration is invalid
        """
        errors = ConfigValidator.validate_config(config)
        if errors:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {e}" for e in errors)
            raise ConfigurationError(error_msg)

