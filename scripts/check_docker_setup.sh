#!/bin/bash
# Check Docker setup for WSL2 + Windows Docker Desktop

echo "🔍 Checking Docker setup..."
echo ""

# Check if Docker is available
if command -v docker &> /dev/null; then
    echo "✅ Docker is installed and accessible"
    docker --version
else
    echo "❌ Docker is not accessible from WSL2"
    echo ""
    echo "📋 To fix:"
    echo "   1. Open Docker Desktop on Windows"
    echo "   2. Go to Settings → Resources → WSL Integration"
    echo "   3. Enable integration for this WSL2 distro"
    echo "   4. Click 'Apply & Restart'"
    echo "   5. Wait for Docker Desktop to restart"
    echo ""
    exit 1
fi

echo ""

# Check if Docker daemon is running
if docker ps &> /dev/null; then
    echo "✅ Docker daemon is running"
else
    echo "❌ Docker daemon is not running"
    echo "   Start Docker Desktop on Windows"
    exit 1
fi

echo ""

# Check GPU support
echo "🔍 Checking GPU support..."
if docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi &> /dev/null; then
    echo "✅ GPU support is working!"
    docker run --rm --gpus all nvidia/cuda:12.1.0-base-ubuntu22.04 nvidia-smi
else
    echo "⚠️  GPU support test failed"
    echo "   This might be normal if:"
    echo "   - NVIDIA drivers aren't installed on Windows"
    echo "   - WSL2 GPU passthrough isn't working"
    echo ""
    echo "   Check: nvidia-smi (should work in WSL2)"
fi

echo ""
echo "✅ Docker setup check complete!"

