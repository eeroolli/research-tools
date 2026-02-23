@echo off
REM PaddleOCR Post-Scan Script for Epson Document Capture Pro
REM Processes scanned PDFs with PaddleOCR API and renames with language/orientation info

setlocal

REM Get the PDF file path from Document Capture (passed as %1)
set "PDF_FILE=%~1"

REM Check if file was provided
if "%PDF_FILE%"=="" (
    echo ERROR: No PDF file provided
    pause
    exit /b 1
)

REM Check if file exists
if not exist "%PDF_FILE%" (
    echo ERROR: File not found: %PDF_FILE%
    pause
    exit /b 1
)

echo ========================================
echo PaddleOCR Post-Scan Processing
echo ========================================
echo File: %PDF_FILE%
echo.

REM Convert Windows path to WSL path
REM I:\FraScanner\papers\scan.pdf -> /mnt/i/FraScanner/papers/scan.pdf
REM Use wslpath to convert Windows path to WSL path (more reliable)
for /f "delims=" %%i in ('wsl wslpath "%PDF_FILE%"') do set "WSL_PDF_FILE=%%i"

REM Project root in WSL
set "PROJECT_ROOT=/home/eero_22/projects/research-tools"

REM API URL (localhost since we're on p1)
set "API_URL=http://localhost:8080"

REM Output directory
set "OUTPUT_DIR=/mnt/i/FraScanner/papers"

echo Converting path: %PDF_FILE%
echo To WSL path: %WSL_PDF_FILE%
echo.

REM Run the PaddleOCR client in WSL
echo Sending to PaddleOCR API...
echo.

wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd %PROJECT_ROOT% && python scripts/paddleocr_client.py \"%WSL_PDF_FILE%\" --api-url %API_URL% --output-dir %OUTPUT_DIR%"

REM Check if command succeeded
if errorlevel 1 (
    echo.
    echo ERROR: PaddleOCR processing failed
    echo Check the output above for details
    pause
    exit /b 1
)

echo.
echo ========================================
echo Processing complete!
echo ========================================
echo.

REM Keep terminal open so user can see the result
REM On success: close after 5 seconds
REM On error: pause and wait for user
if errorlevel 1 (
    echo.
    echo Press any key to close this window...
    pause >nul
) else (
    timeout /t 5 /nobreak >nul
)

endlocal

