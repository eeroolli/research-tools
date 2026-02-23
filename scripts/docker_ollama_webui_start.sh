#!/bin/bash
# Start Open WebUI Docker container for OLLAMA web chat interface

set -e

CONTAINER_NAME="ollama-webui"
IMAGE_NAME="ghcr.io/open-webui/open-webui:main"
OLLAMA_CONTAINER_NAME="ollama-gpu"

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo "🚀 Starting Open WebUI Docker container..."
echo "   Container name: $CONTAINER_NAME"
echo "   Image: $IMAGE_NAME"
echo "   Connecting to OLLAMA: $OLLAMA_CONTAINER_NAME"

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "❌ Error: Docker is not installed or not in PATH"
    exit 1
fi

# Check if OLLAMA container is running
if ! docker ps --format '{{.Names}}' | grep -q "^${OLLAMA_CONTAINER_NAME}$"; then
    echo "⚠️  Warning: OLLAMA container ($OLLAMA_CONTAINER_NAME) is not running"
    echo "   Please start OLLAMA first: ./scripts/docker_ollama_start.sh"
    echo "   Or start it manually: docker start $OLLAMA_CONTAINER_NAME"
    exit 1
fi

# Connect to OLLAMA Docker container via Docker network
# Both containers are on the same bridge network, so we can use the container name
OLLAMA_URL="http://ollama-gpu:11434"

# Get WSL2 IP (for reference - this is internal, not accessible from network)
HOST_IP=$(hostname -I | awk '{print $1}')
if [ -z "$HOST_IP" ]; then
    HOST_IP="host.docker.internal"
fi

echo "   OLLAMA URL: $OLLAMA_URL"

# Ensure ollama-network exists and both containers are on it for hostname-based DNS resolution
NETWORK_NAME="ollama-network"
if ! docker network ls --format "{{.Name}}" | grep -q "^${NETWORK_NAME}$"; then
    echo "📡 Creating ${NETWORK_NAME} for container DNS resolution..."
    docker network create ${NETWORK_NAME}
fi

# Ensure WebUI container is on the network
if ! docker inspect ${CONTAINER_NAME} 2>/dev/null | grep -q "\"${NETWORK_NAME}\""; then
    echo "🔗 Connecting ${CONTAINER_NAME} to ${NETWORK_NAME} for hostname-based DNS resolution..."
    docker network connect ${NETWORK_NAME} ${CONTAINER_NAME} 2>/dev/null || echo "   (Already connected or network issue)"
fi

# Ensure Ollama container is on the network (if it exists)
if docker ps -a --format "{{.Names}}" | grep -q "^${OLLAMA_CONTAINER_NAME}$"; then
    if ! docker inspect ${OLLAMA_CONTAINER_NAME} 2>/dev/null | grep -q "\"${NETWORK_NAME}\""; then
        echo "🔗 Connecting ${OLLAMA_CONTAINER_NAME} to ${NETWORK_NAME} for hostname-based DNS resolution..."
        docker network connect ${NETWORK_NAME} ${OLLAMA_CONTAINER_NAME} 2>/dev/null || echo "   (Already connected or network issue)"
    fi
fi

# Check if container exists
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
    if ! docker images --format '{{.Repository}}:{{.Tag}}' | grep -q "ghcr.io/open-webui/open-webui.*main"; then
        echo "📥 Pulling Docker image (this may take a few minutes)..."
        echo "   Image: $IMAGE_NAME"
        docker pull "$IMAGE_NAME"
    fi
    
    # Create custom network for OLLAMA containers (enables DNS resolution)
    if ! docker network ls --format '{{.Name}}' | grep -q "^ollama-network$"; then
        echo "📡 Creating ollama-network for container DNS resolution..."
        docker network create ollama-network
    fi
    
    # Create container with network access
    # - Connect to OLLAMA via Docker network DNS (ollama-gpu:11434)
    # - Connect to custom network for DNS resolution
    # - Expose port 3000 for web interface
    # - Optional: Disable authentication for easier access (set WEBUI_AUTH=False)
    # - Set default model to llama2:7b (instead of codellama)
    # - Mount volume for data persistence
    docker run -d \
      --name "$CONTAINER_NAME" \
      --network ollama-network \
      -v ollama-webui-data:/app/backend/data \
      -e OLLAMA_BASE_URL="$OLLAMA_URL" \
      -e WEBUI_AUTH=False \
      -e DEFAULT_MODELS=llama2:7b \
      -p 3000:8080 \
      --restart unless-stopped \
      "$IMAGE_NAME"
    
    echo "✅ Container created and started"
fi

# Wait a moment for WebUI to initialize
echo "⏳ Waiting for WebUI to be ready..."
sleep 5

# Check if WebUI is responding
if curl -s http://localhost:3000 > /dev/null 2>&1; then
    echo "✅ WebUI is ready and responding"
else
    echo "⚠️  WebUI may still be starting up. It should be ready shortly."
fi

echo ""
echo "✅ WebUI ready!"
echo ""
echo "Access the web interface:"
echo "   Local: http://localhost:3000"
echo "   WSL2 internal IP: http://$HOST_IP:3000 (not accessible from network)"
echo "   Phone/Mac/Any device: Use your Windows host IP (e.g., http://192.168.178.129:3000)"
echo "   Note: The WSL2 IP ($HOST_IP) is internal. Network devices should use the Windows host IP."
echo ""
echo "Features:"
echo "   - ChatGPT-like interface"
echo "   - Works on any device with a web browser"
echo "   - No authentication required (WEBUI_AUTH=False)"
echo "   - Chat history and model selection"
echo ""
echo "To view WebUI logs:"
echo "   docker logs $CONTAINER_NAME"
echo ""
echo "To stop WebUI:"
echo "   docker stop $CONTAINER_NAME"
echo ""

