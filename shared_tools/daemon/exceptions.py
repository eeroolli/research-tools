#!/usr/bin/env python3
"""
Exception hierarchy for daemon operations.

This module defines a structured exception hierarchy for the paper processor daemon,
allowing for specific error handling and better error recovery strategies.
"""


class DaemonError(Exception):
    """Base exception for all daemon operations.
    
    All daemon-related exceptions should inherit from this base class.
    This allows catching all daemon errors with a single exception type
    while still allowing specific error handling for subclasses.
    
    Example:
        try:
            # daemon operation
        except DaemonError as e:
            logger.error(f"Daemon error: {e}")
    
    Attributes:
        message: Error message describing what went wrong
    """
    pass


class ServiceError(DaemonError):
    """Exception raised for service initialization or runtime errors.
    
    Use this exception when there are issues with external services
    (GROBID, Ollama, etc.), such as:
    - Service unavailable
    - Service initialization failures
    - Service communication errors
    
    Example:
        if not service.is_available():
            raise ServiceError(f"Service {service_name} is not available")
    """
    pass


class FileOperationError(DaemonError):
    """Exception raised for file operation failures.
    
    Use this exception when file operations fail, such as:
    - File copy/move failures
    - File permission errors
    - File not found errors
    - Path validation failures
    
    Example:
        try:
            shutil.copy(source, target)
        except OSError as e:
            raise FileOperationError(f"Failed to copy file: {e}")
    """
    pass


class MetadataExtractionError(DaemonError):
    """Exception raised for metadata extraction failures.
    
    Use this exception when metadata extraction from PDFs fails, such as:
    - GROBID extraction failures
    - Ollama extraction failures
    - Identifier extraction failures
    - Metadata validation failures
    
    Example:
        if not metadata:
            raise MetadataExtractionError("Failed to extract metadata from PDF")
    """
    pass


class ZoteroError(DaemonError):
    """Exception raised for Zotero-related operation failures.
    
    Use this exception when Zotero operations fail, such as:
    - Zotero API errors
    - Zotero search failures
    - Zotero attachment failures
    - Zotero authentication errors
    
    Example:
        if not zotero_item:
            raise ZoteroError("Failed to find item in Zotero library")
    """
    pass


class ConfigurationError(DaemonError):
    """Exception raised for configuration-related errors.
    
    Use this exception when configuration validation fails, such as:
    - Invalid configuration values
    - Missing required configuration
    - Configuration file errors
    - Invalid paths or ports in configuration
    
    Example:
        if not config.get('REQUIRED_KEY'):
            raise ConfigurationError("Missing required configuration key: REQUIRED_KEY")
    """
    pass

