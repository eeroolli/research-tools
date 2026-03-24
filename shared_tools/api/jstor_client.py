#!/usr/bin/env python3
"""
JSTOR client for fetching metadata from JSTOR URLs.

JSTOR pages contain structured metadata in the gaData.content object,
meta tags, and other elements that can be extracted and used directly
or to resolve DOIs for downstream API lookups.

No authentication required, but please respect rate limits.
"""

import ast
import html
import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests
from bs4 import BeautifulSoup

from ..utils.identifier_validator import IdentifierValidator


class JSTORClient:
    """Client for fetching DOIs and metadata from JSTOR URLs."""
    
    def __init__(
        self,
        timeout: int = 10,
        referer: Optional[str] = None,
        cookies: Optional[Dict[str, str]] = None,
        cookie_header: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        """Initialize JSTOR client.
        
        Args:
            timeout: Request timeout in seconds
            referer: Optional Referer header to send with requests
            cookies: Optional dictionary of cookies to attach
            cookie_header: Optional raw Cookie header string ("k1=v1; k2=v2")
            extra_headers: Optional additional headers to merge into the session
        """
        self.timeout = timeout
        self.session = requests.Session()
        # Set a user agent to be respectful
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
        if referer:
            self.session.headers['Referer'] = referer
        if extra_headers:
            self.session.headers.update(extra_headers)
        if cookies:
            self.session.cookies.update(cookies)
        elif cookie_header:
            parsed = self._parse_cookie_header(cookie_header)
            if parsed:
                self.session.cookies.update(parsed)
        self.logger = logging.getLogger(__name__)
    
    def fetch_metadata_from_url(self, jstor_url: str) -> Optional[Dict[str, Any]]:
        """Fetch structured metadata (including DOI) from a JSTOR page.

        Attempts gaData.content extraction first, supplements with meta tags,
        and returns standardized metadata plus raw sources.

        Args:
            jstor_url: Full JSTOR URL (e.g., https://www.jstor.org/stable/2348496)

        Returns:
            Metadata dictionary if found, None otherwise.
        """
        if not jstor_url or not jstor_url.strip():
            return None

        # Normalize URL - ensure it's a full URL
        url = jstor_url.strip()
        if not url.startswith('http://') and not url.startswith('https://'):
            # Assume https if no protocol
            url = 'https://' + url

        try:
            # #region agent log
            import os, time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"jstor_client.py:90","message":"JSTOR fetch attempt","data":{"url":url},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            response = self.session.get(url, timeout=self.timeout)
            # #region agent log
            import os, time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"jstor_client.py:93","message":"JSTOR response status","data":{"status_code":response.status_code,"url":url},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion
            if response.status_code != 200:
                self.logger.debug(f"JSTOR URL returned status {response.status_code}: {url}")
                # #region agent log
                import os, time
                log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
                with open(log_path, 'a', encoding='utf-8') as f:
                    f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"jstor_client.py:96","message":"JSTOR fetch failed","data":{"status_code":response.status_code,"url":url,"response_text_preview":response.text[:200] if hasattr(response,'text') else None},"timestamp":int(time.time()*1000)}) + '\n')
                # #endregion
                return None

            html_text = response.text
            soup = BeautifulSoup(response.content, 'html.parser')

            gadata_raw = self._extract_gadata_content(html_text)
            meta_tags = self._extract_meta_tags(soup)

            gadata_mapped = self._map_gadata_to_standard_format(gadata_raw) if gadata_raw else None
            merged = self._merge_metadata_sources(gadata_mapped, meta_tags)
            # #region agent log
            import os, time
            log_path = r'f:\prog\research-tools\.cursor\debug.log' if os.name == 'nt' else '/mnt/f/prog/research-tools/.cursor/debug.log'
            with open(log_path, 'a', encoding='utf-8') as f:
                f.write(json.dumps({"sessionId":"debug-session","runId":"run1","hypothesisId":"A","location":"jstor_client.py:103","message":"JSTOR metadata merge result","data":{"has_gadata":bool(gadata_raw),"has_meta_tags":bool(meta_tags),"merged_success":bool(merged),"merged_keys":list(merged.keys()) if merged else []},"timestamp":int(time.time()*1000)}) + '\n')
            # #endregion

            if merged:
                # Attach raw sources for debugging/audit
                if gadata_raw:
                    merged['raw_gadata'] = gadata_raw
                if meta_tags and meta_tags.get('raw_meta_description'):
                    merged['raw_meta_description'] = meta_tags['raw_meta_description']
                merged.setdefault('source', 'jstor')
                return merged

            return None

        except requests.Timeout:
            self.logger.warning(f"Timeout fetching JSTOR URL: {url}")
            return None
        except requests.RequestException as e:
            self.logger.warning(f"Error fetching JSTOR URL {url}: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"Error parsing JSTOR page {url}: {e}")
            return None

    def fetch_doi_from_url(self, jstor_url: str) -> Optional[str]:
        """Fetch DOI from JSTOR URL page.

        Tries rich metadata extraction first, then falls back to legacy
        scraping strategies.

        Args:
            jstor_url: Full JSTOR URL (e.g., https://www.jstor.org/stable/2348496)

        Returns:
            DOI string (normalized) if found, None otherwise
        """
        # Try metadata-driven extraction first
        metadata = self.fetch_metadata_from_url(jstor_url)
        if metadata and metadata.get('doi'):
            return metadata['doi']

        try:
            # Fetch page with timeout
            url = jstor_url.strip()
            if not url.startswith('http://') and not url.startswith('https://'):
                url = 'https://' + url

            response = self.session.get(url, timeout=self.timeout)
            if response.status_code != 200:
                self.logger.debug(f"JSTOR URL returned status {response.status_code}: {url}")
                return None
            
            # Parse HTML
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Strategy 1: Try href attributes containing doi.org (handles web components)
            # JSTOR uses web components with href attributes like: href="https://doi.org/10.2307/2348496"
            import re
            doi_pattern = r'10\.\d{4,}/[^\s"\'<>\)]+'
            
            # Search all elements with href attributes containing doi.org
            for element in soup.find_all(href=re.compile(r'doi\.org', re.I)):
                href = element.get('href', '')
                match = re.search(doi_pattern, href)
                if match:
                    potential_doi = match.group(0)
                    doi = IdentifierValidator.normalize_doi(potential_doi)
                    if doi:
                        is_valid, _, _ = IdentifierValidator.validate_doi(doi)
                        if is_valid:
                            self.logger.debug(f"Found DOI via href attribute: {doi}")
                            return doi
            
            # Strategy 2: Try meta tag citation_doi (some pages may have this)
            meta_doi = soup.find('meta', {'name': 'citation_doi'})
            if meta_doi and meta_doi.get('content'):
                doi = IdentifierValidator.normalize_doi(meta_doi['content'])
                if doi:
                    self.logger.debug(f"Found DOI via citation_doi meta tag: {doi}")
                    return doi
            
            # Strategy 3: Try meta property dc.identifier
            meta_dc = soup.find('meta', {'property': 'dc.identifier'})
            if meta_dc and meta_dc.get('content'):
                content = meta_dc.get('content', '').strip()
                # Check if it looks like a DOI
                if content.startswith('10.'):
                    doi = IdentifierValidator.normalize_doi(content)
                    if doi:
                        self.logger.debug(f"Found DOI via dc.identifier meta tag: {doi}")
                        return doi
            
            # Strategy 4: Try schema.org structured data
            # Look for application/ld+json scripts
            script_tags = soup.find_all('script', {'type': 'application/ld+json'})
            for script in script_tags:
                try:
                    import json
                    data = json.loads(script.string)
                    # Handle both single objects and arrays
                    items = data if isinstance(data, list) else [data]
                    for item in items:
                        # Check for DOI in identifier field
                        if 'identifier' in item:
                            identifier = item['identifier']
                            if isinstance(identifier, str) and identifier.startswith('10.'):
                                doi = IdentifierValidator.normalize_doi(identifier)
                                if doi:
                                    self.logger.debug(f"Found DOI via schema.org: {doi}")
                                    return doi
                            elif isinstance(identifier, dict) and identifier.get('value', '').startswith('10.'):
                                doi = IdentifierValidator.normalize_doi(identifier['value'])
                                if doi:
                                    self.logger.debug(f"Found DOI via schema.org (dict): {doi}")
                                    return doi
                except (json.JSONDecodeError, KeyError, AttributeError):
                    continue
            
            # Strategy 5: Try visible text patterns (https://doi.org/10.xxxx/xxxx or just 10.xxxx/xxxx)
            # This handles cases where DOI appears in text content
            text = soup.get_text()
            # Look for full doi.org URLs first
            doi_url_pattern = r'https?://(?:dx\.)?doi\.org/(10\.\d{4,}/[^\s\)]+)'
            matches = re.finditer(doi_url_pattern, text, re.IGNORECASE)
            for match in matches:
                potential_doi = match.group(1)
                doi = IdentifierValidator.normalize_doi(potential_doi)
                if doi:
                    is_valid, _, _ = IdentifierValidator.validate_doi(doi)
                    if is_valid:
                        self.logger.debug(f"Found DOI via doi.org URL in text: {doi}")
                        return doi
            
            # Try standalone DOI patterns
            standalone_doi_pattern = r'\b(10\.\d{4,}/[^\s\)]+)\b'
            matches = re.finditer(standalone_doi_pattern, text)
            for match in matches:
                potential_doi = match.group(1)
                doi = IdentifierValidator.normalize_doi(potential_doi)
                if doi:
                    is_valid, _, _ = IdentifierValidator.validate_doi(doi)
                    if is_valid:
                        self.logger.debug(f"Found DOI via standalone pattern in text: {doi}")
                        return doi
            
            # No DOI found
            self.logger.debug(f"No DOI found in JSTOR URL: {url}")
            return None
            
        except requests.Timeout:
            self.logger.warning(f"Timeout fetching JSTOR URL: {url}")
            return None
        except requests.RequestException as e:
            self.logger.warning(f"Error fetching JSTOR URL {url}: {e}")
            return None
        except Exception as e:
            self.logger.warning(f"Error parsing JSTOR page {url}: {e}")
            return None

    # --- Internal helpers -------------------------------------------------

    def _parse_cookie_header(self, cookie_header: str) -> Dict[str, str]:
        """Parse a Cookie header string into a dict."""
        result: Dict[str, str] = {}
        if not cookie_header:
            return result
        parts = cookie_header.split(';')
        for part in parts:
            if '=' not in part:
                continue
            name, value = part.split('=', 1)
            name = name.strip()
            value = value.strip()
            if name:
                result[name] = value
        return result

    def _extract_gadata_content(self, html_text: str) -> Optional[Dict[str, Any]]:
        """Extract gaData.content object from page HTML."""
        if not html_text:
            return None

        match = re.search(r'gaData\.content\s*=\s*\{', html_text)
        if not match:
            return None

        start_idx = html_text.find('{', match.start())
        if start_idx == -1:
            return None

        # Find matching closing brace using a simple stack-aware scan
        brace_count = 0
        in_string: Optional[str] = None
        escape = False
        end_idx = None

        for idx in range(start_idx, len(html_text)):
            ch = html_text[idx]
            if escape:
                escape = False
                continue
            if ch == '\\\\':
                escape = True
                continue
            if in_string:
                if ch == in_string:
                    in_string = None
                continue
            if ch in ('"', "'"):
                in_string = ch
                continue
            if ch == '{':
                brace_count += 1
            elif ch == '}':
                brace_count -= 1
                if brace_count == 0:
                    end_idx = idx
                    break

        if end_idx is None:
            return None

        js_obj_text = html_text[start_idx:end_idx + 1]
        return self._parse_js_object(js_obj_text)

    def _parse_js_object(self, js_text: str) -> Optional[Dict[str, Any]]:
        """Parse a JavaScript object literal into a Python dictionary."""
        if not js_text:
            return None

        cleaned = html.unescape(js_text.strip())
        if cleaned.endswith(';'):
            cleaned = cleaned[:-1].strip()

        # First attempt: try JSON directly (gaData typically uses double quotes)
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            pass

        # Fallback: convert JS literals to Python and use literal_eval
        fallback = cleaned
        fallback = re.sub(r'\\btrue\\b', 'True', fallback, flags=re.IGNORECASE)
        fallback = re.sub(r'\\bfalse\\b', 'False', fallback, flags=re.IGNORECASE)
        fallback = re.sub(r'\\bnull\\b', 'None', fallback, flags=re.IGNORECASE)

        # Ensure keys wrapped in quotes if missing (basic heuristic)
        try:
            return ast.literal_eval(fallback)
        except Exception:
            self.logger.debug("Failed to parse gaData.content object")
            return None

    def _extract_meta_tags(self, soup: BeautifulSoup) -> Optional[Dict[str, Any]]:
        """Extract metadata from description/og:description meta tags."""
        if soup is None:
            return None

        meta_tag = soup.find('meta', {'name': 'description'}) or soup.find(
            'meta', {'property': 'og:description'}
        )
        if not meta_tag or not meta_tag.get('content'):
            return None

        desc = meta_tag.get('content', '').strip()
        if not desc:
            return None

        parsed = self._parse_meta_description(desc)
        if not parsed:
            return None

        parsed['raw_meta_description'] = desc
        return parsed

    def _parse_meta_description(self, desc: str) -> Optional[Dict[str, Any]]:
        """Parse meta description string into structured fields."""
        pattern = (
            r'^([^,]+),\s*'              # author
            r'([^,]+),\s*'               # title
            r'([^,]+),\s*'               # journal
            r'Vol\.\s*(\d+),\s*'         # volume
            r'No\.\s*(\d+)\s*'           # issue
            r'\([^)]*(\d{4})[^)]*\),\s*' # year in parentheses
            r'pp\.\s*([\d-]+)$'          # pages
        )

        match = re.match(pattern, desc)
        if not match:
            return None

        author, title, journal, volume, issue, year, pages = match.groups()
        return {
            'authors': [author.strip()] if author.strip() else [],
            'title': title.strip() or None,
            'journal': journal.strip() or None,
            'volume': volume.strip() or None,
            'issue': issue.strip() or None,
            'year': year.strip() or None,
            'pages': pages.strip() or None,
        }

    def _parse_content_issue(self, content_issue: str) -> Dict[str, Optional[str]]:
        """Parse gaData contentIssue string into volume/issue/year/pages."""
        if not content_issue:
            return {'volume': None, 'issue': None, 'year': None, 'pages': None}

        pattern = r'Vol\.\s*(\d+).*?No\.\s*(\d+).*?\([^)]*(\d{4})[^)]*\).*?pp\.\s*([\d-]+)'
        match = re.search(pattern, content_issue)
        if not match:
            return {'volume': None, 'issue': None, 'year': None, 'pages': None}

        volume, issue, year, pages = match.groups()
        return {
            'volume': volume,
            'issue': issue,
            'year': year,
            'pages': pages,
        }

    def _parse_content_discipline(self, discipline_value: str) -> Optional[List[str]]:
        """Parse gaData contentDiscipline string into a list of tags."""
        if not discipline_value:
            return None

        decoded = html.unescape(discipline_value)
        try:
            parsed = ast.literal_eval(decoded)
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        except Exception:
            pass

        return None

    def _map_gadata_to_standard_format(self, gadata: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """Map raw gaData content into standardized metadata fields."""
        if not gadata:
            return None

        mapped: Dict[str, Any] = {}

        doi_raw = gadata.get('objectDOI')
        if doi_raw:
            doi = IdentifierValidator.normalize_doi(doi_raw)
            if doi:
                is_valid, _, _ = IdentifierValidator.validate_doi(doi)
                if is_valid:
                    mapped['doi'] = doi

        mapped['title'] = gadata.get('itemTitle')
        mapped['journal'] = gadata.get('contentName')
        mapped['publisher'] = gadata.get('contentPublisher')

        issue_info = self._parse_content_issue(gadata.get('contentIssue', ''))
        mapped.update(issue_info)

        tags = self._parse_content_discipline(gadata.get('contentDiscipline', ''))
        if tags:
            mapped['tags'] = tags

        doc_type = gadata.get('itemType') or gadata.get('contentType')
        if doc_type:
            mapped['document_type'] = 'journal_article' if doc_type.lower() == 'article' else doc_type.lower()

        open_access = gadata.get('openAccess')
        if isinstance(open_access, str):
            mapped['open_access'] = open_access.strip().lower() == 'true'
        elif isinstance(open_access, bool):
            mapped['open_access'] = open_access

        page_count = gadata.get('pageCount')
        try:
            if page_count is not None:
                mapped['page_count'] = int(page_count)
        except (TypeError, ValueError):
            pass

        return mapped

    def _merge_metadata_sources(
        self,
        gadata_meta: Optional[Dict[str, Any]],
        meta_tags: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Merge gaData-derived metadata with meta-tag-derived metadata."""
        if not gadata_meta and not meta_tags:
            return None

        merged: Dict[str, Any] = {}

        if gadata_meta:
            merged.update(gadata_meta)

        if meta_tags:
            # Prefer gaData fields, supplement missing ones
            for key, value in meta_tags.items():
                if value is None or key == 'raw_meta_description':
                    continue
                if key not in merged or merged.get(key) in (None, [], ''):
                    merged[key] = value

            # Authors are only available from meta tags currently
            if meta_tags.get('authors'):
                merged['authors'] = meta_tags['authors']

        merged['source'] = 'jstor'
        return merged


if __name__ == "__main__":
    # Test with a known JSTOR URL
    client = JSTORClient()
    test_url = "https://www.jstor.org/stable/2348496"
    doi = client.fetch_doi_from_url(test_url)
    if doi:
        print(f"✅ Found DOI: {doi}")
    else:
        print("❌ No DOI found")
