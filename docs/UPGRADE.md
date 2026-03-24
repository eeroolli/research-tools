# Upgrade Guide

## Overview

This guide describes how to upgrade the paper processor daemon and handle breaking changes.

## Version Compatibility

### Current Version

- Python 3.11+
- Supports Windows with WSL2
- Distributed setup (blacktower ↔ P1)

## Upgrade Process

### 1. Backup Configuration

Before upgrading, backup your configuration files:

```bash
cp config.conf config.conf.backup
cp config.personal.conf config.personal.conf.backup  # if exists
```

### 2. Update Dependencies

Update Python dependencies:

```bash
conda env update -f environment.yml
# or
pip install -r requirements.txt --upgrade
```

### 3. Review Configuration Changes

Check for new configuration options in `config.conf`:

- `[SERVICE_RESILIENCE]` section (new)
  - `health_check_timeout`
  - `health_check_retries`
  - `health_check_backoff_multiplier`

### 4. Test Services

After upgrade, verify services are working:

1. Start daemon: `python scripts/paper_processor_daemon.py`
2. Check service initialization (GROBID, Ollama)
3. Process a test PDF file

## Breaking Changes

### Modularization (Current)

The daemon has been modularized into separate modules:

**Before:**
- Single monolithic file: `scripts/paper_processor_daemon.py`

**After:**
- Modular structure: `shared_tools/daemon/*.py`
- Main script uses modules

**Migration:**
- No code changes needed for users
- Internal structure changed, but API remains compatible
- Scripts inheriting from `PaperProcessorDaemon` may need updates (e.g., `pdf_self_fixer.py`)

### Exception Handling

**Before:**
- Generic `except Exception:` catches

**After:**
- Specific exception types from `shared_tools.daemon.exceptions`

**Migration:**
- Internal change only
- No user-facing changes

### Service Management

**Before:**
- Service initialization in daemon `__init__`

**After:**
- ServiceManager module handles service lifecycle

**Migration:**
- Internal change only
- Configuration remains the same

## Configuration Migration

### Adding SERVICE_RESILIENCE Section

If upgrading from an older version, add to `config.conf`:

```ini
[SERVICE_RESILIENCE]
# Health check configuration
health_check_timeout = 5
health_check_retries = 3
health_check_backoff_multiplier = 2
```

## Troubleshooting

### Services Not Starting

1. Check service configuration in `config.conf`
2. Verify network connectivity (for remote services)
3. Check service logs
4. Verify Docker is running (for local GROBID)

### Import Errors

If you see import errors for daemon modules:

1. Verify `shared_tools/daemon/` directory exists
2. Check Python path includes project root
3. Verify all modules are present

### File Operation Errors

If file operations fail:

1. Check file permissions
2. Verify paths are correct (WSL vs Windows paths)
3. Check disk space

## Rollback

If upgrade causes issues:

1. Restore configuration backups
2. Revert code changes (git checkout previous version)
3. Restore environment (conda env export > environment.yml.backup)

## Questions

For issues or questions:
1. Check logs in watch directory
2. Review error messages
3. Check GitHub issues (if applicable)

