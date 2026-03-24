# Network Resilience Patterns for Distributed Services

## Problem: Network Failures in Distributed Setup

### Current State

- Services run on remote machine (P1)
- Network failures can occur (connection loss, timeouts, service restarts)
- Limited retry logic
- Unclear error messages for network vs service issues

### Solution: Comprehensive Network Error Handling

## Pattern 1: Health Check with Exponential Backoff

Health checks use exponential backoff to handle transient network failures:

```python
def _check_service_health(
    self,
    service_name: str,
    health_url: str,
    health_check_fn: Callable[[], bool]
) -> Tuple[bool, Optional[str]]:
    """Check service health with exponential backoff."""
    last_error = None
    
    for attempt in range(self.health_check_retries):
        try:
            if health_check_fn():
                return True, None
        except requests.ConnectionError as e:
            last_error = f"Connection error: {e}"
        except requests.Timeout:
            last_error = f"Timeout after {self.health_check_timeout}s"
        
        # Exponential backoff (except on last attempt)
        if attempt < self.health_check_retries - 1:
            wait_time = self.health_check_backoff_multiplier ** attempt
            time.sleep(wait_time)
    
    return False, error_msg
```

**Benefits:**
- Handles transient network failures
- Avoids overwhelming services with rapid retries
- Clear error messages for debugging

## Pattern 2: Service Availability Check

Services are checked on-demand with automatic startup for local services:

```python
def ensure_ollama_ready(self) -> bool:
    """Ensure Ollama is ready (start if local and needed)."""
    # Check if already ready
    if self.ollama_ready:
        is_available, _ = self.check_ollama_health()
        if is_available:
            return True
    
    # Check health
    is_available, error_msg = self.check_ollama_health()
    if is_available:
        return True
    
    # Try to start if local
    if self.is_local_ollama and self.ollama_auto_start:
        if self._start_local_ollama():
            return True
    
    return False
```

**Benefits:**
- Lazy initialization (services start when needed)
- Automatic recovery for local services
- Graceful degradation for remote services

## Pattern 3: Network Error Classification

Network errors are classified for better error messages (future enhancement):

- **Connection errors**: Cannot connect to service (check network/firewall)
- **Timeout errors**: Service did not respond in time (service overloaded)
- **HTTP errors**: Service returned error status (service misconfigured)
- **Unknown errors**: Unexpected error types

## Pattern 4: Circuit Breaker (Future Enhancement)

For production systems, consider implementing a circuit breaker pattern:

- **Closed**: Normal operation, requests pass through
- **Open**: Service is failing, requests fail immediately
- **Half-Open**: Testing if service recovered, allow one request through

## Configuration for Network Resilience

```ini
[SERVICE_RESILIENCE]
# Health check configuration
health_check_timeout = 5
health_check_retries = 3
health_check_backoff_multiplier = 2

# Circuit breaker (future)
circuit_breaker_enabled = false
circuit_breaker_failure_threshold = 5
circuit_breaker_timeout = 60

# Connection pooling
connection_pool_size = 10
connection_pool_timeout = 30
```

## Best Practices

1. **Timeouts**: Always set timeouts for network calls
2. **Retries**: Use exponential backoff for retries
3. **Error Messages**: Provide actionable error messages
4. **Logging**: Log network errors with context
5. **Graceful Degradation**: Don't fail entire system if one service is down
6. **Health Checks**: Regular health checks for remote services
7. **Monitoring**: Track service availability metrics (future)

