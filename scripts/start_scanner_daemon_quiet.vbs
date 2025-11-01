' ========================================
' Paper Processor Daemon - Quiet Auto-Start Launcher
' ========================================
' Use this for Epson scanner post-processing
' Very unobtrusive: only starts if daemon is not running
' No popups, no visible windows if daemon already running

Set objShell = CreateObject("WScript.Shell")

' Check if daemon is already running (quiet check, no output)
' This uses --status which exits with code 0 if running, 1 if not
' Run status check (hidden window, wait for completion)
exitCode = objShell.Run("wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py --status""", 0, True)

' If exit code is 0, daemon is already running - do nothing
If exitCode = 0 Then
    ' Daemon is running, exit silently
    WScript.Quit
End If

' Daemon is not running - start it with minimal window
' Use windowStyle 1 (normal window) so user can interact when prompts appear
' No popup message to be unobtrusive - just start the daemon
startCommand = "wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py"""
objShell.Run startCommand, 1, False

' Exit immediately (daemon runs in background)
WScript.Quit

