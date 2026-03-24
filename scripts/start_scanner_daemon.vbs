' ========================================
' Paper Processor Daemon - VBS Launcher
' ========================================

' Show startup message
Set objShell = CreateObject("WScript.Shell")

' Configuration for Windows and WSL environments
Const PROJECT_DIR_WIN = "F:\prog\research-tools"
Const CONDA_ENV_WIN = "research-tools-win"
Const CONDA_ACTIVATE_PATH = "%USERPROFILE%\miniconda3\Scripts\activate.bat"
Const WSL_DAEMON_CMD = "cmd /K wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py --restart"""

objShell.Popup "Starting Paper Processor Daemon..." & vbCrLf & vbCrLf & _
              "A terminal window will appear where you can interact with the daemon." & vbCrLf & vbCrLf & _
              "KEEP THE TERMINAL WINDOW OPEN - you'll need it to approve each scan!", _
              10, "Paper Processor Daemon", 64

' Test whether the Windows Conda environment is available
Function CanUseWindowsConda()
    Dim testCmd, exitCode
    testCmd = "cmd /C """ & CONDA_ACTIVATE_PATH & """ " & CONDA_ENV_WIN
    exitCode = objShell.Run(testCmd, 0, True)
    If exitCode = 0 Then
        CanUseWindowsConda = True
    Else
        CanUseWindowsConda = False
    End If
End Function

' Start daemon in preferred environment: Windows Conda first, then WSL as fallback
Sub StartDaemonInteractive()
    Dim winCmd
    If CanUseWindowsConda() Then
        winCmd = "cmd /K """ & CONDA_ACTIVATE_PATH & """ " & CONDA_ENV_WIN & " && cd /D " & PROJECT_DIR_WIN & " && python scripts\paper_processor_daemon.py --restart"
        objShell.Run winCmd, 1, False
    Else
        objShell.Run WSL_DAEMON_CMD, 1, False
    End If
End Sub

StartDaemonInteractive

' Exit VBS immediately (but the terminal window stays open)
WScript.Quit
