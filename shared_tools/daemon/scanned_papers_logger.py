#!/usr/bin/env python3
"""
CSV logger for scanned papers processing.

Tracks processing steps including split, border removal, trimming, and Zotero attachment.
"""

import csv
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Set

logger = logging.getLogger(__name__)


class ScannedPapersLogger:
    """CSV logger for scanned papers processing."""
    
    CSV_FIELDS = [
        'timestamp',
        'original_filename',
        'status',
        'final_filename',
        'split',
        'borders',
        'trim',
        'zotero_item_code'
    ]
    
    def __init__(self, log_file: Path):
        """Initialize logger.
        
        Args:
            log_file: Path to CSV log file
        """
        self.log_file = Path(log_file)
        self.lock = threading.Lock()  # Thread-safe CSV writing
        
        # Ensure directory exists
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize log file if needed
        self.initialize_log()
    
    def initialize_log(self):
        """Initialize CSV log file with headers if it doesn't exist."""
        if not self.log_file.exists():
            with self.lock:
                with open(self.log_file, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
                    writer.writerow(self.CSV_FIELDS)
                logger.debug(f"Initialized CSV log file: {self.log_file}")
    
    def log_processing(
        self,
        original_filename: str,
        status: str,
        final_filename: Optional[str] = None,
        split: Optional[str] = None,
        borders: Optional[str] = None,
        trim: Optional[str] = None,
        zotero_item_code: Optional[str] = None,
        timestamp: Optional[str] = None
    ):
        """Log processing entry to CSV.
        
        Args:
            original_filename: Original PDF filename from scanner
            status: Processing status (success, failed, skipped, manual_review)
            final_filename: Final filename in publications directory (if successful)
            split: Whether PDF was split (yes/no/failed)
            borders: Whether borders were removed (yes/no)
            trim: Whether any pages were trimmed (yes/no)
            zotero_item_code: Zotero item key if attached
            timestamp: ISO format timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now().isoformat()
        
        # Default empty strings for optional fields
        final_filename = final_filename or ''
        split = split or 'no'
        borders = borders or 'no'
        trim = trim or 'no'
        zotero_item_code = zotero_item_code or ''
        
        row = [
            timestamp,
            original_filename,
            status,
            final_filename,
            split,
            borders,
            trim,
            zotero_item_code
        ]
        
        with self.lock:
            try:
                with open(self.log_file, 'a', newline='', encoding='utf-8') as f:
                    writer = csv.writer(f, delimiter=';', quotechar='"', quoting=csv.QUOTE_ALL)
                    writer.writerow(row)
                logger.debug(f"Logged processing: {original_filename} -> {status}")
            except Exception as e:
                logger.error(f"Failed to log processing: {e}")
    
    def get_existing_entries(self) -> List[Dict[str, str]]:
        """Get all existing entries from CSV log.
        
        Returns:
            List of dictionaries with CSV field names as keys
        """
        entries = []
        
        if not self.log_file.exists():
            return entries
        
        try:
            with open(self.log_file, 'r', encoding='utf-8', newline='') as f:
                reader = csv.DictReader(f, delimiter=';', quotechar='"')
                entries = list(reader)
        except Exception as e:
            logger.warning(f"Failed to read existing CSV log: {e}")
        
        return entries
    
    def get_existing_filenames(self) -> Set[str]:
        """Get set of original filenames already logged.
        
        Returns:
            Set of original filenames
        """
        entries = self.get_existing_entries()
        return {entry.get('original_filename', '') for entry in entries if entry.get('original_filename')}
    
    def entry_exists(self, original_filename: str) -> bool:
        """Check if an entry for the given filename already exists.
        
        Args:
            original_filename: Original filename to check
            
        Returns:
            True if entry exists, False otherwise
        """
        return original_filename in self.get_existing_filenames()
    
    def add_entry_if_missing(
        self,
        original_filename: str,
        status: str,
        final_filename: Optional[str] = None,
        split: Optional[str] = None,
        borders: Optional[str] = None,
        trim: Optional[str] = None,
        zotero_item_code: Optional[str] = None,
        timestamp: Optional[str] = None
    ) -> bool:
        """Add entry only if it doesn't already exist.
        
        Args:
            original_filename: Original PDF filename
            status: Processing status
            final_filename: Final filename (optional)
            split: Split status (optional)
            borders: Borders status (optional)
            trim: Trim status (optional)
            zotero_item_code: Zotero item key (optional)
            timestamp: Timestamp (optional)
            
        Returns:
            True if entry was added, False if it already existed
        """
        if self.entry_exists(original_filename):
            return False
        
        self.log_processing(
            original_filename=original_filename,
            status=status,
            final_filename=final_filename,
            split=split,
            borders=borders,
            trim=trim,
            zotero_item_code=zotero_item_code,
            timestamp=timestamp
        )
        return True
