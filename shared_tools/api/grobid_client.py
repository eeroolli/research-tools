#!/usr/bin/env python3
"""
GROBID client for academic paper metadata extraction.

GROBID (GeneRation Of BIbliographic Data) is a machine learning-based system
for extracting structured data from PDFs, specifically designed for academic papers.
"""

import requests
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional
import logging


class GrobidClient:
    """Client for GROBID server."""
    
    def __init__(self, base_url: str = "http://localhost:8070"):
        """Initialize GROBID client.
        
        Args:
            base_url: GROBID server URL
        """
        self.base_url = base_url.rstrip('/')
        self.logger = logging.getLogger(__name__)
    
    def is_available(self, verbose: bool = False) -> bool:
        """Check if GROBID server is available.
        
        Args:
            verbose: If True, log debug messages. If False, silent check.
        
        Returns:
            True if server is responding
        """
        try:
            response = requests.get(f"{self.base_url}/api/isalive", timeout=5)
            return response.status_code == 200 and response.text.strip() == "true"
        except Exception as e:
            if verbose:
                self.logger.debug(f"GROBID not available: {e}")
            return False
    
    def extract_metadata(self, pdf_path: Path, max_pages: int = 2) -> Optional[Dict]:
        """Extract metadata from PDF using GROBID.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process (default: 2)
            
        Returns:
            Dictionary with extracted metadata or None if failed
        """
        try:
            # Send PDF to GROBID with page limit for better author extraction
            with open(pdf_path, 'rb') as f:
                files = {'input': f}
                # Limit to specified pages to avoid extracting authors from references
                data = {'start': '1', 'end': str(max_pages)}
                response = requests.post(
                    f"{self.base_url}/api/processFulltextDocument",
                    files=files,
                    data=data,
                    timeout=60  # GROBID can be slow
                )
            
            if response.status_code != 200:
                self.logger.error(f"GROBID failed: {response.status_code}")
                return None
            
            # Parse XML response
            root = ET.fromstring(response.text)
            
            # Extract metadata
            metadata = self._parse_grobid_xml(root)
            
            if metadata:
                metadata['extraction_method'] = 'grobid'
                metadata['extraction_note'] = f'extracted from pages 1-{max_pages} only'
                author_count = len(metadata.get('authors', []))
                self.logger.info(f"GROBID extracted: {author_count} authors from first {max_pages} pages")
            
            return metadata
            
        except Exception as e:
            self.logger.error(f"GROBID extraction failed: {e}")
            return None
    
    def _parse_grobid_xml(self, root: ET.Element) -> Dict:
        """Parse GROBID XML response into metadata dictionary.
        
        Args:
            root: XML root element
            
        Returns:
            Metadata dictionary
        """
        metadata = {}
        
        # Extract title
        title_elem = root.find('.//{http://www.tei-c.org/ns/1.0}title[@type="main"]')
        if title_elem is not None and title_elem.text:
            metadata['title'] = title_elem.text.strip()
        
        # Extract authors
        authors = []
        for author in root.findall('.//{http://www.tei-c.org/ns/1.0}author'):
            forename = author.find('.//{http://www.tei-c.org/ns/1.0}forename')
            surname = author.find('.//{http://www.tei-c.org/ns/1.0}surname')
            
            if forename is not None and surname is not None:
                forename_text = forename.text.strip() if forename.text else ""
                surname_text = surname.text.strip() if surname.text else ""
                if forename_text and surname_text:
                    authors.append(f"{surname_text}, {forename_text}")
            elif surname is not None and surname.text:
                # Only surname available
                authors.append(surname.text.strip())
        
        if authors:
            metadata['authors'] = authors
        
        # Extract abstract
        abstract_elem = root.find('.//{http://www.tei-c.org/ns/1.0}abstract')
        if abstract_elem is not None and abstract_elem.text:
            metadata['abstract'] = abstract_elem.text.strip()
        
        # Extract DOI
        doi_elem = root.find('.//{http://www.tei-c.org/ns/1.0}idno[@type="DOI"]')
        if doi_elem is not None and doi_elem.text:
            metadata['doi'] = doi_elem.text.strip()
        
        # Extract journal
        journal_elem = root.find('.//{http://www.tei-c.org/ns/1.0}monogr/{http://www.tei-c.org/ns/1.0}title')
        if journal_elem is not None and journal_elem.text:
            metadata['journal'] = journal_elem.text.strip()
        
        # Extract year
        date_elem = root.find('.//{http://www.tei-c.org/ns/1.0}date[@type="published"]')
        if date_elem is not None and date_elem.text:
            year = date_elem.text.strip()[:4]  # Get first 4 characters
            if year.isdigit():
                metadata['year'] = year
        
        # Extract document type from GROBID analysis
        metadata['document_type'] = self._extract_document_type(root, metadata)
        
        # Extract additional metadata
        self._extract_additional_metadata(root, metadata)
        
        return metadata
    
    def _extract_document_type(self, root: ET.Element, metadata: Dict) -> str:
        """Extract document type from GROBID XML analysis.
        
        Args:
            root: XML root element
            metadata: Already extracted metadata
            
        Returns:
            Document type string
        """
        # Check for explicit document type in GROBID output
        source_elem = root.find('.//{http://www.tei-c.org/ns/1.0}sourceDesc/{http://www.tei-c.org/ns/1.0}biblStruct')
        
        if source_elem is not None:
            # Check for monograph (book)
            monogr_elem = source_elem.find('.//{http://www.tei-c.org/ns/1.0}monogr')
            if monogr_elem is not None:
                # Check if it's a book or journal article
                title_elem = monogr_elem.find('.//{http://www.tei-c.org/ns/1.0}title')
                if title_elem is not None:
                    title_level = title_elem.get('level', '')
                    if title_level == 'j':
                        return 'journal_article'
                    elif title_level == 'm':
                        return 'book'
                    elif title_level == 'a':
                        return 'book_chapter'
            
            # Check for conference proceedings
            meeting_elem = source_elem.find('.//{http://www.tei-c.org/ns/1.0}meeting')
            if meeting_elem is not None:
                return 'conference_paper'
        
        # Check for thesis indicators
        title = metadata.get('title', '').lower()
        if any(word in title for word in ['thesis', 'dissertation', 'phd', 'master']):
            return 'thesis'
        
        # Check for report indicators
        if any(word in title for word in ['report', 'technical report', 'working paper']):
            return 'report'
        
        # Check for preprint indicators
        if any(word in title for word in ['preprint', 'arxiv', 'working paper']):
            return 'preprint'
        
        # Check for news article indicators
        if any(word in title for word in ['news', 'editorial', 'opinion', 'commentary']):
            return 'news_article'
        
        # Check if journal is present (strong indicator of journal article)
        if metadata.get('journal'):
            return 'journal_article'
        
        # Check title for book indicators
        if any(word in title for word in ['book', 'handbook', 'manual', 'guide']):
            return 'book'
        
        # Default to academic paper if we can't determine
        return 'academic_paper'
    
    def _extract_additional_metadata(self, root: ET.Element, metadata: Dict):
        """Extract additional metadata from GROBID XML.
        
        Args:
            root: XML root element
            metadata: Metadata dictionary to update
        """
        # Extract keywords
        keywords = []
        for keyword in root.findall('.//{http://www.tei-c.org/ns/1.0}keywords/{http://www.tei-c.org/ns/1.0}term'):
            if keyword.text:
                keywords.append(keyword.text.strip())
        if keywords:
            metadata['keywords'] = keywords
        
        # Extract conference information
        meeting_elem = root.find('.//{http://www.tei-c.org/ns/1.0}meeting')
        if meeting_elem is not None:
            meeting_name = meeting_elem.find('.//{http://www.tei-c.org/ns/1.0}name')
            if meeting_name is not None and meeting_name.text:
                metadata['conference'] = meeting_name.text.strip()
        
        # Extract publisher
        publisher_elem = root.find('.//{http://www.tei-c.org/ns/1.0}publisher/{http://www.tei-c.org/ns/1.0}name')
        if publisher_elem is not None and publisher_elem.text:
            metadata['publisher'] = publisher_elem.text.strip()
        
        # Extract volume and issue
        bibl_scope = root.find('.//{http://www.tei-c.org/ns/1.0}biblScope')
        if bibl_scope is not None:
            unit = bibl_scope.get('unit', '')
            if unit == 'volume' and bibl_scope.text:
                metadata['volume'] = bibl_scope.text.strip()
            elif unit == 'issue' and bibl_scope.text:
                metadata['issue'] = bibl_scope.text.strip()
        
        # Extract pages
        pages_elem = root.find('.//{http://www.tei-c.org/ns/1.0}biblScope[@unit="page"]')
        if pages_elem is not None and pages_elem.text:
            metadata['pages'] = pages_elem.text.strip()
        
        # Extract language
        lang_elem = root.find('.//{http://www.tei-c.org/ns/1.0}textLang')
        if lang_elem is not None and lang_elem.text:
            metadata['language'] = lang_elem.text.strip()


if __name__ == "__main__":
    # Test GROBID client
    import sys
    from pathlib import Path
    
    if len(sys.argv) != 2:
        print("Usage: python grobid_client.py <pdf_path>")
        sys.exit(1)
    
    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}")
        sys.exit(1)
    
    client = GrobidClient()
    
    if not client.is_available():
        print("❌ GROBID server not available")
        sys.exit(1)
    
    print(f"✅ GROBID server available")
    print(f"📄 Processing: {pdf_path.name}")
    
    metadata = client.extract_metadata(pdf_path)
    
    if metadata:
        print("\n✅ GROBID extracted metadata:")
        for key, value in metadata.items():
            if isinstance(value, list):
                print(f"  {key}: {', '.join(value)}")
            else:
                print(f"  {key}: {value}")
    else:
        print("❌ GROBID extraction failed")
