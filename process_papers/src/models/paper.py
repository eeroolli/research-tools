"""
Data models for academic papers.
"""
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class ProcessingStatus(Enum):
    """Processing status for papers."""
    PENDING = "pending"
    SCANNED = "scanned"
    OCR_PROCESSED = "ocr_processed"
    METADATA_EXTRACTED = "metadata_extracted"
    MATCHED = "matched"
    INTEGRATED = "integrated"
    FAILED = "failed"


@dataclass
class PaperMetadata:
    """Extracted metadata from a paper."""
    title: Optional[str] = None
    authors: Optional[List[str]] = None
    year: Optional[int] = None
    journal: Optional[str] = None
    volume: Optional[str] = None
    issue: Optional[str] = None
    pages: Optional[str] = None
    doi: Optional[str] = None
    issn: Optional[str] = None
    abstract: Optional[str] = None
    keywords: Optional[List[str]] = None
    language: Optional[str] = None
    confidence: float = 0.0


@dataclass
class ScanInfo:
    """Information about the scanning process."""
    scan_timestamp: Optional[datetime] = None
    scanner_model: Optional[str] = None
    resolution: Optional[str] = None
    color_mode: Optional[str] = None
    file_size: Optional[int] = None
    page_count: Optional[int] = None


@dataclass
class AnnotationInfo:
    """Information about handwritten annotations."""
    has_annotations: bool = False
    annotation_colors: List[str] = field(default_factory=list)
    has_underlining: bool = False
    has_marginal_notes: bool = False
    has_highlighting: bool = False
    annotation_density: float = 0.0


@dataclass
class Paper:
    """Complete paper data model."""
    id: str
    file_path: str
    status: ProcessingStatus = ProcessingStatus.PENDING
    
    # Scan information
    scan_info: Optional[ScanInfo] = None
    
    # Extracted data
    metadata: Optional[PaperMetadata] = None
    ocr_text: Optional[str] = None
    annotation_info: Optional[AnnotationInfo] = None
    
    # Processing information
    processing_log: List[str] = field(default_factory=list)
    error_messages: List[str] = field(default_factory=list)
    processing_time: float = 0.0
    
    # Zotero integration
    zotero_item_id: Optional[str] = None
    zotero_match_confidence: float = 0.0
    zotero_match_method: Optional[str] = None
    
    # File management
    original_filename: Optional[str] = None
    final_filename: Optional[str] = None
    folder_cover_path: Optional[str] = None
    
    def add_log_entry(self, message: str):
        """Add an entry to the processing log."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.processing_log.append(f"[{timestamp}] {message}")
    
    def add_error(self, error: str):
        """Add an error message."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.error_messages.append(f"[{timestamp}] {error}")
    
    def get_display_title(self) -> str:
        """Get a display title for the paper."""
        if self.metadata and self.metadata.title:
            return self.metadata.title[:100] + "..." if len(self.metadata.title) > 100 else self.metadata.title
        return f"Paper {self.id}"
    
    def get_authors_display(self) -> str:
        """Get formatted authors string."""
        if not self.metadata or not self.metadata.authors:
            return "Unknown authors"
        
        authors = self.metadata.authors
        if len(authors) == 1:
            return authors[0]
        elif len(authors) == 2:
            return f"{authors[0]} & {authors[1]}"
        else:
            return f"{authors[0]} et al."
    
    def get_filename_suggestion(self) -> str:
        """Generate suggested filename based on metadata."""
        if not self.metadata:
            return f"paper_{self.id}.pdf"
        
        # Format: author_year_title.pdf
        author_part = self.get_authors_display().replace(" ", "_").replace("&", "and")
        year_part = str(self.metadata.year) if self.metadata.year else "unknown"
        title_part = (self.metadata.title or "untitled")[:50].replace(" ", "_")
        
        return f"{author_part}_{year_part}_{title_part}.pdf"
