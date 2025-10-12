@echo off
REM ========================================
REM Paper Processor Daemon - Manual Start
REM Interactive session for scanning papers
REM ========================================
REM
REM This script starts the daemon in foreground mode.
REM Use this when you want to manually scan papers with full control.
REM
REM Usage:
REM   - Double-click this file to start
REM   - Scan your papers (they will be processed interactively)
REM   - Press Ctrl+C when done to stop daemon
REM   - Close window to stop daemon
REM
REM Author: Eero Olli
REM Date: October 12, 2025
REM ========================================

title Paper Processor Daemon - Interactive Mode

echo.
echo ========================================
echo Paper Processor Daemon
echo Interactive Mode
echo ========================================
echo.
echo Starting daemon...
echo.

REM Change to project directory and run daemon via WSL
cd /d "F:\prog\research-tools"
wsl bash -c "source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && python scripts/paper_processor_daemon.py"

REM If daemon exits with error, pause to show message
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [ERROR] Daemon stopped with error code %ERRORLEVEL%
    echo.
    pause
)

REM Normal exit (Ctrl-C or quit) - just close
exit /b 0

