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
import tempfile
import os
import importlib


class GrobidClient:
    """Client for GROBID server."""
    
    def __init__(self, base_url: str = "http://localhost:8070", config: Dict = None):
        """Initialize GROBID client.
        
        Args:
            base_url: GROBID server URL
            config: Configuration dictionary for rotation handling
        """
        self.base_url = base_url.rstrip('/')
        self.logger = logging.getLogger(__name__)
        self.config = config or {}
        
        # Initialize PDF rotation handler lazily to avoid hard dependency on cv2 in test contexts
        self.rotation_handler = None
        try:
            mod = importlib.import_module('shared_tools.pdf.pdf_rotation_handler')
            PDFRotationHandler = getattr(mod, 'PDFRotationHandler')
            self.rotation_handler = PDFRotationHandler(config)
        except Exception:
            # Provide a no-op handler
            class _NoOpRotationHandler:
                def process_pdf_with_rotation(self, pdf_path: Path, max_pages: int = 2):
                    return pdf_path, None
                def create_corrected_pdf(self, pdf_path: Path, rotation: str, output_path: Optional[Path] = None):
                    return None
            self.rotation_handler = _NoOpRotationHandler()
        self.temp_files = []  # Track temporary files for cleanup
    
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
    
    def extract_metadata(self, pdf_path: Path, max_pages: int = 2, handle_rotation: bool = True) -> Optional[Dict]:
        """Extract metadata from PDF using GROBID with optional rotation handling.
        
        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to process (default: 2)
            handle_rotation: Whether to detect and correct PDF rotation (default: True)
            
        Returns:
            Dictionary with extracted metadata or None if failed
        """
        try:
            # Preprocessing: Try structured repository metadata first
            try:
                import pdfplumber
                with pdfplumber.open(pdf_path) as pdf:
                    if len(pdf.pages) > 0:
                        first_page_text = pdf.pages[0].extract_text()
                        if first_page_text:
                            # Try structured extraction
                            structured_metadata = self._extract_structured_repository_metadata(first_page_text)
                            if structured_metadata and structured_metadata.get('title') and structured_metadata.get('authors'):
                                self.logger.info("Found structured repository metadata, using it instead of GROBID")
                                return structured_metadata
            except ImportError:
                pass  # pdfplumber not available, skip preprocessing
            except Exception as e:
                self.logger.debug(f"Structured metadata extraction failed: {e}")
            
            # Handle PDF rotation if enabled
            pdf_to_process = pdf_path
            rotation_applied = None
            
            if handle_rotation:
                self.logger.info("Checking PDF for rotation issues...")
                corrected_pdf, rotation_applied = self.rotation_handler.process_pdf_with_rotation(
                    pdf_path, max_pages
                )
                
                if rotation_applied:
                    self.logger.info(f"Applied rotation correction: {rotation_applied}")
                    pdf_to_process = corrected_pdf
                    # Track temp file for cleanup
                    if corrected_pdf != pdf_path:
                        self.temp_files.append(corrected_pdf)
                else:
                    self.logger.info("No rotation correction needed")
            
            # Helper to call GROBID
            def _call_grobid(in_path: Path, end_pages: int):
                with open(in_path, 'rb') as f:
                    files = {'input': f}
                    data = {'start': '1', 'end': str(end_pages)}
                    return requests.post(
                        f"{self.base_url}/api/processFulltextDocument",
                        files=files,
                        data=data,
                        timeout=60
                    )

            # Send PDF to GROBID with page limit for better author extraction
            response = _call_grobid(pdf_to_process, max_pages)
            
            if response.status_code != 200:
                self.logger.error(f"GROBID failed: {response.status_code}")
                return None
            
            # Log raw XML response in debug mode for troubleshooting
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"GROBID XML response (first 2000 chars):\n{response.text[:2000]}")
                # Try to pretty-print full XML for easier reading
                try:
                    import xml.dom.minidom
                    pretty_xml = xml.dom.minidom.parseString(response.text).toprettyxml(indent="  ")[:5000]
                    self.logger.debug(f"GROBID XML (pretty, first 5000 chars):\n{pretty_xml}")
                except Exception:
                    pass  # If formatting fails, just use raw XML
            
            # Parse XML response
            root = ET.fromstring(response.text)
            
            # Extract metadata
            metadata = self._parse_grobid_xml(root)
            
            # Log what was extracted for debugging conference info
            if self.logger.isEnabledFor(logging.DEBUG):
                self.logger.debug(f"GROBID extracted metadata: {metadata}")
                # Check if conference info exists in XML but wasn't parsed
                meeting_elems = root.findall('.//{http://www.tei-c.org/ns/1.0}meeting')
                if meeting_elems:
                    self.logger.debug(f"Found {len(meeting_elems)} meeting elements in XML")
                    for i, meeting in enumerate(meeting_elems):
                        self.logger.debug(f"  Meeting {i+1}: {ET.tostring(meeting, encoding='unicode')[:500]}")
                else:
                    self.logger.debug("No meeting elements found in GROBID XML")
            
            if metadata:
                metadata['extraction_method'] = 'grobid'
                extraction_note = f'extracted from pages 1-{max_pages} only'
                if rotation_applied:
                    extraction_note += f', rotation corrected ({rotation_applied})'
                metadata['extraction_note'] = extraction_note
                author_count = len(metadata.get('authors', []))
                self.logger.info(f"GROBID extracted: {author_count} authors from first {max_pages} pages")
            
            # TEI debug + retry logic when authors are empty
            if not metadata or not metadata.get('authors'):
                try:
                    # Dump TEI for debugging
                    temp_dir = Path('data') / 'temp' / 'grobid_tei'
                    temp_dir.mkdir(parents=True, exist_ok=True)
                    tei_path = temp_dir / (Path(pdf_to_process).stem + '.tei.xml')
                    tei_path.write_text(response.text)
                    self.logger.info(f"Saved GROBID TEI for debugging: {tei_path}")
                except Exception:
                    pass
                
                # Retry with more pages
                if max_pages < 4:
                    self.logger.info("Retrying GROBID with max_pages=4...")
                    resp2 = _call_grobid(pdf_to_process, 4)
                    if resp2.status_code == 200:
                        try:
                            root2 = ET.fromstring(resp2.text)
                            metadata2 = self._parse_grobid_xml(root2)
                            if metadata2 and metadata2.get('authors'):
                                metadata2['extraction_method'] = 'grobid'
                                metadata2['extraction_note'] = 'extracted from pages 1-4'
                                self.logger.info(f"GROBID retry succeeded: {len(metadata2.get('authors', []))} authors from first 4 pages")
                                return metadata2
                        except Exception:
                            pass
                
                # Try forced rotation variants (90/270) once
                for rot in ['rotated_90', 'rotated_270']:
                    try:
                        self.logger.info(f"Retrying GROBID with forced rotation: {rot}...")
                        rotated_pdf = self.rotation_handler.create_corrected_pdf(pdf_path, rot)
                        if rotated_pdf and rotated_pdf.exists():
                            self.temp_files.append(rotated_pdf)
                            resp3 = _call_grobid(rotated_pdf, 2)
                            if resp3.status_code == 200:
                                root3 = ET.fromstring(resp3.text)
                                metadata3 = self._parse_grobid_xml(root3)
                                if metadata3 and metadata3.get('authors'):
                                    metadata3['extraction_method'] = 'grobid'
                                    metadata3['extraction_note'] = f'extracted from pages 1-2, forced rotation {rot}'
                                    self.logger.info(f"GROBID rotation retry succeeded: {len(metadata3.get('authors', []))} authors")
                                    return metadata3
                    except Exception as e:
                        self.logger.debug(f"Rotation retry failed for {rot}: {e}")
            
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
        
        # Extract title - handle multi-line titles with <lb/> tags
        title_elem = root.find('.//{http://www.tei-c.org/ns/1.0}title[@type="main"]')
        if title_elem is not None:
            # Use itertext() to get all text content recursively, including after <lb/> tags
            # This handles multi-line titles properly
            title_parts = []
            
            # Iterate through all text nodes in the title element
            # ElementTree's itertext() gets all text content, including tail text after <lb/>
            for text in title_elem.itertext():
                if text and text.strip():
                    title_parts.append(text.strip())
            
            # Combine all parts with spaces
            if title_parts:
                full_title = ' '.join(title_parts)
                # Clean up multiple spaces (from line breaks becoming spaces)
                full_title = ' '.join(full_title.split())
                if full_title:
                    metadata['title'] = full_title
        
        # Extract authors
        authors = []
        for author in root.findall('.//{http://www.tei-c.org/ns/1.0}author'):
            # Get all forenames (first name, middle names, etc.)
            forenames = author.findall('.//{http://www.tei-c.org/ns/1.0}forename')
            surname = author.find('.//{http://www.tei-c.org/ns/1.0}surname')
            
            if forenames and surname is not None and surname.text:
                # Combine all forenames
                forename_parts = [f.text.strip() for f in forenames if f.text]
                forename_text = ' '.join(forename_parts)
                surname_text = surname.text.strip()
                
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
    
    def _extract_structured_repository_metadata(self, text: str) -> Optional[Dict]:
        """Extract structured metadata from repository pages using labeled fields.
        
        Handles patterns like:
        Title
        [title text]
        
        Author
        [author name]
        
        Publication Date
        1995-07-01
        
        Args:
            text: First page text from PDF
            
        Returns:
            Metadata dictionary if found, None otherwise
        """
        import re
        
        metadata = {}
        found_any = False
        
        # Extract title (case-insensitive, flexible spacing)
        title_pattern = r'(?:^|\n)title\s*\n(.+?)(?=\n(?:author|publication|journal|date|url)|$)'
        match = re.search(title_pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            title = match.group(1).strip()
            # Clean up title (remove extra whitespace, newlines)
            title = ' '.join(title.split())
            if len(title) > 5:  # Valid titles are usually >5 chars
                metadata['title'] = title
                found_any = True
        
        # Extract author (case-insensitive)
        author_pattern = r'(?:^|\n)author\s*\n(.+?)(?=\n(?:title|publication|journal|date|url)|$)'
        match = re.search(author_pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            author = match.group(1).strip()
            # Clean up author
            author = ' '.join(author.split())
            if len(author) > 2 and ',' in author:  # Author format "Last, First"
                metadata['authors'] = [author]
                found_any = True
        
        # Extract publication date (multiple formats: YYYY-MM-DD, DD.MM.YYYY, July 1994, etc.)
        date_pattern = r'(?:publication\s+date|date)\s*\n([^\n]+)'
        match = re.search(date_pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            date_str = match.group(1).strip()
            
            # Try various date formats to extract year
            year = None
            
            # Format 1: ISO format (1995-07-01)
            iso_match = re.search(r'(\d{4})-\d{2}-\d{2}', date_str)
            if iso_match:
                year = iso_match.group(1)
            
            # Format 2: European format (01.07.1994)
            if not year:
                euro_match = re.search(r'\d{2}\.\d{2}\.(\d{4})', date_str)
                if euro_match:
                    year = euro_match.group(1)
            
            # Format 3: Month name + year (July 1994, Jul 1994)
            if not year:
                month_year_match = re.search(r'[A-Za-z]+\s+(\d{4})', date_str)
                if month_year_match:
                    year = month_year_match.group(1)
            
            # Format 4: YYYY format (1994)
            if not year:
                year_match = re.search(r'(\d{4})', date_str)
                if year_match:
                    year = year_match.group(1)
            
            # Validate year
            if year and 1900 <= int(year) <= 2100:
                metadata['year'] = year
                found_any = True
        
        # Extract journal (case-insensitive)
        journal_pattern = r'(?:^|\n)journal\s*\n(.+?)(?=\n(?:author|title|publication|date|url)|$)'
        match = re.search(journal_pattern, text, re.IGNORECASE | re.MULTILINE | re.DOTALL)
        if match:
            journal = match.group(1).strip()
            journal = ' '.join(journal.split())
            if len(journal) > 3:
                metadata['journal'] = journal
                found_any = True
        
        # Extract URL (http:// or https://)
        url_pattern = r'(?:^|\n)(?:url|permanent\s+link|doi)\s*\n(https?://[^\s\n]+)'
        match = re.search(url_pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            url = match.group(1).strip()
            # Validate URL
            if url.startswith('http://') or url.startswith('https://'):
                metadata['url'] = url
                found_any = True
        
        if found_any:
            metadata['extraction_method'] = 'structured_repository_metadata'
            return metadata
        
        return None
    
    def cleanup_temp_files(self):
        """Clean up temporary files created during processing."""
        for temp_file in self.temp_files:
            try:
                if temp_file.exists():
                    temp_file.unlink()
                    self.logger.debug(f"Cleaned up temp file: {temp_file}")
            except Exception as e:
                self.logger.warning(f"Failed to clean up temp file {temp_file}: {e}")
        self.temp_files.clear()
    
    def __del__(self):
        """Cleanup on destruction."""
        self.cleanup_temp_files()


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
