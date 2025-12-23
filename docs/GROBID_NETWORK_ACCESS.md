# GROBID Network Access from blacktower

## Overview

GROBID runs in a Docker container on **p1** and is accessible via HTTP on port **8070**. To access it from **blacktower**, you need to connect via p1's network address.

## Current Setup

- **GROBID Container**: Runs on p1
- **Port Mapping**: `-p 8070:8070` (maps container port 8070 to host port 8070)
- **Local Access**: `http://localhost:8070` (works on p1)
- **Network Access**: `http://192.168.178.129:8070` (works from blacktower)

## Accessing from blacktower

### Option 1: Use p1's IP Address

1. **Find p1's IP address:**
   ```bash
   # On p1
   hostname -I
   # Or
   ip addr show | grep "inet " | grep -v 127.0.0.1
   ```

2. **Configure GROBID client on blacktower:**
   ```python
   # In your script on blacktower
   from shared_tools.api.grobid_client import GrobidClient
   
   # Use p1's IP address instead of localhost
   grobid = GrobidClient(base_url="http://192.168.178.129:8070")
   ```

3. **Or set environment variable:**
   ```bash
   export GROBID_URL=http://192.168.178.129:8070
   ```

### Option 2: Use p1's Hostname

If both machines are on the same network and can resolve hostnames:

```python
grobid = GrobidClient(base_url="http://p1:8070")
```

### Option 3: SSH Tunnel (Secure but Slower)

Create an SSH tunnel from blacktower to p1:

```bash
# On blacktower
ssh -L 8070:localhost:8070 user@p1
```

Then use `http://localhost:8070` on blacktower (tunneled through SSH).

## Configuration

### Update config.conf for Network Access

Add a GROBID URL configuration option:

```ini
[GROBID]
# GROBID server URL (use p1 IP for network access)
# For local access: http://localhost:8070
# For network access: http://<p1-ip>:8070
base_url = http://localhost:8070
```

### Update GrobidClient to Use Config

Modify `shared_tools/api/grobid_client.py` to read from config:

```python
# In GrobidClient.__init__
base_url = config.get('GROBID', 'base_url', fallback='http://localhost:8070')
```

## Firewall Considerations

Ensure p1's firewall allows incoming connections on port 8070:

```bash
# On p1 (if using ufw)
sudo ufw allow 8070/tcp

# Or check if port is listening
netstat -tulpn | grep 8070
```

## Testing Network Access

From blacktower, test if GROBID is accessible:

```bash
# Test if port is reachable
curl http://<p1-ip>:8070/api/isalive

# Should return: true
```

## Security Note

GROBID on port 8070 is typically safe for local network access, but consider:
- Restricting access to specific IPs (firewall rules)
- Using SSH tunnel for more security
- Running GROBID on a non-standard port if needed

