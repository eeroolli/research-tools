#!/bin/bash
# Start OLLAMA Docker container with GPU support

set -e

CONTAINER_NAME="ollama-gpu"
# Use official Ollama image
IMAGE_NAME="ollama/ollama:latest"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting OLLAMA Docker container..."
echo "   Container name: $CONTAINER_NAME"
echo "   Image: $IMAGE_NAME"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    echo "   Install Docker Desktop and enable WSL2 integration"
    exit 1
fi

# Check if NVIDIA runtime is available
if ! docker info 2>/dev/null | grep -q "nvidia"; then
    echo "⚠️  Warning: NVIDIA runtime not detected"
    echo "   GPU support may not work. Install NVIDIA Container Toolkit"
fi

# Check if container exists (similar to GROBID/PaddleOCR container management)
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
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "ollama/ollama.*latest"; then
        echo "📥 Pulling Docker image (this may take a few minutes)..."
        echo "   Image: $IMAGE_NAME"
        docker pull "$IMAGE_NAME"
    fi
    
    # Create custom network for OLLAMA containers (enables DNS resolution)
    if ! docker network ls --format '{{.Name}}' | grep -q "^ollama-network$"; then
        echo "📡 Creating ollama-network for container DNS resolution..."
        docker network create ollama-network
    fi
    
    # Create container with GPU support and network access
    # - Set OLLAMA_HOST=0.0.0.0:11434 for network access
    # - Mount volume for model persistence
    # - Expose port 11434 for API access
    # - Connect to custom network for DNS resolution with WebUI
    docker run -d \
      --name "$CONTAINER_NAME" \
      --gpus all \
      --network ollama-network \
      -v ollama-models:/root/.ollama \
      -e OLLAMA_HOST=0.0.0.0:11434 \
      -p 11434:11434 \
      --restart unless-stopped \
      "$IMAGE_NAME"
    
    echo "✅ Container created and started"
    echo "   OLLAMA is now accessible on http://localhost:11434"
    echo "   Network access: http://<p1-ip>:11434"
fi

# Wait a moment for OLLAMA to initialize
echo "⏳ Waiting for OLLAMA to be ready..."
sleep 3

# Check if OLLAMA is responding
if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "✅ OLLAMA is ready and responding"
else
    echo "⚠️  OLLAMA may still be starting up. It should be ready shortly."
    echo "   Check status: curl http://localhost:11434/api/tags"
fi

echo ""
echo "✅ Container ready!"
echo ""
echo "OLLAMA API:"
echo "   URL: http://localhost:11434 (or http://<p1-ip>:11434 from network)"
echo "   Health check: curl http://localhost:11434/api/tags"
echo ""
echo "To enter the container:"
echo "   docker exec -it $CONTAINER_NAME bash"
echo ""
echo "To view OLLAMA logs:"
echo "   docker logs $CONTAINER_NAME"
echo ""
echo "To pull models (inside container or from host with ollama CLI):"
echo "   docker exec $CONTAINER_NAME ollama pull llama2:7b"
echo ""

