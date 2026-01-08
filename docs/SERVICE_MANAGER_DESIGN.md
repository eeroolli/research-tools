# Service Manager Module Design

## Overview

The ServiceManager module centralizes all service lifecycle management (GROBID, Ollama) with robust network resilience for distributed setups (blacktower ↔ P1).

## Architecture

### Module Location

`shared_tools/daemon/service_manager.py`

### Responsibilities

- Service initialization and health checks
- Network connectivity monitoring
- Retry logic with exponential backoff
- Local vs remote service detection
- Graceful degradation when services unavailable
- Service lifecycle management (start/stop for local services)

### Key Design Principles

1. **Network-Aware**: Handles both local and remote services transparently
2. **Resilient**: Automatic retries with exponential backoff for network failures
3. **Observable**: Clear status reporting and error messages
4. **Testable**: Dependency injection allows mocking for testing
5. **Non-Blocking**: Health checks don't block daemon startup

## Class Structure

```python
class ServiceManager:
    """Manages service lifecycle for GROBID and Ollama (local or remote)."""
    
    # Configuration
    grobid_host: str
    grobid_port: int
    ollama_host: str
    ollama_port: int
    grobid_auto_start: bool
    ollama_auto_start: bool
    
    # State
    grobid_ready: bool
    ollama_ready: bool
    grobid_client: Optional[GrobidClient]
    ollama_client: Optional[OllamaClient]
    
    # Methods
    def initialize_grobid() -> bool
    def initialize_ollama() -> bool
    def ensure_grobid_ready() -> bool
    def ensure_ollama_ready() -> bool
    def check_grobid_health() -> Tuple[bool, Optional[str]]
    def check_ollama_health() -> Tuple[bool, Optional[str]]
    def shutdown()
```

## Network Resilience Patterns

### 1. Health Check with Retries

- Short timeout (5 seconds) for health checks
- Exponential backoff (1s, 2s, 4s)
- Clear error messages for network vs service issues

### 2. Service Discovery

- Detect local vs remote from config
- Different strategies for local (Docker management) vs remote (network checks only)

### 3. Graceful Degradation

- Daemon starts even if services unavailable
- Services can be checked/lazy-started when needed
- Clear status reporting to user

### 4. Connection Pooling (Future)

- Reuse HTTP connections for remote services
- Connection timeouts and keepalive
- Automatic reconnection on failure

## Error Handling

### Exception Hierarchy

Uses `shared_tools.daemon.exceptions.ServiceError` for service-related errors.

### Error Recovery

- Network errors: Retry with backoff
- Service unavailable: Report status, continue with fallbacks
- Startup failures: Log error, disable service, continue

## Testing Strategy

### Unit Tests

- Mock network calls
- Test retry logic
- Test local vs remote detection

### Integration Tests

- Test with actual services (local)
- Test network error scenarios (simulate failures)
- Test service startup/shutdown

## Configuration

### Config Parameters

```ini
[GROBID]
host = 192.168.178.129  # localhost or remote IP
port = 8070
auto_start = true  # Only for localhost
auto_stop = true   # Only for localhost
container_name = grobid

[OLLAMA]
host = 192.168.178.129  # localhost or remote IP
port = 11434
auto_start = true  # Only for localhost
startup_timeout = 30
shutdown_timeout = 10

[SERVICE_RESILIENCE]
health_check_timeout = 5
health_check_retries = 3
health_check_backoff_multiplier = 2
```

## Migration Path

1. Extract service management code from daemon
2. Create ServiceManager class
3. Update daemon to use ServiceManager (Chunk 2.3)
4. Add network resilience features
5. Add comprehensive error handling
6. Add tests (Chunk 3.1)

## Performance Considerations

- Health checks are lightweight (HTTP GET)
- Network timeouts prevent hanging
- Lazy initialization (Ollama only when needed)
- Connection reuse for remote services

