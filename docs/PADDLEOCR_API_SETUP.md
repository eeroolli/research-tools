# PaddleOCR API Setup Guide

## Overview

PaddleOCR API provides GPU-accelerated OCR processing via HTTP API. The service runs in a Docker container on p1 and can be accessed from blacktower for processing scanned PDFs.

## Features

- **GPU-accelerated OCR** using PaddleOCR (5-10x faster than CPU)
- **Automatic language detection** from OCR text (EN, NO, SV, FI, DE)
- **Automatic orientation detection** (portrait vs landscape/two-up pages)
- **File renaming** with language prefix (EN_, NO_, etc.) and `_double` suffix for landscape pages
- **HTTP API** accessible from network (blacktower → p1)

## Architecture

```
Epson Document Capture (blacktower)
    ↓ (send raw PDF)
PaddleOCR API Server (p1 Docker, port 8080)
    ↓ (OCR processing with GPU)
    ↓ (detect language & orientation)
    ↓ (rename file: EN_..._double.pdf if landscape)
Save OCR'd PDF to papers/ directory (blacktower)
    ↓ (triggers daemon)
Daemon processes with GROBID (p1)
```

## Setup

### 1. Start PaddleOCR Docker Container

```bash
./scripts/docker_paddleocr_start.sh
```

This will:
- **Use existing container** if `paddleocr-gpu` already exists (no need to recreate)
- Create new container only if it doesn't exist
- Install PaddleOCR and dependencies (if needed, only on first setup)
- Expose port 8080 for API access
- Auto-start the API server as a **persistent background service** (stays running)

**Important**: 
- The API server runs continuously in the background - **no need to start Python for each scan**
- PaddleOCR is initialized once and reused for all requests (efficient GPU memory usage)
- Server handles multiple concurrent requests (threaded mode)
- Perfect for high-frequency scanning - just send PDFs to the API

### 2. Verify API Server

Check if the API server is running:

```bash
# Health check
curl http://localhost:8080/health

# Or from blacktower (replace with p1's IP)
curl http://192.168.178.129:8080/health
```

Expected response:
```json
{
  "status": "healthy",
  "service": "paddleocr-api",
  "gpu_available": true
}
```

### 3. Configure API URL

Edit `config.conf`:

```ini
[PADDLEOCR]
# For local access (on p1):
api_url = http://localhost:8080

# For network access (from blacktower):
api_url = http://192.168.178.129:8080
```

## Usage

### Command Line Client

Process a PDF file (API server must be running):

```bash
# Basic usage (uses config.conf for API URL)
python scripts/paddleocr_client.py input.pdf

# Specify API URL explicitly
python scripts/paddleocr_client.py input.pdf --api-url http://192.168.178.129:8080

# Specify output location
python scripts/paddleocr_client.py input.pdf --output-dir /mnt/i/FraScanner/papers

# Disable automatic renaming
python scripts/paddleocr_client.py input.pdf --no-rename
```

**Note**: The API server runs as a persistent service. You can process many PDFs in rapid succession - each call is handled by the same running server instance. No need to start Python for each scan.

The client will:
1. Send PDF to the persistent API server
2. Receive OCR'd PDF with metadata
3. Automatically rename file with language prefix and `_double` suffix if landscape
4. Save to specified location

### API Endpoints

#### POST /ocr

Process PDF and return OCR'd PDF.

**Request:**
```bash
curl -X POST -F "file=@document.pdf" http://localhost:8080/ocr \
  --output ocr_document.pdf
```

**Response:**
- OCR'd PDF file (binary)

#### POST /ocr_with_metadata

Process PDF and return OCR'd PDF + metadata.

**Request:**
```bash
curl -X POST -F "file=@document.pdf" http://localhost:8080/ocr_with_metadata \
  --output ocr_document.pdf \
  -v
```

**Response:**
- OCR'd PDF file (binary)
- Headers:
  - `X-OCR-Language`: Detected language (en, no, sv, fi, de)
  - `X-OCR-Language-Prefix`: Filename prefix (EN_, NO_, SE_, FI_, DE_)
  - `X-OCR-Is-Two-Up`: true/false
  - `X-OCR-Aspect-Ratio`: Aspect ratio (width/height)

#### GET /health

Health check endpoint.

**Request:**
```bash
curl http://localhost:8080/health
```

**Response:**
```json
{
  "status": "healthy",
  "service": "paddleocr-api",
  "gpu_available": true
}
```

## Integration with Epson Document Capture

### Option 1: Post-Scan Script

1. **Create a post-scan script** that calls the client:

```bash
#!/bin/bash
# post_scan_paddleocr.sh

PDF_FILE="$1"
API_URL="http://192.168.178.129:8080"
OUTPUT_DIR="/mnt/i/FraScanner/papers"

python /path/to/research-tools/scripts/paddleocr_client.py \
  "$PDF_FILE" \
  --api-url "$API_URL" \
  --output-dir "$OUTPUT_DIR"
```

2. **Configure in Epson Document Capture:**
   - Create a new job/button
   - Set post-scan action to run the script
   - Pass PDF file path as argument

### Option 2: Watch Directory

1. **Create a watcher script** that monitors a directory:

```python
#!/usr/bin/env python3
"""Watch directory for new PDFs and send to PaddleOCR API."""

import time
from pathlib import Path
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import subprocess

WATCH_DIR = Path("/mnt/i/FraScanner/papers_raw")
API_URL = "http://192.168.178.129:8080"
OUTPUT_DIR = Path("/mnt/i/FraScanner/papers")

class PDFHandler(FileSystemEventHandler):
    def on_created(self, event):
        if event.src_path.endswith('.pdf'):
            pdf_path = Path(event.src_path)
            print(f"Processing: {pdf_path.name}")
            subprocess.run([
                'python', 'scripts/paddleocr_client.py',
                str(pdf_path),
                '--api-url', API_URL,
                '--output-dir', str(OUTPUT_DIR)
            ])

if __name__ == '__main__':
    event_handler = PDFHandler()
    observer = Observer()
    observer.schedule(event_handler, str(WATCH_DIR), recursive=False)
    observer.start()
    
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()
```

2. **Configure scanner to save to watched directory**

## File Naming Convention

The API automatically detects language and orientation, then renames files:

- **Language prefix**: `EN_`, `NO_`, `SE_`, `FI_`, `DE_`
- **Orientation suffix**: `_double.pdf` for landscape/two-up pages

Examples:
- `scan_001.pdf` (English, portrait) → `EN_scan_001.pdf`
- `scan_002.pdf` (Norwegian, landscape) → `NO_scan_002_double.pdf`
- `scan_003.pdf` (Swedish, portrait) → `SE_scan_003.pdf`

## Configuration Options

Edit `config.conf`:

```ini
[PADDLEOCR]
# API server URL
api_url = http://192.168.178.129:8080

# Languages for OCR
languages = en,no,sv,fi,de

# Language detection settings
lang_detection_threshold = 0.8
lang_detection_min_chars = 100

# Two-up detection
two_up_aspect_ratio = 1.3
```

## Troubleshooting

### API Server Not Starting

Check if server is running:
```bash
docker exec paddleocr-gpu pgrep -f paddleocr_api_server.py
```

Check container logs:
```bash
docker exec paddleocr-gpu cat /tmp/paddleocr_api.log
```

Manually start server (if needed):
```bash
docker exec -d paddleocr-gpu bash -c "cd /workspace && nohup python scripts/paddleocr_api_server.py > /tmp/paddleocr_api.log 2>&1 &"
```

### API Server Stopped

If the API server stops (e.g., after container restart), restart it:
```bash
./scripts/docker_paddleocr_start.sh
```

This will detect if the server is not running and start it automatically.

### High-Frequency Scanning

The API server is designed to handle multiple requests in rapid succession:
- **Persistent service**: Stays running between requests
- **No startup overhead**: PaddleOCR is initialized once and reused
- **Concurrent requests**: Flask handles multiple simultaneous requests
- **GPU efficiency**: GPU memory is reused across requests

For very high-frequency scanning (10+ documents/minute), the server handles it efficiently without restarting.

### Network Access Issues

1. **Check firewall**: Ensure port 8080 is open on p1
2. **Check IP address**: Verify p1's IP with `hostname -I` or `ip addr`
3. **Test connectivity**: From blacktower: `ping <p1-ip>`

### GPU Not Available

Check GPU in container:
```bash
docker exec paddleocr-gpu nvidia-smi
```

If GPU not available, the API will fall back to CPU (much slower).

### Language Detection Fails

- Increase `lang_detection_min_chars` in config
- Check if text is sufficient for detection (needs ~100+ characters)
- Language detection requires `langdetect` library (installed automatically)

## Performance

- **GPU (T1000)**: ~5-7 seconds per page
- **CPU**: ~25-50 seconds per page
- **Speedup**: 5-10x with GPU

## Dependencies

The API server requires:
- PaddleOCR (in Docker container)
- Flask (for HTTP API)
- langdetect (for language detection)
- pdfplumber (for orientation detection)
- PyMuPDF (for PDF manipulation)

All dependencies are installed automatically when starting the Docker container.

## See Also

- `docs/DOCKER_PADDLEOCR_SETUP.md` - Docker container setup
- `scripts/paddleocr_api_server.py` - API server code
- `scripts/paddleocr_client.py` - Client script
- `scripts/paddleocr_rename.py` - File renaming utility

