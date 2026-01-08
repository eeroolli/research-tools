#!/usr/bin/env python3
"""
File operations module for daemon.

Provides safe file copy and move operations with proper error handling,
resource cleanup, and path validation.
"""

import shutil
import logging
from contextlib import contextmanager
from pathlib import Path
from typing import Optional, Tuple

from shared_tools.daemon.exceptions import FileOperationError
from shared_tools.daemon.constants import DaemonConstants


def copy_file_safely(source: Path, target: Path, replace_existing: bool = False) -> bool:
    """Copy file with atomic operation where possible.
    
    This is a simplified version that performs basic atomic file copy.
    For complex WSL/Windows path handling, the daemon's _copy_file_universal
    method should be used.
    
    Args:
        source: Source file path
        target: Target file path
        replace_existing: If True, replace existing file if it differs
        
    Returns:
        True if copy successful, False otherwise
        
    Raises:
        FileOperationError: If copy fails
    """
    if not source.exists():
        raise FileOperationError(f"Source file not found: {source}")
    
    try:
        # Ensure target directory exists
        target.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if target exists and handle replacement
        if target.exists():
            if not replace_existing:
                # Check if files are identical (same size)
                try:
                    source_size = source.stat().st_size
                    target_size = target.stat().st_size
                    if source_size == target_size:
                        # Files might be identical
                        return True
                except Exception:
                    pass
                raise FileOperationError(f"Target file already exists: {target}")
            else:
                # Remove existing file for replacement
                target.unlink()
        
        # Use temporary file for atomic operation
        temp_target = target.with_suffix(target.suffix + '.tmp')
        
        # Perform copy
        shutil.copy2(source, temp_target)
        
        # Verify copy
        if not temp_target.exists():
            raise FileOperationError("Target file not found after copy")
        
        source_size = source.stat().st_size
        temp_size = temp_target.stat().st_size
        if source_size != temp_size:
            temp_target.unlink()
            raise FileOperationError(f"File size mismatch after copy (source: {source_size}, target: {temp_size})")
        
        # Atomic rename
        temp_target.replace(target)
        
        return True
        
    except FileOperationError:
        raise
    except (OSError, PermissionError, FileNotFoundError) as e:
        raise FileOperationError(f"Copy failed: {e}") from e
    except Exception as e:
        raise FileOperationError(f"Unexpected error during copy: {e}") from e


def move_file_safely(source: Path, target: Path, create_dirs: bool = True) -> bool:
    """Move file safely with directory creation.
    
    Args:
        source: Source file path
        target: Target file path
        create_dirs: If True, create target directory if it doesn't exist
        
    Returns:
        True if move successful, False otherwise
        
    Raises:
        FileOperationError: If move fails
    """
    if not source.exists():
        raise FileOperationError(f"Source file not found: {source}")
    
    try:
        # Ensure target directory exists
        if create_dirs:
            target.parent.mkdir(parents=True, exist_ok=True)
        
        # Perform move
        shutil.move(str(source), str(target))
        
        # Verify move
        if not target.exists():
            raise FileOperationError("Target file not found after move")
        
        return True
        
    except (OSError, PermissionError, FileNotFoundError) as e:
        raise FileOperationError(f"Move failed: {e}") from e
    except Exception as e:
        raise FileOperationError(f"Unexpected error during move: {e}") from e


def move_to_subdirectory(
    source: Path,
    base_dir: Path,
    subdirectory: str,
    logger: Optional[logging.Logger] = None
) -> bool:
    """Move file to a subdirectory within base directory.
    
    This is a helper function for moving files to done/, failed/, skipped/ directories.
    
    Args:
        source: Source file path
        base_dir: Base directory
        subdirectory: Subdirectory name (e.g., 'done', 'failed', 'skipped')
        logger: Optional logger for warnings
        
    Returns:
        True if move successful, False otherwise
    """
    if not source.exists():
        if logger:
            logger.warning(f"Cannot move to {subdirectory}/: file no longer exists: {source}")
        return False
    
    try:
        target_dir = base_dir / subdirectory
        target_dir.mkdir(exist_ok=True)
        target = target_dir / source.name
        
        move_file_safely(source, target, create_dirs=False)
        return True
        
    except FileOperationError as e:
        if logger:
            logger.error(f"Failed to move to {subdirectory}/: {e}")
        return False


@contextmanager
def temporary_file(base_path: Path, suffix: str = '.tmp'):
    """Context manager for temporary files.
    
    Creates a temporary file and ensures cleanup on exit.
    
    Args:
        base_path: Base path for temporary file (temp file will be base_path + suffix)
        suffix: Suffix for temporary file
        
    Yields:
        Path to temporary file
        
    Example:
        with temporary_file(Path("output.pdf"), '.tmp') as temp_path:
            # Use temp_path
            shutil.copy(source, temp_path)
    """
    temp_path = base_path.with_suffix(base_path.suffix + suffix)
    try:
        yield temp_path
    finally:
        if temp_path.exists():
            try:
                temp_path.unlink()
            except Exception as e:
                # Log cleanup errors but don't raise
                logging.getLogger(__name__).warning(f"Failed to clean up temporary file {temp_path}: {e}")


@contextmanager
def temporary_directory(prefix: str = 'daemon_', suffix: str = ''):
    """Context manager for temporary directories.
    
    Creates a temporary directory and ensures cleanup on exit.
    
    Args:
        prefix: Prefix for temporary directory name
        suffix: Suffix for temporary directory name
        
    Yields:
        Path to temporary directory
        
    Example:
        with temporary_directory(prefix='pdf_processing_') as temp_dir:
            # Use temp_dir
            process_file(temp_dir)
    """
    import tempfile
    temp_dir = Path(tempfile.mkdtemp(prefix=prefix, suffix=suffix))
    try:
        yield temp_dir
    finally:
        # Clean up directory and all contents
        try:
            shutil.rmtree(temp_dir)
        except Exception as e:
            # Log cleanup errors but don't raise
            logging.getLogger(__name__).warning(f"Failed to clean up temporary directory {temp_dir}: {e}")

