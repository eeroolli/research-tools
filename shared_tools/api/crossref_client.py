#!/usr/bin/env python3
"""
CrossRef API client for DOI metadata lookup.

CrossRef is the official DOI registration agency and provides
authoritative metadata for scholarly works.

API Documentation: https://github.com/CrossRef/rest-api-doc
No authentication required, but please add email for "polite" pool.
"""

import requests
import time
from typing import Optional, Dict
from pathlib import Path


class CrossRefClient:
    """Client for CrossRef API."""
    
    BASE_URL = "https://api.crossref.org/works/"
    
    def __init__(self, email: Optional[str] = None, timeout: int = 10):
        """Initialize CrossRef client.
        
        Args:
            email: Your email for polite pool (gets better rate limits)
            timeout: Request timeout in seconds
        """
        self.email = email
        self.timeout = timeout
        self.session = requests.Session()
        
        # Set user agent for polite pool
        if email:
            self.session.headers.update({
                'User-Agent': f'research-tools/1.0 (mailto:{email})'
            })
    
    def get_metadata(self, doi: str) -> Optional[Dict]:
        """Get metadata for a DOI from CrossRef.
        
        Args:
            doi: DOI string (with or without https://doi.org/ prefix)
            
        Returns:
            Dictionary with metadata or None if not found
        """
        # Normalize DOI using centralized function
        from shared_tools.utils.identifier_validator import IdentifierValidator
        normalized_doi = IdentifierValidator.normalize_doi(doi)
        if not normalized_doi:
            return None
        doi = normalized_doi
        
        try:
            url = f"{self.BASE_URL}{doi}"
            response = self.session.get(url, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_crossref_response(data)
            elif response.status_code == 404:
                return None
            else:
                print(f"CrossRef API error: {response.status_code}")
                return None
                
        except requests.RequestException as e:
            print(f"CrossRef API request failed: {e}")
            return None
    
    def _parse_crossref_response(self, data: Dict) -> Dict:
        """Parse CrossRef API response into standardized format.
        
        Args:
            data: Raw CrossRef API response
            
        Returns:
            Standardized metadata dictionary
        """
        message = data.get('message', {})
        
        # Extract authors
        authors = []
        for author in message.get('author', []):
            given = author.get('given', '')
            family = author.get('family', '')
            if given and family:
                authors.append(f"{given} {family}")
            elif family:
                authors.append(family)
        
        # Extract title (usually an array with one element)
        titles = message.get('title', [])
        title = titles[0] if titles else None
        
        # Extract publication info
        journal = message.get('container-title', [])
        journal = journal[0] if journal else None
        
        publisher = message.get('publisher')
        
        # Extract year from published date
        year = None
        published = message.get('published-print') or message.get('published-online')
        if published and 'date-parts' in published:
            date_parts = published['date-parts'][0]
            if date_parts:
                year = str(date_parts[0])
        
        # Extract ISSN
        issns = message.get('ISSN', [])
        issn = issns[0] if issns else None
        
        # Extract ISBN (for books/chapters)
        isbns = message.get('ISBN', [])
        isbn = isbns[0] if isbns else None
        
        # Extract document type
        doc_type = message.get('type', 'unknown')
        document_type = self._map_crossref_type(doc_type)
        
        # Extract URL
        url = message.get('URL')
        
        # Extract abstract (if available)
        abstract = message.get('abstract')
        if abstract:
            # Clean JATS XML markup from abstract
            import re
            abstract = re.sub(r'<[^>]+>', '', abstract)  # Remove XML tags
            abstract = abstract.strip()
        
        # Extract volume, issue, pages (for journal articles)
        volume = message.get('volume')
        issue = message.get('issue')
        
        # Pages - can be in different formats
        page = message.get('page')  # e.g., "1220-1234"
        if not page:
            # Try page-first and page-last
            page_first = message.get('page-first')
            page_last = message.get('page-last')
            if page_first and page_last:
                page = f"{page_first}-{page_last}"
            elif page_first:
                page = page_first
        
        # Extract subjects/keywords as tags (if available)
        tags = message.get('subject', [])  # CrossRef subject classifications
        
        # Extract publication date info more completely
        date_published = None
        if published and 'date-parts' in published:
            date_parts = published['date-parts'][0]
            if len(date_parts) >= 3:
                date_published = f"{date_parts[0]}-{date_parts[1]:02d}-{date_parts[2]:02d}"
            elif len(date_parts) >= 2:
                date_published = f"{date_parts[0]}-{date_parts[1]:02d}"
        
        return {
            'doi': message.get('DOI'),
            'title': title,
            'authors': authors,
            'journal': journal,
            'publisher': publisher,
            'year': year,
            'date_published': date_published,
            'volume': volume,
            'issue': issue,
            'pages': page,
            'issn': issn,
            'isbn': isbn,
            'url': url,
            'document_type': document_type,
            'abstract': abstract,
            'tags': tags,
            'source': 'crossref',
            'raw_type': doc_type,
        }
    
    def _map_crossref_type(self, crossref_type: str) -> str:
        """Map CrossRef document type to our standard types.
        
        Args:
            crossref_type: CrossRef type string
            
        Returns:
            Standardized document type
        """
        type_mapping = {
            'journal-article': 'journal_article',
            'book-chapter': 'book_chapter',
            'book': 'book',
            'proceedings-article': 'conference_paper',
            'report': 'report',
            'dataset': 'dataset',
            'posted-content': 'preprint',
        }
        
        return type_mapping.get(crossref_type, 'unknown')
    
    def search_by_metadata(self, title: str = None, authors: list = None, 
                          year: str = None, journal: str = None, 
                          max_results: int = 5) -> list:
        """Search CrossRef by metadata (title, authors, year, journal).
        
        Args:
            title: Paper title (or keywords)
            authors: List of author names
            year: Publication year
            journal: Journal name
            max_results: Maximum number of results to return
            
        Returns:
            List of metadata dictionaries (empty if no matches)
        """
        # Build query parameters
        query_parts = []
        
        if title:
            # Remove common words and use as phrase search
            query_parts.append(f'title:{title}')
        elif authors and len(authors) > 0:
            # Use first author's last name if no title
            first_author = authors[0]
            if ' ' in first_author:
                last_name = first_author.split()[-1]
            else:
                last_name = first_author
            query_parts.append(f'author:{last_name}')
        
        if journal:
            query_parts.append(f'container-title:{journal}')
        
        if year:
            # CrossRef can filter by year using filter parameter
            pass  # Will use filter below
        
        if not query_parts:
            return []
        
        # Build query string
        query = '+'.join(query_parts)
        
        # Build request parameters
        params = {
            'query': query,
            'rows': max_results,
            'sort': 'relevance'
        }
        
        if year:
            # Filter by publication year
            params['filter'] = f'from-pub-date:{year},to-pub-date:{year}'
        
        try:
            # CrossRef search endpoint
            url = "https://api.crossref.org/works"
            response = self.session.get(url, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                items = data.get('message', {}).get('items', [])
                
                results = []
                for item in items:
                    # Parse each item
                    # Wrap in 'message' format for _parse_crossref_response
                    parsed = self._parse_crossref_response({'message': item})
                    if parsed:
                        results.append(parsed)
                
                return results
            else:
                print(f"CrossRef search error: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            print(f"CrossRef search request failed: {e}")
            return []


if __name__ == "__main__":
    # Test with the Nature paper
    client = CrossRefClient(email="test@example.com")
    
    print("Testing CrossRef API with Nature paper DOI")
    print("=" * 60)
    
    doi = "10.1038/s42256-025-01072-0"
    metadata = client.get_metadata(doi)
    
    if metadata:
        print(f"\n✅ Found metadata:")
        print(f"  Title: {metadata['title'][:80]}...")
        print(f"  Authors: {', '.join(metadata['authors'][:3])}...")
        print(f"  Journal: {metadata['journal']}")
        print(f"  Volume: {metadata.get('volume', 'N/A')}")
        print(f"  Issue: {metadata.get('issue', 'N/A')}")
        print(f"  Pages: {metadata.get('pages', 'N/A')}")
        print(f"  Publisher: {metadata['publisher']}")
        print(f"  Year: {metadata['year']}")
        print(f"  Date: {metadata.get('date_published', 'N/A')}")
        print(f"  ISSN: {metadata['issn']}")
        print(f"  Type: {metadata['document_type']}")
        print(f"  DOI: {metadata['doi']}")
        print(f"  Tags: {', '.join(metadata.get('tags', [])[:5]) if metadata.get('tags') else 'N/A'}")
        print(f"  Abstract: {metadata.get('abstract', 'N/A')[:100]}...")
    else:
        print("\n❌ Failed to retrieve metadata")
