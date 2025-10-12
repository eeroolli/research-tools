# ========================================
# Paper Processor Daemon Launcher (PowerShell)
# Called by Epson Capture Pro after scan
# ========================================
#
# This script is triggered by Epson Capture Pro after saving a PDF.
# It checks if the daemon is running and starts it if needed.
# The daemon watches /mnt/i/FraScanner/papers/ for new PDFs.
#
# Author: Eero Olli
# Date: October 11, 2025
# ========================================

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Paper Processor Daemon Launcher" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# Get script directory and convert to WSL path format
# $PSScriptRoot gives us the script's directory (e.g., F:\prog\research-tools\scripts)
$scriptPath = Join-Path $PSScriptRoot "start_paper_processor.py"

# Convert Windows path to WSL path using wslpath
# Use proper escaping for PowerShell to WSL path conversion
$wslScriptPath = wsl wslpath -u `"$scriptPath`"

# Call WSL with conda activation and run the daemon launcher
Write-Host "Checking daemon status..." -ForegroundColor Yellow

$result = wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python '$wslScriptPath'"

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[OK] Daemon check complete" -ForegroundColor Green
    Write-Host ""
} else {
    Write-Host ""
    Write-Host "[WARNING] Daemon start returned error code $LASTEXITCODE" -ForegroundColor Yellow
    Write-Host ""
    Read-Host "Press Enter to continue"
}

# Exit
exit 0

