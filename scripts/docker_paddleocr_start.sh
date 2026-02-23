#!/bin/bash
# Start PaddleOCR Docker container with GPU support

set -e

CONTAINER_NAME="paddleocr-gpu"
# Use official PaddlePaddle base image with CUDA 12.6 (compatible with CUDA 12.8 driver)
# This is the official recommended approach per PaddleOCR docs
# Note: PaddleOCR must be installed inside container (standard procedure)
IMAGE_NAME="paddlepaddle/paddle:3.2.2-gpu-cuda12.6-cudnn9.5"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting PaddleOCR Docker container..."
echo "   Container name: $CONTAINER_NAME"
echo "   Image: $IMAGE_NAME"
echo "   Project root: $PROJECT_ROOT"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    echo "   Install Docker Desktop and enable WSL2 integration"
    echo "   See: docs/DOCKER_PADDLEOCR_SETUP.md"
    exit 1
fi

# Check if NVIDIA runtime is available
if ! docker info 2>/dev/null | grep -q "nvidia"; then
    echo "⚠️  Warning: NVIDIA runtime not detected"
    echo "   GPU support may not work. Install NVIDIA Container Toolkit"
    echo "   See: docs/DOCKER_PADDLEOCR_SETUP.md"
fi

# Check if container exists (similar to GROBID container management)
if docker ps -a --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
    echo "📦 Container $CONTAINER_NAME exists"
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
        echo "✅ Container is already running"
    else
        echo "🔄 Starting existing container..."
        docker start "$CONTAINER_NAME"
        echo "✅ Container started"
    fi
else
    echo "🆕 Creating new container..."
    
    # Check if image exists
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "paddlepaddle/paddle.*3.2.2-gpu-cuda12.6"; then
        echo "📥 Pulling Docker image (this may take a few minutes)..."
        echo "   Image: $IMAGE_NAME"
        if ! docker pull "$IMAGE_NAME"; then
            echo "⚠️  Failed to pull $IMAGE_NAME"
            echo "   Trying alternative: paddlepaddle/paddle:3.2.2-gpu-cuda11.8-cudnn8.9"
            IMAGE_NAME="paddlepaddle/paddle:3.2.2-gpu-cuda11.8-cudnn8.9"
            docker pull "$IMAGE_NAME"
        fi
    fi
    
    # Create container (similar pattern to GROBID, but with GPU support)
    # Mount project directory from Linux filesystem (follows Docker WSL best practices)
    # Limit memory to prevent excessive usage (12GB limit, 8GB soft limit)
    # Expose port 8080 for API server (accessible from network)
    docker run -d \
      --name "$CONTAINER_NAME" \
      --gpus all \
      -v "$PROJECT_ROOT":/workspace \
      -w /workspace \
      --shm-size=8g \
      --memory=12g \
      --memory-swap=12g \
      -p 8080:8080 \
      -it \
      "$IMAGE_NAME" \
      /bin/bash
    
    echo "✅ Container created and started"
    
    # Fix permissions on mounted directories (Docker runs as root, but host user needs access)
    echo "🔧 Fixing permissions on mounted directories..."
    HOST_UID=$(id -u)
    HOST_GID=$(id -g)
    docker exec "$CONTAINER_NAME" bash -c "chown -R $HOST_UID:$HOST_GID /workspace/test_results 2>/dev/null || true"
    
    # Install dependencies (standard procedure per PaddleOCR docs)
    echo "📦 Installing system dependencies (OpenCV, PDF tools)..."
    docker exec "$CONTAINER_NAME" bash -c "apt-get update -qq && apt-get install -y -qq libgl1-mesa-glx libglib2.0-0 poppler-utils > /dev/null 2>&1 || true"
    
    echo "📦 Installing PaddleOCR and dependencies..."
    docker exec "$CONTAINER_NAME" bash -c "pip install paddleocr pdf2image pdfplumber pillow flask langdetect PyMuPDF > /dev/null 2>&1 || echo 'Installing...'"
    
    echo "📦 Installing API server dependencies..."
    docker exec "$CONTAINER_NAME" bash -c "pip install flask werkzeug > /dev/null 2>&1 || echo 'Installing Flask...'"
fi

# Start API server if not already running (persistent background service)
echo "🔍 Checking API server status..."
if ! docker exec "$CONTAINER_NAME" bash -c "pgrep -f paddleocr_api_server.py > /dev/null 2>&1"; then
    echo "🚀 Starting PaddleOCR API server (persistent service)..."
    # Use nohup to ensure it stays running even if terminal disconnects
    # Run in background with proper logging
    docker exec -d "$CONTAINER_NAME" bash -c "cd /workspace && nohup python scripts/paddleocr_api_server.py > /tmp/paddleocr_api.log 2>&1 &"
    sleep 3
    if docker exec "$CONTAINER_NAME" bash -c "pgrep -f paddleocr_api_server.py > /dev/null 2>&1"; then
        echo "✅ API server started on port 8080 (running as persistent service)"
    else
        echo "⚠️  API server may not have started. Check logs: docker exec $CONTAINER_NAME cat /tmp/paddleocr_api.log"
    fi
else
    echo "✅ API server is already running (persistent service)"
fi

echo ""
echo "✅ Container ready!"
echo ""
echo "API server:"
echo "   URL: http://localhost:8080 (or http://<p1-ip>:8080 from blacktower)"
echo "   Health check: curl http://localhost:8080/health"
echo ""
echo "To enter the container:"
echo "   docker exec -it $CONTAINER_NAME bash"
echo ""
echo "To view API server logs:"
echo "   docker exec $CONTAINER_NAME cat /tmp/paddleocr_api.log"
echo ""

