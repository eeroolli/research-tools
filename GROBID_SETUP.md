# GROBID Integration Guide

## Overview

The research-tools system uses **GROBID** (GeneRation Of BIbliographic Data) for advanced academic paper metadata extraction. GROBID is a machine learning-based system specifically designed for extracting structured data from academic PDFs.

## Features

### ✅ **Smart Author Extraction**
- Processes only the first 2 pages of PDFs (configurable)
- Prevents extraction of authors from references/citations
- Extracts only the main document authors

### ✅ **Document Type Detection**
Automatically identifies:
- **Journal Articles** - Based on GROBID XML structure analysis
- **Books** - Monographs and book chapters
- **Conference Papers** - Meeting/conference proceedings
- **Theses** - PhD and master's dissertations
- **Reports** - Technical reports and working papers
- **Preprints** - ArXiv preprints and working papers
- **News Articles** - Editorials, opinions, commentaries

### ✅ **Enhanced Metadata Extraction**
- **Basic Info**: Title, authors, year, abstract, DOI
- **Publication Details**: Journal, conference, publisher, volume, issue, pages
- **Content Info**: Keywords, language, subjects
- **Technical Info**: Document type, extraction method, processing notes

## Configuration

### Automatic Setup
The daemon automatically manages GROBID:
- **Auto-start**: Starts Docker container when daemon launches (local GROBID only)
- **Auto-stop**: Stops container when daemon shuts down (configurable, local GROBID only)
- **Health checks**: Monitors GROBID availability (local and remote)
- **Remote support**: Can connect to GROBID running on another machine
- **Fallback**: Uses Ollama 7B if GROBID is unavailable

### Configuration Options
Edit `config.conf` to customize GROBID behavior:

```ini
[GROBID]
# GROBID server host (localhost or remote hostname/IP)
# For local GROBID: host = localhost
# For remote GROBID: host = p1
# For remote GROBID: host = 192.168.1.100
host = localhost
# GROBID server port (default is 8070)
port = 8070
# Automatically start GROBID Docker container if not running (only if host=localhost)
auto_start = true
# Stop GROBID container when daemon shuts down (if we started it, only if host=localhost)
auto_stop = true
# Docker container name for GROBID
container_name = grobid
# Maximum pages to process for metadata extraction (prevents extracting authors from references)
max_pages = 2
```

## Installation

### Prerequisites
- **Docker** - Required for GROBID container
- **WSL2** - For running the daemon
- **Python 3.11** - With research-tools conda environment

### Automatic Installation
GROBID is automatically installed and configured when you run the paper processor daemon:

```bash
# Start the daemon (GROBID will be set up automatically)
python scripts/paper_processor_daemon.py
```

The daemon will:
1. Check if GROBID container exists
2. Start existing container or create new one
3. Wait for GROBID to be ready (up to 60 seconds)
4. Begin processing papers

## Usage

### Basic Usage
```bash
# Start the paper processor daemon
python scripts/paper_processor_daemon.py

# The daemon will automatically:
# 1. Start GROBID container
# 2. Wait for GROBID to be ready
# 3. Process any existing PDFs in the scanner directory
# 4. Watch for new PDFs and process them interactively
```

### Processing Workflow
1. **PDF Detection** - Daemon detects new PDF in scanner directory
2. **GROBID Processing** - Extracts metadata from first 2 pages
3. **User Review** - Interactive menu for reviewing/editing metadata
4. **Zotero Integration** - Search local database and attach PDFs
5. **File Management** - Copy to publications directory with smart naming

## Troubleshooting

### Common Issues

#### GROBID Container Won't Start
```bash
# Check Docker status
docker ps -a

# Check GROBID container logs
docker logs grobid

# Manually start container
docker start grobid
```

#### Port 8070 Already in Use
```bash
# Check what's using port 8070
netstat -tulpn | grep 8070

# Kill the process or change port in config.conf
```

#### GROBID Not Responding
```bash
# Check container health
docker exec grobid curl http://localhost:8070/api/isalive

# Restart container
docker restart grobid
```

### Debug Mode
Enable debug logging to see detailed GROBID processing:

```bash
python scripts/paper_processor_daemon.py --debug
```

### Manual GROBID Testing
Test GROBID directly:

```bash
# Test GROBID client
python shared_tools/api/grobid_client.py /path/to/paper.pdf
```

## Performance

### Processing Speed
- **GROBID**: ~2-5 seconds per paper (first 2 pages only)
- **Ollama Fallback**: ~30-60 seconds per paper (full document)
- **Startup Time**: ~30-60 seconds (container startup)

### Resource Usage
- **Memory**: ~2-4GB for GROBID container
- **CPU**: Moderate during processing
- **Disk**: ~1GB for container image

## Advanced Configuration

### Custom Page Limits
Change the number of pages processed:

```ini
[GROBID]
# Process first 3 pages instead of 2
max_pages = 3
```

### Disable Auto-start
If you prefer to manage GROBID manually:

```ini
[GROBID]
auto_start = false
auto_stop = false
```

### Custom Container Name
Use a different container name:

```ini
[GROBID]
container_name = my-grobid
```

### Remote GROBID Configuration
Use GROBID running on another machine (e.g., for distributed processing):

```ini
[GROBID]
# Connect to GROBID on remote machine
host = p1
# Or use IP address
# host = 192.168.1.100
port = 8070
# Docker management is skipped for remote GROBID
auto_start = false
auto_stop = false
```

**Prerequisites for Remote GROBID:**
- GROBID must be running and accessible on the remote machine
- Network connectivity between machines
- GROBID port (8070) must be accessible (check firewall settings)
- Remote GROBID should be started manually or via system service

**Testing Remote GROBID:**
```bash
# Test connectivity from daemon machine
curl http://p1:8070/api/isalive

# Should return: true
```

**Distributed Processing Setup:**
- **Machine 1 (P1)**: Runs GROBID Docker container, accessible via network
- **Machine 2 (blacktower)**: Runs daemon, connects to remote GROBID
- Both machines can access shared storage (F: drive) for PDFs
- Only one daemon should run at a time (daemon locking prevents conflicts)

## Integration with Other Tools

### Zotero Integration
GROBID metadata integrates seamlessly with Zotero:
- **Field Mapping** - Automatic mapping to Zotero fields
- **Tag Management** - Smart tag extraction and management
- **Duplicate Detection** - Enhanced matching with GROBID metadata

### Fallback Processing
When GROBID is unavailable, the system falls back to:
1. **Ollama 7B** - AI-powered extraction
2. **Manual Entry** - Guided user input
3. **Online APIs** - CrossRef, arXiv, etc.

## Support

For issues with GROBID integration:
1. Check the troubleshooting section above
2. Review daemon logs for error messages
3. Test GROBID manually using the test command
4. Check Docker and port availability

## References

- [GROBID Documentation](https://grobid.readthedocs.io/)
- [GROBID GitHub](https://github.com/kermitt2/grobid)
- [Docker GROBID Image](https://hub.docker.com/r/lfoppiano/grobid)
