# Research-Tools Test Suite

This directory contains the test files for the research-tools project.

## Test Files

### `test_library_by_params.py`
**Purpose**: Parameterized testing tool for any national library
**Usage**: `python test_library_by_params.py [COUNTRY_CODE] [ISBN] [LANGUAGE]`
**Example**: `python test_library_by_params.py NO 978-82-02-48434-7 no`

**Features**:
- Tests any library by country code, ISBN, and language
- Validates ISBN format and checksums
- Extracts ISBN prefixes for library matching
- Tests both book search and general search functionality
- Provides detailed error messages and validation feedback

### `test_integration.py`
**Purpose**: Integration testing for shared components
**Usage**: `python test_integration.py`

**Tests**:
- ISBNMatcher utility functions
- Configuration loading
- Basic API client functionality
- End-to-end workflow testing

### `test_config_driven_national_libraries.py`
**Purpose**: Comprehensive testing of configuration-driven national library system
**Usage**: `python test_config_driven_national_libraries.py`

**Tests**:
- All configured national libraries
- Field mapping and response parsing
- Error handling and fallback behavior
- Configuration validation

## Running Tests

```bash
# Test specific library with ISBN
python tests/test_library_by_params.py NO 978-82-02-48434-7 no

# Run integration tests
python tests/test_integration.py

# Run comprehensive library tests
python tests/test_config_driven_national_libraries.py
```

## Test Coverage

- ✅ Norwegian National Library
- ✅ Swedish National Library (Libris)
- ✅ Finnish National Library (Finna)
- ✅ OpenLibrary
- ✅ Google Books
- ✅ ISBN validation and prefix extraction
- ✅ Configuration-driven client system
- ✅ Field mapping and response parsing
