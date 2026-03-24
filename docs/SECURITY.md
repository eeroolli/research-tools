# Security Best Practices

## Overview

This document outlines security best practices for the paper processor daemon, including secure configuration handling, subprocess security, and file permissions.

## Configuration Security

### Environment Variables

Sensitive configuration values (API keys, passwords) should be provided via environment variables when possible, as they are more secure than storing in files.

**Supported Environment Variables:**

- `ZOTERO_API_KEY` - Zotero API key
- `ZOTERO_LIBRARY_ID` - Zotero library ID
- `ZOTERO_LIBRARY_TYPE` - Zotero library type
- `GROBID_HOST` - GROBID server host
- `GROBID_PORT` - GROBID server port
- `OLLAMA_HOST` - Ollama server host
- `OLLAMA_PORT` - Ollama server port
- `OLLAMA_MODEL` - Ollama model name

**Priority Order:**
1. Environment variables (highest priority)
2. Personal config file (`config.personal.conf`)
3. Main config file (`config.conf`)

### Configuration File Permissions

Personal configuration files containing sensitive data should have restrictive permissions:

```bash
chmod 600 config.personal.conf
```

This ensures only the file owner can read/write the file.

The daemon will warn if personal config files are readable by group or others.

### Secure Configuration Loading

Use `SecureConfigLoader` for loading configuration:

```python
from shared_tools.daemon.config_loader import SecureConfigLoader

loader = SecureConfigLoader()
config = loader.load_config(
    config_path=Path("config.conf"),
    personal_config_path=Path("config.personal.conf"),
    check_permissions=True
)

# Get API key securely (checks env var first)
api_key = loader.get_secure_api_key(config, 'zotero')
```

## Subprocess Security

### Safe Subprocess Usage

Always use the list form of `subprocess.run()` or `subprocess.Popen()` to prevent command injection:

**✅ Safe:**
```python
result = subprocess.run(
    ['docker', 'start', container_name],
    capture_output=True,
    text=True,
    check=False,
    timeout=30
)
```

**❌ Unsafe:**
```python
# NEVER do this with user input
result = subprocess.run(f"docker start {container_name}", shell=True)
```

### Timeout Protection

Always set timeouts for subprocess calls to prevent hanging:

```python
result = subprocess.run(
    ['command', 'arg1', 'arg2'],
    timeout=30  # 30 second timeout
)
```

### Input Validation

Validate all inputs before passing to subprocess:

```python
def safe_docker_command(container_name: str) -> bool:
    # Validate container name (no special characters)
    if not container_name.replace('_', '').replace('-', '').isalnum():
        raise ValueError(f"Invalid container name: {container_name}")
    
    result = subprocess.run(
        ['docker', 'start', container_name],
        timeout=30
    )
    return result.returncode == 0
```

## File Path Security

### Path Validation

Always validate file paths to prevent path traversal attacks:

```python
from shared_tools.daemon.config_validator import ConfigValidator

# Validate path is within allowed directory
def validate_path_in_base(path: Path, base_dir: Path) -> Path:
    resolved = path.resolve()
    base_resolved = base_dir.resolve()
    
    if not str(resolved).startswith(str(base_resolved)):
        raise ValueError(f"Path outside allowed directory: {path}")
    
    return resolved
```

### File Permissions

Check file permissions before reading sensitive files:

```python
import stat

def check_file_permissions(file_path: Path) -> bool:
    """Check if file has restrictive permissions (600 or more restrictive)."""
    file_stat = file_path.stat()
    mode = file_stat.st_mode
    
    # File should not be readable by group or others
    return not (mode & (stat.S_IRGRP | stat.S_IROTH))
```

## Network Security

### Service Communication

For distributed setups (blacktower ↔ P1):

1. **Use HTTPS when possible** (if services support it)
2. **Firewall rules**: Only allow necessary ports
3. **Network isolation**: Use VPN or private network when possible
4. **Authentication**: Use API keys or tokens for service authentication

### Timeout Configuration

Set appropriate timeouts for network operations:

```python
# In config.conf
[SERVICE_RESILIENCE]
health_check_timeout = 5  # Short timeout for health checks
health_check_retries = 3  # Retry failed checks
```

## Best Practices Summary

1. **Use environment variables** for sensitive data (API keys, passwords)
2. **Set restrictive file permissions** (600) for personal config files
3. **Use list form** for subprocess calls (never `shell=True` with user input)
4. **Set timeouts** for all subprocess and network operations
5. **Validate inputs** before using in subprocess commands
6. **Check file permissions** before reading sensitive files
7. **Use secure configuration loader** (`SecureConfigLoader`)
8. **Log security warnings** but don't expose sensitive data in logs

## Security Checklist

- [ ] API keys stored in environment variables or `config.personal.conf`
- [ ] `config.personal.conf` has permissions 600
- [ ] All subprocess calls use list form (no `shell=True` with user input)
- [ ] All subprocess calls have timeouts
- [ ] File paths are validated before use
- [ ] Network timeouts are configured appropriately
- [ ] Sensitive data is not logged
- [ ] Configuration validation checks for required values

## Reporting Security Issues

If you discover a security vulnerability, please:
1. Do not create a public issue
2. Contact the maintainer directly
3. Provide details of the vulnerability
4. Allow time for a fix before public disclosure

