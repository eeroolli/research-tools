#!/bin/bash
# Stop and disable native OLLAMA service (after migrating to Docker)

set -e

echo "🛑 Stopping native OLLAMA service..."

# Check if native OLLAMA service is running
if systemctl is-active --quiet ollama 2>/dev/null; then
    echo "   Stopping ollama.service..."
    sudo systemctl stop ollama
    echo "   ✅ Service stopped"
else
    echo "   ℹ️  Service is not running"
fi

# Check if service is enabled
if systemctl is-enabled --quiet ollama 2>/dev/null; then
    echo "   Disabling ollama.service from auto-start..."
    sudo systemctl disable ollama
    echo "   ✅ Service disabled"
else
    echo "   ℹ️  Service is not enabled"
fi

# Check if process is still running
if pgrep -f "ollama serve" > /dev/null; then
    echo "   ⚠️  Warning: OLLAMA process is still running"
    echo "   Process ID(s): $(pgrep -f 'ollama serve' | tr '\n' ' ')"
    echo "   You may need to kill it manually: sudo kill <PID>"
else
    echo "   ✅ No OLLAMA processes running"
fi

echo ""
echo "✅ Native OLLAMA service stopped and disabled"
echo ""
echo "Next steps:"
echo "   1. Verify Docker OLLAMA is working: curl http://localhost:11434/api/tags"
echo "   2. Test WebUI: http://localhost:3000"
echo "   3. Once verified, you can remove native OLLAMA installation:"
echo "      - Remove service file: sudo rm /etc/systemd/system/ollama.service"
echo "      - Remove binary: sudo rm /usr/local/bin/ollama"
echo "      - Remove models: sudo rm -r /usr/share/ollama"
echo "      - Reload systemd: sudo systemctl daemon-reload"
echo ""

