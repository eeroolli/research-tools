' ========================================
' Paper Processor Daemon - VBS Launcher
' ========================================

' Show startup message
Set objShell = CreateObject("WScript.Shell")
objShell.Popup "Starting Paper Processor Daemon..." & vbCrLf & vbCrLf & _
              "A terminal window will appear where you can interact with the daemon." & vbCrLf & vbCrLf & _
              "KEEP THE TERMINAL WINDOW OPEN - you'll need it to approve each scan!", _
              10, "Paper Processor Daemon", 64

' Launch Windows Terminal with WSL and the daemon
' Using cmd /K keeps the window open even if the daemon exits
' The terminal window will remain visible for you to interact with
objShell.Run "cmd /K wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py --restart""", 1, False

' Exit VBS immediately (but the terminal window stays open)
WScript.Quit
