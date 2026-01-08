#!/usr/bin/env python3
"""
Zotero workflow orchestration module for daemon.

Coordinates Zotero search, matching, and attachment workflows.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any, List

from shared_tools.daemon.exceptions import ZoteroError
from shared_tools.zotero.paper_processor import ZoteroPaperProcessor
from shared_tools.zotero.local_search import ZoteroLocalSearch


class ZoteroWorkflow:
    """Orchestrates Zotero search, matching, and attachment workflows."""
    
    def __init__(
        self,
        zotero_processor: Optional[ZoteroPaperProcessor] = None,
        local_search: Optional[ZoteroLocalSearch] = None,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize Zotero workflow.
        
        Args:
            zotero_processor: ZoteroPaperProcessor instance (created if None)
            local_search: ZoteroLocalSearch instance (created if None)
            logger: Optional logger instance
        """
        self.zotero_processor = zotero_processor or ZoteroPaperProcessor()
        self.local_search = local_search or ZoteroLocalSearch()
        self.logger = logger or logging.getLogger(__name__)
    
    def search_zotero(self, metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Search Zotero library for matching items.
        
        Args:
            metadata: Metadata dictionary with title, authors, etc.
            
        Returns:
            List of matching Zotero items
            
        Raises:
            ZoteroError: If search fails
        """
        try:
            # Use local search for fast matching
            results = self.local_search.search_by_metadata(metadata)
            return results
        except Exception as e:
            raise ZoteroError(f"Zotero search failed: {e}") from e
    
    def attach_pdf_to_item(
        self,
        pdf_path: Path,
        zotero_item: Dict[str, Any],
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Attach PDF to Zotero item.
        
        Args:
            pdf_path: Path to PDF file to attach
            zotero_item: Zotero item dictionary
            metadata: Optional metadata dictionary
            
        Returns:
            True if attachment successful, False otherwise
            
        Raises:
            ZoteroError: If attachment fails
        """
        try:
            item_key = zotero_item.get('key') or zotero_item.get('item_key')
            if not item_key:
                raise ZoteroError("No item key found in Zotero item")
            
            # Use zotero processor to attach PDF
            success = self.zotero_processor.attach_pdf_to_item(pdf_path, item_key, metadata)
            return success
        except ZoteroError:
            raise
        except Exception as e:
            raise ZoteroError(f"Failed to attach PDF to Zotero item: {e}") from e
    
    def create_new_item(
        self,
        pdf_path: Path,
        metadata: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """Create new Zotero item with PDF attachment.
        
        Args:
            pdf_path: Path to PDF file
            metadata: Metadata dictionary for new item
            
        Returns:
            Created Zotero item dictionary, or None if creation failed
            
        Raises:
            ZoteroError: If item creation fails
        """
        try:
            item = self.zotero_processor.create_item_with_pdf(pdf_path, metadata)
            return item
        except Exception as e:
            raise ZoteroError(f"Failed to create Zotero item: {e}") from e

