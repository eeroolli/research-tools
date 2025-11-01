#!/usr/bin/env python3
"""
Show raw GROBID XML response to see what GROBID actually extracted.
This helps debug if information is in the XML but not being parsed.
"""

import sys
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

def show_grobid_xml(pdf_path: Path, max_pages: int = 2):
    """Show raw GROBID XML response."""
    print(f"Extracting from: {pdf_path.name}")
    print(f"Processing pages: 1-{max_pages if max_pages > 0 else 'all'}")
    print("=" * 70)
    
    # Send to GROBID
    grobid_url = "http://localhost:8070/api/processFulltextDocument"
    
    with open(pdf_path, 'rb') as f:
        files = {'input': f}
        data = {'start': '1', 'end': str(max_pages) if max_pages > 0 else '0'}
        
        print("\n⏳ Sending to GROBID...")
        response = requests.post(grobid_url, files=files, data=data, timeout=60)
    
    if response.status_code != 200:
        print(f"❌ GROBID failed: {response.status_code}")
        print(response.text)
        return
    
    # Parse and show XML
    root = ET.fromstring(response.text)
    
    print("\n" + "=" * 70)
    print("GROBID XML STRUCTURE")
    print("=" * 70)
    
    # Pretty print XML
    try:
        import xml.dom.minidom
        pretty = xml.dom.minidom.parseString(response.text).toprettyxml(indent="  ")
        print(pretty[:10000])  # First 10000 chars
        if len(pretty) > 10000:
            print(f"\n... (truncated, total length: {len(pretty)} chars)")
    except Exception as e:
        print("Could not pretty-print XML:")
        print(response.text[:5000])
    
    print("\n" + "=" * 70)
    print("LOOKING FOR CONFERENCE/MEETING INFO")
    print("=" * 70)
    
    # Check for meeting elements
    meeting_elems = root.findall('.//{http://www.tei-c.org/ns/1.0}meeting')
    if meeting_elems:
        print(f"\n✅ Found {len(meeting_elems)} <meeting> element(s):")
        for i, meeting in enumerate(meeting_elems, 1):
            print(f"\nMeeting {i}:")
            name = meeting.find('.//{http://www.tei-c.org/ns/1.0}name')
            if name is not None:
                print(f"  Name: {name.text}")
            print(f"  XML: {ET.tostring(meeting, encoding='unicode')[:500]}")
    else:
        print("\n❌ No <meeting> elements found in XML")
    
    # Check for dates
    date_elems = root.findall('.//{http://www.tei-c.org/ns/1.0}date')
    if date_elems:
        print(f"\n📅 Found {len(date_elems)} <date> element(s):")
        for i, date_elem in enumerate(date_elems[:5], 1):  # Show first 5
            date_type = date_elem.get('type', 'no type')
            date_text = date_elem.text if date_elem.text else ''
            print(f"  Date {i}: type='{date_type}', text='{date_text}'")
    
    # Check title page for conference text
    print("\n" + "=" * 70)
    print("CHECKING TITLE PAGE CONTENT")
    print("=" * 70)
    
    title_pages = root.findall('.//{http://www.tei-c.org/ns/1.0}titlePage')
    if title_pages:
        print(f"\nFound {len(title_pages)} titlePage element(s)")
        for i, title_page in enumerate(title_pages, 1):
            print(f"\nTitle Page {i} content (first 1000 chars):")
            text_content = ET.tostring(title_page, method='text', encoding='unicode')
            print(text_content[:1000])
    else:
        print("\nNo <titlePage> elements found")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python show_grobid_xml.py <pdf_path> [max_pages]")
        print("  max_pages: 0 = all pages, 2 = first 2 pages (default)")
        sys.exit(1)
    
    pdf_path = Path(sys.argv[1])
    max_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    
    if not pdf_path.exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)
    
    show_grobid_xml(pdf_path, max_pages)

