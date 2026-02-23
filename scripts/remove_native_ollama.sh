#!/bin/bash
# Remove native OLLAMA installation files

set -e

echo "🗑️  Removing native OLLAMA installation..."
echo ""

# Check if Docker OLLAMA is working first
echo "Verifying Docker OLLAMA is working..."
if ! curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
    echo "❌ Error: Docker OLLAMA is not responding!"
    echo "   Please ensure Docker OLLAMA is running before removing native installation."
    exit 1
fi
echo "✅ Docker OLLAMA is working"
echo ""

# Remove systemd service file
if [ -f /etc/systemd/system/ollama.service ]; then
    echo "Removing systemd service file..."
    sudo rm /etc/systemd/system/ollama.service
    echo "✅ Service file removed"
else
    echo "ℹ️  Service file not found (may already be removed)"
fi

# Remove OLLAMA binary
if [ -f /usr/local/bin/ollama ]; then
    echo "Removing OLLAMA binary..."
    sudo rm /usr/local/bin/ollama
    echo "✅ Binary removed"
else
    echo "ℹ️  Binary not found (may already be removed)"
fi

# Remove native models directory
if [ -d /usr/share/ollama ]; then
    echo "Removing native models directory..."
    echo "   Size: $(du -sh /usr/share/ollama 2>/dev/null | awk '{print $1}')"
    echo "   Note: This will free up disk space. Docker models are separate."
    sudo rm -r /usr/share/ollama
    echo "✅ Models directory removed"
else
    echo "ℹ️  Models directory not found (may already be removed)"
fi

# Reload systemd
echo "Reloading systemd..."
sudo systemctl daemon-reload
echo "✅ Systemd reloaded"
echo ""

# Final verification
echo "Final verification..."
if pgrep -f "ollama serve" > /dev/null; then
    echo "⚠️  Warning: OLLAMA process still running (PID: $(pgrep -f 'ollama serve'))"
    echo "   You may need to kill it manually"
else
    echo "✅ No native OLLAMA processes running"
fi

echo ""
echo "✅ Native OLLAMA installation removed!"
echo ""
echo "Docker OLLAMA status:"
docker ps --format "table {{.Names}}\t{{.Status}}" | grep ollama || echo "   (No Docker containers found)"
echo ""
echo "You can verify Docker OLLAMA is working:"
echo "   curl http://localhost:11434/api/tags"


