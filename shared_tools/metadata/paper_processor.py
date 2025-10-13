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
import configparser
from pathlib import Path
from typing import Optional, Dict

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from shared_tools.utils.identifier_extractor import IdentifierExtractor
from shared_tools.utils.identifier_validator import IdentifierValidator
from shared_tools.api.crossref_client import CrossRefClient
from shared_tools.api.arxiv_client import ArxivClient
from shared_tools.ai.ollama_client import OllamaClient


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
        self.crossref = CrossRefClient(email=email)
        self.arxiv = ArxivClient()
        self.ollama = OllamaClient()
    
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
    
    def process_pdf(self, pdf_path: Path, use_ollama_fallback: bool = True) -> Dict:
        """Process a PDF to extract metadata using smart workflow.
        
        Args:
            pdf_path: Path to PDF file
            use_ollama_fallback: Whether to use Ollama if no identifiers found
            
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
        
        # Step 1: Fast identifier extraction with regex
        print("\n📋 Step 1: Extracting identifiers with regex...")
        identifiers = self.extractor.extract_first_page_identifiers(pdf_path)
        result['identifiers_found'] = identifiers
        
        print(f"  DOIs: {identifiers['dois']}")
        print(f"  arXiv IDs: {identifiers['arxiv_ids']}")
        print(f"  ISSNs: {identifiers['issns']}")
        print(f"  ISBNs: {identifiers['isbns']}")
        print(f"  URLs: {len(identifiers['urls'])} found")
        
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
        
        # Step 3: Try API lookup if we have valid identifiers
        if valid_dois:
            print(f"\n🌐 Step 3: Fetching metadata from CrossRef API...")
            doi = valid_dois[0]  # Use first valid DOI
            metadata = self.crossref.get_metadata(doi)
            if metadata:
                result['method'] = 'crossref_api'
                result['metadata'] = metadata
                result['success'] = True
                result['processing_time_seconds'] = time.time() - start_time
                print(f"  ✅ Got metadata from CrossRef in {result['processing_time_seconds']:.1f}s")
                return result
            else:
                print(f"  ❌ CrossRef API returned no data for DOI: {doi}")
        
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
        
        if has_urls and not valid_dois and not valid_isbns:
            print(f"\n🌐 Step 4: URL found but no DOI/ISBN - likely news/web article")
            print(f"  Found URLs: {len(identifiers['urls'])}")
            if use_ollama_fallback:
                print(f"  🤖 Using Ollama with NEWS ARTICLE prompt...")
                print(f"  ⚠️  This is slow (60-120 seconds)...")
                # Pass context hint for better extraction
                import pdfplumber
                with pdfplumber.open(pdf_path) as pdf:
                    text = pdf.pages[0].extract_text()
                metadata = self.ollama.extract_paper_metadata(text, validate=True, 
                                                              document_context="news_article")
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
        if use_ollama_fallback:
            print(f"\n🤖 Step 5: No identifiers found - using Ollama with BOOK CHAPTER prompt...")
            print(f"  ⚠️  This is slow (60-120 seconds)...")
            # Pass context hint for better extraction of chapters
            import pdfplumber
            with pdfplumber.open(pdf_path) as pdf:
                text = pdf.pages[0].extract_text()
            metadata = self.ollama.extract_paper_metadata(text, validate=True,
                                                          document_context="book_chapter")
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
    
    def search_by_doi(self, doi: str) -> Dict:
        """Search for metadata using a DOI.
        
        Args:
            doi: DOI to search for
            
        Returns:
            Dictionary with success status and metadata
        """
        try:
            metadata = self.crossref.get_metadata(doi)
            if metadata:
                return {
                    'success': True,
                    'metadata': metadata,
                    'method': 'crossref_api'
                }
            else:
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
