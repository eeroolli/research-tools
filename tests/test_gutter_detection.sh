#!/bin/bash
# Test script for gutter detection - uses same conda environment as daemon

# Try to activate conda (check multiple possible locations)
if [ -f ~/miniconda3/etc/profile.d/conda.sh ]; then
    source ~/miniconda3/etc/profile.d/conda.sh
elif [ -f /home/eero_22/miniconda3/etc/profile.d/conda.sh ]; then
    source /home/eero_22/miniconda3/etc/profile.d/conda.sh
elif [ -f ~/anaconda3/etc/profile.d/conda.sh ]; then
    source ~/anaconda3/etc/profile.d/conda.sh
fi

# Activate research-tools environment (same as daemon uses)
conda activate research-tools 2>/dev/null || {
    echo "Warning: Could not activate research-tools environment"
    echo "Trying to continue with current Python environment..."
}

# Change to project directory
cd /mnt/f/prog/research-tools

# Run the test script
python3 tests/test_gutter_detection.py "$@"

