#!/usr/bin/env python3
"""Test JSTOR metadata and DOI extraction with optional cookies/headers."""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.api.jstor_client import JSTORClient
import logging


def parse_cookie_header(header: str):
    cookies = {}
    for part in header.split(';'):
        if '=' not in part:
            continue
        name, value = part.split('=', 1)
        name = name.strip()
        value = value.strip()
        if name:
            cookies[name] = value
    return cookies


def build_browser_headers():
    # Defaults mirrored from captured cURL
    base_headers = {
        "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
        "accept-language": "en-US,en;q=0.9,sv;q=0.8,no;q=0.7,de;q=0.6,zh-CN;q=0.5,zh;q=0.4,fi;q=0.3",
        "cache-control": "max-age=0",
        "sec-ch-ua": '"Opera";v="125", "Not?A_Brand";v="8", "Chromium";v="141"',
        "sec-ch-ua-mobile": "?0",
        "sec-ch-ua-platform": '"Windows"',
        "sec-fetch-dest": "document",
        "sec-fetch-mode": "navigate",
        "sec-fetch-site": "same-origin",
        "sec-fetch-user": "?1",
        "upgrade-insecure-requests": "1",
        "user-agent": 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36 OPR/125.0.0.0',
    }

    # Allow JSON-encoded header overrides via env
    headers_json = os.getenv("JSTOR_HEADERS_JSON")
    if headers_json:
        try:
            overrides = json.loads(headers_json)
            if isinstance(overrides, dict):
                base_headers.update({k.lower(): v for k, v in overrides.items()})
        except json.JSONDecodeError:
            print("Warning: JSTOR_HEADERS_JSON is not valid JSON; ignoring.")

    return base_headers


# Set up logging to see debug messages
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

cookie_header = os.getenv("JSTOR_COOKIE_HEADER") or os.getenv("JSTOR_COOKIE", "")
cookies = parse_cookie_header(cookie_header) if cookie_header else None
referer = os.getenv("JSTOR_REFERER", "https://www.jstor.org/stable/353415")
extra_headers = build_browser_headers()

if cookie_header:
    print("Using cookies from JSTOR_COOKIE_HEADER/JSTOR_COOKIE env var")
else:
    print("No JSTOR_COOKIE provided; requests may be blocked (403).")

client = JSTORClient(
    referer=referer,
    cookies=cookies,
    cookie_header=cookie_header if not cookies else None,
    extra_headers=extra_headers,
)
test_url = "https://www.jstor.org/stable/353415"

print(f"Testing JSTOR URL: {test_url}")

# Test metadata extraction (preferred path)
metadata = client.fetch_metadata_from_url(test_url)
if metadata:
    print("✅ Metadata extracted")
    print(f"  DOI: {metadata.get('doi')}")
    print(f"  Title: {metadata.get('title')}")
    print(f"  Authors: {metadata.get('authors')}")
    print(f"  Journal: {metadata.get('journal')}")
    print(f"  Volume/Issue: {metadata.get('volume')}/{metadata.get('issue')}")
    print(f"  Pages: {metadata.get('pages')}")
    print(f"  Year: {metadata.get('year')}")
    print(f"  Tags: {metadata.get('tags')}")
    print(f"  Open Access: {metadata.get('open_access')}")
    print(f"  Page Count: {metadata.get('page_count')}")
else:
    print("❌ No metadata extracted; falling back to DOI-only extraction")

# Test DOI extraction (backward compatibility path)
doi = metadata.get('doi') if metadata else client.fetch_doi_from_url(test_url)

if doi:
    print(f"✅ Found DOI: {doi}")
else:
    print("❌ No DOI found")
    print("\nThis could mean:")
    print("1. JSTOR page structure changed")
    print("2. DOI is in a format not covered by extraction strategies")
    print("3. Page requires JavaScript to render")
    print("4. Network/access issue (check cookies and Referer)")
    print("\nCheck the debug logs above for more details")