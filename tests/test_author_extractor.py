import pytest

from shared_tools.utils.author_extractor import AuthorExtractor


def test_extract_authors_simple_basic():
    text = "Authors: Jane Doe and John Smith\nDepartment of Something"
    authors = AuthorExtractor.extract_authors_simple(text)
    assert "Jane Doe" in authors
    assert "John Smith" in authors


def test_extract_authors_with_regex_labelled():
    text = "Author(s): Alice Johnson, Bob Miller"
    authors = AuthorExtractor.extract_authors_with_regex(text)
    assert set(authors) == {"Alice Johnson", "Bob Miller"}
