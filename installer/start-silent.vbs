' QMT Gateway - silent launcher
'
' Started by the "QMT Gateway" Windows scheduled task at user logon.
'
' Delegates to start-silent.bat in the same directory:
'   - WshShell.Run with intWindowStyle=0 hides the cmd window;
'   - bWaitOnReturn=True blocks until python exits, so the bat's
'     exit /b %ERRORLEVEL% reaches the task scheduler's "Last Result".
'
' Both this file and start-silent.bat must live in an ASCII-only path.
' schtasks-launched cscript/wscript runs with a process locale where
' ANSI-based filesystem APIs (FindFirstFileA, GetFileAttributesA) cannot
' resolve CJK paths even if the system code page is 936, so vbs / bat
' shipped to a Chinese install directory fail to find anything there.
' The NSIS installer must therefore force an ASCII default INSTDIR.

Option Explicit

Const HIDDEN_WINDOW = 0
Const WAIT_FOR_PROCESS = True

Dim shell, fso, installDir, batPath, rc
Set shell = CreateObject("WScript.Shell")
Set fso   = CreateObject("Scripting.FileSystemObject")

installDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = installDir

batPath = installDir & "\start-silent.bat"

rc = shell.Run("""" & batPath & """", HIDDEN_WINDOW, WAIT_FOR_PROCESS)
WScript.Quit rc
