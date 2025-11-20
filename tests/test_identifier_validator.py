"""
Unit tests for identifier validation system.

Tests DOI, ISSN, ISBN, and URL validation with focus on hallucination detection.
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared_tools.utils.identifier_validator import IdentifierValidator


class TestDOIValidation:
    """Test DOI validation."""
    
    def test_valid_doi(self):
        """Test valid DOI format."""
        is_valid, cleaned, reason = IdentifierValidator.validate_doi("10.1038/s42256-025-01072-0")
        assert is_valid is True
        assert cleaned == "10.1038/s42256-025-01072-0"
        assert "Valid" in reason
    
    def test_doi_with_prefix(self):
        """Test DOI with various prefixes."""
        is_valid, cleaned, reason = IdentifierValidator.validate_doi("doi:10.1038/nature12345")
        assert is_valid is True
        assert cleaned == "10.1038/nature12345"
        
        is_valid, cleaned, reason = IdentifierValidator.validate_doi("https://doi.org/10.1038/nature12345")
        assert is_valid is True
        assert cleaned == "10.1038/nature12345"
    
    def test_suspicious_doi(self):
        """Test detection of fake DOI patterns."""
        is_valid, cleaned, reason = IdentifierValidator.validate_doi("10.1234/fake")
        assert is_valid is False
        assert cleaned is None
        assert "Suspicious" in reason
    
    def test_invalid_doi_format(self):
        """Test invalid DOI format."""
        is_valid, cleaned, reason = IdentifierValidator.validate_doi("not-a-doi")
        assert is_valid is False
        assert cleaned is None
        assert "Invalid" in reason
    
    def test_none_doi(self):
        """Test None DOI."""
        is_valid, cleaned, reason = IdentifierValidator.validate_doi(None)
        assert is_valid is True
        assert cleaned is None


class TestISSNValidation:
    """Test ISSN validation."""
    
    def test_valid_issn(self):
        """Test valid ISSN format."""
        is_valid, cleaned, reason = IdentifierValidator.validate_issn("0028-0836")
        assert is_valid is True
        assert cleaned == "0028-0836"
        assert "Valid" in reason
    
    def test_issn_with_x(self):
        """Test ISSN with X check digit."""
        is_valid, cleaned, reason = IdentifierValidator.validate_issn("1234-567X")
        assert is_valid is True
        assert cleaned == "1234-567X"
    
    def test_suspicious_issn(self):
        """Test detection of fake ISSN patterns."""
        is_valid, cleaned, reason = IdentifierValidator.validate_issn("1234-5678")
        assert is_valid is False
        assert cleaned is None
        assert "Suspicious" in reason
    
    def test_invalid_issn_format(self):
        """Test invalid ISSN format."""
        is_valid, cleaned, reason = IdentifierValidator.validate_issn("12345678")
        assert is_valid is False
        assert "Invalid" in reason
    
    def test_none_issn(self):
        """Test None ISSN."""
        is_valid, cleaned, reason = IdentifierValidator.validate_issn(None)
        assert is_valid is True
        assert cleaned is None


class TestISBNValidation:
    """Test ISBN validation using ISBNMatcher."""
    
    def test_valid_isbn13(self):
        """Test valid ISBN-13."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn("9780262033848")
        assert is_valid is True
        assert cleaned == "9780262033848"
        assert "ISBN-13" in reason
    
    def test_valid_isbn10(self):
        """Test valid ISBN-10."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn("0262033844")
        assert is_valid is True
        assert cleaned == "0262033844"
        assert "ISBN-10" in reason
    
    def test_suspicious_isbn(self):
        """Test detection of fake ISBN patterns."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn("978123456789")
        assert is_valid is False
        assert cleaned is None
        assert "Suspicious" in reason
    
    def test_invalid_isbn_checksum(self):
        """Test ISBN with invalid checksum."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn("9780262033841")
        assert is_valid is False
        assert "checksum" in reason.lower()
    
    def test_formatted_isbn(self):
        """Test ISBN with formatting."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn("978-0-262-03384-8")
        assert is_valid is True
        assert cleaned == "9780262033848"
    
    def test_none_isbn(self):
        """Test None ISBN."""
        is_valid, cleaned, reason = IdentifierValidator.validate_isbn(None)
        assert is_valid is True
        assert cleaned is None


class TestURLValidation:
    """Test URL validation."""
    
    def test_valid_https_url(self):
        """Test valid HTTPS URL."""
        is_valid, cleaned, reason = IdentifierValidator.validate_url("https://www.nature.com/articles/s42256-025-01072-0")
        assert is_valid is True
        assert "https://www.nature.com" in cleaned
        assert "Valid" in reason
    
    def test_valid_http_url(self):
        """Test valid HTTP URL."""
        is_valid, cleaned, reason = IdentifierValidator.validate_url("http://example.com/article")
        assert is_valid is True
        assert "http://example.com" in cleaned
    
    def test_invalid_url(self):
        """Test invalid URL."""
        is_valid, cleaned, reason = IdentifierValidator.validate_url("not a url")
        assert is_valid is False
        assert cleaned is None
        assert "Invalid" in reason
    
    def test_invalid_scheme(self):
        """Test URL with invalid scheme."""
        is_valid, cleaned, reason = IdentifierValidator.validate_url("ftp://example.com")
        assert is_valid is False
        assert "scheme" in reason.lower()
    
    def test_none_url(self):
        """Test None URL."""
        is_valid, cleaned, reason = IdentifierValidator.validate_url(None)
        assert is_valid is True
        assert cleaned is None


class TestValidateAll:
    """Test validation of complete metadata dictionaries."""
    
    def test_valid_metadata(self):
        """Test metadata with all valid identifiers."""
        metadata = {
            'doi': '10.1038/nature12345',
            'issn': '0028-0836',
            'isbn': '9780262033848',
            'url': 'https://www.nature.com/article',
            'title': 'Test Article',
            'authors': ['John Doe'],
            'year': '2025'
        }
        
        validated = IdentifierValidator.validate_all(metadata)
        
        assert validated['doi'] == '10.1038/nature12345'
        assert validated['doi_valid'] is True
        assert validated['has_hallucinations'] is False
        assert len(validated['confidence_flags']) == 0
    
    def test_hallucinated_metadata(self):
        """Test metadata with fake identifiers."""
        metadata = {
            'doi': '10.1234/fake',
            'issn': '1234-5678',
            'isbn': '978123456789',
            'title': 'Test Article',
            'authors': ['John Doe'],
            'year': '2025'
        }
        
        validated = IdentifierValidator.validate_all(metadata)
        
        assert validated['doi'] is None
        assert validated['doi_valid'] is False
        assert validated['issn'] is None
        assert validated['issn_valid'] is False
        assert validated['isbn'] is None
        assert validated['isbn_valid'] is False
        assert validated['has_hallucinations'] is True
        assert len(validated['confidence_flags']) == 3  # All three identifiers should be flagged
    
    def test_mixed_metadata(self):
        """Test metadata with mix of valid and invalid identifiers."""
        metadata = {
            'doi': '10.1038/nature12345',  # Valid
            'issn': '1234-5678',  # Fake
            'isbn': None,
            'title': 'Test Article',
            'year': '2025'
        }
        
        validated = IdentifierValidator.validate_all(metadata)
        
        assert validated['doi'] == '10.1038/nature12345'
        assert validated['doi_valid'] is True
        assert validated['issn'] is None
        assert validated['issn_valid'] is False
        assert validated['has_hallucinations'] is True
        assert len(validated['confidence_flags']) == 1
    
    def test_empty_metadata(self):
        """Test empty metadata dictionary."""
        metadata = {}
        
        validated = IdentifierValidator.validate_all(metadata)
        
        assert validated['doi'] is None
        assert validated['issn'] is None
        assert validated['isbn'] is None
        assert validated['url'] is None
        assert validated['has_hallucinations'] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
