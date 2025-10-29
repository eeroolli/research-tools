#!/usr/bin/env python3
"""
PubMed API client for biomedical paper metadata lookup.

PubMed is a free database of biomedical literature with 35M+ citations.

API Documentation: https://www.ncbi.nlm.nih.gov/books/NBK25497/
Uses eutils API: https://eutils.ncbi.nlm.nih.gov/entrez/eutils/
No authentication required.
"""

import requests
import xml.etree.ElementTree as ET
import time
from typing import Optional, Dict, List
from pathlib import Path


class PubMedClient:
    """Client for PubMed API."""
    
    BASE_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
    
    def __init__(self, timeout: int = 10, email: Optional[str] = None, tool_name: str = "research-tools"):
        """Initialize PubMed client.
        
        Args:
            timeout: Request timeout in seconds
            email: Your email for polite usage (recommended by NCBI)
            tool_name: Tool name for API calls (required by NCBI best practices)
        """
        self.timeout = timeout
        self.email = email
        self.tool_name = tool_name
        self.session = requests.Session()
    
    def get_metadata_by_doi(self, doi: str) -> Optional[Dict]:
        """Get metadata for a DOI.
        
        Args:
            doi: DOI string (with or without https://doi.org/ prefix)
            
        Returns:
            Dictionary with metadata or None if not found
        """
        # Clean DOI
        doi = doi.replace('https://doi.org/', '').replace('http://dx.doi.org/', '')
        doi = doi.replace('doi:', '').strip()
        
        try:
            # Step 1: Search for DOI
            search_params = {
                'db': 'pubmed',
                'term': f'{doi}[DOI]',
                'retmode': 'xml',
                'retmax': 1
            }
            
            if self.email:
                search_params['email'] = self.email
            if self.tool_name:
                search_params['tool'] = self.tool_name
            
            search_url = f"{self.BASE_URL}/esearch.fcgi"
            search_response = self.session.get(search_url, params=search_params, timeout=self.timeout)
            
            if search_response.status_code != 200:
                return None
            
            # Parse search results
            search_tree = ET.fromstring(search_response.content)
            pmids = [id_elem.text for id_elem in search_tree.findall('.//Id')]
            
            if not pmids:
                return None
            
            # Step 2: Fetch metadata using PMID
            return self.get_metadata_by_pmid(pmids[0])
                
        except Exception as e:
            print(f"PubMed DOI lookup failed: {e}")
            return None
    
    def get_metadata_by_pmid(self, pmid: str) -> Optional[Dict]:
        """Get metadata for a PubMed ID.
        
        Args:
            pmid: PubMed ID
            
        Returns:
            Dictionary with metadata or None if not found
        """
        try:
            # Fetch metadata
            fetch_params = {
                'db': 'pubmed',
                'id': pmid,
                'retmode': 'xml',
                'rettype': 'abstract'
            }
            
            if self.email:
                fetch_params['email'] = self.email
            if self.tool_name:
                fetch_params['tool'] = self.tool_name
            
            fetch_url = f"{self.BASE_URL}/efetch.fcgi"
            fetch_response = self.session.get(fetch_url, params=fetch_params, timeout=self.timeout)
            
            if fetch_response.status_code != 200:
                return None
            
            # Parse XML response
            return self._parse_pubmed_xml(fetch_response.content)
                
        except Exception as e:
            print(f"PubMed metadata fetch failed: {e}")
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
            # Build search query
            terms = []
            
            if title:
                terms.append(f'"{title}"[Title]')
            
            if authors and len(authors) > 0:
                # Use last name of first author
                author_name = authors[0]
                if ',' in author_name:
                    lastname = author_name.split(',')[0].strip()
                else:
                    parts = author_name.split()
                    lastname = parts[-1] if len(parts) > 0 else author_name
                terms.append(f'{lastname}[Author]')
            
            if year:
                terms.append(f'{year}[PDAT]')
            
            if journal:
                terms.append(f'"{journal}"[Journal]')
            
            if not terms:
                return []
            
            search_query = ' AND '.join(terms)
            
            # Search for PMIDs
            search_params = {
                'db': 'pubmed',
                'term': search_query,
                'retmode': 'xml',
                'retmax': min(max_results, 20)  # PubMed limits
            }
            
            if self.email:
                search_params['email'] = self.email
            if self.tool_name:
                search_params['tool'] = self.tool_name
            
            search_url = f"{self.BASE_URL}/esearch.fcgi"
            search_response = self.session.get(search_url, params=search_params, timeout=self.timeout)
            
            if search_response.status_code != 200:
                return []
            
            # Parse search results
            search_tree = ET.fromstring(search_response.content)
            pmids = [id_elem.text for id_elem in search_tree.findall('.//Id')][:max_results]
            
            if not pmids:
                return []
            
            # Fetch metadata for each PMID
            results = []
            for pmid in pmids:
                metadata = self.get_metadata_by_pmid(pmid)
                if metadata:
                    results.append(metadata)
                    # Be polite - avoid rate limiting
                    time.sleep(0.34)  # NCBI recommends 3 requests/second
            
            return results
                
        except Exception as e:
            print(f"PubMed search failed: {e}")
            return []
    
    def _parse_pubmed_xml(self, xml_content: bytes) -> Optional[Dict]:
        """Parse PubMed XML response into our standard format.
        
        Args:
            xml_content: XML response from PubMed API
            
        Returns:
            Dictionary with normalized metadata
        """
        try:
            tree = ET.fromstring(xml_content)
            
            # Find PubmedArticle
            article = tree.find('.//PubmedArticle')
            if article is None:
                return None
            
            # Extract basic info
            medline = article.find('.//MedlineCitation')
            if medline is None:
                return None
            
            # Title
            title_elem = medline.find('.//ArticleTitle')
            title = title_elem.text if title_elem is not None else ''
            
            # Authors
            authors = []
            for author in medline.findall('.//Author'):
                lastname = author.find('LastName')
                firstname = author.find('ForeName')
                if lastname is not None:
                    if firstname is not None:
                        authors.append(f"{lastname.text}, {firstname.text}")
                    else:
                        authors.append(lastname.text)
            
            # Journal
            journal_elem = medline.find('.//Journal/Title')
            journal = journal_elem.text if journal_elem is not None else ''
            
            # Publication date
            pub_date = medline.find('.//PubDate')
            year = None
            if pub_date is not None:
                year_elem = pub_date.find('Year')
                if year_elem is not None:
                    year = year_elem.text
            
            # Abstract
            abstract_parts = []
            for abstract_text in medline.findall('.//AbstractText'):
                if abstract_text.text:
                    abstract_parts.append(abstract_text.text)
            abstract = ' '.join(abstract_parts) if abstract_parts else ''
            
            # Volume and Issue
            volume_elem = medline.find('.//Volume')
            volume = volume_elem.text if volume_elem is not None else None
            
            issue_elem = medline.find('.//Issue')
            issue = issue_elem.text if issue_elem is not None else None
            
            # Pages
            pages_elem = medline.find('.//Pagination/MedlinePgn')
            pages = pages_elem.text if pages_elem is not None else None
            
            # DOI
            doi = None
            for article_id in medline.findall('.//ArticleId'):
                if article_id.get('IdType') == 'doi':
                    doi = article_id.text
                    break
            
            # PMID
            pmid = medline.find('.//PMID')
            pmid_value = pmid.text if pmid is not None else None
            
            # Mesh terms as tags
            tags = []
            for mesh_term in medline.findall('.//MeshHeading/DescriptorName'):
                if mesh_term.text:
                    tags.append(mesh_term.text)
            
            # Document type
            pub_types = []
            for pub_type in medline.findall('.//PublicationType'):
                if pub_type.text:
                    pub_types.append(pub_type.text)
            
            document_type = 'journal_article'
            if any('review' in pt.lower() for pt in pub_types):
                document_type = 'review'
            elif any('case report' in pt.lower() for pt in pub_types):
                document_type = 'case_study'
            elif any('meta-analysis' in pt.lower() for pt in pub_types):
                document_type = 'meta_analysis'
            
            return {
                'title': title,
                'authors': authors,
                'year': year,
                'abstract': abstract,
                'journal': journal,
                'publisher': journal,  # PubMed doesn't have separate publisher
                'doi': doi,
                'volume': volume,
                'issue': issue,
                'pages': pages,
                'url': f"https://pubmed.ncbi.nlm.nih.gov/{pmid_value}" if pmid_value else None,
                'document_type': document_type,
                'tags': tags[:10],  # Top 10 MeSH terms
                'source': 'pubmed',
                'date_published': year
            }
            
        except Exception as e:
            print(f"Error parsing PubMed XML: {e}")
            return None


if __name__ == "__main__":
    # Test with a known paper
    client = PubMedClient(email="test@example.com")
    
    print("Testing PubMed API")
    print("=" * 60)
    
    # Test DOI lookup
    doi = "10.1056/NEJMoa2002032"  # Example medical paper
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
    
    print("\n2. Testing search functionality...")
    print("Searching for COVID-19 papers from 2020...")
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

