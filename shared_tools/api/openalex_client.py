#!/usr/bin/env python3
"""
OpenAlex API client for scholarly paper metadata lookup.

OpenAlex is a free, open catalog of the global research system,
providing 200M+ scholarly works with comprehensive metadata.

API Documentation: https://docs.openalex.org/
No authentication required, but include email for polite pool.
"""

import requests
import time
from typing import Optional, Dict, List
from pathlib import Path


class OpenAlexClient:
    """Client for OpenAlex API."""
    
    BASE_URL = "https://api.openalex.org/works"
    
    def __init__(self, email: Optional[str] = None, timeout: int = 10):
        """Initialize OpenAlex client.
        
        Args:
            email: Your email for polite pool (gets better rate limits)
            timeout: Request timeout in seconds
        """
        self.email = email
        self.timeout = timeout
        self.session = requests.Session()
    
    def get_metadata_by_doi(self, doi: str) -> Optional[Dict]:
        """Get metadata for a DOI.
        
        Args:
            doi: DOI string (with or without https://doi.org/ prefix)
            
        Returns:
            Dictionary with metadata or None if not found
        """
        # Normalize DOI 
        from shared_tools.utils.identifier_validator import IdentifierValidator
        normalized_doi = IdentifierValidator.normalize_doi(doi)
        if not normalized_doi:
            return None
        doi = normalized_doi
        
        try:
            params = {
                'filter': f'doi:{doi}',
                'per_page': 1
            }
            
            if self.email:
                params['mailto'] = self.email
            
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                if data.get('results') and len(data['results']) > 0:
                    return self._parse_openalex_response(data['results'][0])
                else:
                    return None
            else:
                print(f"OpenAlex API error: {response.status_code}")
                return None
                
        except requests.RequestException as e:
            print(f"OpenAlex API request failed: {e}")
            return None
    
    def search_by_metadata(self, title: str = None, authors: List[str] = None,
                          year: str = None, journal: str = None,
                          max_results: int = 5) -> List[Dict]:
        """Search for works by metadata.
        
        Args:
            title: Title keywords (optional)
            authors: Author names (optional)
            year: Publication year (optional)
            journal: Journal name (optional)
            max_results: Maximum number of results to return
            
        Returns:
            List of dictionaries with metadata
        """
        try:
            # Build filters
            filters = []
            
            if title:
                # Use title search
                filters.append(f'display_name.search:"{title}"')
            
            if year:
                filters.append(f'publication_year:{year}')
            
            if journal:
                # Search in venue/source
                filters.append(f'primary_location.source.display_name.search:"{journal}"')
            
            if authors and len(authors) > 0:
                # Use first author for filtering
                author_name = authors[0]
                # Remove suffixes like "Jr." and split
                author_name = author_name.replace(', Jr.', '').replace(' Jr.', '')
                if ',' in author_name:
                    parts = author_name.split(',')
                    if len(parts) >= 2:
                        lastname = parts[0].strip()
                        firstname = parts[1].strip().split()[0] if parts[1].strip() else ''
                        author_filter = f'author.display_name.search:"{lastname}, {firstname}"'
                    else:
                        author_filter = f'author.display_name.search:"{author_name}"'
                else:
                    # Try to extract last name
                    parts = author_name.split()
                    if len(parts) > 0:
                        author_filter = f'author.display_name.search:"{parts[-1]}"'
                    else:
                        author_filter = f'author.display_name.search:"{author_name}"'
                filters.append(author_filter)
            
            params = {
                'filter': ','.join(filters) if filters else None,
                'per_page': min(max_results, 10),  # API limits per_page to 200
                'sort': 'relevance_score:desc'
            }
            
            if self.email:
                params['mailto'] = self.email
            
            # Remove None values
            params = {k: v for k, v in params.items() if v is not None}
            
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                data = response.json()
                results = []
                for item in data.get('results', [])[:max_results]:
                    parsed = self._parse_openalex_response(item)
                    if parsed:
                        results.append(parsed)
                return results
            else:
                print(f"OpenAlex API error: {response.status_code}")
                return []
                
        except requests.RequestException as e:
            print(f"OpenAlex search request failed: {e}")
            return []
    
    def _parse_openalex_response(self, data: Dict) -> Optional[Dict]:
        """Parse OpenAlex API response into our standard format.
        
        Args:
            data: JSON response from OpenAlex API
            
        Returns:
            Dictionary with normalized metadata
        """
        try:
            # Extract title
            title = data.get('title', '').strip()
            
            # Extract authors
            authors = []
            for author_data in data.get('authorships', []):
                author = author_data.get('author', {})
                display_name = author.get('display_name', '')
                if display_name:
                    authors.append(display_name)
            
            # Extract year
            year = None
            pub_date = data.get('publication_date', '')
            if pub_date:
                year = pub_date.split('-')[0]
            
            # Extract abstract
            abstract = data.get('abstract', '')
            if abstract and abstract.startswith('Abstract'):
                # Remove "Abstract" prefix
                abstract = abstract[8:].strip()
            
            # Extract journal/source
            journal = None
            source = data.get('primary_location', {}).get('source', {})
            if source:
                journal = source.get('display_name', '')
            
            # Extract publisher
            publisher = None
            if source:
                publisher = source.get('host_organization', '')
            
            # Extract DOI
            doi = None
            for doi_data in data.get('ids', {}):
                if 'doi' in doi_data.lower() and doi_data != 'doi':
                    doi = data['ids'][doi_data]
            
            # Extract volume, issue, pages
            volume = None
            issue = None
            pages = None
            
            # OpenAlex doesn't always provide these in the main work object
            # They might be in the primary location
            primary_loc = data.get('primary_location', {})
            if primary_loc:
                volume = primary_loc.get('source', {}).get('volume', primary_loc.get('volume'))
                issue = primary_loc.get('issue')
                pages = primary_loc.get('pages')
            
            # Extract document type
            document_type = 'journal_article'  # default
            openalex_type = data.get('type', '')
            if 'book' in openalex_type.lower():
                document_type = 'book'
            elif 'chapter' in openalex_type.lower():
                document_type = 'book_chapter'
            elif 'preprint' in openalex_type.lower():
                document_type = 'preprint'
            elif 'dissertation' in openalex_type.lower() or 'thesis' in openalex_type.lower():
                document_type = 'thesis'
            elif 'report' in openalex_type.lower():
                document_type = 'report'
            
            # Extract URL
            url = None
            for url_type in ['pdf_url', 'landing_page_url', 's2_url']:
                if url_type in data:
                    url = data[url_type]
                    break
            
            # If no URL in main object, check primary location
            if not url:
                primary_loc = data.get('primary_location', {})
                if primary_loc:
                    url = primary_loc.get('landing_page_url') or primary_loc.get('pdf_url')
            
            # Extract concepts as tags
            tags = []
            for concept in data.get('concepts', [])[:10]:  # Top 10 concepts
                display_name = concept.get('display_name', '')
                if display_name:
                    tags.append(display_name)
            
            return {
                'title': title,
                'authors': authors,
                'year': year,
                'abstract': abstract,
                'journal': journal or 'Unknown',
                'publisher': publisher or 'Unknown',
                'doi': doi,
                'volume': volume,
                'issue': issue,
                'pages': pages,
                'url': url,
                'document_type': document_type,
                'tags': tags,
                'source': 'openalex',
                'date_published': pub_date
            }
            
        except Exception as e:
            print(f"Error parsing OpenAlex response: {e}")
            return None


if __name__ == "__main__":
    # Test with a known paper
    client = OpenAlexClient(email="test@example.com")
    
    print("Testing OpenAlex API")
    print("=" * 60)
    
    # Test DOI lookup
    doi = "10.1038/s41586-020-2649-2"  # Example Nature paper
    print(f"\n1. Testing DOI lookup: {doi}")
    metadata = client.get_metadata_by_doi(doi)
    
    if metadata:
        print(f"✅ Found metadata:")
        print(f"  Title: {metadata['title'][:80]}...")
        print(f"  Authors: {', '.join(metadata['authors'][:3])}...")
        print(f"  Journal: {metadata['journal']}")
        print(f"  Year: {metadata['year']}")
        print(f"  DOI: {metadata['doi']}")
        print(f"  Type: {metadata['document_type']}")
        print(f"  Tags: {', '.join(metadata.get('tags', [])[:5]) if metadata.get('tags') else 'N/A'}")
    else:
        print("❌ DOI not found")
    
    # Test search
    print(f"\n2. Testing search by title and year")
    results = client.search_by_metadata(
        title="COVID-19",
        year="2020",
        max_results=3
    )
    
    if results:
        print(f"✅ Found {len(results)} results:")
        for i, result in enumerate(results[:3], 1):
            print(f"\n  Result {i}:")
            print(f"    Title: {result['title'][:60]}...")
            print(f"    Journal: {result['journal']}")
            print(f"    Year: {result['year']}")
    else:
        print("❌ No search results found")

