' ========================================
' Paper Processor Daemon - Quiet Auto-Start Launcher
' ========================================
' Use this for Epson scanner post-processing
' Very unobtrusive: only starts if daemon is not running
' No popups, no visible windows if daemon already running
'
Set objShell = CreateObject("WScript.Shell")

' Configuration for Windows and WSL environments
Const PROJECT_DIR_WIN = "F:\prog\research-tools"
Const CONDA_ENV_WIN = "research-tools-win"
Const CONDA_ACTIVATE_PATH = "%USERPROFILE%\miniconda3\Scripts\activate.bat"

' Function to check if a visible terminal window is already running the daemon
' This checks for cmd.exe or WindowsTerminal.exe processes with the daemon script in command line
Function HasVisibleDaemonTerminal()
    On Error Resume Next
    Set objWMIService = GetObject("winmgmts:\\.\root\cimv2")
    
    ' Check for cmd.exe processes (which host visible terminal windows)
    ' Look for command lines containing both "wsl" and "paper_processor_daemon.py"
    ' but NOT containing "--status" (which is our check command, not the actual daemon)
    Set colProcesses = objWMIService.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'cmd.exe' OR Name = 'WindowsTerminal.exe'")
    
    For Each objProcess in colProcesses
        Dim cmdLine
        cmdLine = LCase(objProcess.CommandLine)
        ' Check if this is a terminal running the daemon (not just a status check)
        If InStr(cmdLine, "paper_processor_daemon.py") > 0 And InStr(cmdLine, "--status") = 0 And (InStr(cmdLine, "wsl") > 0 Or InStr(cmdLine, "bash") > 0) Then
            ' Found a visible terminal running the daemon
            HasVisibleDaemonTerminal = True
            Exit Function
        End If
    Next
    
    ' Also check for wsl.exe processes directly (in case cmd wrapper isn't used)
    Set colWslProcesses = objWMIService.ExecQuery("SELECT CommandLine FROM Win32_Process WHERE Name = 'wsl.exe'")
    For Each objProcess in colWslProcesses
        Dim wslCmdLine
        wslCmdLine = LCase(objProcess.CommandLine)
        If InStr(wslCmdLine, "paper_processor_daemon.py") > 0 And InStr(wslCmdLine, "--status") = 0 Then
            HasVisibleDaemonTerminal = True
            Exit Function
        End If
    Next
    
    HasVisibleDaemonTerminal = False
    On Error GoTo 0
End Function

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

' First check: Is daemon process running?
' This uses --status which exits with code 0 if running, 1 if not
' Run status check (hidden window, wait for completion)
Dim statusCmd, exitCode
If CanUseWindowsConda() Then
    statusCmd = "cmd /C """ & CONDA_ACTIVATE_PATH & """ " & CONDA_ENV_WIN & " && cd /D " & PROJECT_DIR_WIN & " && python scripts\paper_processor_daemon.py --status"
    exitCode = objShell.Run(statusCmd, 0, True)
Else
    exitCode = objShell.Run("wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py --status""", 0, True)
End If

' If exit code is 0, daemon process is running
If exitCode = 0 Then
    ' Second check: Is there already a visible terminal window?
    If HasVisibleDaemonTerminal() Then
        ' Both daemon is running AND terminal window exists - exit silently
        WScript.Quit
    Else
        ' Daemon is running but no visible terminal - don't open one
        ' (User might have started it in background or another way)
        WScript.Quit
    End If
End If

' Daemon is not running - start it with minimal window
' Use windowStyle 1 (normal window) so user can interact when prompts appear
' No popup message to be unobtrusive - just start the daemon
Dim startCommand
If CanUseWindowsConda() Then
    startCommand = "cmd /K """ & CONDA_ACTIVATE_PATH & """ " & CONDA_ENV_WIN & " && cd /D " & PROJECT_DIR_WIN & " && python scripts\paper_processor_daemon.py"
Else
    startCommand = "wsl -e bash -c ""source ~/miniconda3/etc/profile.d/conda.sh && conda activate research-tools && cd /mnt/f/prog/research-tools && python scripts/paper_processor_daemon.py"""
End If
objShell.Run startCommand, 1, False

' Exit immediately (daemon runs in background)
WScript.Quit

