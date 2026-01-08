#!/usr/bin/env python3
"""
Repopulate scanned papers CSV log from existing text logs and directory scans.

This script rebuilds the scanned_papers_log.csv file by:
1. Parsing existing text log files (processing_*.log)
2. Scanning done/, failed/, skipped/, manual_review/ directories
3. Merging and deduplicating results
4. Preserving existing CSV entries
"""

import sys
import re
import csv
import argparse
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Set
from collections import defaultdict

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.daemon.scanned_papers_logger import ScannedPapersLogger
from shared_tools.daemon.config_loader import SecureConfigLoader


def normalize_path(path_str: str) -> str:
    """Normalize a path string to WSL format."""
    if path_str.startswith('/'):
        return path_str
    
    if ':' in path_str or (len(path_str) > 1 and path_str[1].isalpha()):
        path_str = path_str.replace('\\', '/')
        if ':' in path_str:
            drive_letter = path_str[0].lower()
            remainder = path_str.split(':', 1)[1].lstrip('/')
            return f'/mnt/{drive_letter}/{remainder}'
    
    return path_str


def parse_text_logs(log_dir: Path) -> Dict[str, Dict]:
    """Parse existing text log files to extract processing information.
    
    Args:
        log_dir: Directory containing log files
        
    Returns:
        Dictionary mapping original filenames to processing info
    """
    entries = {}
    log_files = sorted(log_dir.glob('processing_*.log'))
    
    print(f"Parsing {len(log_files)} log files...")
    
    for log_file in log_files:
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Extract timestamp from log file name or content
            timestamp_match = re.search(r'(\d{4}-\d{2}-\d{2}(?:_\d{6})?)', log_file.name)
            if timestamp_match:
                ts_str = timestamp_match.group(1).replace('_', ' ')
                try:
                    if ' ' in ts_str:
                        timestamp = datetime.strptime(ts_str, '%Y-%m-%d %H%M%S').isoformat()
                    else:
                        timestamp = datetime.strptime(ts_str, '%Y-%m-%d').isoformat()
                except ValueError:
                    timestamp = datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
            else:
                timestamp = datetime.fromtimestamp(log_file.stat().st_mtime).isoformat()
            
            # Look for "New scan:" or "Processing:" entries
            scan_pattern = r'New scan:|Processing:|Moved to (done|failed|skipped|manual review)'
            
            lines = content.split('\n')
            current_file = None
            status = None
            
            for line in lines:
                # Extract filename from "New scan:" or "Processing:" lines
                scan_match = re.search(r'(?:New scan|Processing):\s+([^\s]+\.pdf)', line, re.IGNORECASE)
                if scan_match:
                    current_file = scan_match.group(1)
                
                # Extract status from "Moved to" lines
                move_match = re.search(r'Moved to (done|failed|skipped|manual review)', line, re.IGNORECASE)
                if move_match:
                    status_map = {
                        'done': 'success',
                        'failed': 'failed',
                        'skipped': 'skipped',
                        'manual review': 'manual_review'
                    }
                    status = status_map.get(move_match.group(1).lower(), 'unknown')
                    
                    # If we have a file, record the entry
                    if current_file and status:
                        if current_file not in entries or timestamp > entries[current_file].get('timestamp', ''):
                            entries[current_file] = {
                                'original_filename': current_file,
                                'status': status,
                                'timestamp': timestamp
                            }
                            current_file = None
                            status = None
        
        except Exception as e:
            print(f"Warning: Failed to parse {log_file.name}: {e}")
    
    print(f"Extracted {len(entries)} entries from text logs")
    return entries


def scan_directories(scanner_dir: Path, publications_dir: Path) -> Dict[str, Dict]:
    """Scan done/, failed/, skipped/, manual_review/ directories.
    
    Args:
        scanner_dir: Scanner directory containing subdirectories
        publications_dir: Publications directory to check for final filenames
        
    Returns:
        Dictionary mapping original filenames to processing info
    """
    entries = {}
    status_map = {
        'done': 'success',
        'failed': 'failed',
        'skipped': 'skipped',
        'manual_review': 'manual_review'
    }
    
    print("Scanning directories...")
    
    for subdir_name, status in status_map.items():
        subdir = scanner_dir / subdir_name
        if not subdir.exists():
            continue
        
        pdf_files = list(subdir.glob('*.pdf'))
        print(f"  {subdir_name}/: {len(pdf_files)} PDFs")
        
        for pdf_file in pdf_files:
            filename = pdf_file.name
            mtime = pdf_file.stat().st_mtime
            timestamp = datetime.fromtimestamp(mtime).isoformat()
            
            # Try to find corresponding file in publications directory
            final_filename = None
            if status == 'success':
                # Search for files that might match (exact match or variations)
                possible_names = [
                    filename,
                    filename.replace('.pdf', '_scanned.pdf'),
                    filename.replace('.pdf', '_scan.pdf')
                ]
                
                for name in possible_names:
                    pub_file = publications_dir / name
                    if pub_file.exists():
                        final_filename = name
                        break
            
            entries[filename] = {
                'original_filename': filename,
                'status': status,
                'timestamp': timestamp,
                'final_filename': final_filename
            }
    
    print(f"Extracted {len(entries)} entries from directories")
    return entries


def query_zotero_for_item_key(filename: str, zotero_db_path: Optional[Path]) -> Optional[str]:
    """Query Zotero database for item key by filename.
    
    Args:
        filename: PDF filename (may need to search variations)
        zotero_db_path: Path to Zotero SQLite database
        
    Returns:
        Zotero item key if found, None otherwise
    """
    if not zotero_db_path or not zotero_db_path.exists():
        return None
    
    try:
        conn = sqlite3.connect(str(zotero_db_path))
        cursor = conn.cursor()
        
        # Search in itemAttachments and items tables
        # Look for attachments with matching filename
        query = """
            SELECT i.key
            FROM items i
            JOIN itemAttachments ia ON i.itemID = ia.itemID
            WHERE ia.path LIKE ?
            LIMIT 1
        """
        
        # Try exact match and variations
        search_patterns = [
            f'%{filename}%',
            f'%{filename.replace("_scanned.pdf", ".pdf")}%',
            f'%{filename.replace("_scan.pdf", ".pdf")}%'
        ]
        
        for pattern in search_patterns:
            cursor.execute(query, (pattern,))
            result = cursor.fetchone()
            if result:
                conn.close()
                return result[0]
        
        conn.close()
    except Exception as e:
        print(f"Warning: Failed to query Zotero database: {e}")
    
    return None


def merge_entries(
    text_log_entries: Dict[str, Dict],
    directory_entries: Dict[str, Dict],
    zotero_db_path: Optional[Path] = None
) -> List[Dict]:
    """Merge entries from both sources, prioritizing text logs.
    
    Args:
        text_log_entries: Entries from text logs
        directory_entries: Entries from directory scans
        zotero_db_path: Optional path to Zotero database
        
    Returns:
        List of merged entries
    """
    merged = {}
    
    # Start with directory entries (baseline)
    merged.update(directory_entries)
    
    # Override with text log entries (more accurate)
    for filename, entry in text_log_entries.items():
        merged[filename] = entry
    
    # Try to get Zotero item codes for successful entries
    if zotero_db_path:
        print("Querying Zotero database for item codes...")
        success_count = 0
        for filename, entry in merged.items():
            if entry.get('status') == 'success':
                item_key = query_zotero_for_item_key(filename, zotero_db_path)
                if item_key:
                    entry['zotero_item_code'] = item_key
                    success_count += 1
        print(f"Found {success_count} Zotero item codes")
    
    # Convert to list and sort by timestamp
    entries_list = list(merged.values())
    entries_list.sort(key=lambda x: x.get('timestamp', ''))
    
    return entries_list


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Repopulate scanned papers CSV log')
    parser.add_argument('--parse-logs', action='store_true', help='Parse text log files')
    parser.add_argument('--scan-dirs', action='store_true', help='Scan directories')
    parser.add_argument('--both', action='store_true', default=True, help='Use both methods (default)')
    parser.add_argument('--config', type=str, help='Path to config file')
    
    args = parser.parse_args()
    
    # Determine methods to use
    use_logs = args.parse_logs or args.both
    use_dirs = args.scan_dirs or args.both
    
    # Load configuration
    if args.config:
        config_path = Path(args.config)
        personal_config_path = config_path.parent / 'config.personal.conf'
    else:
        root_dir = Path(__file__).parent.parent
        config_path = root_dir / 'config.conf'
        personal_config_path = root_dir / 'config.personal.conf'
    
    config_loader = SecureConfigLoader()
    config = config_loader.load_config(
        config_path=config_path,
        personal_config_path=personal_config_path,
        check_permissions=False
    )
    
    # Get paths from config
    log_folder = config.get('PATHS', 'log_folder', fallback='./data/logs')
    log_folder_path = Path(normalize_path(log_folder))
    
    scanner_papers_dir = config.get('PATHS', 'scanner_papers_dir', 
                                    fallback='/mnt/i/FraScanner/papers')
    scanner_dir = Path(normalize_path(scanner_papers_dir))
    
    publications_dir = config.get('PATHS', 'publications_dir',
                                  fallback='/mnt/g/My Drive/publications')
    pub_dir = Path(normalize_path(publications_dir))
    
    zotero_db_path = config.get('PATHS', 'zotero_db_path', fallback='')
    zotero_db = Path(normalize_path(zotero_db_path)) if zotero_db_path else None
    
    # Initialize logger
    log_file = log_folder_path / 'scanned_papers_log.csv'
    logger = ScannedPapersLogger(log_file)
    
    print("=" * 70)
    print("REPOPULATE SCANNED PAPERS CSV LOG")
    print("=" * 70)
    print(f"Log file: {log_file}")
    print(f"Scanner dir: {scanner_dir}")
    print(f"Publications dir: {pub_dir}")
    print()
    
    # Get existing entries to avoid duplicates
    existing_entries = logger.get_existing_entries()
    existing_filenames = {e.get('original_filename') for e in existing_entries if e.get('original_filename')}
    print(f"Existing CSV entries: {len(existing_filenames)}")
    print()
    
    # Collect entries
    text_log_entries = {}
    directory_entries = {}
    
    if use_logs and log_folder_path.exists():
        text_log_entries = parse_text_logs(log_folder_path)
    
    if use_dirs and scanner_dir.exists():
        directory_entries = scan_directories(scanner_dir, pub_dir)
    
    # Merge entries
    print("\nMerging entries...")
    merged_entries = merge_entries(text_log_entries, directory_entries, zotero_db)
    
    # Filter out entries that already exist
    new_entries = [e for e in merged_entries 
                   if e.get('original_filename') not in existing_filenames]
    
    print(f"\nNew entries to add: {len(new_entries)}")
    
    if new_entries:
        # Add new entries
        for entry in new_entries:
            logger.log_processing(
                original_filename=entry.get('original_filename', ''),
                status=entry.get('status', 'unknown'),
                final_filename=entry.get('final_filename'),
                zotero_item_code=entry.get('zotero_item_code'),
                timestamp=entry.get('timestamp')
            )
        
        print(f"✅ Added {len(new_entries)} new entries to CSV log")
    else:
        print("ℹ️  No new entries to add")
    
    # Summary
    total_entries = len(existing_entries) + len(new_entries)
    print(f"\nTotal entries in CSV log: {total_entries}")
    print(f"Done!")


if __name__ == '__main__':
    main()

