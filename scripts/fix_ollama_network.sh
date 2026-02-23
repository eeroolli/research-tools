#!/bin/bash
# Fix Ollama container network connectivity - ensures both containers are on ollama-network

set -e

NETWORK_NAME="ollama-network"
OLLAMA_CONTAINER="ollama-gpu"
WEBUI_CONTAINER="ollama-webui"

echo "Diagnosing Ollama network connectivity issue..."
echo ""

# Check if Docker is available
if ! command -v docker &> /dev/null; then
    echo "Error: Docker is not installed or not in PATH"
    exit 1
fi

# Ensure ollama-network exists
if ! docker network ls --format '{{.Name}}' | grep -q "^${NETWORK_NAME}$"; then
    echo "Creating ${NETWORK_NAME}..."
    docker network create ${NETWORK_NAME}
    echo "Network created"
else
    echo "Network ${NETWORK_NAME} exists"
fi

# Check if ollama-gpu is on ollama-network
if docker inspect ${OLLAMA_CONTAINER} 2>/dev/null | grep -q "\"${NETWORK_NAME}\""; then
    echo "Container ${OLLAMA_CONTAINER} is already on ${NETWORK_NAME}"
else
    echo "Connecting ${OLLAMA_CONTAINER} to ${NETWORK_NAME}..."
    docker network connect ${NETWORK_NAME} ${OLLAMA_CONTAINER} 2>/dev/null || echo "Already connected or container not running"
fi

# Check if ollama-webui is on ollama-network
if docker inspect ${WEBUI_CONTAINER} 2>/dev/null | grep -q "\"${NETWORK_NAME}\""; then
    echo "Container ${WEBUI_CONTAINER} is already on ${NETWORK_NAME}"
else
    echo "Connecting ${WEBUI_CONTAINER} to ${NETWORK_NAME}..."
    docker network connect ${NETWORK_NAME} ${WEBUI_CONTAINER} 2>/dev/null || echo "Already connected or container not running"
fi

# Restart WebUI to pick up network changes
echo ""
echo "Restarting WebUI to pick up network changes..."
docker restart ${WEBUI_CONTAINER} 2>/dev/null || echo "WebUI container not running"

echo ""
echo "Waiting for WebUI to restart..."
sleep 5

# Test connectivity
echo ""
echo "Testing connectivity from WebUI to Ollama..."
if docker exec ${WEBUI_CONTAINER} curl -s http://${OLLAMA_CONTAINER}:11434/api/tags > /dev/null 2>&1; then
    echo "SUCCESS: WebUI can reach Ollama!"
    echo ""
    echo "Models should now be visible in WebUI at http://localhost:3000"
else
    echo "WARNING: WebUI still cannot reach Ollama"
    echo "Check logs: docker logs ${WEBUI_CONTAINER}"
fi

echo ""
echo "Fix complete!"
