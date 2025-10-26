' ========================================
' Paper Processor Daemon - VBS Launcher
' ========================================

' Show startup message
Set objShell = CreateObject("WScript.Shell")
objShell.Popup "Paper Processor Daemon Starting..." & vbCrLf & vbCrLf & _
              "If this is the first scan today, it takes a minute to get everything running." & vbCrLf & _
              "Please, be patient." & vbCrLf & vbCrLf & _
              "Processing the following scans will be fast." & vbCrLf & vbCrLf & _
              "You can close this window - the daemon will continue starting in the background.", 30, "Paper Processor Daemon", 64

' Launch the daemon in WSL
objShell.Run "wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && echo '========================================' && echo '  Paper Processor Daemon Starting...' && echo '========================================' && echo '' && python scripts/paper_processor_daemon.py --debug""", 1, False

' Exit immediately
WScript.Quit
