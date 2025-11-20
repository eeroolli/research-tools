# Laptop Setup Plan - NVIDIA T1000 4GB GPU

## Overview

Planning for a new laptop with NVIDIA T1000 4GB GPU to run AI workloads and potentially Cursor. The laptop will be left on for extended periods. Key decisions needed:

1. Ubuntu vs Windows WSL for the laptop
2. How to modify the daemon script to use the other computer
3. Benefits of running Cursor on laptop but accessing from Windows tower

---

## 1. Operating System Choice: Ubuntu vs Windows WSL

### Recommendation: **Ubuntu (Native Linux)**

#### Advantages of Ubuntu:
- **Better NVIDIA GPU Support**: CUDA drivers and libraries are more straightforward on native Linux
- **Ollama GPU Acceleration**: Ollama works better with NVIDIA GPUs on Linux
- **Docker Performance**: GROBID runs in Docker; native Linux typically performs better
- **Lower Overhead**: No WSL virtualization layer
- **Long-Running Stability**: Better for leaving laptop on for extended periods

#### When WSL Makes Sense:
- If you need Windows-specific software
- If you prefer Windows for daily use

---

## 2. Modifying Daemon Script to Use Other Computer

### Difficulty: **Medium** (Moderate changes required)

### Current Architecture:
- Daemon runs locally, connects to `localhost:11434` for Ollama
- GROBID runs in Docker locally
- Watches a local directory (`/mnt/i/FraScanner/papers/`)

### Required Changes:

1. **Network Configuration**: Make Ollama accessible over network
   - Already documented in `docs/ollama-network-sharing.md`
   - Set `OLLAMA_HOST=0.0.0.0:11434` on laptop

2. **Configuration Updates**: Add remote host settings to `config.conf`
   ```ini
   [OLLAMA]
   # Remote Ollama server (if using laptop)
   host = 192.168.x.x  # laptop IP address
   port = 11434
   ```

3. **Path Handling**: Ensure daemon can access files on remote machine
   - Shared network drive, or
   - File sync mechanism

4. **GROBID**: Can run on either machine (CPU-bound, less benefit from GPU)

### Approach Options:

#### Option A: Run Daemon on Tower, Use Laptop for Ollama Only
- **Daemon stays on tower** (accesses scanner directory directly)
- **Ollama runs on laptop** with GPU acceleration
- **Configure daemon** to connect to `laptop-ip:11434`
- **Pros**: Minimal changes, keeps file watching local
- **Cons**: Network dependency for AI processing

#### Option B: Run Full Daemon on Laptop
- **Move daemon to laptop**
- **Share scanner directory** via network mount
- **All processing on laptop**
- **Pros**: Centralized processing, full GPU utilization
- **Cons**: More complex setup, network file access

### Recommended Approach: **Option A**
- Keep daemon on tower (simpler file access)
- Offload only Ollama to laptop (GPU acceleration)
- Minimal code changes needed

---

## 3. Running Cursor on Laptop, Accessing from Windows Tower

### Benefits:
- **GPU Acceleration**: Cursor can use NVIDIA GPU for AI features
- **Offloads CPU/GPU Load**: Frees up tower resources
- **Better Performance**: For AI-assisted coding tasks

### Considerations:
- **Remote Access Setup**: SSH, VS Code Remote, or similar
- **Network Latency**: May affect responsiveness
- **File Sync**: Ensure code stays in sync between machines
- **Complexity**: More moving parts to manage

### Alternative Approach:
Run Cursor locally on tower, use laptop only for heavy AI workloads (Ollama, model inference).

---

## Recommended Setup Plan

### Phase 1: Initial Setup
1. **Install Ubuntu** on laptop (primary OS for AI work)
2. **Install NVIDIA drivers** and CUDA toolkit
3. **Install Ollama** with GPU support
4. **Configure Ollama** for network access (`OLLAMA_HOST=0.0.0.0:11434`)

### Phase 2: Daemon Integration
1. **Keep daemon on tower** (accesses scanner directory)
2. **Run Ollama on laptop** with GPU acceleration
3. **Configure daemon** to connect to laptop's Ollama instance
4. **Test network connectivity** and fallback mechanisms

### Phase 3: Cursor (Optional)
1. **Start with Cursor locally** on tower
2. **Consider remote setup later** if needed
3. **Use laptop primarily** for AI workloads (Ollama)

---

## Implementation Details

### Configuration Changes Needed

#### In `config.conf`:
```ini
[OLLAMA]
# Remote Ollama server configuration
host = 192.168.x.x  # laptop IP address (or localhost if local)
port = 11434
auto_start = false  # Don't start Ollama on tower if using laptop
```

#### In `shared_tools/ai/ollama_client.py`:
- Modify to accept host parameter instead of hardcoded `localhost`
- Update connection logic to use configured host

#### In `scripts/paper_processor_daemon.py`:
- Update `is_ollama_running()` to check remote host
- Update `_start_ollama_background()` to skip if using remote
- Add configuration for remote Ollama host

### Network Requirements
- Both machines on same local network
- Firewall rules to allow port 11434 (Ollama)
- Static IP or reliable hostname for laptop

### Security Considerations
- Restrict Ollama access to local network only
- Consider authentication if exposing to broader network
- Use firewall rules to limit access

---

## Testing Checklist

- [ ] Ollama runs on laptop with GPU acceleration
- [ ] Ollama accessible from tower via network
- [ ] Daemon can connect to remote Ollama
- [ ] Fallback mechanisms work if laptop unavailable
- [ ] File watching still works on tower
- [ ] GROBID continues to work (can stay on tower)
- [ ] Network latency acceptable for AI processing

---

## Related Documentation

- `docs/ollama-network-sharing.md` - Network sharing guide for Ollama
- `config.conf` - Main configuration file
- `scripts/paper_processor_daemon.py` - Main daemon script
- `shared_tools/ai/ollama_client.py` - Ollama client implementation

---

## Next Steps

1. **Decide on approach** (Option A recommended)
2. **Set up Ubuntu laptop** with NVIDIA drivers
3. **Install and configure Ollama** on laptop
4. **Modify daemon configuration** for remote Ollama
5. **Test end-to-end** workflow
6. **Consider Cursor remote setup** if needed later

---

*Document created: Based on discussion about new laptop setup with NVIDIA T1000 4GB GPU*

