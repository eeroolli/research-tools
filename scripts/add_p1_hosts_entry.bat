@echo off
REM Wrapper batch file to run PowerShell script with execution policy bypass
REM Run this as Administrator on blacktower

PowerShell -ExecutionPolicy Bypass -File "%~dp0add_p1_hosts_entry.ps1"

pause

