#!/bin/bash
# Script to check for multiple Ollama instances and where models are stored

echo "Checking Ollama instances and model locations..."
echo "=" * 80

echo ""
echo "1. Checking for running Ollama processes/containers:"
echo "---------------------------------------------------"
echo "Docker containers:"
docker ps | grep -i ollama || echo "  No Ollama containers found"

echo ""
echo "Processes:"
ps aux | grep -i ollama | grep -v grep || echo "  No Ollama processes found"

echo ""
echo "2. Checking Ollama API endpoints:"
echo "---------------------------------------------------"
echo "Testing localhost:11434..."
curl -s http://localhost:11434/api/tags 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Not responding"

echo ""
echo "Testing 192.168.178.129:11434..."
curl -s http://192.168.178.129:11434/api/tags 2>/dev/null | python3 -m json.tool 2>/dev/null || echo "  Not responding"

echo ""
echo "3. Checking WebUI configuration (if accessible):"
echo "---------------------------------------------------"
echo "Testing WebUI at http://192.168.178.129:3000..."
curl -s http://192.168.178.129:3000 2>/dev/null | head -20 || echo "  WebUI not accessible or not responding"

echo ""
echo "4. If you have SSH access to p1, run these commands on p1:"
echo "---------------------------------------------------"
echo "  # Check Docker containers"
echo "  docker ps | grep ollama"
echo ""
echo "  # Check models in container"
echo "  docker exec <ollama-container-name> ollama list"
echo ""
echo "  # Check if Ollama is running outside Docker"
echo "  ps aux | grep ollama"
echo ""
echo "  # Check Ollama data directory (if running outside Docker)"
echo "  ls -la ~/.ollama/models/"
echo ""
echo "  # Check Docker volume for models"
echo "  docker volume ls | grep ollama"
echo "  docker volume inspect <ollama-volume-name>"

