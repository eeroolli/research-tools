# ========================================
# Copy PDF to Publications Directory
# ========================================
# This script is called from WSL Python daemon to copy files to Google Drive
# using native Windows file operations for reliable sync.
#
# Usage:
#   powershell.exe -File copy_to_publications.ps1 <source_path> <target_path> [-Replace]
#
# Exit codes:
#   0 = Success
#   1 = Source file not found
#   2 = Target already exists (and differs, when -Replace not specified)
#   3 = Copy failed
#   4 = Verification failed

param(
    [Parameter(Mandatory=$true)]
    [string]$SourcePath,
    
    [Parameter(Mandatory=$true)]
    [string]$TargetPath,
    
    [Parameter(Mandatory=$false)]
    [switch]$Replace
)

# Function to get file hash
function Get-FileHashQuick {
    param([string]$Path)
    try {
        $hash = Get-FileHash -Path $Path -Algorithm SHA256
        return $hash.Hash
    } catch {
        return $null
    }
}

# Check if source exists
if (-not (Test-Path $SourcePath)) {
    Write-Host "ERROR: Source file not found: $SourcePath" -ForegroundColor Red
    exit 1
}

# Check if target already exists
if (Test-Path $TargetPath) {
    Write-Host "WARNING: Target file already exists: $TargetPath" -ForegroundColor Yellow
    
    # Compare file sizes
    $sourceSize = (Get-Item $SourcePath).Length
    $targetSize = (Get-Item $TargetPath).Length
    
    if ($sourceSize -eq $targetSize) {
        Write-Host "Files have same size. Checking hash..." -ForegroundColor Yellow
        $sourceHash = Get-FileHashQuick $SourcePath
        $targetHash = Get-FileHashQuick $TargetPath
        
        if ($sourceHash -eq $targetHash) {
            Write-Host "SUCCESS: Files are identical (already copied)" -ForegroundColor Green
            exit 0
        }
    }
    
    # If -Replace flag is set, proceed with replacement
    if ($Replace) {
        Write-Host "Replacing existing file (user requested replacement)..." -ForegroundColor Yellow
        # Continue to copy section below
    } else {
        Write-Host "ERROR: Target exists but differs from source" -ForegroundColor Red
        exit 2
    }
}

# Get source file info
$sourceFile = Get-Item $SourcePath
$sourceSize = $sourceFile.Length
$sourceSizeMB = [math]::Round($sourceSize / 1MB, 2)

Write-Host "Copying $sourceSizeMB MB to publications directory..." -ForegroundColor Cyan

# Ensure target directory exists
$targetDir = Split-Path $TargetPath -Parent
if (-not (Test-Path $targetDir)) {
    Write-Host "Creating directory: $targetDir" -ForegroundColor Cyan
    try {
        New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
    } catch {
        Write-Host "ERROR: Failed to create directory: $_" -ForegroundColor Red
        exit 3
    }
}

# Copy file
try {
    Copy-Item -Path $SourcePath -Destination $TargetPath -Force
} catch {
    Write-Host "ERROR: Copy failed: $_" -ForegroundColor Red
    exit 3
}

# Verify copy
if (-not (Test-Path $TargetPath)) {
    Write-Host "ERROR: Target file not found after copy" -ForegroundColor Red
    exit 4
}

$targetSize = (Get-Item $TargetPath).Length
if ($targetSize -ne $sourceSize) {
    Write-Host "ERROR: Size mismatch (source: $sourceSize, target: $targetSize)" -ForegroundColor Red
    # Clean up bad copy
    Remove-Item $TargetPath -Force
    exit 4
}

Write-Host "SUCCESS: File copied and verified" -ForegroundColor Green
Write-Host "Target: $TargetPath" -ForegroundColor Gray
exit 0
