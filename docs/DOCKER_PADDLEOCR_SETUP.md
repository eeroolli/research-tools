# Docker Setup for PaddleOCR with CUDA 12 Support

This guide helps you set up PaddleOCR in a Docker container with CUDA 12 support for your NVIDIA T1000 GPU.

## Quick Start

**If Docker Desktop is already installed on Windows (like GROBID):**

1. **Enable WSL2 Integration** (one-time setup):
   - Open Docker Desktop on Windows
   - Settings → Resources → WSL Integration
   - Enable your WSL2 distro → Apply & Restart

2. **Verify setup:**
   ```bash
   ./scripts/check_docker_setup.sh
   ```

3. **Start PaddleOCR container:**
   ```bash
   ./scripts/docker_paddleocr_start.sh
   ```

4. **Run tests:**
   ```bash
   ./scripts/docker_paddleocr_test.sh
   ```

**Note:** PaddleOCR container can run alongside your existing GROBID container. Both use Docker Desktop on Windows with WSL2 integration.

---

## Prerequisites

### 1. Install Docker Desktop and Enable WSL2 Integration

**If Docker Desktop is already installed on Windows:**

1. **Open Docker Desktop** (from Windows Start menu)
2. **Enable WSL2 Integration:**
   - Click the ⚙️ Settings icon (gear) in Docker Desktop
   - Go to **"Resources"** → **"WSL Integration"**
   - Find your WSL2 distro (e.g., "Ubuntu" or your distro name)
   - **Enable** the toggle for your WSL2 distro
   - Click **"Apply & Restart"**
   - Wait for Docker Desktop to restart

3. **Verify from WSL2:**
   ```bash
   # In WSL2 terminal
   docker --version
   docker ps
   ```

**If Docker Desktop is NOT installed:**

1. Download and install [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/)
2. During installation, ensure "Use WSL 2 instead of Hyper-V" is selected
3. After installation, follow steps 2-3 above to enable WSL2 integration

**Note:** With Docker Desktop on Windows, GPU support works through WSL2's GPU passthrough (no need for NVIDIA Container Toolkit in WSL2).

**Option B: Docker Engine in WSL2 (Alternative - not recommended if Docker Desktop is available)**

```bash
# Install Docker in WSL2
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# Log out and back in for group changes to take effect
```

### 2. GPU Support (Windows Docker Desktop + WSL2)

**For Windows Docker Desktop with WSL2:**

GPU support works automatically through WSL2's GPU passthrough. No additional setup needed in WSL2!

**Verify GPU access:**
```bash
# In WSL2 terminal
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
```

If this works, you're all set! If it fails, check:
1. NVIDIA drivers are installed on Windows
2. WSL2 can see GPU: `nvidia-smi` (should work in WSL2)
3. Docker Desktop is running on Windows

**Note:** If you're using Docker Engine directly in WSL2 (not Docker Desktop), then you would need NVIDIA Container Toolkit. But with Docker Desktop, it's handled automatically.

## PaddleOCR Docker Setup

### Step 1: Pull PaddlePaddle Docker Image

**For CUDA 12.x (Recommended for T1000 with CUDA 12.8):**
```bash
# Official PaddlePaddle image with CUDA 12.6 (compatible with CUDA 12.8 driver)
docker pull paddlepaddle/paddle:3.2.2-gpu-cuda12.6-cudnn9.5

# Or other CUDA 12 options:
# docker pull paddlepaddle/paddle:3.2.2-gpu-cuda12.9-cudnn9.9
# docker pull paddlepaddle/paddle:3.2.1-gpu-cuda12.6-cudnn9.5
```

**Alternative (if CUDA 12 not available, use CUDA 11.8):**
```bash
docker pull paddlepaddle/paddle:3.2.2-gpu-cuda11.8-cudnn8.9
```

### Step 2: Create Docker Container

```bash
# Navigate to your project directory
cd ~/projects/research-tools

    # Create and run container with GPU support
    # Mount project directory and Windows C: drive (read-only) for accessing test files
    docker run -d \
      --name paddleocr-gpu \
      --gpus all \
      -v $(pwd):/workspace \
      -v /mnt/c:/mnt/c:ro \
      -w /workspace \
      --shm-size=8g \
      --network=host \
      -it \
      paddlepaddle/paddle:3.2.2-gpu-cuda12.6-cudnn9.5 \
      /bin/bash

# Or use the helper script (see below)
```

### Step 3: Install PaddleOCR in Container

```bash
# Enter the container
docker exec -it paddleocr-gpu bash

# Inside container, install PaddleOCR
pip install paddleocr

# Verify installation
python -c "from paddleocr import PaddleOCR; print('PaddleOCR installed successfully')"
python -c "import paddle; print('CUDA:', paddle.device.is_compiled_with_cuda()); print('CUDA version:', paddle.version.cuda() if paddle.device.is_compiled_with_cuda() else 'N/A')"
```

### Step 4: Test PaddleOCR

```bash
# Inside container
python -c "from paddleocr import PaddleOCR; ocr = PaddleOCR(use_angle_cls=True, lang='en'); print('PaddleOCR initialized successfully')"
```

## Helper Scripts

### Start Container Script

Create `scripts/docker_paddleocr_start.sh`:

```bash
#!/bin/bash
# Start PaddleOCR Docker container

CONTAINER_NAME="paddleocr-gpu"
IMAGE_NAME="paddlepaddle/paddle:latest-gpu-cuda12.0-cudnn8"

# Check if container exists
if docker ps -a | grep -q $CONTAINER_NAME; then
    echo "Container $CONTAINER_NAME exists"
    if docker ps | grep -q $CONTAINER_NAME; then
        echo "Container is already running"
    else
        echo "Starting existing container..."
        docker start $CONTAINER_NAME
    fi
else
    echo "Creating new container..."
    docker run -d \
      --name $CONTAINER_NAME \
      --gpus all \
      -v $(pwd):/workspace \
      -w /workspace \
      --shm-size=8g \
      --network=host \
      -it \
      $IMAGE_NAME \
      /bin/bash
fi

echo "Container ready. Enter with: docker exec -it $CONTAINER_NAME bash"
```

### Run Tests in Container Script

Create `scripts/docker_paddleocr_test.sh`:

```bash
#!/bin/bash
# Run OCR tests inside PaddleOCR Docker container

CONTAINER_NAME="paddleocr-gpu"

# Check if container is running
if ! docker ps | grep -q $CONTAINER_NAME; then
    echo "Error: Container $CONTAINER_NAME is not running"
    echo "Start it with: ./scripts/docker_paddleocr_start.sh"
    exit 1
fi

# Run test script inside container
docker exec -it $CONTAINER_NAME bash -c "
    cd /workspace && \
    python scripts/test_ocr_empirical.py \
        --test-dir /mnt/c/temp/test \
        --engines paddleocr \
        --languages en,no,sv,de \
        --output-dir test_results_docker_\$(date +%Y%m%d_%H%M%S)
"
```

## Usage

### Daily Workflow

1. **Start container:**
   ```bash
   ./scripts/docker_paddleocr_start.sh
   ```

2. **Enter container:**
   ```bash
   docker exec -it paddleocr-gpu bash
   ```

3. **Run tests:**
   ```bash
   # Inside container
   cd /workspace
   python scripts/test_ocr_empirical.py --engines paddleocr --test-dir /path/to/test
   ```

4. **Or use helper script:**
   ```bash
   ./scripts/docker_paddleocr_test.sh
   ```

### Stop Container

```bash
docker stop paddleocr-gpu
```

### Remove Container (if needed)

```bash
docker stop paddleocr-gpu
docker rm paddleocr-gpu
```

## Troubleshooting

### GPU Not Detected

```bash
# Test GPU access
docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi

# If this fails, check NVIDIA Container Toolkit installation
```

### Container Can't Access Host Files

- Ensure volume mount is correct: `-v $(pwd):/workspace`
- Check file permissions (WSL2 file permissions can be tricky)

### CUDA Version Mismatch

- Verify driver supports CUDA 12: `nvidia-smi`
- Use matching Docker image version
- Check PaddlePaddle CUDA version inside container: `python -c "import paddle; print(paddle.version.cuda())"`

## Integration with GROBID

Since GROBID is already running in Docker, PaddleOCR container follows the same pattern:

- **Same Docker setup** - Both use Docker Desktop on Windows with WSL2 integration
- **Independent containers** - Can run simultaneously without conflicts
- **Similar management** - Both use `docker start/stop` commands
- **Shared volumes** - Both can access the same project directory

**Container Management:**
```bash
# Check both containers
docker ps

# Start both (if stopped)
docker start grobid
docker start paddleocr-gpu

# Stop both
docker stop grobid
docker stop paddleocr-gpu
```

## Benefits

✅ **Proper CUDA 12 support** - No version mismatches  
✅ **Isolated environment** - Won't conflict with other projects  
✅ **Reproducible** - Same environment every time  
✅ **Easy to share** - Others can use same container  
✅ **Clean uninstall** - Just remove container  
✅ **Consistent with GROBID** - Same Docker management pattern

## Next Steps

1. Install Docker Desktop and enable WSL2 integration
2. Install NVIDIA Container Toolkit
3. Pull PaddlePaddle Docker image
4. Create and start container
5. Install PaddleOCR inside container
6. Run tests!

