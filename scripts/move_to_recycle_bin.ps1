# ========================================
# Move file to Windows Recycle Bin
# ========================================
# Usage:
#   powershell.exe -File move_to_recycle_bin.ps1 <path>
#
# Exit codes:
#   0 = Success
#   1 = Source file not found
#   2 = Failed to move to recycle bin

param(
    [Parameter(Mandatory=$true)]
    [string]$Path
)

# Check if source exists
if (-not (Test-Path $Path)) {
    Write-Host "ERROR: Source file not found: $Path" -ForegroundColor Red
    exit 1
}

try {
    Add-Type -AssemblyName Microsoft.VisualBasic | Out-Null
    [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile(
        $Path,
        'OnlyErrorDialogs',
        'SendToRecycleBin'
    )
    Write-Host "SUCCESS: Moved to Recycle Bin" -ForegroundColor Green
    exit 0
} catch {
    Write-Host "ERROR: Failed to move to Recycle Bin: $_" -ForegroundColor Red
    exit 2
}


