#!/usr/bin/env python3
"""
Unit tests for file operations module.
"""

import unittest
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

from shared_tools.daemon.file_operations import (
    copy_file_safely,
    move_file_safely,
    validate_file_path,
    temporary_file_context
)
from shared_tools.daemon.exceptions import FileOperationError


class TestFileOperations(unittest.TestCase):
    """Test cases for file operations."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.temp_dir = Path(tempfile.mkdtemp())
        self.test_file = self.temp_dir / "test.txt"
        self.test_file.write_text("test content")
    
    def tearDown(self):
        """Clean up test fixtures."""
        import shutil
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir)
    
    def test_copy_file_safely_success(self):
        """Test successful file copy."""
        target = self.temp_dir / "copy.txt"
        result = copy_file_safely(self.test_file, target)
        
        self.assertTrue(result)
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "test content")
    
    def test_copy_file_safely_source_not_exists(self):
        """Test file copy with non-existent source."""
        source = self.temp_dir / "nonexistent.txt"
        target = self.temp_dir / "copy.txt"
        
        with self.assertRaises(FileOperationError):
            copy_file_safely(source, target)
    
    def test_move_file_safely_success(self):
        """Test successful file move."""
        target = self.temp_dir / "moved.txt"
        result = move_file_safely(self.test_file, target)
        
        self.assertTrue(result)
        self.assertFalse(self.test_file.exists())
        self.assertTrue(target.exists())
        self.assertEqual(target.read_text(), "test content")
    
    def test_validate_file_path_success(self):
        """Test successful path validation."""
        result = validate_file_path(self.test_file, self.temp_dir)
        self.assertEqual(result, self.test_file.resolve())
    
    def test_validate_file_path_outside_base(self):
        """Test path validation with path outside base directory."""
        outside_path = Path("/tmp/outside.txt")
        
        with self.assertRaises(FileOperationError):
            validate_file_path(outside_path, self.temp_dir)
    
    def test_temporary_file_context(self):
        """Test temporary file context manager."""
        with temporary_file_context(self.temp_dir, "temp_", ".txt") as temp_path:
            self.assertTrue(temp_path.exists())
            temp_path.write_text("temp content")
        
        # File should be deleted after context exit
        self.assertFalse(temp_path.exists())


if __name__ == '__main__':
    unittest.main()

