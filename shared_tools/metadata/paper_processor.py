#!/usr/bin/env python3
"""
Smart paper metadata extraction workflow.

Optimized extraction strategy:
1. Fast regex extraction of identifiers (1-2 seconds)
2. API lookup if identifier found (1-2 seconds)
3. Ollama fallback only if no identifiers (60-120 seconds)

This makes 90% of papers process in seconds instead of minutes.
"""

import sys
import json
import time
import configparser
import re
from pathlib import Path
from typing import Optional, Dict, List

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.utils.identifier_extractor import IdentifierExtractor
from shared_tools.utils.identifier_validator import IdentifierValidator
from shared_tools.utils.api_priority_manager import APIPriorityManager
from shared_tools.api.crossref_client import CrossRefClient
from shared_tools.api.arxiv_client import ArxivClient
from shared_tools.api.openalex_client import OpenAlexClient
from shared_tools.api.pubmed_client import PubMedClient
from shared_tools.api.jstor_client import JSTORClient
from shared_tools.ai.ollama_client import OllamaClient
from shared_tools.utils.author_extractor import AuthorExtractor
from shared_tools.utils.document_classifier import DocumentClassifier
from shared_tools.metadata.jstor_handler import JSTORHandler
from shared_tools.utils.author_validator import AuthorValidator
from shared_tools.utils.journal_validator import JournalValidator
from shared_tools.utils.author_filter import AuthorFilter


class PaperMetadataProcessor:
    """Smart paper metadata extraction with fast-path optimization."""
    
    def __init__(self, email: Optional[str] = None):
        """Initialize processor.
        
        Args:
            email: Your email for CrossRef polite pool (better rate limits)
                   If None, reads from config.conf/config.personal.conf
        """
        # Read email from config if not provided
        if email is None:
            email = self._read_email_from_config()
        
        self.extractor = IdentifierExtractor()
        self.validator = IdentifierValidator()
        self.priority_manager = APIPriorityManager()
        
        # Initialize author/journal validators (lazy loading with caching)
        self.author_validator = None
        self.journal_validator = None
        
        # Initialize API clients
        self.crossref = CrossRefClient(email=email)
        self.arxiv = ArxivClient()
        self.openalex = OpenAlexClient(email=email)
        self.pubmed = PubMedClient(email=email)
        self.jstor = JSTORClient()
        self.ollama = OllamaClient()
        
        # Map API names to clients
        self.api_clients = {
            'crossref': self.crossref,
            'arxiv': self.arxiv,
            'openalex': self.openalex,
            'pubmed': self.pubmed
        }
        self.jstor_handler = JSTORHandler(self.api_clients, self.priority_manager, self.jstor)
    
    def _read_email_from_config(self) -> Optional[str]:
        """Read CrossRef email from config files.
        
        Returns:
            Email address or None
        """
        try:
            config = configparser.ConfigParser()
            
            # Read both config files (personal overrides main)
            root_dir = Path(__file__).parent.parent.parent
            config.read([
                root_dir / 'config.conf',
                root_dir / 'config.personal.conf'
            ])
            
            if config.has_option('APIS', 'crossref_email'):
                email = config.get('APIS', 'crossref_email').strip()
                return email if email else None
            
            return None
        except Exception:
            return None
    
    def _validate_doi_metadata_against_pdf(self, doi_metadata: Dict, pdf_path: Path, page_offset: int = 0) -> bool:
        """Validate that DOI metadata matches PDF text to avoid false positives.
        
        Checks if the DOI metadata title or key author last names appear in the PDF text.
        This prevents accepting metadata from a citation/reference DOI instead of the actual paper.
        
        Args:
            doi_metadata: Metadata dict from DOI lookup (expects 'title' and 'authors')
            pdf_path: Path to PDF file
            page_offset: 0-indexed page offset for extraction
            
        Returns:
            True if metadata matches PDF text, False otherwise
        """
        if not doi_metadata:
            return False
        
        # Extract text from first 1-3 pages
        doc_text = IdentifierExtractor.extract_text(pdf_path, page_offset=page_offset, max_pages=3)
        if not doc_text:
            return False  # Can't validate if no text extracted
        
        doc_text_lower = doc_text.lower()
        
        # Check title
        title = doi_metadata.get('title', '').strip()
        if title:
            # Try to find significant words from title (at least 3 words or key phrases)
            title_words = [w for w in title.lower().split() if len(w) > 3]  # Skip short words
            if len(title_words) >= 2:
                # Check if at least 2 significant words appear in text
                found_words = sum(1 for word in title_words if word in doc_text_lower)
                if found_words >= 2:
                    return True  # Title matches
        
        # Check authors (last names)
        authors = doi_metadata.get('authors', [])
        if authors and isinstance(authors, list):
            authors_found = 0
            for author in authors[:3]:  # Check first 3 authors
                if not author or not isinstance(author, str):
                    continue
                author_lower = author.lower()
                # Extract last name (last word, or part before comma)
                if ',' in author_lower:
                    last_name = author_lower.split(',')[0].strip()
                else:
                    parts = author_lower.split()
                    last_name = parts[-1].strip() if parts else ""
                
                if last_name and len(last_name) > 2:
                    # Check if last name appears in text (word boundary matching)
                    import re
                    pattern = r'\b' + re.escape(last_name) + r'\b'
                    if re.search(pattern, doc_text_lower):
                        authors_found += 1
            
            # If at least one author last name found, consider it a match
            if authors_found >= 1:
                return True
        
        # If neither title nor authors match, likely a false positive
        return False
    
    def _filter_regex_authors(self, regex_authors: List[str]) -> List[str]:
        """Filter regex-extracted authors using Zotero author/journal lists.
        
        Args:
            regex_authors: List of author names from regex extraction
            
        Returns:
            Filtered list of authors based on config mode
        """
        if not regex_authors:
            return []
        
        # Lazy initialization of validators (they handle caching internally)
        if self.author_validator is None:
            try:
                self.author_validator = AuthorValidator()
            except Exception as e:
                # If validator fails (e.g., DB not found), skip filtering
                print(f"  ⚠️  Could not initialize author validator: {e}")
                return regex_authors
        
        if self.journal_validator is None:
            try:
                self.journal_validator = JournalValidator()
            except Exception as e:
                # If validator fails, skip journal filtering
                print(f"  ⚠️  Could not initialize journal validator: {e}")
                self.journal_validator = None
        
        # Use shared filtering method with strict (last-name only) matching for regex
        return AuthorFilter.filter_authors_against_zotero(
            authors=regex_authors,
            author_validator=self.author_validator,
            journal_validator=self.journal_validator,
            logger=None,
            strict_match=True,
        )
    
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
        # Matches "author\n...", "authors\n...", "Author(s): ...", and "Authors: ..." formats
        author_pattern = r'(?:^|\n)author(?:s|\(s\))?\s*(?::\s*|\n)([^\n]+)(?=\n(?:title|publication|journal|date|url)|$)'
        match = re.search(author_pattern, text, re.IGNORECASE | re.MULTILINE)
        if match:
            author = match.group(1).strip()
            # Clean up author
            author = ' '.join(author.split())
            if len(author) > 2:  # Removed comma requirement to support "First Last and First Last" format
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
    
    def _detect_language_from_filename(self, pdf_path: Path) -> Optional[str]:
        """Detect language from filename prefix (NO_, EN_, DE_, etc.)
        
        Args:
            pdf_path: Path to PDF file
            
        Returns:
            Language code (NO, EN, DE, FI, SV) or None if not detected
        """
        filename = pdf_path.name.upper()
        language_map = {
            'NO_': 'NO',
            'EN_': 'EN',
            'DE_': 'DE',
            'FI_': 'FI',
            'SV_': 'SV'  # Swedish (matches filename prefix SV_)
        }
        
        for prefix, lang_code in language_map.items():
            if filename.startswith(prefix):
                return lang_code
        
        return None
    
    def process_pdf(self, pdf_path: Path, use_ollama_fallback: bool = True, progress_callback=None, page_offset: int = 0) -> Dict:
        """Process a PDF to extract metadata using smart workflow.
        
        Args:
            pdf_path: Path to PDF file
            use_ollama_fallback: Whether to use Ollama if no identifiers found
            progress_callback: Optional callback for progress updates
            page_offset: 0-indexed page offset (0 = page 1, 1 = page 2, etc.) to skip pages before document starts
            
        Returns:
            Dictionary with metadata and processing info
        """
        pdf_path = Path(pdf_path)
        result = {
            'file': pdf_path.name,
            'method': None,
            'metadata': None,
            'processing_time_seconds': 0,
            'identifiers_found': {},
            'success': False,
        }
        
        import time
        start_time = time.time()
        
        print(f"\n{'='*80}")
        print(f"Processing: {pdf_path.name}")
        print(f"{'='*80}")
        
        # Step 0: Check if this appears to be a handwritten note
        print("\n🔍 Step 0: Checking document type...")
        try:
            if DocumentClassifier.is_handwritten_note(pdf_path, page_offset=page_offset):
                print(f"  📝 Detected: Handwritten note (very little OCR text)")
                print(f"  ⚠️  Skipping Ollama processing - no extractable text")
                result['method'] = 'handwritten_note_detected'
                result['metadata'] = {
                    'document_type': 'handwritten_note',
                    'title': '',
                    'authors': [],
                    'extraction_method': 'handwritten_note_detection'
                }
                result['success'] = False  # Mark as needing manual entry
                result['processing_time_seconds'] = time.time() - start_time
                return result
        except Exception as e:
            # If detection fails (e.g., pdfplumber not available), continue with normal processing
            print(f"  ⚠️  Could not check for handwritten note: {e}")
            print(f"  ℹ️  Continuing with normal processing...")
        
        # Step 1: Fast identifier extraction with regex
        print("\n📋 Step 1: Extracting identifiers with regex...")
        identifiers = self.extractor.extract_first_page_identifiers(pdf_path, page_offset=page_offset)
        result['identifiers_found'] = identifiers
        # #region agent log
        import os
        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
        with open(log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"C","location":"paper_processor.py:467","message":"Identifiers extracted","data":{"jstor_ids":identifiers.get('jstor_ids',[]),"dois":identifiers.get('dois',[]),"years":identifiers.get('years',[]) if 'years' in identifiers else None},"timestamp":int(time.time()*1000)}) + '\n')
        # #endregion
        
        print(f"  DOIs: {identifiers['dois']}")
        print(f"  arXiv IDs: {identifiers['arxiv_ids']}")
        print(f"  JSTOR IDs: {identifiers['jstor_ids']}")
        print(f"  ISSNs: {identifiers['issns']}")
        print(f"  ISBNs: {identifiers['isbns']}")
        print(f"  URLs: {len(identifiers['urls'])} found")
        if identifiers.get('years'):
            print(f"  Years: {identifiers['years']} (best: {identifiers.get('best_year')})")
        elif identifiers.get('best_year'):
            print(f"  Year: {identifiers.get('best_year')}")
        
        # Step 1b: Fast author extraction with regex (runs early to catch "Author(s): Name" patterns)
        regex_authors = []
        try:
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > page_offset:
                    first_page_text = pdf.pages[page_offset].extract_text() or ""
                    if first_page_text:
                        regex_authors = AuthorExtractor.extract_authors_simple(first_page_text)
                        # #region agent log
                        log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                        with open(log_path, 'a', encoding='utf-8') as f:
                            f.write(json.dumps({
                                "sessionId": "debug-session",
                                "runId": "author-regex-step1",
                                "hypothesisId": "A1",
                                "location": "paper_processor.py:535",
                                "message": "Regex authors step1",
                                "data": {
                                    "text_length": len(first_page_text),
                                    "regex_authors": regex_authors[:10],
                                    "num_regex_authors": len(regex_authors)
                                },
                                "timestamp": int(time.time() * 1000)
                            }) + '\n')
                        # #endregion
                        if regex_authors:
                            # Filter against Zotero author/journal lists before presenting to user
                            filtered_authors = self._filter_regex_authors(regex_authors)
                            if filtered_authors:
                                print(f"  Authors (regex, after filtering): {filtered_authors}")
                                # Store filtered regex authors in identifiers for later use
                                identifiers['regex_authors'] = filtered_authors
                            else:
                                print(f"  ⚠️  All regex authors filtered out")
                                identifiers['regex_authors'] = []
        except Exception as e:
            # If extraction fails, continue without regex authors
            pass
        
        # Step 2: Validate identifiers
        print("\n🔍 Step 2: Validating identifiers...")
        valid_dois = []
        for doi in identifiers['dois']:
            is_valid, cleaned, reason = self.validator.validate_doi(doi)
            if is_valid and cleaned:
                print(f"  ✅ Valid DOI: {cleaned}")
                valid_dois.append(cleaned)
            else:
                print(f"  ❌ Invalid DOI: {doi} - {reason}")
        
        valid_issns = []
        for issn in identifiers['issns']:
            is_valid, cleaned, reason = self.validator.validate_issn(issn)
            if is_valid and cleaned:
                print(f"  ✅ Valid ISSN: {cleaned}")
                valid_issns.append(cleaned)
            else:
                print(f"  ❌ Invalid ISSN: {issn} - {reason}")
        
        valid_isbns = []
        for isbn in identifiers['isbns']:
            is_valid, cleaned, reason = self.validator.validate_isbn(isbn)
            if is_valid and cleaned:
                print(f"  ✅ Valid ISBN: {cleaned}")
                valid_isbns.append(cleaned)
            else:
                print(f"  ❌ Invalid ISBN: {isbn} - {reason}")
        
        valid_arxiv_ids = []
        for arxiv_id in identifiers['arxiv_ids']:
            is_valid, cleaned, reason = self.validator.validate_arxiv_id(arxiv_id)
            if is_valid and cleaned:
                print(f"  ✅ Valid arXiv ID: {cleaned}")
                valid_arxiv_ids.append(cleaned)
            else:
                print(f"  ❌ Invalid arXiv ID: {arxiv_id} - {reason}")
        
        valid_jstor_ids = []
        for jstor_id in identifiers['jstor_ids']:
            print(f"  ✅ Valid JSTOR ID: {jstor_id}")
            valid_jstor_ids.append(jstor_id)
        
        # Step 3: Try API lookup if we have valid identifiers
        if valid_dois:
            print(f"\n🌐 Step 3: Fetching metadata from APIs (priority order)...")
            doi = valid_dois[0]  # Use first valid DOI
            
            # Try APIs in priority order
            doi_apis = ['crossref', 'openalex', 'pubmed']
            metadata = self._try_apis_for_doi(doi, doi_apis)
            
            if metadata:
                # Validate DOI metadata against PDF text to avoid false positives
                # (e.g., DOI from a citation rather than the actual paper)
                is_valid = self._validate_doi_metadata_against_pdf(metadata, pdf_path, page_offset=page_offset)
                
                if is_valid:
                    source = metadata.get('source', 'unknown')
                    result['method'] = f'{source}_api'
                    result['metadata'] = metadata
                    result['success'] = True
                    result['processing_time_seconds'] = time.time() - start_time
                    print(f"  ✅ Got metadata from {source} in {result['processing_time_seconds']:.1f}s")
                    return result
                else:
                    print(f"  ⚠️  DOI metadata doesn't match PDF text (likely from a citation) - skipping")
                    print(f"  ℹ️  Falling back to GROBID/extraction methods...")
            else:
                print(f"  ❌ All APIs returned no data for DOI: {doi}")
        
        elif valid_arxiv_ids:
            print(f"\n📄 Step 3: Fetching metadata from arXiv API...")
            arxiv_id = valid_arxiv_ids[0]  # Use first valid arXiv ID
            metadata = self.arxiv.get_metadata(arxiv_id)
            if metadata:
                result['method'] = 'arxiv_api'
                result['metadata'] = metadata
                result['success'] = True
                result['processing_time_seconds'] = time.time() - start_time
                print(f"  ✅ Got metadata from arXiv in {result['processing_time_seconds']:.1f}s")
                # Note if it also has a DOI
                if metadata.get('doi'):
                    print(f"  ℹ️  Also has DOI (published version): {metadata['doi']}")
                return result
            else:
                print(f"  ❌ arXiv API returned no data for ID: {arxiv_id}")
        
        elif valid_jstor_ids:
            print(f"\n📚 Step 3: JSTOR ID found - treating as journal article")
            jstor_id = valid_jstor_ids[0]
            print(f"  JSTOR ID: {jstor_id}")
            print(f"  ℹ️  JSTOR ID confirms this is a journal article")
            print("  ℹ️  Skipping JSTOR page scraping; using PDF extraction + legal APIs (Crossref/OpenAlex/PubMed) instead.")
            # Store JSTOR ID for later use as a hint only (no web fetch).
            result['jstor_id'] = jstor_id
            result['document_type_hint'] = 'journal_article'
            # #region agent log
            try:
                import os as _os, json as _json, time as _time
                log_path = r"f:\prog\research-tools\.cursor\debug.log" if _os.name == "nt" else "/mnt/f/prog/research-tools/.cursor/debug.log"
                with open(log_path, "a", encoding="utf-8") as _f:
                    _f.write(_json.dumps({
                        "sessionId": "debug-session",
                        "runId": "run1",
                        "hypothesisId": "JST_SKIP",
                        "location": "paper_processor.py:jstor_branch",
                        "message": "JSTOR id present; skipping JSTOR page fetch",
                        "data": {"jstor_id": jstor_id},
                        "timestamp": int(_time.time() * 1000),
                    }) + "\n")
            except Exception:
                pass
            # #endregion
            # Continue processing - don't return yet
        
        elif valid_isbns:
            print(f"\n📚 Step 3: ISBN found - use existing book lookup workflow")
            # TODO: Integrate with existing book lookup system
            result['method'] = 'isbn_found'
            result['success'] = False
            result['metadata'] = {'note': 'Use existing book processing workflow'}
            result['processing_time_seconds'] = time.time() - start_time
            return result
        
        # Step 4: Check if we have URLs (news articles, blog posts, web content)
        has_urls = len(identifiers.get('urls', [])) > 0
        
        if has_urls and not valid_dois and not valid_isbns and not valid_jstor_ids:
            # Analyze URLs to determine likely document type
            urls = identifiers.get('urls', [])
            institutional_domains = ['.edu', '.ac.', 'university', 'college', 'institute', 'ssrn.com', 'arxiv.org', 'repec.org']
            is_institutional = any(any(domain in url.lower() for domain in institutional_domains) for url in urls)
            
            if is_institutional:
                print(f"\n🏛️ Step 4: Institutional URL found - likely working paper, preprint, or academic publication")
                print(f"  Found URLs: {len(urls)}")
                document_context = "working_paper"
                context_hint = "institutional/academic document"
            else:
                print(f"\n🌐 Step 4: URL found but no DOI/ISBN - could be working paper, preprint, or web content")
                print(f"  Found URLs: {len(urls)}")
                document_context = "academic_paper"
                context_hint = "general document"
            
            # Try regex extraction first
            print(f"  🔍 Trying regex author extraction...")
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                if len(pdf.pages) > page_offset:
                    text = pdf.pages[page_offset].extract_text()
                else:
                    text = ""
            
            regex_authors = AuthorExtractor.extract_authors_simple(text or "")
            if regex_authors:
                print(f"  ✅ Regex found {len(regex_authors)} author(s) (before filtering): {', '.join(regex_authors)}")
                # Filter against Zotero author/journal lists
                filtered_authors = self._filter_regex_authors(regex_authors)
                if filtered_authors:
                    print(f"  ✅ Regex found {len(filtered_authors)} author(s) (after filtering): {', '.join(filtered_authors)}")
                else:
                    print(f"  ⚠️  All regex authors filtered out")
                    filtered_authors = []
                
                # Create metadata with filtered regex authors
                metadata = {
                    'title': identifiers.get('title', ''),
                    'authors': filtered_authors,
                    'url': identifiers['urls'][0] if identifiers['urls'] else '',
                    'document_type': 'working_paper' if is_institutional else 'academic_paper',
                    'extraction_method': 'regex_fallback'
                }
                
                result['method'] = 'regex_web_article'
                result['metadata'] = metadata
                result['success'] = True
                result['processing_time_seconds'] = time.time() - start_time
                print(f"  ✅ Got metadata from regex in {result['processing_time_seconds']:.1f}s")
                return result
            else:
                print(f"  ❌ Regex found no authors, trying Ollama...")
                
            if use_ollama_fallback:
                print(f"  🤖 Using Ollama with {context_hint} prompt...")
                print(f"  ⚠️  This is slow (60-120 seconds)...")
                
                # Display found information before Ollama processing
                found_info = {
                    'title': identifiers.get('title'),
                    'authors': identifiers.get('authors'),
                    'institution': identifiers.get('institution'),
                    'urls': identifiers.get('urls', []),
                    'doi': identifiers.get('doi'),
                    'context_hint': context_hint
                }
                
                if progress_callback:
                    progress_callback(found_info, 0)
                
                # Detect language from filename if available
                language = self._detect_language_from_filename(pdf_path)
                
                # Start Ollama processing with progress indicator
                metadata = self.ollama.extract_paper_metadata(text, validate=True, 
                                                              document_context=document_context,
                                                              language=language,
                                                              progress_callback=progress_callback,
                                                              found_info=found_info)
                if metadata:
                    # Add URL to metadata
                    if not metadata.get('url') and identifiers['urls']:
                        metadata['url'] = identifiers['urls'][0]
                    
                    result['method'] = 'ollama_web_article'
                    result['metadata'] = metadata
                    result['success'] = True
                    result['processing_time_seconds'] = time.time() - start_time
                    print(f"  ✅ Got metadata from Ollama in {result['processing_time_seconds']:.1f}s")
                    
                    if metadata.get('has_hallucinations'):
                        print(f"  ⚠️  WARNING: Possible hallucinations detected:")
                        for flag in metadata.get('confidence_flags', []):
                            print(f"      - {flag}")
                    
                    return result
                else:
                    print(f"  ❌ Ollama extraction failed")
                    result['processing_time_seconds'] = time.time() - start_time
                    return result
            else:
                print(f"  ⚠️  Ollama fallback disabled - cannot extract web article metadata")
                result['processing_time_seconds'] = time.time() - start_time
                return result
        
        # Step 5: Ollama fallback if no identifiers found at all (book chapters, scanned papers)
        # Skip if we have a JSTOR ID - daemon will handle GROBID + metadata fetching
        if result.get('jstor_id'):
            # JSTOR ID found - return early so daemon can handle GROBID extraction
            # and subsequent CrossRef/OpenAlex metadata fetching
            result['processing_time_seconds'] = time.time() - start_time
            return result
        
        if use_ollama_fallback:
            print(f"\n🤖 Step 5: No identifiers found - trying regex first, then Ollama...")
            
            # Check text length before attempting Ollama
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                # Extract page at offset for regex
                if len(pdf.pages) > page_offset:
                    text_page1 = pdf.pages[page_offset].extract_text() or ""
                else:
                    text_page1 = ""
            
            # Check if text is too short (likely handwritten note)
            threshold = DocumentClassifier.get_handwritten_threshold()
            if len(text_page1.strip()) < threshold:
                print(f"  📝 Very little text extracted ({len(text_page1.strip())} chars) - likely handwritten note")
                print(f"  ⚠️  Skipping Ollama processing - no extractable text")
                result['method'] = 'handwritten_note_detected'
                result['metadata'] = {
                    'document_type': 'handwritten_note',
                    'title': '',
                    'authors': [],
                    'extraction_method': 'handwritten_note_detection'
                }
                result['success'] = False  # Mark as needing manual entry
                result['processing_time_seconds'] = time.time() - start_time
                return result
            
            # Try regex extraction first
            print(f"  🔍 Trying regex author extraction...")
            regex_authors = AuthorExtractor.extract_authors_simple(text_page1 or "")
            # #region agent log
            import os
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"E","location":"paper_processor.py:758","message":"Regex author extraction result","data":{"regex_authors":regex_authors,"text_length":len(text_page1) if text_page1 else 0,"text_preview":text_page1[:200] if text_page1 else None},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            if regex_authors:
                print(f"  ✅ Regex found {len(regex_authors)} author(s) (before filtering): {', '.join(regex_authors)}")
                # Filter against Zotero author/journal lists
                filtered_authors = self._filter_regex_authors(regex_authors)
                if filtered_authors:
                    print(f"  ✅ Regex found {len(filtered_authors)} author(s) (after filtering): {', '.join(filtered_authors)}")
                else:
                    print(f"  ⚠️  All regex authors filtered out")
                    filtered_authors = []
                
                # Create basic metadata with filtered regex authors
                metadata = {
                    'title': identifiers.get('title', ''),
                    'authors': filtered_authors,
                    'document_type': 'book_chapter',
                    'extraction_method': 'regex_fallback'
                }
                
                result['method'] = 'regex_fallback'
                result['metadata'] = metadata
                result['success'] = True
                result['processing_time_seconds'] = time.time() - start_time
                print(f"  ✅ Got metadata from regex in {result['processing_time_seconds']:.1f}s")
                return result
            else:
                print(f"  ❌ Regex found no authors, trying Ollama...")
                print(f"  ⚠️  This is slow (60-120 seconds)...")
                
                # For book chapters, extract strategically:
                # - Full first page (main content + author/title info)
                # - Next 3-4 pages: first 100 chars (header) + last 20 chars (footer/page numbers)
                with pdfplumber.open(pdf_path) as pdf:
                    pages_text = []
                    
                    # First page at offset: extract everything
                    if len(pdf.pages) > page_offset:
                        first_page_text = pdf.pages[page_offset].extract_text()
                        if first_page_text:
                            pages_text.append(f"=== PAGE {page_offset + 1} ===\n{first_page_text}\n")
                    
                    # Next 3-4 pages: header + footer only
                    for i in range(page_offset + 1, min(page_offset + 5, len(pdf.pages))):
                        page_text = pdf.pages[i].extract_text()
                        if page_text:
                            # Get first 100 chars (header) and last 20 chars (footer/page number)
                            header = page_text[:100].strip()
                            footer = page_text[-20:].strip()
                            pages_text.append(f"=== PAGE {i+1} HEADER: {header}\nPAGE {i+1} FOOTER: {footer} ===\n")
                    
                    text = '\n'.join(pages_text)
                
                # Detect language from filename if available
                language = self._detect_language_from_filename(pdf_path)
                
                metadata = self.ollama.extract_paper_metadata(text, validate=True,
                                                              document_context="book_chapter",
                                                              language=language)
                if metadata:
                    result['method'] = 'ollama_fallback'
                    result['metadata'] = metadata
                    result['success'] = True
                    result['processing_time_seconds'] = time.time() - start_time
                    print(f"  ✅ Got metadata from Ollama in {result['processing_time_seconds']:.1f}s")
                    
                    if metadata.get('has_hallucinations'):
                        print(f"  ⚠️  WARNING: Possible hallucinations detected:")
                        for flag in metadata.get('confidence_flags', []):
                            print(f"      - {flag}")
                    
                    return result
                else:
                    print(f"  ❌ Ollama extraction failed")
                    result['processing_time_seconds'] = time.time() - start_time
                    return result
        else:
            print(f"\n⚠️  No valid identifiers found and Ollama fallback disabled")
            result['processing_time_seconds'] = time.time() - start_time
            return result
    
    def _try_apis_for_doi(self, doi: str, api_list: List[str]) -> Optional[Dict]:
        """Try multiple APIs in priority order for a DOI.
        
        Args:
            doi: DOI to search for
            api_list: List of API names to try
            
        Returns:
            Metadata dict if found, None otherwise
        """
        ordered_apis = self.priority_manager.get_ordered_apis(api_list)
        
        for api_name in ordered_apis:
            if not self.priority_manager.is_api_enabled(api_name):
                continue
                
            client = self.api_clients.get(api_name)
            if not client:
                continue
            
            try:
                print(f"  🔄 Trying {api_name}...")
                metadata = client.get_metadata_by_doi(doi)
                if metadata:
                    print(f"  ✅ Found metadata in {api_name}")
                    return metadata
            except Exception as e:
                print(f"  ⚠️  {api_name} error: {e}")
                continue
        
        return None
    
    def search_by_doi(self, doi: str) -> Dict:
        """Search for metadata using a DOI.
        
        Uses priority-based API selection from config.
        
        Args:
            doi: DOI to search for
            
        Returns:
            Dictionary with success status and metadata
        """
        try:
            # APIs that support DOI lookup
            doi_apis = ['crossref', 'openalex', 'pubmed']
            metadata = self._try_apis_for_doi(doi, doi_apis)
            
            if metadata:
                return {
                    'success': True,
                    'metadata': metadata,
                    'method': metadata.get('source', 'unknown') + '_api'
                }
            
            return {
                'success': False,
                'error': f'No metadata found for DOI: {doi}'
            }
        except Exception as e:
            return {
                'success': False,
                'error': f'Error searching DOI {doi}: {e}'
            }
    
    def search_by_isbn(self, isbn: str) -> Dict:
        """Search for metadata using an ISBN.
        
        Args:
            isbn: ISBN to search for
            
        Returns:
            Dictionary with success status and metadata
        """
        # For now, return a placeholder since book processing uses a different workflow
        return {
            'success': False,
            'error': 'ISBN search not implemented - use existing book processing workflow',
            'metadata': {'note': 'Use existing book processing workflow for ISBNs'}
        }
    
    def display_result(self, result: Dict):
        """Display processing result in a nice format."""
        print(f"\n{'='*80}")
        print(f"RESULT")
        print(f"{'='*80}")
        print(f"File: {result['file']}")
        print(f"Method: {result['method']}")
        print(f"Time: {result['processing_time_seconds']:.1f} seconds")
        print(f"Success: {result['success']}")
        
        if result['metadata']:
            print(f"\nMetadata:")
            metadata = result['metadata']
            print(f"  Title: {metadata.get('title', 'N/A')[:80]}")
            print(f"  Authors: {', '.join(metadata.get('authors', [])[:3])}")
            print(f"  Journal: {metadata.get('journal', 'N/A')}")
            if metadata.get('volume'):
                print(f"  Volume: {metadata['volume']}")
            if metadata.get('issue'):
                print(f"  Issue: {metadata['issue']}")
            if metadata.get('pages'):
                print(f"  Pages: {metadata['pages']}")
            print(f"  Year: {metadata.get('year', 'N/A')}")
            print(f"  DOI: {metadata.get('doi', 'N/A')}")
            print(f"  Type: {metadata.get('document_type', 'N/A')}")
            if metadata.get('abstract'):
                print(f"  Abstract: {metadata['abstract'][:100]}...")


if __name__ == "__main__":
    # Test with the Nature paper
    processor = PaperMetadataProcessor()  # Reads email from config
    
    test_pdf = Path("/mnt/i/FraScanner/Doerig et al._2025_High-level visual representations in the human brain are aligned with large language models.pdf")
    
    if test_pdf.exists():
        result = processor.process_pdf(test_pdf, use_ollama_fallback=False)
        processor.display_result(result)
    else:
        print(f"Test PDF not found: {test_pdf}")
