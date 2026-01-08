#!/usr/bin/env python3
"""
Metadata workflow orchestration module for daemon.

Coordinates metadata extraction strategies (GREP, GROBID, Ollama)
and handles confirmation workflows.
"""

import logging
from pathlib import Path
from typing import Optional, Dict, Any

from shared_tools.daemon.exceptions import MetadataExtractionError
from shared_tools.metadata.paper_processor import PaperMetadataProcessor


class MetadataWorkflow:
    """Orchestrates metadata extraction workflows."""
    
    def __init__(
        self,
        metadata_processor: Optional[PaperMetadataProcessor] = None,
        logger: Optional[logging.Logger] = None
    ):
        """Initialize metadata workflow.
        
        Args:
            metadata_processor: PaperMetadataProcessor instance (created if None)
            logger: Optional logger instance
        """
        self.metadata_processor = metadata_processor or PaperMetadataProcessor()
        self.logger = logger or logging.getLogger(__name__)
    
    def extract_metadata(
        self,
        pdf_path: Path,
        use_grobid: bool = True,
        use_ollama: bool = True,
        page_offset: int = 0
    ) -> Dict[str, Any]:
        """Extract metadata from PDF using multiple strategies.
        
        Tries extraction strategies in order:
        1. GREP identifier extraction + API lookup (fast)
        2. GROBID extraction (medium speed, if use_grobid=True)
        3. Ollama extraction (slow, fallback if use_ollama=True)
        
        Args:
            pdf_path: Path to PDF file
            use_grobid: If True, try GROBID extraction
            use_ollama: If True, try Ollama extraction as fallback
            page_offset: Page offset for processing (0-indexed)
            
        Returns:
            Dictionary containing extracted metadata and extraction method
            
        Raises:
            MetadataExtractionError: If all extraction methods fail
        """
        # Try GREP + API lookup first (fast path)
        try:
            metadata = self.metadata_processor.process_pdf(
                pdf_path,
                use_ollama_fallback=False,
                page_offset=page_offset
            )
            if metadata and metadata.get('title'):
                self.logger.info("Metadata extracted via GREP + API lookup")
                return metadata
        except Exception as e:
            self.logger.debug(f"GREP + API extraction failed: {e}")
        
        # Try GROBID extraction
        if use_grobid:
            try:
                metadata = self.metadata_processor.process_pdf(
                    pdf_path,
                    use_ollama_fallback=False,
                    page_offset=page_offset
                )
                if metadata and metadata.get('title'):
                    self.logger.info("Metadata extracted via GROBID")
                    return metadata
            except Exception as e:
                self.logger.debug(f"GROBID extraction failed: {e}")
        
        # Try Ollama extraction as fallback
        if use_ollama:
            try:
                metadata = self.metadata_processor.process_pdf(
                    pdf_path,
                    use_ollama_fallback=True,
                    page_offset=page_offset
                )
                if metadata and metadata.get('title'):
                    self.logger.info("Metadata extracted via Ollama")
                    return metadata
            except Exception as e:
                self.logger.debug(f"Ollama extraction failed: {e}")
        
        # All methods failed
        raise MetadataExtractionError(f"All metadata extraction methods failed for {pdf_path.name}")

