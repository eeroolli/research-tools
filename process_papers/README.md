# Process Papers - Academic Paper Digitization and Integration

This module handles the complete academic paper processing workflow from scanning to Zotero library integration.

## Features

- **Smart OCR Processing** optimized for academic papers with annotations
- **Metadata Extraction** from OCR text (DOI, ISSN, Title, Authors, Journal, etc.)
- **Zotero Integration** with fuzzy matching against existing library
- **Annotation Preservation** keeps handwritten notes as image overlay
- **Language Detection** (EN, DE, NO, FI, SE)
- **Batch Processing** for large collections of papers
- **File Organization** with standardized naming conventions

## Quick Start

```bash
# Activate conda environment (from research-tools root)
conda activate research-tools

# Process scanned papers
python scripts/process_papers.py

# Match with Zotero entries
python scripts/match_zotero.py

# Integrate into Zotero
python scripts/integrate_zotero.py
```

## Workflow

### 1. Scanning
- Use Ricoh scanner or similar high-quality scanner
- Scan papers with handwritten annotations preserved
- Save to `/mnt/i/documents/scan/` with language prefix if needed
- Files should be named with timestamp or descriptive names

### 2. OCR Processing
```bash
python scripts/process_papers.py
```
- Extracts text from scanned PDFs
- Preserves annotations as image overlay
- Detects language automatically
- Extracts metadata (title, authors, DOI, etc.)

### 3. Zotero Matching
```bash
python scripts/match_zotero.py
```
- Matches papers to existing Zotero entries using fuzzy matching
- Uses DOI, title, and author information
- Provides confidence scores for matches
- Allows manual review of uncertain matches

### 4. Integration
```bash
python scripts/integrate_zotero.py
```
- Links scanned PDFs to Zotero entries
- Applies standardized file naming
- Stores in `G:/publications/` folder
- Preserves annotations and metadata

## Architecture

### Core Components

1. **OCREngine** - OCR processing with annotation preservation
2. **MetadataExtractor** - Extracts academic metadata from OCR text
3. **ZoteroLocalDatabaseMatcher** - Fuzzy matching against local Zotero SQLite database
4. **FileProcessor** - PDF optimization and file management

### Processing Pipeline

1. **Scan Analysis** - Detect annotations, language, quality
2. **OCR Processing** - Extract text while preserving annotations
3. **Metadata Extraction** - Parse academic metadata
4. **Zotero Matching** - Find existing entries in library
5. **File Integration** - Link PDFs and apply naming conventions

## Configuration

- **config/process_papers.conf** - Main configuration
- **shared-tools/config/manager.py** - Centralized configuration management

## File Naming Convention

Papers are renamed using the pattern:
```
{author}_{year}_{title}.pdf
```

Examples:
- `Smith_2023_Advanced_Machine_Learning.pdf`
- `Johnson_and_Brown_2022_Climate_Change_Impact.pdf`
- `Garcia_et_al_2024_Neural_Networks_Review.pdf`

## Metadata Extraction

The system extracts:
- **Title** - From the beginning of the document
- **Authors** - From title page or header
- **Year** - Publication year
- **DOI** - Digital Object Identifier
- **ISSN** - International Standard Serial Number
- **Journal** - Journal or publication name
- **Abstract** - If present in the document
- **Keywords** - If present in the document

## Zotero Integration

### Matching Strategy
1. **DOI Match** - Direct match using DOI (95% confidence)
2. **Title + Authors** - Fuzzy match on title and author names
3. **Title Only** - Fuzzy match on title only (lower confidence)

### Fuzzy Matching Thresholds
- Title similarity: 80% minimum
- Author similarity: 70% minimum
- Combined confidence: 75% minimum

## Annotation Handling

- **Detection** - Automatically detects colored annotations
- **Preservation** - Keeps annotations as image overlay
- **Analysis** - Identifies annotation colors and density
- **Storage** - Stores annotation metadata in Zotero

## Integration with Research-Tools

This module integrates with the shared-tools infrastructure:
- **shared-tools/metadata/extractor.py** - Unified metadata extraction
- **shared-tools/config/manager.py** - Centralized configuration
- **shared-tools/api/** - API clients for metadata sources

## Success Metrics

- **OCR Accuracy** - 90%+ for clean academic papers
- **Metadata Extraction** - 85%+ for standard academic formats
- **Zotero Matching** - 95%+ for papers with DOI, 80%+ for others
- **Processing Speed** - 2-3 minutes per paper
