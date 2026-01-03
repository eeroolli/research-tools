#!/bin/bash
# Check if ocrmypdf is installed on the current machine

echo "Checking for ocrmypdf installation..."
echo "======================================"

# Check if ocrmypdf command exists
if command -v ocrmypdf &> /dev/null; then
    echo "✅ ocrmypdf is installed"
    ocrmypdf --version
    echo ""
    
    # Check if it's in conda environment
    if [ -n "$CONDA_DEFAULT_ENV" ]; then
        echo "Current conda environment: $CONDA_DEFAULT_ENV"
    fi
    
    # Check tesseract languages available
    echo ""
    echo "Available Tesseract languages:"
    if command -v tesseract &> /dev/null; then
        tesseract --list-langs 2>/dev/null || echo "  (tesseract not found or error listing languages)"
    else
        echo "  tesseract not found"
    fi
else
    echo "❌ ocrmypdf is NOT installed"
    echo ""
    echo "To install on this machine:"
    echo "  conda install ocrmypdf -c conda-forge"
    echo "  or"
    echo "  pip install ocrmypdf"
fi


