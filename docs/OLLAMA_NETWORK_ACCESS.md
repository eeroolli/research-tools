# OLLAMA Network Access from blacktower

## Overview

OLLAMA runs in a **Docker container** on **p1** and is accessible via HTTP on port **11434**. The container is configured for network access by default, making it easy to access from **blacktower**, phones, Macs, and any device on your network.

## Current Setup

- **OLLAMA Container**: Runs in Docker on p1 (container name: `ollama-gpu`)
- **Default Port**: 11434
- **Local Access**: `http://localhost:11434` (works on p1)
- **Network Access**: `http://192.168.178.129:11434` (works from blacktower, phone, Mac, and other devices)
- **Web Chat Interface**: Optional Open WebUI on port 3000 (ChatGPT-like interface)
  - **Local**: `http://localhost:3000`
  - **Network**: `http://192.168.178.129:3000` (accessible from phone, Mac, any device)

## Docker Setup on p1

### Step 1: Start OLLAMA Docker Container

The easiest way to set up OLLAMA is using the provided script:

```bash
# On p1
./scripts/docker_ollama_start.sh
```

This script will:
- Create a custom Docker network (`ollama-network`) for container DNS resolution
- Check if the `ollama-gpu` container exists
- Create the container if needed (with GPU support)
- Configure network access automatically (`OLLAMA_HOST=0.0.0.0:11434`)
- Connect container to `ollama-network` for DNS resolution with WebUI
- Start the container and wait for it to be ready

### Step 2: Verify Container is Running

```bash
# On p1 - Check container status
docker ps | grep ollama-gpu

# Test OLLAMA API
curl http://localhost:11434/api/tags
```

### Step 3: Configure Firewall (if needed)

Ensure p1's firewall allows incoming connections on port 11434:

```bash
# On p1 (if using ufw)
sudo ufw allow 11434/tcp

# Or restrict to local network only
sudo ufw allow from 192.168.178.0/24 to any port 11434
```

## Web Chat Interface (Open WebUI)

For easy access from **phone, Mac, and any device**, you can set up Open WebUI - a ChatGPT-like web interface:

### Setup Open WebUI

```bash
# On p1 - Start the web interface
./scripts/docker_ollama_webui_start.sh
```

This will:
- Create a custom Docker network (`ollama-network`) if it doesn't exist
- Create and start the `ollama-webui` container
- Connect to `ollama-network` for DNS resolution
- Connect to your OLLAMA container automatically via Docker network (`ollama-gpu:11434`)
- Expose the web interface on port 3000
- No authentication required (can be enabled if needed)

### Accessing the Web Interface

Once started, access the web interface from:
- **Phone**: Open browser and go to `http://192.168.178.129:3000`
- **Mac**: Open Safari/Chrome and go to `http://192.168.178.129:3000`
- **Any device**: Works on any device with a web browser
- **Local (p1)**: `http://localhost:3000`

**Note**: Replace `192.168.178.129` with your actual p1 IP address if different.

**Features:**
- ChatGPT-like interface
- Chat history
- Model selection
- Works on mobile, tablet, desktop
- No installation needed on client devices

## Accessing from blacktower

### Option 1: Use p1's IP Address (Recommended)

1. **Find p1's IP address:**
   ```bash
   # On p1
   hostname -I
   # Or
   ip addr show | grep "inet " | grep -v 127.0.0.1
   ```

2. **Test connection from blacktower:**
   ```bash
   # On blacktower - Test if OLLAMA is accessible
   curl http://192.168.178.129:11434/api/tags
   
   # Should return list of available models
   ```

3. **Update config.conf on blacktower:**
   ```ini
   [OLLAMA]
   base_url = http://192.168.178.129:11434
   ```

### Option 2: Use p1's Hostname

If both machines are on the same network and can resolve hostnames:

```ini
[OLLAMA]
base_url = http://p1:11434
```

### Option 3: SSH Tunnel (Secure but Slower)

Create an SSH tunnel from blacktower to p1:

```bash
# On blacktower
ssh -L 11434:localhost:11434 user@p1
```

Then use `http://localhost:11434` on blacktower (tunneled through SSH).

## Configuration for Daemon

### Update config.conf for Network Access

The daemon automatically reads OLLAMA configuration from `config.conf`:

```ini
[OLLAMA]
# Ollama server configuration (Docker container)
# Docker container name for OLLAMA
container_name = ollama-gpu
# Automatically start Ollama Docker container if not running
auto_start = true
# Stop Ollama container when daemon shuts down (if we started it)
auto_stop = true
# Seconds to wait for Ollama to start
startup_timeout = 30
# Seconds to wait for Ollama to stop gracefully
shutdown_timeout = 10
# Ollama server port (default is 11434)
port = 11434
# Ollama server URL (use p1 IP for network access from blacktower)
# For local access: http://localhost:11434
# For network access: http://<p1-ip>:11434
base_url = http://localhost:11434

[OLLAMA_WEBUI]
# Open WebUI web chat interface configuration (optional)
# Enable web chat interface for easy access from phone, Mac, and other devices
enabled = false
# Docker container name for Open WebUI
container_name = ollama-webui
# WebUI server port (default is 3000)
port = 3000
```

### OllamaClient Uses HTTP API

The `OllamaClient` now uses the HTTP API instead of CLI commands, which means:
- ✅ Works with Docker containers (local or remote)
- ✅ Supports network access automatically
- ✅ Reads `base_url` from config
- ✅ No need for `ollama` CLI to be installed on client machines

## Testing Network Access

From blacktower, test if OLLAMA is accessible:

```bash
# Test if port is reachable
curl http://<p1-ip>:11434/api/tags

# Test with a simple request
curl http://<p1-ip>:11434/api/generate \
  -d '{"model": "llama2:7b", "prompt": "Hello", "stream": false}'
```

## Using OLLAMA from blacktower

### Via HTTP API (Recommended)

The daemon and scripts automatically use the HTTP API when `base_url` is configured:

```python
# In your Python code
from shared_tools.ai.ollama_client import OllamaClient

# Client automatically reads base_url from config.conf
client = OllamaClient()
metadata = client.extract_paper_metadata(text)
```

### Via Command Line (if ollama CLI is installed)

```bash
# On blacktower - Set environment variable
export OLLAMA_HOST=http://192.168.178.129:11434

# Then use ollama CLI
ollama list  # List models on p1
ollama run llama2:7b "Hello"  # Run model on p1
```

## Container Management

### Start/Stop Containers

```bash
# On p1 - Start OLLAMA container
docker start ollama-gpu
# Or use the script
./scripts/docker_ollama_start.sh

# On p1 - Stop OLLAMA container
docker stop ollama-gpu

# On p1 - Start WebUI container
./scripts/docker_ollama_webui_start.sh

# On p1 - Stop WebUI container
docker stop ollama-webui
```

### View Logs

```bash
# View OLLAMA container logs
docker logs ollama-gpu

# View WebUI container logs
docker logs ollama-webui

# Follow logs in real-time
docker logs -f ollama-gpu
```

### Pull Models

Models need to be downloaded inside the container:

```bash
# Pull models in the container
docker exec ollama-gpu ollama pull llama2:7b
docker exec ollama-gpu ollama pull mistral:7b
docker exec ollama-gpu ollama pull codellama:7b
```

Or if you have `ollama` CLI installed on the host and OLLAMA is accessible:

```bash
# From host (if OLLAMA_HOST is set)
export OLLAMA_HOST=http://localhost:11434
ollama pull llama2:7b
```

## Security Note

OLLAMA on port 11434 is typically safe for local network access, but consider:
- **No authentication by default** - OLLAMA is open to anyone on the network
- Restricting access to specific IPs (firewall rules)
- Using SSH tunnel for more security
- Running OLLAMA on a non-standard port if needed
- Consider VPN for remote access
- WebUI can be configured with authentication if needed

## Troubleshooting

### Container Won't Start

```bash
# On p1 - Check Docker status
docker ps -a | grep ollama-gpu

# Check container logs
docker logs ollama-gpu

# Check if port is in use
netstat -tulpn | grep 11434
```

### Connection Refused from blacktower

```bash
# On p1 - Verify container is running
docker ps | grep ollama-gpu

# On p1 - Check if OLLAMA is listening on network
docker exec ollama-gpu netstat -tulpn | grep 11434
# Should show 0.0.0.0:11434

# On blacktower - Test connection
curl http://<p1-ip>:11434/api/tags
```

### Firewall Blocking

```bash
# On p1 - Check firewall status
sudo ufw status

# Allow OLLAMA port
sudo ufw allow 11434/tcp

# Allow WebUI port (if using)
sudo ufw allow 3000/tcp
```

### Models Not Found

Models must be downloaded in the container:

```bash
# On p1 - Pull models in container
docker exec ollama-gpu ollama pull llama2:7b
docker exec ollama-gpu ollama pull mistral:7b
```

### GPU Not Working

```bash
# On p1 - Check GPU access in container
docker exec ollama-gpu nvidia-smi

# Verify NVIDIA runtime
docker info | grep nvidia
```

## Access from Different Devices

### Phone (iOS/Android)
1. Connect to the same Wi-Fi network as p1
2. Open browser
3. Go to `http://<p1-ip>:3000` (if WebUI is running)
4. Start chatting!

### Mac
1. Connect to the same network as p1
2. Open Safari/Chrome
3. Go to `http://<p1-ip>:3000` (if WebUI is running)
4. Or use Ollama Desktop app and configure it to connect to `http://<p1-ip>:11434`

### Windows
1. Connect to the same network as p1
2. Open browser
3. Go to `http://<p1-ip>:3000` (if WebUI is running)

## Migrating from Native OLLAMA to Docker

If you previously installed OLLAMA natively and want to migrate to Docker:

### Step 1: Stop Native OLLAMA Service

Use the provided script to stop and disable the native service:

```bash
./scripts/stop_native_ollama.sh
```

This will:
- Stop the `ollama.service` systemd service
- Disable it from auto-starting
- Verify no OLLAMA processes are running

### Step 2: Verify Docker OLLAMA is Working

```bash
# Check Docker container is running
docker ps | grep ollama-gpu

# Test API
curl http://localhost:11434/api/tags

# Test WebUI (if enabled)
curl http://localhost:3000
```

### Step 3: Remove Native Installation

Once you've verified Docker OLLAMA is working correctly, use the provided script to remove the native installation:

```bash
./scripts/remove_native_ollama.sh
```

This script will:
- Verify Docker OLLAMA is working before proceeding
- Remove the systemd service file (`/etc/systemd/system/ollama.service`)
- Remove the OLLAMA binary (`/usr/local/bin/ollama`)
- Remove native models directory (`/usr/share/ollama`) - frees up ~7GB
- Reload systemd daemon
- Verify no native processes are running

**Note**: Native models are separate from Docker models. If you want to use the same models in Docker, you'll need to pull them again in the Docker container (they'll be stored in the Docker volume `ollama-models`).

## Summary

With Docker setup:
- ✅ OLLAMA runs in a container with GPU support
- ✅ Network access configured automatically
- ✅ Easy access from any device on your network
- ✅ Web chat interface available (optional)
- ✅ Daemon manages containers automatically
- ✅ HTTP API works for remote access
- ✅ Models persist in Docker volume
- ✅ Custom Docker network for container DNS resolution
- ✅ WebUI connects to OLLAMA via Docker network

## Current Status

**OLLAMA is fully dockerized** - The native installation has been removed and OLLAMA runs exclusively in Docker containers:
- `ollama-gpu`: Main OLLAMA container with GPU support
- `ollama-webui`: Optional web chat interface
- Both containers connected via `ollama-network` for DNS resolution
