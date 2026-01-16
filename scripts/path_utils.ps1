# ========================================
# Universal Path Utilities for WSL/Windows
# ========================================
# This script provides path conversion and validation utilities that work
# reliably with cloud drives (Google Drive, OneDrive, etc.) that may not
# be accessible from WSL but are accessible from Windows PowerShell.
#
# Usage:
#   powershell.exe -File path_utils.ps1 <command> [arguments...]
#
# Commands:
#   convert-wsl-to-windows <wsl_path>     - Convert WSL path to Windows path
#   convert-windows-to-wsl <windows_path> - Convert Windows path to WSL path
#   test-path <path>                      - Check if path exists (returns JSON)
#   test-directory <path>                 - Check if directory exists and is accessible (returns JSON)
#   ensure-directory <path>               - Create directory if it doesn't exist (returns JSON)
#   get-file-info <path> [-Hash]          - Get file info (size/ctime/mtime/hash) (returns JSON)
#   copy-file <source_path> <target_path> [-Replace] - Copy file with verification (returns JSON)
#   list-pdfs <directory_path>            - List all PDF files in directory (returns JSON)
#
# Exit codes:
#   0 = Success
#   1 = Invalid command or missing arguments
#   2 = Path conversion failed
#   3 = Path validation/copy failed
#   4 = Source file not found
#   5 = Target exists but differs (when -Replace not specified)
#   6 = Copy operation failed
#   7 = Verification failed

param(
    [Parameter(Mandatory=$true)]
    [string]$Command,
    
    [Parameter(ValueFromRemainingArguments=$true)]
    [string[]]$Arguments
)

# Function to convert WSL path to Windows path
function Convert-WSLToWindows {
    param([string]$WSLPath)
    
    # Remove leading/trailing whitespace
    $WSLPath = $WSLPath.Trim()
    
    # If already a Windows path (contains : or starts with letter drive), return as-is
    if ($WSLPath -match '^[A-Za-z]:') {
        return $WSLPath
    }
    
    # Handle WSL paths like /mnt/c/... or /mnt/g/...
    if ($WSLPath -match '^/mnt/([a-z])/(.+)$') {
        $driveLetter = $matches[1].ToUpper()
        $remainder = $matches[2]
        
        # Replace forward slashes with backslashes for Windows
        $windowsPath = $remainder -replace '/', '\'
        
        # Construct Windows path: G:\My Drive\publications
        return "${driveLetter}:\${windowsPath}"
    }
    
    # Handle other WSL paths (like /home/..., /tmp/...)
    # Try using wslpath if available, but don't fail if it's not
    try {
        # Try calling wslpath via wsl.exe (works from PowerShell)
        $wslResult = wsl wslpath -w $WSLPath 2>&1
        $wslExitCode = $LASTEXITCODE
        if ($wslExitCode -eq 0 -and $wslResult -and ($wslResult -notmatch '^/')) {
            # Successfully converted - result should be Windows path
            return $wslResult.Trim()
        }
        # If wslpath failed, try direct wslpath (might work in some environments)
        $result = wslpath -w $WSLPath 2>&1
        if ($LASTEXITCODE -eq 0 -and $result -and ($result -notmatch '^/')) {
            return $result.Trim()
        }
    } catch {
        # wslpath not available or failed - continue with manual conversion
    }
    
    # If we can't convert, return original path (might work if it's already Windows format)
    return $WSLPath
}

# Function to convert Windows path to WSL path
function Convert-WindowsToWSL {
    param([string]$WindowsPath)
    
    # Remove leading/trailing whitespace
    $WindowsPath = $WindowsPath.Trim()
    
    # If already a WSL path (starts with /), return as-is
    if ($WindowsPath -match '^/') {
        return $WindowsPath
    }
    
    # Handle Windows paths like G:\My Drive\publications
    if ($WindowsPath -match '^([A-Za-z]):\\(.+)$') {
        $driveLetter = $matches[1].ToLower()
        $remainder = $matches[2]
        
        # Replace backslashes with forward slashes
        $wslPath = $remainder -replace '\\', '/'
        
        # Construct WSL path: /mnt/g/My Drive/publications
        return "/mnt/${driveLetter}/${wslPath}"
    }
    
    # If we can't convert, return original path
    return $WindowsPath
}

# Function to test if path exists and return JSON result
function Test-PathWithResult {
    param([string]$Path)
    
    $exists = Test-Path -Path $Path -ErrorAction SilentlyContinue
    $isFile = $false
    $isDirectory = $false
    $accessible = $false
    $errorMsg = $null
    
    if ($exists) {
        try {
            $item = Get-Item -Path $Path -ErrorAction Stop
            $isFile = -not $item.PSIsContainer
            $isDirectory = $item.PSIsContainer
            $accessible = $true
        } catch {
            $errorMsg = $_.Exception.Message
        }
    }
    
    $result = @{
        exists = $exists
        isFile = $isFile
        isDirectory = $isDirectory
        accessible = $accessible
        error = $errorMsg
    } | ConvertTo-Json -Compress
    
    return $result
}

# Function to test directory and return JSON result
function Test-DirectoryWithResult {
    param([string]$Path)
    
    $exists = Test-Path -Path $Path -PathType Container -ErrorAction SilentlyContinue
    $accessible = $false
    $writable = $false
    $errorMsg = $null
    
    if ($exists) {
        try {
            # Try to get directory info
            $dir = Get-Item -Path $Path -ErrorAction Stop
            $accessible = $true
            
            # Try to create a test file to check writability
            $testFile = Join-Path $Path ".path_utils_test_$(Get-Random)"
            try {
                New-Item -ItemType File -Path $testFile -Force | Out-Null
                Remove-Item -Path $testFile -Force
                $writable = $true
            } catch {
                $writable = $false
            }
        } catch {
            $errorMsg = $_.Exception.Message
        }
    }
    
    $result = @{
        exists = $exists
        accessible = $accessible
        writable = $writable
        error = $errorMsg
    } | ConvertTo-Json -Compress
    
    return $result
}

# Function to get file info and optional hash
function Get-FileInfoWithResult {
    param(
        [string]$Path,
        [switch]$Hash
    )
    
    $exists = Test-Path -Path $Path -ErrorAction SilentlyContinue
    $isFile = $false
    $size = $null
    $ctime = $null
    $mtime = $null
    $hashValue = $null
    $errorMsg = $null
    
    if ($exists) {
        try {
            $item = Get-Item -Path $Path -ErrorAction Stop
            $isFile = -not $item.PSIsContainer
            if ($isFile) {
                $size = $item.Length
                $ctime = $item.CreationTimeUtc.ToString("o")
                $mtime = $item.LastWriteTimeUtc.ToString("o")
                if ($Hash) {
                    $hashValue = (Get-FileHash -Path $Path -Algorithm SHA256).Hash
                }
            }
        } catch {
            $errorMsg = $_.Exception.Message
        }
    }
    
    $result = @{
        exists = $exists
        isFile = $isFile
        size = $size
        ctime = $ctime
        mtime = $mtime
        hash = $hashValue
        error = $errorMsg
    } | ConvertTo-Json -Compress
    
    return $result
}

# Function to ensure directory exists
function Ensure-Directory {
    param([string]$Path)
    
    $created = $false
    $errorMsg = $null
    
    if (-not (Test-Path -Path $Path -PathType Container)) {
        try {
            New-Item -ItemType Directory -Path $Path -Force | Out-Null
            $created = $true
        } catch {
            $errorMsg = $_.Exception.Message
        }
    }
    
    $exists = Test-Path -Path $Path -PathType Container
    $accessible = $false
    
    if ($exists) {
        try {
            Get-Item -Path $Path -ErrorAction Stop | Out-Null
            $accessible = $true
        } catch {
            $errorMsg = $_.Exception.Message
        }
    }
    
    $result = @{
        exists = $exists
        created = $created
        accessible = $accessible
        error = $errorMsg
    } | ConvertTo-Json -Compress
    
    return $result
}

# Function to copy file with verification
function Copy-FileWithVerification {
    param(
        [string]$SourcePath,
        [string]$TargetPath,
        [switch]$Replace
    )
    
    $errorMsg = $null
    $copied = $false
    $verified = $false
    
    # Check if source exists
    if (-not (Test-Path $SourcePath)) {
        $result = @{
            success = $false
            error = "Source file not found: $SourcePath"
            errorCode = 4
        } | ConvertTo-Json -Compress
        return $result
    }
    
    # Check if target drive/path is accessible (important for cloud drives like Google Drive)
    $targetDir = Split-Path $TargetPath -Parent
    $targetDrive = $null
    $isCloudDrive = $false
    
    # Extract drive letter or root path
    if ($targetDir -match '^([A-Z]):') {
        $targetDrive = $matches[1] + ':'
    } elseif ($targetDir -match '^\\\\') {
        # UNC path (network drive)
        $targetDrive = Split-Path $targetDir -Qualifier
        $isCloudDrive = $true
    }
    
    # Check if target directory or drive is accessible
    if ($targetDrive) {
        try {
            # Try to access the drive root
            $driveRoot = if ($targetDrive -match '^[A-Z]:') {
                $targetDrive + '\'
            } else {
                $targetDrive
            }
            
            $driveTest = Test-Path -Path $driveRoot -ErrorAction Stop
            if (-not $driveTest) {
                # Determine if it's likely a cloud drive
                $driveName = if ($targetDir -match 'My Drive') {
                    "Google Drive"
                } elseif ($targetDir -match 'OneDrive') {
                    "OneDrive"
                } else {
                    "drive"
                }
                
                $result = @{
                    success = $false
                    error = "$driveName is not available. The local sync may be paused or the drive may be disconnected. Target path: $TargetPath"
                    errorCode = 8
                    drive = $targetDrive
                    isCloudDrive = $isCloudDrive
                } | ConvertTo-Json -Compress
                return $result
            }
            
            # Try to access the target directory (or its parent if it doesn't exist yet)
            $dirToCheck = $targetDir
            while (-not (Test-Path $dirToCheck) -and $dirToCheck -ne $driveRoot) {
                $dirToCheck = Split-Path $dirToCheck -Parent
            }
            
            if (-not (Test-Path $dirToCheck)) {
                $result = @{
                    success = $false
                    error = "Target directory is not accessible: $targetDir"
                    errorCode = 8
                } | ConvertTo-Json -Compress
                return $result
            }
            
            # Try to get directory info to verify accessibility
            try {
                Get-Item -Path $dirToCheck -ErrorAction Stop | Out-Null
            } catch {
                $driveName = if ($targetDir -match 'My Drive') {
                    "Google Drive"
                } elseif ($targetDir -match 'OneDrive') {
                    "OneDrive"
                } else {
                    "Target drive"
                }
                
                $result = @{
                    success = $false
                    error = "$driveName is not accessible. The local sync may be paused or the drive may be disconnected. Error: $_"
                    errorCode = 8
                    drive = $targetDrive
                    isCloudDrive = $isCloudDrive
                } | ConvertTo-Json -Compress
                return $result
            }
        } catch {
            $driveName = if ($targetDir -match 'My Drive') {
                "Google Drive"
            } elseif ($targetDir -match 'OneDrive') {
                "OneDrive"
            } else {
                "Target drive"
            }
            
            $result = @{
                success = $false
                error = "$driveName is not accessible. The local sync may be paused or the drive may be disconnected. Error: $_"
                errorCode = 8
                drive = $targetDrive
                isCloudDrive = $isCloudDrive
            } | ConvertTo-Json -Compress
            return $result
        }
    }
    
    # Check if target already exists
    if (Test-Path $TargetPath) {
        # Compare file sizes
        $sourceSize = (Get-Item $SourcePath).Length
        $targetSize = (Get-Item $TargetPath).Length
        
        if ($sourceSize -eq $targetSize) {
            # Check hash if sizes match
            try {
                $sourceHash = (Get-FileHash -Path $SourcePath -Algorithm SHA256).Hash
                $targetHash = (Get-FileHash -Path $TargetPath -Algorithm SHA256).Hash
                
                if ($sourceHash -eq $targetHash) {
                    # Files are identical
                    $result = @{
                        success = $true
                        error = $null
                        errorCode = 0
                        message = "Files are identical (already copied)"
                        copied = $false
                        verified = $true
                    } | ConvertTo-Json -Compress
                    return $result
                }
            } catch {
                # Hash check failed, continue with copy
            }
        }
        
        # If -Replace flag is set, proceed with replacement
        if (-not $Replace) {
            $result = @{
                success = $false
                error = "Target exists but differs from source"
                errorCode = 5
            } | ConvertTo-Json -Compress
            return $result
        }
    }
    
    # Ensure target directory exists
    $targetDir = Split-Path $TargetPath -Parent
    if (-not (Test-Path $targetDir)) {
        try {
            New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
        } catch {
            $result = @{
                success = $false
                error = "Failed to create directory: $_"
                errorCode = 6
            } | ConvertTo-Json -Compress
            return $result
        }
    }
    
    # Get source file size for progress
    $sourceSize = (Get-Item $SourcePath).Length
    $sourceSizeMB = [math]::Round($sourceSize / 1MB, 2)
    
    # Copy file
    try {
        Copy-Item -Path $SourcePath -Destination $TargetPath -Force
        $copied = $true
    } catch {
        $result = @{
            success = $false
            error = "Copy failed: $_"
            errorCode = 6
        } | ConvertTo-Json -Compress
        return $result
    }
    
    # Verify copy
    if (-not (Test-Path $TargetPath)) {
        $result = @{
            success = $false
            error = "Target file not found after copy"
            errorCode = 7
        } | ConvertTo-Json -Compress
        return $result
    }
    
    $targetSize = (Get-Item $TargetPath).Length
    if ($targetSize -ne $sourceSize) {
        # Clean up bad copy
        try {
            Remove-Item $TargetPath -Force
        } catch {
            # Ignore cleanup errors
        }
        $result = @{
            success = $false
            error = "Size mismatch (source: $sourceSize, target: $targetSize)"
            errorCode = 7
        } | ConvertTo-Json -Compress
        return $result
    }
    
    $verified = $true
    
    $result = @{
        success = $true
        error = $null
        errorCode = 0
        message = "File copied and verified"
        sourceSize = $sourceSize
        targetSize = $targetSize
        sourceSizeMB = $sourceSizeMB
        copied = $copied
        verified = $verified
    } | ConvertTo-Json -Compress
    
    return $result
}

# Function to list PDF files in a directory
function Get-PDFFiles {
    param(
        [string]$DirectoryPath
    )
    
    $pdfFiles = @()
    
    # Check if directory exists
    if (-not (Test-Path $DirectoryPath)) {
        $result = @{
            success = $false
            error = "Directory not found: $DirectoryPath"
            pdf_files = @()
        } | ConvertTo-Json -Compress
        return $result
    }
    
    # Check if it's actually a directory
    if (-not (Test-Path $DirectoryPath -PathType Container)) {
        $result = @{
            success = $false
            error = "Path is not a directory: $DirectoryPath"
            pdf_files = @()
        } | ConvertTo-Json -Compress
        return $result
    }
    
    try {
        # Get all PDF files
        $pdfPaths = Get-ChildItem -Path $DirectoryPath -Filter "*.pdf" -File -ErrorAction Stop
        $pdfFiles = $pdfPaths | ForEach-Object { $_.Name }
        
        $result = @{
            success = $true
            error = $null
            pdf_files = $pdfFiles
            count = $pdfFiles.Count
        } | ConvertTo-Json -Compress
        
        return $result
    } catch {
        $result = @{
            success = $false
            error = "Failed to list PDF files: $_"
            pdf_files = @()
        } | ConvertTo-Json -Compress
        return $result
    }
}

# Main command dispatcher
try {
    switch ($Command.ToLower()) {
        'convert-wsl-to-windows' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $wslPath = $Arguments[0]
            $windowsPath = Convert-WSLToWindows -WSLPath $wslPath
            Write-Host $windowsPath
            exit 0
        }
        
        'convert-windows-to-wsl' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $windowsPath = $Arguments[0]
            $wslPath = Convert-WindowsToWSL -WindowsPath $windowsPath
            Write-Host $wslPath
            exit 0
        }
        
        'test-path' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $path = $Arguments[0]
            $result = Test-PathWithResult -Path $path
            Write-Host $result
            exit 0
        }
        
        'test-directory' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $path = $Arguments[0]
            $result = Test-DirectoryWithResult -Path $path
            Write-Host $result
            exit 0
        }
        
        'ensure-directory' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $path = $Arguments[0]
            $result = Ensure-Directory -Path $path
            Write-Host $result
            exit 0
        }
        
        'get-file-info' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing path argument" -ForegroundColor Red
                exit 1
            }
            $path = $Arguments[0]
            $withHash = $false
            if ($Arguments.Count -gt 1 -and $Arguments[1] -eq '-Hash') {
                $withHash = $true
            }
            $result = Get-FileInfoWithResult -Path $path -Hash:$withHash
            Write-Host $result
            exit 0
        }
        
        'copy-file' {
            if ($Arguments.Count -lt 2) {
                Write-Host "ERROR: Missing source or target path argument" -ForegroundColor Red
                exit 1
            }
            $sourcePath = $Arguments[0]
            $targetPath = $Arguments[1]
            $replace = $false
            if ($Arguments.Count -gt 2 -and $Arguments[2] -eq '-Replace') {
                $replace = $true
            }
            $result = Copy-FileWithVerification -SourcePath $sourcePath -TargetPath $targetPath -Replace:$replace
            Write-Host $result
            # Exit with error code from result if failed
            $resultObj = $result | ConvertFrom-Json
            if (-not $resultObj.success) {
                exit $resultObj.errorCode
            }
            exit 0
        }
        
        'list-pdfs' {
            if ($Arguments.Count -lt 1) {
                Write-Host "ERROR: Missing directory path argument" -ForegroundColor Red
                exit 1
            }
            $directoryPath = $Arguments[0]
            $result = Get-PDFFiles -DirectoryPath $directoryPath
            Write-Host $result
            exit 0
        }
        
        default {
            Write-Host "ERROR: Unknown command: $Command" -ForegroundColor Red
            Write-Host "Available commands: convert-wsl-to-windows, convert-windows-to-wsl, test-path, test-directory, ensure-directory, get-file-info, copy-file, list-pdfs" -ForegroundColor Yellow
            exit 1
        }
    }
} catch {
    Write-Host "ERROR: $($_.Exception.Message)" -ForegroundColor Red
    exit 3
}

