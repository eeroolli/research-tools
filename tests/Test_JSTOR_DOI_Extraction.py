#!/usr/bin/env python3
"""Test JSTOR DOI extraction for debugging."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.api.jstor_client import JSTORClient
import logging

# Set up logging to see debug messages
logging.basicConfig(level=logging.DEBUG, format='%(levelname)s: %(message)s')

client = JSTORClient()
test_url = "https://www.jstor.org/stable/353415"

# Align test session headers with production defaults
client.session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
    'Accept-Encoding': 'gzip, deflate, br',
    'Connection': 'keep-alive',
    'Upgrade-Insecure-Requests': '1'
})

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
    print("4. Network/access issue")
    print("\nCheck the debug logs above for more details")