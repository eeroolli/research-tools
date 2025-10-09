#!/usr/bin/env python3
"""
arXiv API client for preprint metadata lookup.

arXiv is a free distribution service for scholarly articles,
primarily in physics, mathematics, computer science, and related fields.

API Documentation: https://info.arxiv.org/help/api/index.html
No authentication required, free to use.
"""

import requests
import xml.etree.ElementTree as ET
from typing import Optional, Dict
from pathlib import Path


class ArxivClient:
    """Client for arXiv API."""
    
    BASE_URL = "http://export.arxiv.org/api/query"
    
    # XML namespaces
    NAMESPACES = {
        'atom': 'http://www.w3.org/2005/Atom',
        'arxiv': 'http://arxiv.org/schemas/atom'
    }
    
    def __init__(self, timeout: int = 10):
        """Initialize arXiv client.
        
        Args:
            timeout: Request timeout in seconds
        """
        self.timeout = timeout
        self.session = requests.Session()
    
    def get_metadata(self, arxiv_id: str) -> Optional[Dict]:
        """Get metadata for an arXiv ID.
        
        Args:
            arxiv_id: arXiv ID (e.g., '2301.12345' or 'cs.AI/0001001')
            
        Returns:
            Dictionary with metadata or None if not found
        """
        # Clean arXiv ID
        arxiv_id = arxiv_id.replace('arXiv:', '').replace('arxiv:', '').strip()
        
        try:
            # Query arXiv API
            params = {
                'id_list': arxiv_id,
                'max_results': 1
            }
            
            response = self.session.get(self.BASE_URL, params=params, timeout=self.timeout)
            
            if response.status_code == 200:
                return self._parse_arxiv_response(response.text, arxiv_id)
            else:
                print(f"arXiv API error: {response.status_code}")
                return None
                
        except requests.RequestException as e:
            print(f"arXiv API request failed: {e}")
            return None
    
    def _parse_arxiv_response(self, xml_text: str, arxiv_id: str) -> Optional[Dict]:
        """Parse arXiv API XML response into standardized format.
        
        Args:
            xml_text: Raw XML response from arXiv
            arxiv_id: The requested arXiv ID
            
        Returns:
            Standardized metadata dictionary or None if not found
        """
        try:
            root = ET.fromstring(xml_text)
            
            # Find the entry
            entries = root.findall('atom:entry', self.NAMESPACES)
            
            if not entries:
                return None
            
            entry = entries[0]
            
            # Extract title
            title_elem = entry.find('atom:title', self.NAMESPACES)
            title = title_elem.text.strip().replace('\n', ' ') if title_elem is not None else None
            
            # Extract authors
            authors = []
            for author in entry.findall('atom:author', self.NAMESPACES):
                name_elem = author.find('atom:name', self.NAMESPACES)
                if name_elem is not None:
                    authors.append(name_elem.text.strip())
            
            # Extract abstract
            summary_elem = entry.find('atom:summary', self.NAMESPACES)
            abstract = summary_elem.text.strip().replace('\n', ' ') if summary_elem is not None else None
            
            # Extract published date
            published_elem = entry.find('atom:published', self.NAMESPACES)
            year = None
            date_published = None
            if published_elem is not None:
                date_published = published_elem.text.strip()[:10]  # YYYY-MM-DD
                year = date_published[:4]
            
            # Extract categories (subjects)
            categories = []
            for category in entry.findall('atom:category', self.NAMESPACES):
                term = category.get('term')
                if term:
                    categories.append(term)
            
            # Extract DOI if it has one (some arXiv papers get DOIs when published)
            doi = None
            doi_elem = entry.find('arxiv:doi', self.NAMESPACES)
            if doi_elem is not None:
                doi = doi_elem.text.strip()
            
            # Build arXiv URL
            arxiv_url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
            
            return {
                'arxiv_id': arxiv_id,
                'doi': doi,
                'title': title,
                'authors': authors,
                'abstract': abstract,
                'year': year,
                'date_published': date_published,
                'categories': categories,
                'tags': categories,  # Use categories as tags
                'url': arxiv_url,
                'pdf_url': pdf_url,
                'publisher': 'arXiv',
                'journal': 'arXiv',
                'document_type': 'preprint',
                'source': 'arxiv',
            }
            
        except ET.ParseError as e:
            print(f"Error parsing arXiv XML: {e}")
            return None
        except Exception as e:
            print(f"Error processing arXiv response: {e}")
            return None


if __name__ == "__main__":
    # Test with a known arXiv paper
    client = ArxivClient()
    
    print("Testing arXiv API")
    print("=" * 60)
    
    # Test with GPT4All paper (from your samples)
    arxiv_id = "2304.05490"  # GPT4All paper
    metadata = client.get_metadata(arxiv_id)
    
    if metadata:
        print(f"\n✅ Found metadata:")
        print(f"  arXiv ID: {metadata['arxiv_id']}")
        print(f"  Title: {metadata['title'][:80]}...")
        print(f"  Authors: {', '.join(metadata['authors'][:3])}...")
        print(f"  Year: {metadata['year']}")
        print(f"  Categories: {', '.join(metadata['categories'][:5])}")
        print(f"  DOI: {metadata.get('doi', 'None')}")
        print(f"  URL: {metadata['url']}")
        print(f"  Abstract: {metadata['abstract'][:100]}...")
    else:
        print("\n❌ Failed to retrieve metadata")
