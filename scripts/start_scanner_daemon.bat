@echo off
REM ========================================
REM Paper Processor Daemon Launcher
REM Called by Epson Capture Pro after scan
REM ========================================
REM
REM This script is triggered by Epson Capture Pro after saving a PDF.
REM It checks if the daemon is running and starts it if needed.
REM The daemon watches /mnt/i/FraScanner/papers/ for new PDFs.
REM
REM Author: Eero Olli
REM Date: October 11, 2025
REM ========================================

echo.
echo ========================================
echo Paper Processor Daemon Launcher
echo ========================================
echo.

REM Get script directory and convert to WSL path format
REM %~dp0 gives us the script's directory (e.g., F:\prog\research-tools\scripts\)
set SCRIPT_PATH=%~dp0start_paper_processor.py

REM Convert Windows path to WSL path using wslpath
for /f "delims=" %%i in ('wsl wslpath -u "%SCRIPT_PATH%"') do set WSL_SCRIPT_PATH=%%i

REM Call WSL with conda activation and run the daemon launcher
wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python '%WSL_SCRIPT_PATH%'"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo [OK] Daemon check complete
    echo.
) else (
    echo.
    echo [WARNING] Daemon start returned error code %ERRORLEVEL%
    echo.
    pause
)

REM Exit silently
exit /b 0

