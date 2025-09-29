"""
Metadata extraction for academic papers from OCR text.
"""
import re
import logging
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass
import dateutil.parser
from ..models.paper import PaperMetadata


class MetadataExtractor:
    """Extract metadata from OCR text of academic papers."""
    
    def __init__(self):
        self.logger = logging.getLogger(__name__)
        
        # Common patterns for academic paper metadata
        self.patterns = {
            'doi': re.compile(r'DOI:\s*([^\s]+)', re.IGNORECASE),
            'doi_url': re.compile(r'https?://doi\.org/([^\s]+)', re.IGNORECASE),
            'issn': re.compile(r'ISSN:\s*([0-9]{4}-?[0-9]{4})', re.IGNORECASE),
            'year': re.compile(r'\\b(19|20)\\d{2}\\b'),
            'volume': re.compile(r'Vol\.?\s*(\\d+)', re.IGNORECASE),
            'issue': re.compile(r'(?:No\.?|Issue|Nr\.?)\\s*(\\d+)', re.IGNORECASE),
            'pages': re.compile(r'(?:pp\.?|pages?)\\s*([0-9-]+)', re.IGNORECASE),
            'journal': re.compile(r'([A-Z][a-z]+\\s+(?:Journal|Review|Studies|Quarterly|Monthly|Annual))', re.IGNORECASE),
        }
        
        # Title patterns (usually at the beginning of the text)
        self.title_patterns = [
            re.compile(r'^([^\\n]{10,200})\\n', re.MULTILINE),  # First line if reasonable length
            re.compile(r'^([A-Z][^\\n]{20,150})\\n', re.MULTILINE),  # First line starting with capital
        ]
        
        # Author patterns
        self.author_patterns = [
            re.compile(r'^([A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*)\\s*$', re.MULTILINE),
            re.compile(r'([A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*)(?:,|and|&)', re.IGNORECASE),
        ]
    
    def extract_metadata(self, ocr_text: str) -> PaperMetadata:
        """
        Extract metadata from OCR text.
        
        Args:
            ocr_text: OCR-extracted text from the paper
            
        Returns:
            PaperMetadata object with extracted information
        """
        if not ocr_text or not ocr_text.strip():
            return PaperMetadata()
        
        metadata = PaperMetadata()
        
        # Extract DOI
        metadata.doi = self._extract_doi(ocr_text)
        
        # Extract ISSN
        metadata.issn = self._extract_issn(ocr_text)
        
        # Extract year
        metadata.year = self._extract_year(ocr_text)
        
        # Extract title (usually at the beginning)
        metadata.title = self._extract_title(ocr_text)
        
        # Extract authors
        metadata.authors = self._extract_authors(ocr_text)
        
        # Extract journal information
        metadata.journal = self._extract_journal(ocr_text)
        
        # Extract volume, issue, pages
        metadata.volume = self._extract_volume(ocr_text)
        metadata.issue = self._extract_issue(ocr_text)
        metadata.pages = self._extract_pages(ocr_text)
        
        # Extract abstract (usually after title/authors)
        metadata.abstract = self._extract_abstract(ocr_text)
        
        # Extract keywords
        metadata.keywords = self._extract_keywords(ocr_text)
        
        # Detect language
        metadata.language = self._detect_language(ocr_text)
        
        # Use national libraries based on detected language
        if metadata.language and metadata.confidence < 70:
            enhanced_metadata = self._enhance_with_national_libraries(metadata, ocr_text)
            if enhanced_metadata.confidence > metadata.confidence:
                metadata = enhanced_metadata
        
        # Calculate confidence based on extracted fields
        metadata.confidence = self._calculate_confidence(metadata)
        
        return metadata
    
    def _extract_doi(self, text: str) -> Optional[str]:
        """Extract DOI from text."""
        # Try DOI: pattern first
        match = self.patterns['doi'].search(text)
        if match:
            return match.group(1).strip()
        
        # Try DOI URL pattern
        match = self.patterns['doi_url'].search(text)
        if match:
            return match.group(1).strip()
        
        return None
    
    def _extract_issn(self, text: str) -> Optional[str]:
        """Extract ISSN from text."""
        match = self.patterns['issn'].search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_year(self, text: str) -> Optional[int]:
        """Extract publication year from text."""
        matches = self.patterns['year'].findall(text)
        if matches:
            # Return the most recent year (likely publication year)
            years = [int(year) for year in matches if 1900 <= int(year) <= 2030]
            if years:
                return max(years)
        return None
    
    def _extract_title(self, text: str) -> Optional[str]:
        """Extract title from text."""
        lines = text.split('\\n')[:10]  # Check first 10 lines
        
        for line in lines:
            line = line.strip()
            if len(line) > 10 and len(line) < 200:
                # Check if line looks like a title
                if (line[0].isupper() and 
                    not line.endswith('.') and 
                    not re.search(r'\\b(DOI|ISSN|Abstract|Keywords|Introduction)\\b', line, re.IGNORECASE)):
                    return line
        
        return None
    
    def _extract_authors(self, text: str) -> List[str]:
        """Extract author names from text."""
        authors = []
        lines = text.split('\\n')[:15]  # Check first 15 lines
        
        for line in lines:
            line = line.strip()
            # Look for author patterns
            if re.match(r'^[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*$', line) and len(line) > 5:
                authors.append(line)
            elif re.search(r'\\b(and|&|,)\\b', line, re.IGNORECASE):
                # Split on common separators
                parts = re.split(r'\\b(?:and|&|,)\\b', line, flags=re.IGNORECASE)
                for part in parts:
                    part = part.strip()
                    if len(part) > 5 and re.match(r'^[A-Z][a-z]+(?:\\s+[A-Z][a-z]+)*$', part):
                        authors.append(part)
        
        return authors[:10]  # Limit to reasonable number
    
    def _extract_journal(self, text: str) -> Optional[str]:
        """Extract journal name from text."""
        match = self.patterns['journal'].search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_volume(self, text: str) -> Optional[str]:
        """Extract volume number from text."""
        match = self.patterns['volume'].search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_issue(self, text: str) -> Optional[str]:
        """Extract issue number from text."""
        match = self.patterns['issue'].search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_pages(self, text: str) -> Optional[str]:
        """Extract page numbers from text."""
        match = self.patterns['pages'].search(text)
        if match:
            return match.group(1).strip()
        return None
    
    def _extract_abstract(self, text: str) -> Optional[str]:
        """Extract abstract from text."""
        # Look for abstract section
        abstract_match = re.search(r'\\bAbstract\\b[\\s\\n]+([^\\n]{50,1000})', text, re.IGNORECASE | re.DOTALL)
        if abstract_match:
            abstract = abstract_match.group(1).strip()
            # Clean up the abstract
            abstract = re.sub(r'\\s+', ' ', abstract)
            return abstract[:1000]  # Limit length
        
        return None
    
    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        keywords = []
        
        # Look for keywords section
        keywords_match = re.search(r'\\bKeywords?\\b[\\s\\n:]+([^\\n]{20,500})', text, re.IGNORECASE)
        if keywords_match:
            keywords_text = keywords_match.group(1).strip()
            # Split on common separators
            keyword_list = re.split(r'[,;]', keywords_text)
            for keyword in keyword_list:
                keyword = keyword.strip()
                if len(keyword) > 2:
                    keywords.append(keyword)
        
        return keywords[:20]  # Limit to reasonable number
    
    def _detect_language(self, text: str) -> Optional[str]:
        """Detect language of the text."""
        # Simple language detection based on common words
        text_lower = text.lower()
        
        # English indicators
        en_words = ['the', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for', 'of', 'with', 'by']
        en_count = sum(1 for word in en_words if word in text_lower)
        
        # German indicators
        de_words = ['der', 'die', 'das', 'und', 'oder', 'aber', 'in', 'auf', 'zu', 'für', 'von', 'mit']
        de_count = sum(1 for word in de_words if word in text_lower)
        
        # Norwegian indicators
        no_words = ['og', 'eller', 'men', 'i', 'på', 'til', 'for', 'av', 'med', 'hvis', 'når']
        no_count = sum(1 for word in no_words if word in text_lower)
        
        # Finnish indicators
        fi_words = ['ja', 'tai', 'mutta', 'kuten', 'jos', 'kun', 'kunnes', 'vaikka']
        fi_count = sum(1 for word in fi_words if word in text_lower)
        
        # Determine language
        counts = {'EN': en_count, 'DE': de_count, 'NO': no_count, 'FI': fi_count}
        detected_lang = max(counts, key=counts.get)
        
        return detected_lang if counts[detected_lang] > 0 else None
    
    def _calculate_confidence(self, metadata: PaperMetadata) -> float:
        """Calculate confidence score for extracted metadata."""
        score = 0.0
        max_score = 0.0
        
        # DOI is very reliable
        if metadata.doi:
            score += 20
        max_score += 20
        
        # Title is important
        if metadata.title:
            score += 15
        max_score += 15
        
        # Authors are important
        if metadata.authors:
            score += 15
        max_score += 30
        
        # Year is important
        if metadata.year:
            score += 10
        max_score += 10
        
        # Journal is helpful
        if metadata.journal:
            score += 10
        max_score += 10
        
        # Other fields
        if metadata.issn:
            score += 10
        max_score += 10
        
        if metadata.volume:
            score += 5
        max_score += 5
        
        if metadata.issue:
            score += 5
        max_score += 5
        
        if metadata.pages:
            score += 5
        max_score += 5
        
        if metadata.abstract:
            score += 10
        max_score += 10
        
        return (score / max_score * 100) if max_score > 0 else 0.0
    
    def _enhance_with_national_libraries(self, metadata: 'PaperMetadata', ocr_text: str) -> 'PaperMetadata':
        """Enhance metadata using national libraries based on detected language."""
        try:
            # Import shared tools
            import sys
            from pathlib import Path
            shared_tools_path = Path(__file__).parent.parent.parent.parent.parent / "shared_tools"
            sys.path.insert(0, str(shared_tools_path))
            
            from metadata.extractor import MetadataExtractor as SharedExtractor
            from config.manager import ConfigManager
            
            # Initialize shared extractor with config
            config_manager = ConfigManager()
            config = config_manager.config
            
            shared_extractor = SharedExtractor(config)
            
            # Search national libraries
            result = shared_extractor.extract_paper_metadata(
                title=metadata.title,
                authors=metadata.authors,
                language=metadata.language
            )
            
            # Merge results if we got better data
            if result.confidence > metadata.confidence:
                if result.title and not metadata.title:
                    metadata.title = result.title
                if result.authors and not metadata.authors:
                    metadata.authors = result.authors
                if result.abstract and not metadata.abstract:
                    metadata.abstract = result.abstract
                if result.language and not metadata.language:
                    metadata.language = result.language
                metadata.confidence = max(metadata.confidence, result.confidence)
            
        except Exception as e:
            # If national library enhancement fails, continue with original metadata
            import logging
            logging.warning(f"National library enhancement failed: {e}")
        
        return metadata
