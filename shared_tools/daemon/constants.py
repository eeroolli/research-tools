#!/usr/bin/env python3
"""
Constants for daemon operation.

This module centralizes all magic numbers and strings used in the daemon,
making the code more maintainable and allowing for easy configuration changes.
"""


class DaemonConstants:
    """Constants for daemon operation."""
    
    # Timeouts (in seconds)
    FILE_WRITE_DELAY = 2.0
    """Delay in seconds to wait for file to be fully written after creation.
    
    This delay ensures that files copied to the watch directory are completely
    written before processing begins.
    """
    
    PROMPT_TIMEOUT = 10
    """Timeout in seconds for user input prompts.
    
    Default timeout for user interaction prompts. Can be overridden by config.
    """
    
    PAGE_OFFSET_TIMEOUT = 10
    """Timeout in seconds for page offset prompt.
    
    Timeout for the interactive prompt that asks users to specify which page
    to start processing from (for papers with cover pages, etc.).
    """
    
    SERVICE_STARTUP_TIMEOUT = 30
    """Timeout in seconds for service initialization.
    
    Default timeout for waiting for services (GROBID, Ollama) to start up.
    GROBID uses 60 seconds, Ollama uses this value (configurable).
    """
    
    GROBID_STARTUP_TIMEOUT = 60
    """Timeout in seconds for GROBID service initialization.
    
    GROBID can be slow to start, so it gets a longer timeout than Ollama.
    """
    
    # File patterns
    PDF_EXTENSION = '.pdf'
    """File extension for PDF files."""
    
    PID_FILENAME = '.daemon.pid'
    """Filename for the daemon PID file.
    
    This file is created in the watch directory to track the daemon process ID.
    """
    
    # Directories
    DONE_SUBDIR = 'done'
    """Subdirectory name for successfully processed files."""
    
    FAILED_SUBDIR = 'failed'
    """Subdirectory name for files that failed processing."""
    
    SKIPPED_SUBDIR = 'skipped'
    """Subdirectory name for files that were skipped (non-academic, etc.)."""
    
    # Other constants
    FILE_WRITE_CHECK_DELAY = 0.5
    """Small delay in seconds for file system operations.
    
    Used to ensure file system operations (like PDF viewer opening) complete
    before continuing.
    """

