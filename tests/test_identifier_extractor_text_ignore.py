"""URL extraction respects TEXT_IGNORE patterns."""

from shared_tools.utils.identifier_extractor import IdentifierExtractor


def test_extract_urls_filters_ignored_stamp_url():
    text = (
        "See https://example.org/paper\n"
        "http://eero.no\n"
    )
    urls = IdentifierExtractor.extract_urls(text)
    assert "http://eero.no" not in urls
    assert any("example.org" in u for u in urls)
