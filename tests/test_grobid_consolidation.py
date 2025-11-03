import io
from pathlib import Path
from typing import Any, Dict

import types

import xml.etree.ElementTree as ET

from shared_tools.api.grobid_client import GrobidClient


class _Resp:
    def __init__(self, status_code: int, text: str):
        self.status_code = status_code
        self.text = text


TEI_MIN = (
    """
<TEI xmlns=\"http://www.tei-c.org/ns/1.0\">
  <teiHeader>
    <fileDesc>
      <titleStmt>
        <title type=\"main\">A Sample Paper</title>
        <author>
          <persName>
            <forename>Jane</forename>
            <surname>Doe</surname>
          </persName>
        </author>
      </titleStmt>
    </fileDesc>
  </teiHeader>
</TEI>
"""
).strip()


def test_consolidation_params_enabled(monkeypatch, tmp_path):
    sent: Dict[str, Any] = {}

    def fake_post(url, files=None, data=None, timeout=None):
        sent['url'] = url
        sent['data'] = dict(data or {})
        return _Resp(200, TEI_MIN)

    # Patch requests.post
    import requests
    monkeypatch.setattr(requests, 'post', fake_post)

    # Create a temporary PDF file
    pdf = tmp_path / 'test.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%fake\n')

    client = GrobidClient(config={
        'grobid.consolidation.enable': True,
        'grobid.consolidation.header': 2,
        'grobid.consolidation.citations': 0,
    })

    md = client.extract_metadata(pdf)
    assert md is not None
    assert sent['data'].get('consolidateHeader') == '2'
    assert sent['data'].get('consolidateCitations') == '0'


def test_consolidation_params_disabled(monkeypatch, tmp_path):
    sent: Dict[str, Any] = {}

    def fake_post(url, files=None, data=None, timeout=None):
        sent['data'] = dict(data or {})
        return _Resp(200, TEI_MIN)

    import requests
    monkeypatch.setattr(requests, 'post', fake_post)

    pdf = tmp_path / 'test.pdf'
    pdf.write_bytes(b'%PDF-1.4\n%fake\n')

    client = GrobidClient(config={
        'grobid.consolidation.enable': False,
    })

    md = client.extract_metadata(pdf)
    assert md is not None
    assert 'consolidateHeader' not in sent['data']
    assert 'consolidateCitations' not in sent['data']


