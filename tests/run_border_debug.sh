#!/bin/bash
# Wrapper script to run border detection debug test in WSL with conda environment

# Find conda installation
if [ -f "$HOME/miniconda3/etc/profile.d/conda.sh" ]; then
    CONDA_SETUP="$HOME/miniconda3/etc/profile.d/conda.sh"
elif [ -f "$HOME/anaconda3/etc/profile.d/conda.sh" ]; then
    CONDA_SETUP="$HOME/anaconda3/etc/profile.d/conda.sh"
else
    echo "ERROR: Could not find conda installation"
    echo "Please activate conda manually and run:"
    echo "  python tests/test_border_detection_debug.py [pdf_path]"
    exit 1
fi

# Source conda
source "$CONDA_SETUP"

# Activate research-tools environment
conda activate research-tools

# Check if activation succeeded
if [ $? -ne 0 ]; then
    echo "ERROR: Failed to activate 'research-tools' conda environment"
    echo "Please create it first with:"
    echo "  conda env create -f environment.yml"
    exit 1
fi

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Run the test script with any provided arguments
cd "$PROJECT_ROOT"
python "$SCRIPT_DIR/test_border_detection_debug.py" "$@"

