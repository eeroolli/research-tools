"""
File management utilities for book photo processing.
Handles photo file organization, statistics, and directory management.
"""
import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any
from configparser import ConfigParser


class FileManager:
    """Manages photo files for book processing workflow."""
    
    def __init__(self, config_file: str = None):
        """
        Initialize FileManager with configuration.
        
        Args:
            config_file: Path to configuration file. If None, uses default.
        """
        self.logger = logging.getLogger(__name__)
        
        # Load configuration
        if config_file is None:
            # Look for config in process_books directory first, then fall back to root
            config_file = Path(__file__).parent.parent.parent / "config" / "process_books.conf"
            if not config_file.exists():
                config_file = Path(__file__).parent.parent.parent.parent / "config.conf"
        
        self.config = ConfigParser()
        self.config.read(config_file)
        
        # Set up paths from config with fallbacks
        self.base_photos_dir = Path(self.config.get('PATHS', 'scan_folder', fallback='/mnt/i/FraMobil/Camera/Books/'))
        self.done_dir = self.base_photos_dir / "done"
        self.failed_dir = self.base_photos_dir / "failed"
        self.permanently_failed_dir = self.base_photos_dir / "permanently_failed"
        
        # Create directories if they don't exist
        self._ensure_directories()
        
        self.logger.info(f"FileManager initialized with base directory: {self.base_photos_dir}")
    
    def _ensure_directories(self):
        """Create necessary directories if they don't exist."""
        for directory in [self.base_photos_dir, self.done_dir, self.failed_dir, self.permanently_failed_dir]:
            directory.mkdir(parents=True, exist_ok=True)
            self.logger.debug(f"Ensured directory exists: {directory}")
    
    def get_pending_photos(self) -> List[Path]:
        """
        Get list of pending photos to process based on processing log.
        
        Returns:
            List of Path objects for photos that need processing.
        """
        pending_photos = []
        processed_files = self._load_processed_files()
        
        # Look for common image file extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.tiff', '.tif', '.bmp', '.webp'}
        
        try:
            for file_path in self.base_photos_dir.iterdir():
                if (file_path.is_file() and 
                    file_path.suffix.lower() in image_extensions and
                    not file_path.name.startswith('.')):  # Skip hidden files
                    
                    # Check if file needs processing
                    if file_path.name not in processed_files:
                        # New photo - needs processing
                        pending_photos.append(file_path)
                    elif (processed_files[file_path.name].get('status') == 'failed' and 
                          processed_files[file_path.name].get('retry_count', 0) < 3):
                        # Failed photo - retry if under limit
                        pending_photos.append(file_path)
                    # Skip if already successfully processed
            
            # Sort by modification time (oldest first)
            pending_photos.sort(key=lambda p: p.stat().st_mtime)
            
            self.logger.info(f"Found {len(pending_photos)} pending photos")
            
        except Exception as e:
            self.logger.error(f"Error scanning for pending photos: {e}")
        
        return pending_photos
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get processing statistics.
        
        Returns:
            Dictionary with counts of pending, done, failed, and permanently_failed photos.
        """
        stats = {
            'pending': 0,
            'done': 0,
            'failed': 0,
            'permanently_failed': 0,
            'total_processed': 0
        }
        
        try:
            # Count pending photos
            stats['pending'] = len(self.get_pending_photos())
            
            # Count done photos
            if self.done_dir.exists():
                stats['done'] = len([f for f in self.done_dir.iterdir() 
                                   if f.is_file() and not f.name.startswith('.')])
            
            # Count failed photos
            if self.failed_dir.exists():
                stats['failed'] = len([f for f in self.failed_dir.iterdir() 
                                     if f.is_file() and not f.name.startswith('.')])
            
            # Count permanently failed photos
            if self.permanently_failed_dir.exists():
                stats['permanently_failed'] = len([f for f in self.permanently_failed_dir.iterdir() 
                                                 if f.is_file() and not f.name.startswith('.')])
            
            # Calculate total processed
            stats['total_processed'] = stats['done'] + stats['failed'] + stats['permanently_failed']
            
        except Exception as e:
            self.logger.error(f"Error calculating statistics: {e}")
        
        return stats
    
    def move_to_done(self, photo_path: Path) -> bool:
        """
        Move photo to done directory.
        
        Args:
            photo_path: Path to the photo file to move.
            
        Returns:
            True if successful, False otherwise.
        """
        return self._move_photo(photo_path, self.done_dir, "done")
    
    def move_to_failed(self, photo_path: Path) -> bool:
        """
        Move photo to failed directory.
        
        Args:
            photo_path: Path to the photo file to move.
            
        Returns:
            True if successful, False otherwise.
        """
        return self._move_photo(photo_path, self.failed_dir, "failed")
    
    def _move_photo(self, photo_path: Path, target_dir: Path, status: str) -> bool:
        """
        Move photo to target directory with error handling.
        
        Args:
            photo_path: Path to the photo file to move.
            target_dir: Target directory to move the photo to.
            status: Status description for logging.
            
        Returns:
            True if successful, False otherwise.
        """
        try:
            if not photo_path.exists():
                self.logger.warning(f"Photo file does not exist: {photo_path}")
                return False
            
            # Ensure target directory exists
            target_dir.mkdir(parents=True, exist_ok=True)
            
            # Create target path
            target_path = target_dir / photo_path.name
            
            # Handle filename conflicts
            counter = 1
            while target_path.exists():
                stem = photo_path.stem
                suffix = photo_path.suffix
                target_path = target_dir / f"{stem}_{counter}{suffix}"
                counter += 1
            
            # Move the file
            photo_path.rename(target_path)
            self.logger.info(f"Moved {photo_path.name} to {status} directory")
            return True
            
        except Exception as e:
            self.logger.error(f"Error moving {photo_path.name} to {status}: {e}")
            return False
    
    def get_photo_info(self, photo_path: Path) -> Dict[str, Any]:
        """
        Get information about a photo file.
        
        Args:
            photo_path: Path to the photo file.
            
        Returns:
            Dictionary with photo information.
        """
        info = {
            'name': photo_path.name,
            'size': 0,
            'modified': None,
            'exists': False
        }
        
        try:
            if photo_path.exists():
                stat = photo_path.stat()
                info['size'] = stat.st_size
                info['modified'] = stat.st_mtime
                info['exists'] = True
        except Exception as e:
            self.logger.error(f"Error getting photo info for {photo_path}: {e}")
        
        return info
    
    def _load_processed_files(self) -> Dict[str, Any]:
        """Load the processing log to get already processed files."""
        import csv
        # Use absolute path relative to the research-tools root
        log_file = Path(__file__).parent.parent.parent.parent / "data" / "books" / "book_processing_log.csv"
        if not log_file.exists():
            return {}
        
        try:
            processed_files = {}
            with open(log_file, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f)
                for row in reader:
                    processed_files[row['filename']] = row
            return processed_files
        except Exception as e:
            self.logger.error(f"Error loading processing log: {e}")
            return {}
    
    def move_to_done(self, photo_path: Path) -> bool:
        """
        Move photo to done directory.
        
        Args:
            photo_path: Path to the photo file to move.
            
        Returns:
            True if successful, False otherwise.
        """
        return self._move_photo(photo_path, self.done_dir, "done")
    
    def move_to_failed(self, photo_path: Path, retry_count: int = 0) -> bool:
        """
        Move photo to failed or permanently_failed directory based on retry count.
        
        Args:
            photo_path: Path to the photo file to move.
            retry_count: Number of retry attempts for this photo.
            
        Returns:
            True if successful, False otherwise.
        """
        if retry_count >= 3:
            return self._move_photo(photo_path, self.permanently_failed_dir, "permanently_failed")
        else:
            return self._move_photo(photo_path, self.failed_dir, "failed")
