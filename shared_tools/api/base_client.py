"""
Base API client with common functionality.
"""
import requests
import time
from typing import Dict, Any, Optional
from abc import ABC, abstractmethod


class BaseAPIClient(ABC):
    """Base class for API clients with rate limiting and error handling."""
    
    def __init__(self, base_url: str, api_key: Optional[str] = None, 
                 rate_limit_delay: float = 1.0):
        """
        Initialize API client.
        
        Args:
            base_url: Base URL for the API
            api_key: API key if required
            rate_limit_delay: Delay between requests in seconds
        """
        self.base_url = base_url.rstrip('/')
        self.api_key = api_key
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0
        self.session = requests.Session()
        
        # Set up session headers
        if self.api_key:
            self.session.headers.update({'Authorization': f'Bearer {self.api_key}'})
    
    def _rate_limit(self):
        """Implement rate limiting."""
        current_time = time.time()
        time_since_last = current_time - self.last_request_time
        
        if time_since_last < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - time_since_last)
        
        self.last_request_time = time.time()
    
    def _make_request(self, endpoint: str, params: Optional[Dict[str, Any]] = None, headers: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        """
        Make a rate-limited request to the API.
        
        Args:
            endpoint: API endpoint
            params: Query parameters
            headers: Custom headers
            
        Returns:
            JSON response data
            
        Raises:
            requests.RequestException: If request fails
        """
        self._rate_limit()
        
        if endpoint and endpoint.strip():
            url = f"{self.base_url}/{endpoint.lstrip('/')}"
        else:
            url = self.base_url
        
        # Merge custom headers with session headers
        request_headers = {}
        if hasattr(self.session, 'headers'):
            request_headers.update(self.session.headers)
        if headers:
            request_headers.update(headers)
        
        try:
            response = self.session.get(url, params=params, headers=request_headers, timeout=30)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as e:
            print(f"API request failed: {e}")
            raise
    
    @abstractmethod
    def search(self, query: str, **kwargs) -> Dict[str, Any]:
        """
        Search for items using the API.
        
        Args:
            query: Search query
            **kwargs: Additional search parameters
            
        Returns:
            Search results
        """
        pass
    
    @abstractmethod
    def get_by_id(self, item_id: str) -> Dict[str, Any]:
        """
        Get item by ID.
        
        Args:
            item_id: Item identifier
            
        Returns:
            Item data
        """
        pass
