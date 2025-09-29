"""
National library API clients for academic papers and books.
"""
import requests
import logging
from typing import Optional, Dict, Any, List
from .base_client import BaseAPIClient


class NationalLibraryClient(BaseAPIClient):
    """Base client for national library APIs."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None, 
                 rate_limit_delay: float = 1.0, country_code: str = ""):
        super().__init__(base_url, api_key, rate_limit_delay)
        self.country_code = country_code
        self.logger = logging.getLogger(f"{__name__}.{country_code}")
    
    def search_papers(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for academic papers."""
        # Override in subclasses
        raise NotImplementedError
    
    def search_books(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for books."""
        # Override in subclasses
        raise NotImplementedError


class NorwegianLibraryClient(NationalLibraryClient):
    """Norwegian National Library API client."""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            base_url="https://api.nb.no/catalog/v1",
            api_key=api_key,
            rate_limit_delay=1.0,
            country_code="NO"
        )
    
    def search_papers(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for academic papers in Norwegian National Library."""
        try:
            params = {
                'q': query,
                'size': kwargs.get('size', 10),
                'contentClasses': 'article,journal'
            }
            
            response = self._make_request('items', params)
            return self._parse_paper_results(response)
            
        except Exception as e:
            self.logger.error(f"Norwegian library paper search failed: {e}")
            return {}
    
    def search_books(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for books in Norwegian National Library."""
        try:
            params = {
                'q': query,
                'size': kwargs.get('size', 10),
                'contentClasses': 'book'
            }
            
            response = self._make_request('items', params)
            return self._parse_book_results(response)
            
        except Exception as e:
            self.logger.error(f"Norwegian library book search failed: {e}")
            return {}
    
    def _parse_paper_results(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse paper search results."""
        papers = []
        
        items = response.get('_embedded', {}).get('items', [])
        for item in items:
            metadata = item.get('metadata', {})
            
            paper = {
                'title': metadata.get('title', ''),
                'authors': self._extract_authors(metadata),
                'journal': metadata.get('originInfo', {}).get('publisher', ''),
                'year': self._extract_year(metadata),
                'doi': self._extract_doi(metadata),
                'issn': self._extract_issn(metadata),
                'abstract': metadata.get('abstract', ''),
                'language': 'no',  # Norwegian
                'source': 'Norwegian National Library',
                'url': item.get('_links', {}).get('self', {}).get('href', '')
            }
            papers.append(paper)
        
        return {
            'papers': papers,
            'total': response.get('page', {}).get('totalElements', 0),
            'source': 'Norwegian National Library'
        }
    
    def _parse_book_results(self, response: Dict[str, Any]) -> Dict[str, Any]:
        """Parse book search results."""
        books = []
        
        items = response.get('_embedded', {}).get('items', [])
        for item in items:
            metadata = item.get('metadata', {})
            
            book = {
                'title': metadata.get('title', ''),
                'authors': self._extract_authors(metadata),
                'publisher': metadata.get('originInfo', {}).get('publisher', ''),
                'year': self._extract_year(metadata),
                'isbn': self._extract_isbn(metadata),
                'language': 'no',  # Norwegian
                'source': 'Norwegian National Library',
                'url': item.get('_links', {}).get('self', {}).get('href', '')
            }
            books.append(book)
        
        return {
            'books': books,
            'total': response.get('page', {}).get('totalElements', 0),
            'source': 'Norwegian National Library'
        }
    
    def _extract_authors(self, metadata: Dict[str, Any]) -> List[str]:
        """Extract authors from metadata."""
        authors = []
        creators = metadata.get('creators', [])
        
        for creator in creators:
            if creator and creator != "Likhetens paradokser":
                name_parts = creator.split(', ')
                if len(name_parts) >= 2:
                    authors.append(f"{name_parts[1]} {name_parts[0]}")
                else:
                    authors.append(creator)
        
        return authors
    
    def _extract_year(self, metadata: Dict[str, Any]) -> Optional[int]:
        """Extract publication year."""
        issued = metadata.get('originInfo', {}).get('issued', '')
        if issued:
            try:
                return int(issued[:4])
            except:
                pass
        return None
    
    def _extract_doi(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract DOI from metadata."""
        identifiers = metadata.get('identifiers', [])
        for identifier in identifiers:
            if identifier.get('type') == 'DOI':
                return identifier.get('value')
        return None
    
    def _extract_issn(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract ISSN from metadata."""
        identifiers = metadata.get('identifiers', [])
        for identifier in identifiers:
            if identifier.get('type') == 'ISSN':
                return identifier.get('value')
        return None
    
    def _extract_isbn(self, metadata: Dict[str, Any]) -> Optional[str]:
        """Extract ISBN from metadata."""
        identifiers = metadata.get('identifiers', [])
        for identifier in identifiers:
            if identifier.get('type') == 'ISBN':
                return identifier.get('value')
        return None
    
    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for items using the API."""
        # Default to searching both papers and books
        item_type = kwargs.get('item_type', 'both')
        
        if item_type == 'papers':
            return self.search_papers(query, **kwargs)
        elif item_type == 'books':
            return self.search_books(query, **kwargs)
        else:
            # Return both
            papers_result = self.search_papers(query, **kwargs)
            books_result = self.search_books(query, **kwargs)
            return {
                'papers': papers_result.get('papers', []),
                'books': books_result.get('books', []),
                'total': papers_result.get('total', 0) + books_result.get('total', 0),
                'source': 'Norwegian National Library'
            }
    
    def get_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item by ID."""
        try:
            response = self._make_request(f'items/{item_id}')
            return response
        except Exception as e:
            self.logger.error(f"Failed to get item {item_id}: {e}")
            return {}


class FinnishLibraryClient(NationalLibraryClient):
    """Finnish National Library API client."""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            base_url="https://api.kirjastot.fi",
            api_key=api_key,
            rate_limit_delay=1.0,
            country_code="FI"
        )
    
    def search_papers(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for academic papers in Finnish National Library."""
        # TODO: Implement Finnish library paper search
        # This would require understanding the Finnish API structure
        return {'papers': [], 'total': 0, 'source': 'Finnish National Library'}
    
    def search_books(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for books in Finnish National Library."""
        # TODO: Implement Finnish library book search
        return {'books': [], 'total': 0, 'source': 'Finnish National Library'}
    
    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for items using the API."""
        # Default to searching both papers and books
        item_type = kwargs.get('item_type', 'both')
        
        if item_type == 'papers':
            return self.search_papers(query, **kwargs)
        elif item_type == 'books':
            return self.search_books(query, **kwargs)
        else:
            # Return both
            papers_result = self.search_papers(query, **kwargs)
            books_result = self.search_books(query, **kwargs)
            return {
                'papers': papers_result.get('papers', []),
                'books': books_result.get('books', []),
                'total': papers_result.get('total', 0) + books_result.get('total', 0),
                'source': 'Finnish National Library'
            }
    
    def get_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item by ID."""
        try:
            response = self._make_request(f'items/{item_id}')
            return response
        except Exception as e:
            self.logger.error(f"Failed to get item {item_id}: {e}")
            return {}


class SwedishLibraryClient(NationalLibraryClient):
    """Swedish National Library API client."""
    
    def __init__(self, api_key: Optional[str] = None):
        super().__init__(
            base_url="https://libris.kb.se/api",
            api_key=api_key,
            rate_limit_delay=1.0,
            country_code="SE"
        )
    
    def search_papers(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for academic papers in Swedish National Library."""
        try:
            params = {
                'q': query,
                'format': 'json',
                'type': 'article'
            }
            
            response = self._make_request('search', params)
            return self._parse_libris_results(response, 'papers')
            
        except Exception as e:
            self.logger.error(f"Swedish library paper search failed: {e}")
            return {'papers': [], 'total': 0, 'source': 'Swedish National Library'}
    
    def search_books(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for books in Swedish National Library."""
        try:
            params = {
                'q': query,
                'format': 'json',
                'type': 'book'
            }
            
            response = self._make_request('search', params)
            return self._parse_libris_results(response, 'books')
            
        except Exception as e:
            self.logger.error(f"Swedish library book search failed: {e}")
            return {'books': [], 'total': 0, 'source': 'Swedish National Library'}
    
    def _parse_libris_results(self, response: Dict[str, Any], item_type: str) -> Dict[str, Any]:
        """Parse Libris API results."""
        items = []
        
        # Libris API structure varies, this is a simplified parser
        search_results = response.get('items', [])
        
        for item in search_results:
            parsed_item = {
                'title': item.get('title', ''),
                'authors': self._extract_libris_authors(item),
                'language': 'sv',  # Swedish
                'source': 'Swedish National Library',
                'url': item.get('uri', '')
            }
            
            if item_type == 'papers':
                parsed_item.update({
                    'journal': item.get('publication', {}).get('title', ''),
                    'year': self._extract_libris_year(item),
                    'doi': item.get('doi', ''),
                    'issn': item.get('issn', '')
                })
            else:  # books
                parsed_item.update({
                    'publisher': item.get('publication', {}).get('publisher', ''),
                    'year': self._extract_libris_year(item),
                    'isbn': item.get('isbn', '')
                })
            
            items.append(parsed_item)
        
        return {
            item_type: items,
            'total': len(items),
            'source': 'Swedish National Library'
        }
    
    def _extract_libris_authors(self, item: Dict[str, Any]) -> List[str]:
        """Extract authors from Libris item."""
        authors = []
        creators = item.get('creator', [])
        
        for creator in creators:
            if isinstance(creator, dict):
                name = creator.get('name', '')
                if name:
                    authors.append(name)
            elif isinstance(creator, str):
                authors.append(creator)
        
        return authors
    
    def _extract_libris_year(self, item: Dict[str, Any]) -> Optional[int]:
        """Extract year from Libris item."""
        publication = item.get('publication', {})
        year = publication.get('year')
        if year:
            try:
                return int(year)
            except:
                pass
        return None
    
    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """Search for items using the API."""
        # Default to searching both papers and books
        item_type = kwargs.get('item_type', 'both')
        
        if item_type == 'papers':
            return self.search_papers(query, **kwargs)
        elif item_type == 'books':
            return self.search_books(query, **kwargs)
        else:
            # Return both
            papers_result = self.search_papers(query, **kwargs)
            books_result = self.search_books(query, **kwargs)
            return {
                'papers': papers_result.get('papers', []),
                'books': books_result.get('books', []),
                'total': papers_result.get('total', 0) + books_result.get('total', 0),
                'source': 'Swedish National Library'
            }
    
    def get_by_id(self, item_id: str) -> Dict[str, Any]:
        """Get item by ID."""
        try:
            response = self._make_request(f'search/{item_id}')
            return response
        except Exception as e:
            self.logger.error(f"Failed to get item {item_id}: {e}")
            return {}


class NationalLibraryManager:
    """Manager for national library clients based on language/country."""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.clients = {}
        self._initialize_clients()
    
    def _initialize_clients(self):
        """Initialize national library clients."""
        self.clients = {
            'NO': NorwegianLibraryClient(self.config.get('norwegian_library_api_key')),
            'FI': FinnishLibraryClient(self.config.get('finnish_library_api_key')),
            'SE': SwedishLibraryClient(self.config.get('swedish_library_api_key')),
            # Add more clients as needed
        }
    
    def get_client(self, country_code: str) -> Optional[NationalLibraryClient]:
        """Get national library client for country."""
        return self.clients.get(country_code.upper())
    
    def search_by_language(self, query: str, language: str, item_type: str = 'both') -> Dict[str, Any]:
        """Search national libraries based on language."""
        results = {}
        
        # Map language to country codes
        language_to_country = {
            'NO': 'NO', 'norwegian': 'NO',
            'FI': 'FI', 'finnish': 'FI', 
            'SE': 'SE', 'swedish': 'SE',
            'SV': 'SE',  # Alternative Swedish code
        }
        
        country_code = language_to_country.get(language.upper())
        if not country_code:
            return results
        
        client = self.get_client(country_code)
        if not client:
            return results
        
        try:
            if item_type in ['papers', 'both']:
                results['papers'] = client.search_papers(query)
            
            if item_type in ['books', 'both']:
                results['books'] = client.search_books(query)
                
        except Exception as e:
            logging.error(f"National library search failed for {country_code}: {e}")
        
        return results
    
    def search_by_country(self, query: str, country_code: str, item_type: str = 'both') -> Dict[str, Any]:
        """Search national library for specific country."""
        results = {}
        client = self.get_client(country_code)
        
        if not client:
            return results
        
        try:
            if item_type in ['papers', 'both']:
                results['papers'] = client.search_papers(query)
            
            if item_type in ['books', 'both']:
                results['books'] = client.search_books(query)
                
        except Exception as e:
            logging.error(f"National library search failed for {country_code}: {e}")
        
        return results
