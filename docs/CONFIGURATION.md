# Configuration Guide

## Overview

The paper processor daemon uses `config.conf` for all configuration settings. Personal overrides can be placed in `config.personal.conf` (which should be in `.gitignore`).

## Configuration File Structure

### Main Configuration File: `config.conf`

Located in the project root. This file contains default settings.

### Personal Configuration: `config.personal.conf`

Optional file in project root for personal settings (API keys, paths, etc.). This file should be in `.gitignore` and not committed to version control.

## Configuration Sections

### [PATHS]

Directory paths for the daemon.

- `scanner_papers_dir`: Directory to watch for new scanned PDFs (WSL or Windows format)
- `publications_dir`: Directory where processed PDFs are copied

### [GROBID]

GROBID service configuration for metadata extraction.

- `host`: GROBID host address (default: `localhost`)
  - For distributed setup: use the primary remote IP (e.g., `192.168.178.129`)
  - Other reference IPs: `192.168.178.130`, `192.168.178.176`
  - For local setup: use `localhost`
- `port`: GROBID port (default: `8070`)
- `auto_start`: Automatically start GROBID container if local (default: `true`)
- `auto_stop`: Automatically stop GROBID container on daemon shutdown (default: `true`)
- `container_name`: Docker container name for GROBID (default: `grobid`)
- `handle_rotation`: Handle PDF rotation automatically (default: `true`)
- `rotation_check_pages`: Number of pages to check for rotation (default: `2`)
- `max_pages`: Maximum pages to process with GROBID (default: `2`)

### [OLLAMA]

Ollama service configuration for AI-powered metadata extraction (fallback).

- `host`: Ollama host address (default: `localhost`)
  - For distributed setup: use hostname (e.g., `p1`) or primary remote IP (e.g., `192.168.178.129`)
  - Other reference IPs: `192.168.178.130`, `192.168.178.176`
  - For local setup: use `localhost`
- `fallback_hosts`: Comma-separated IPs to try when `host` is a hostname that doesn't resolve (e.g. `192.168.178.176,192.168.178.129`). Leave empty to disable fallback.
- `port`: Ollama port (default: `11434`)
- `auto_start`: Automatically start Ollama if local (default: `true`)
- `startup_timeout`: Timeout in seconds for Ollama startup (default: `30`)
- `shutdown_timeout`: Timeout in seconds for Ollama shutdown (default: `10`)

### [SERVICE_RESILIENCE]

Network resilience configuration for distributed setups (blacktower ↔ P1).

These settings help handle network failures and service unavailability gracefully.

- `health_check_timeout`: Timeout in seconds for service health checks (default: `5`)
- `health_check_retries`: Number of retry attempts for health checks (default: `3`)
- `health_check_backoff_multiplier`: Exponential backoff multiplier for retries (default: `2`)
  - With multiplier 2: retry delays are 1s, 2s, 4s

**Future enhancements** (currently disabled):
- `circuit_breaker_enabled`: Enable circuit breaker pattern (default: `false`)
- `circuit_breaker_failure_threshold`: Number of failures before opening circuit
- `circuit_breaker_timeout`: Timeout before attempting to close circuit

### [APIS]

API keys for external services.

- `zotero_api_key`: Zotero API key (required)
- `zotero_library_id`: Zotero library ID (required)
- Other API keys as needed

**Security Note**: Store sensitive API keys in `config.personal.conf` or environment variables.

### [PROCESSING]

Processing configuration.

- `tesseract_path`: Path to Tesseract OCR executable (optional)
- Other processing settings

## Distributed Setup Configuration

For distributed setup (blacktower ↔ P1):

### On blacktower (daemon runs here):

```ini
[GROBID]
host = 192.168.178.129  # P1 primary API IP
port = 8070
auto_start = false  # Service runs on P1, not blacktower

[OLLAMA]
host = 192.168.178.129  # P1 primary API IP
fallback_hosts = 192.168.178.130,192.168.178.176
port = 11434
auto_start = false  # Service runs on P1, not blacktower

[SERVICE_RESILIENCE]
health_check_timeout = 5
health_check_retries = 3
health_check_backoff_multiplier = 2
```

### On P1 (services run here):

Services should be configured to listen on the network interface (not just localhost).

## Environment Variables

Sensitive configuration can be provided via environment variables (takes precedence over config file):

- `ZOTERO_API_KEY`: Zotero API key
- Other API keys as needed

Example:
```bash
export ZOTERO_API_KEY="your_api_key_here"
python scripts/paper_processor_daemon.py
```

## Configuration Validation

The daemon validates configuration on startup using `ConfigValidator`:

- Paths are validated and normalized
- Ports are validated (1-65535)
- Required keys are checked
- Service connectivity is checked (for remote services)

Errors are reported with clear messages indicating what needs to be fixed.

## Security Best Practices

1. **Never commit sensitive data**: Use `config.personal.conf` (in `.gitignore`) for personal settings
2. **File permissions**: Set restrictive permissions on personal config file:
   ```bash
   chmod 600 config.personal.conf
   ```
3. **Environment variables**: Use environment variables for API keys in production
4. **Network security**: For distributed setups, ensure proper firewall rules for service ports

## Troubleshooting

### Services Not Starting

1. Check service configuration (host, port)
2. Verify network connectivity (for remote services):
   ```bash
   curl http://192.168.178.129:8070/api/isalive  # GROBID (primary API)
   curl http://192.168.178.129:11434/api/tags    # Ollama (primary API)
   # Other reference IPs: 192.168.178.130 (LAN), 192.168.178.176 (legacy)
   ```
3. Check service logs
4. Verify Docker is running (for local GROBID)

### Configuration Errors

Configuration validation errors are reported on daemon startup. Check the error messages for:
- Invalid paths
- Invalid ports
- Missing required keys
- Network connectivity issues

### Path Issues

Paths can be in WSL format (`/mnt/c/...`) or Windows format (`C:\...`). The daemon normalizes paths automatically. If you encounter path issues:

1. Check path exists
2. Verify path format matches your environment (WSL vs Windows)
3. Check file permissions

