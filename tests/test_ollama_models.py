#!/usr/bin/env python3
"""
Test script to check which Ollama models are available and working.
"""

import requests
import json

OLLAMA_HOST = "192.168.178.129"
OLLAMA_PORT = 11434
BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

def test_ollama_connection():
    """Test Ollama connection and list available models."""
    print("Testing Ollama Connection")
    print("=" * 80)
    
    # Test 1: Check if API is reachable
    print("\n1. Testing API endpoint...")
    try:
        response = requests.get(f"{BASE_URL}/api/tags", timeout=10)
        response.raise_for_status()
        print(f"   ✅ API is reachable (HTTP {response.status_code})")
        
        data = response.json()
        models = data.get('models', [])
        
        if models:
            print(f"\n   Available models ({len(models)}):")
            for model in models:
                name = model.get('name', 'Unknown')
                size = model.get('size', 0)
                size_gb = size / (1024**3) if size > 0 else 0
                print(f"   - {name} ({size_gb:.2f} GB)")
        else:
            print("   ⚠️  No models found. Models need to be pulled first.")
            print("   Run on p1: ollama pull llama2:7b")
    except requests.exceptions.RequestException as e:
        print(f"   ❌ Connection failed: {e}")
        return
    
    # Test 2: Try common model names
    print("\n2. Testing common model names...")
    test_models = [
        "llama2:7b",
        "llama2",
        "codellama",
        "codellama:7b",
        "ollama-gpu",  # In case this is the model name
    ]
    
    for model_name in test_models:
        print(f"\n   Testing model: {model_name}")
        try:
            payload = {
                "model": model_name,
                "prompt": "Hello",
                "stream": False
            }
            response = requests.post(
                f"{BASE_URL}/api/generate",
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                result = response.json()
                print(f"   ✅ Model '{model_name}' is available!")
                if 'response' in result:
                    print(f"      Response preview: {result['response'][:50]}...")
                break
            elif response.status_code == 404:
                print(f"   ❌ Model '{model_name}' not found")
            else:
                print(f"   ⚠️  HTTP {response.status_code}: {response.text[:100]}")
        except requests.exceptions.Timeout:
            print(f"   ⏳ Timeout (container might be waking up)")
        except requests.exceptions.RequestException as e:
            print(f"   ❌ Error: {e}")
    
    print("\n" + "=" * 80)
    print("Summary:")
    print("  - If no models are listed, you need to pull them on p1:")
    print("    docker exec <ollama-container> ollama pull llama2:7b")
    print("  - The model name in config should match the actual model name")
    print("    (not the container image name)")

if __name__ == "__main__":
    test_ollama_connection()


