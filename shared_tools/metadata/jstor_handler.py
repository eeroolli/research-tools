#!/usr/bin/env python3
"""
JSTOR metadata workflow orchestration.
"""

from typing import Dict, Optional

from shared_tools.api.jstor_client import JSTORClient
from shared_tools.utils.api_priority_manager import APIPriorityManager


class JSTORHandler:
    """Handle JSTOR metadata fetching and enrichment."""

    def __init__(self, api_clients: Dict[str, object], priority_manager: APIPriorityManager, jstor_client: Optional[JSTORClient] = None):
        self.api_clients = api_clients
        self.priority_manager = priority_manager
        self.jstor_client = jstor_client or JSTORClient()

    def _try_apis_for_doi(self, doi: str, api_list):
        ordered_apis = self.priority_manager.get_ordered_apis(api_list)

        for api_name in ordered_apis:
            if not self.priority_manager.is_api_enabled(api_name):
                continue

            client = self.api_clients.get(api_name)
            if not client:
                continue

            try:
                metadata = client.get_metadata_by_doi(doi)
                if metadata:
                    return metadata
            except Exception:
                continue

        return None

    def process_jstor_id(self, jstor_id: str) -> Optional[Dict]:
        """Fetch JSTOR metadata and optionally enrich via DOI APIs."""
        if not jstor_id:
            return None

        jstor_url = f"https://www.jstor.org/stable/{jstor_id}"
        jstor_metadata = self.jstor_client.fetch_metadata_from_url(jstor_url)

        if not jstor_metadata:
            return None

        jstor_metadata['jstor_id'] = jstor_id
        jstor_metadata['document_type'] = 'journal_article'

        method = 'jstor'

        if jstor_metadata.get('doi'):
            api_metadata = self._try_apis_for_doi(jstor_metadata['doi'], ['crossref', 'openalex', 'pubmed'])
            if api_metadata:
                jstor_metadata.update(api_metadata)
                method = f'jstor+{api_metadata.get("source", "api")}'

        return {
            'metadata': jstor_metadata,
            'method': method
        }
