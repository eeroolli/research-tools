@echo off
REM Wrapper batch file to run PowerShell script with execution policy bypass
REM Run this as Administrator on Windows (p1's host)

PowerShell -ExecutionPolicy Bypass -File "%~dp0setup_wsl_ssh_forward.ps1"

pause

