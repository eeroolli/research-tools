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
- `zotero_web_library_url`: Web Zotero library URL opened in the default browser at daemon start (e.g. `https://www.zotero.org/your.name/library`). Leave empty to disable.

Recommended Windows-first setup (native Windows Python, CMD/PowerShell):

```ini
[PATHS]
scanner_papers_dir = I:\FraScanner\papers
publications_dir = I:\publications
zotero_web_library_url = https://www.zotero.org/your.name/library
```

Equivalent WSL-style paths (when running the daemon inside WSL):

```ini
[PATHS]
scanner_papers_dir = /mnt/i/FraScanner/papers
publications_dir = /mnt/i/publications
```

### [PDF_VIEWER]

Optional Windows-only setting for the daemon-owned SumatraPDF instance:

```ini
[PDF_VIEWER]
sumatra_exe = C:\Program Files\SumatraPDF\SumatraPDF.exe
```

Leave unset if `SumatraPDF.exe` is already on PATH. The daemon always uses a private `-appdata` profile so it does not control your normal Sumatra window.

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
- `remote_auto_start`: If `true` and `host` is remote, run `remote_start_command` over SSH once at daemon startup (default: `false`)
- `remote_ssh_host`: SSH host to connect to for remote start (default: same as `host`)
- `remote_ssh_user`: SSH username (optional). If empty, uses SSH defaults / `~/.ssh/config`
- `remote_start_command`: Command run on the remote host (default: `docker start grobid`). Safe to run even if the container is already running.
- `tcp_precheck_timeout`: TCP connection timeout (seconds) for a fast `host:port` reachability probe before HTTP health checks (default: `1.0`)
- `handle_rotation`: If `true`, the daemon’s GROBID client will attempt to detect and correct PDF rotation *before sending pages to GROBID* (default: `true`). Disable this if your scanner software already outputs correctly oriented PDFs (e.g., Epson Document Capture Pro), to avoid unnecessary processing or accidental double-correction.
- `rotation_check_pages`: Number of pages to check for rotation (default: `2`)
- `max_pages`: Maximum pages to process with GROBID (default: `2`)

### [OLLAMA]

Ollama service configuration for AI-powered metadata extraction (fallback) and filename shortening.

- `host`: Ollama host address (default: `localhost`)
  - For distributed setup: use hostname (e.g., `p1`) or primary remote IP (e.g., `192.168.178.129`)
  - Other reference IPs: `192.168.178.130`, `192.168.178.176`
  - For local setup: use `localhost`
- `fallback_hosts`: Comma-separated IPs to try when `host` is a hostname that doesn't resolve (e.g. `192.168.178.176,192.168.178.129`). Leave empty to disable fallback.
- `port`: Ollama port (default: `11434`)
- `model`: Base Ollama model name. Used when role-specific models are not configured (default: `llama3.2:8b` in `config.conf`).
- `metadata_model` (optional): Model used for *PDF metadata extraction* and other heavy text-understanding tasks. If omitted or empty, falls back to `model`.
- `title_model` (optional): Model used for *filename shortening* (`shorten_title`). If omitted or empty, falls back to `model`.
- `metadata_temperature` (optional): Temperature for metadata extraction calls. If omitted or empty, a conservative default (≈ `0.1`) is used.
- `title_temperature` (optional): Temperature for filename shortening calls. If omitted or empty, a near-zero default (≈ `0.0`) is used.
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

### [ENRICHMENT]

Controls how online metadata candidates are scored against an existing Zotero item and which fields can be applied automatically.

- `auto_accept_threshold`: Minimum composite score for automatic acceptance (default: `0.85`).
- `manual_review_threshold`: Minimum score for manual review; lower scores are rejected (default: `0.75`).
- `language_confidence_min`: Ignores lower-confidence language evidence during scoring (default: `0.90`).
- `weight_title`, `weight_authors`, `weight_year`, `weight_type`, `weight_language`: Relative contributions to the composite score. Document-type matching uses the aliases and partial matches in `document_types.conf`.
- `field_policy`: Comma-separated `field:rule` entries. Supported rules are:
  - `auto_if_missing`: Fill the field only when Zotero has no value.
  - `auto_if_missing_with_confidence`: Fill a missing value only when its confidence check passes.
  - `manual`: Show a changed value for manual review.
  - `manual_on_conflict`: Fill a missing value, but require review when both sources have different values.

Example:

```ini
[ENRICHMENT]
auto_accept_threshold = 0.85
manual_review_threshold = 0.75
weight_title = 0.45
weight_authors = 0.30
weight_year = 0.15
weight_type = 0.10
weight_language = 0.05
field_policy = doi:manual_on_conflict,issn:auto_if_missing,title:manual,authors:manual,document_type:manual
```

An exact DOI, ISBN, or ISSN match is accepted regardless of the composite threshold. A conflicting identifier requires manual review only when the composite score reaches `auto_accept_threshold`; otherwise the candidate is rejected.

### Document type mappings

The repo-root `document_types.conf` maps document labels from internal metadata, CrossRef/DataCite, CSL, and selected COAR terms to Zotero `itemType` values. These mappings are used by enrichment comparison and planning, metadata merging, and Zotero item creation and updates.

```ini
[aliases]
journal-article = journalArticle
article-journal = journalArticle
book_chapter = bookSection

[partial_matches]
journalArticle = conferencePaper
```

- Alias keys are case-insensitive; spaces and hyphens are normalized to underscores and other punctuation is removed.
- Alias values should be valid Zotero `itemType` strings such as `journalArticle` or `bookSection`.
- Labels that map to the same value are equivalent and score `1.0`. A pair in `[partial_matches]` scores `0.3`; other or unmapped pairs score `0.0`.
- Add mappings for every source label that should be treated as equivalent. An unmapped label is not considered a match.
- Mappings are cached in a running process. Restart the daemon after editing `document_types.conf`.

### [TEXT_IGNORE]

Configurable ignore patterns for recurring stamps/headers that should **never** be treated as metadata.

- **Goal**: remove known “stamp” lines (name/phone/URL blocks, institutional footers, etc.) from extracted PDF text *before* regex extraction, GROBID structured-page pre-processing, and Ollama prompts.
- **Format**: one regex per line in a ConfigParser multiline value (continuation lines must be indented).
- **Safety**: prefer patterns that match a single line (use `(?m)^...$`) rather than large multi-line blocks.

Example:

```ini
[TEXT_IGNORE]
ignore_regex =
    (?m)^\s*eero\s+olli\b.*$
    (?m)^\s*\+?47\b.*9577.*0064.*$
    (?m)^\s*https?://(?:www\.)?eero\.no\b.*$
```

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

## Environments and Security Best Practices

### Recommended environments

- **Windows environment (recommended)**: `research-tools-win`
  - Primary runtime for the paper processor daemon and tests.
  - Typical activation:
    ```powershell
    cd F:\prog\research-tools
    conda activate research-tools-win
    python .\scripts\paper_processor_daemon.py
    python -m pytest tests
    ```
  - You can create this env by exporting your WSL `research-tools` env and recreating it on Windows, for example:
    ```bash
    # In WSL
    conda activate research-tools
    conda env export --no-builds > environment-research-tools.yml

    # In Windows PowerShell
    conda env create -n research-tools-win -f environment-research-tools.yml
    conda activate research-tools-win
    ```
- **WSL (Linux) environment (legacy / optional)**: `research-tools`
  - Used for legacy WSL-based workflows and scripts that assume `/mnt/...` paths.
  - Typical activation:
    ```bash
    cd /mnt/f/prog/research-tools
    conda activate research-tools
    ```

### Security Best Practices

1. **Never commit sensitive data**: Use `config.personal.conf` (in `.gitignore`) for personal settings
2. **File permissions**: Set restrictive permissions on personal config file:
   ```bash
   chmod 600 config.personal.conf
   ```
3. **Environment variables**: Use environment variables for API keys in production
4. **Network security**: For distributed setups, ensure proper firewall rules for service ports

## Daemon lifecycle commands

Run these commands from the repository root in the same Windows or WSL environment used for the daemon:

```bash
python scripts/paper_processor_daemon.py --status
python scripts/paper_processor_daemon.py --stop
python scripts/paper_processor_daemon.py --restart
```

- `--status` prints `running (PID …)` and exits successfully when a worker is found; it prints `not running` and exits with status `1` otherwise.
- `--stop` requests a graceful stop and clears the PID file.
- `--restart` stops an existing worker, then starts a new interactive daemon in the current terminal.

Status and stop first use `.daemon.pid` in `scanner_papers_dir`. If that file is missing or stale, the daemon also checks the Windows process list or Linux `pgrep`, so a live worker can still be found. The configured scanner directory must exist before any lifecycle command can run.

## Troubleshooting

### Recommended Windows-first runtime

On a Windows workstation, the preferred way to run the daemon is:

```powershell
cd F:\prog\research-tools
python .\scripts\paper_processor_daemon.py
```

In this mode (`sys.platform == 'win32'`):

- Windows-style paths in `[PATHS]` (like `I:\FraScanner\papers` and `I:\publications`) are used directly.
- At startup the daemon positions the terminal on the right half once (`SetWindowPos` only; no keyboard snap).
- It also starts a **daemon-owned** SumatraPDF instance with a private `-appdata` profile (`%LOCALAPPDATA%\research-tools\sumatra-daemon`), positions that window on the left half once, then returns focus to the terminal. Any Sumatra you already had open is left alone.
- Later papers only send a quiet DDE `Open` to that owned instance (no raise, no focus steal, no re-snap). Closing tabs releases file locks; the process stays up until daemon shutdown (`CmdExit`).
- At startup, if `PATHS.zotero_web_library_url` is set, the default browser opens that Web Zotero library; with two or more monitors the browser is moved to the screen that does not host the terminal.
- If `SumatraPDF.exe` is not on PATH, set `[PDF_VIEWER] sumatra_exe` in `config.personal.conf`.

#### Owned Sumatra / window layout (manual check)

1. Open Sumatra on another virtual desktop (or leave it closed).
2. Start the daemon from a terminal on your usual desktop.
3. Confirm a **new** Sumatra window appears beside the terminal (left), not the one on the other desktop.
4. Process a paper, then another: the document changes in the owned window without stealing keyboard focus from the terminal.
5. Stop the daemon: the owned Sumatra should exit; your other Sumatra (if any) should remain.

Running the daemon from inside WSL is still supported as a best-effort mode, but Windows-specific features (one-time terminal/Sumatra placement, PowerShell-based file copying) are skipped, and only Linux tools such as `wslview` and `xdg-open` are used for opening PDFs.

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
   - When running natively on Windows, prefer Windows-style paths (e.g. `I:\FraScanner\papers`).
   - When running inside WSL, prefer `/mnt/...` paths (e.g. `/mnt/i/FraScanner/papers`).
3. Check file permissions

