#!/usr/bin/env python3
"""
Path utility functions for WSL/Windows path handling.

This module centralizes path normalization and conversion utilities,
handling both WSL paths (/mnt/c/...) and Windows paths (C:\...).
"""

from pathlib import Path
from typing import Optional


def normalize_path_for_wsl(path_str: Optional[str]) -> str:
    """Normalize a path string to WSL format.
    
    Handles both WSL paths (/mnt/c/...) and Windows paths (C:\...)
    - Windows paths like "G:\My Drive\publications" -> "/mnt/g/My Drive/publications"
    - WSL paths already in correct format are returned as-is
    
    Args:
        path_str: Path string that may be in WSL or Windows format
        
    Returns:
        Normalized WSL path string
    """
    # Sanitize quotes and whitespace
    if path_str is None:
        return path_str
    
    path_str = path_str.strip().strip('"\'')
    path_str = path_str.replace('"', '').replace("'", '')
    
    # If already a WSL path (starts with /), normalize duplicate slashes and return
    if path_str.startswith('/'):
        while '//' in path_str:
            path_str = path_str.replace('//', '/')
        return path_str
    
    # If Windows path (contains : or starts with letter), convert to WSL
    if ':' in path_str or (len(path_str) > 1 and path_str[1].isalpha() and path_str[1] != ':'):
        # Handle Windows paths like "G:\My Drive\publications" or "G:/My Drive/publications"
        # Convert backslashes to forward slashes
        path_str = path_str.replace('\\', '/')
        
        # Extract drive letter (first character before :)
        if ':' in path_str:
            drive_letter = path_str[0].lower()
            # Remove drive letter and colon: "G:/My Drive/publications" -> "/My Drive/publications"
            remainder = path_str.split(':', 1)[1].lstrip('/')
            # Convert to WSL format: /mnt/g/My Drive/publications
            wsl_path = f'/mnt/{drive_letter}/{remainder}'
            while '//' in wsl_path:
                wsl_path = wsl_path.replace('//', '/')
            return wsl_path
    
    # If no clear format, return as-is
    return path_str


def validate_file_path(path: Path, base_dir: Path) -> Path:
    """Validate that path is within base_dir (prevent path traversal).
    
    Args:
        path: Path to validate
        base_dir: Base directory that path must be within
        
    Returns:
        Resolved path if valid
        
    Raises:
        ValueError: If path is outside base_dir
        OSError: If path resolution fails
    """
    try:
        resolved = path.resolve()
        base_resolved = base_dir.resolve()
        if not str(resolved).startswith(str(base_resolved)):
            raise ValueError(f"Path outside allowed directory: {path}")
        return resolved
    except (OSError, ValueError) as e:
        raise ValueError(f"Invalid path: {e}") from e

