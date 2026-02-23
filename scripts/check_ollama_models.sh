#!/bin/bash
# Script to check Ollama models available on p1

echo "Checking Ollama on p1 (192.168.178.129:11434)..."
echo ""

# Check if Ollama is responding
echo "1. Testing Ollama connection..."
curl -s http://192.168.178.129:11434/api/tags | python3 -m json.tool 2>/dev/null || curl -s http://192.168.178.129:11434/api/tags

echo ""
echo ""

# Try to list models
echo "2. Available models:"
curl -s http://192.168.178.129:11434/api/tags | grep -o '"name":"[^"]*"' | sed 's/"name":"//g' | sed 's/"//g' || echo "Could not parse model names"

echo ""
echo ""

# Check if we can reach the API
echo "3. Testing API endpoint..."
response=$(curl -s -o /dev/null -w "%{http_code}" http://192.168.178.129:11434/api/tags)
if [ "$response" = "200" ]; then
    echo "✅ Ollama API is responding (HTTP $response)"
else
    echo "❌ Ollama API returned HTTP $response"
fi

