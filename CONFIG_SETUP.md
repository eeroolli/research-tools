# Configuration Setup

This document explains how to configure the research-tools system.

## Configuration Files

### `config.conf` (Template)
- **Purpose**: Template configuration file (safe for Git)
- **Contains**: Generic settings, placeholder API keys
- **Usage**: Copy to `config.personal.conf` and fill in your actual values

### `config.personal.conf` (Personal - Git Ignored)
- **Purpose**: Your personal configuration with actual API keys
- **Contains**: Real API keys, personal paths, sensitive data
- **Usage**: This file is gitignored - add your actual settings here

### `shared_tools/api/national_library_config.yaml`
- **Purpose**: Configuration for all metadata APIs (books and papers)
- **Contains**: API endpoints, field mappings, country/language codes
- **Usage**: Edit this file to modify library APIs or add new ones

## Setup Instructions

1. **Copy the template**:
   ```bash
   cp config.conf config.personal.conf
   ```

2. **Edit your personal config**:
   ```bash
   nano config.personal.conf
   ```

3. **Add your API keys**:
   - Zotero API key and library ID
   - Google Books API key (optional)
   - Update scan folder path

4. **Configure metadata APIs** (if needed):
   ```bash
   nano shared_tools/api/national_library_config.yaml
   ```

## API Key Sources

- **Zotero**: https://www.zotero.org/settings/keys
- **Google Books**: https://console.cloud.google.com/
- **Academic APIs**: OpenAlex, CrossRef, PubMed, arXiv (no keys required)
- **National Libraries**: Norwegian, Swedish, Finnish (no keys required)

## Security Notes

- `config.personal.conf` is gitignored - your API keys are safe
- Never commit API keys to Git
- The template `config.conf` contains only placeholders
