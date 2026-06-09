Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = CreateObject("Scripting.FileSystemObject").GetParentFolderName(WScript.ScriptFullName)
WshShell.Environment("Process").Item("QMT_GATEWAY_HOME") = WshShell.CurrentDirectory & "\data\home"
WshShell.Environment("Process").Item("PYTHONUTF8") = "1"
WshShell.Environment("Process").Item("PYTHONPATH") = WshShell.CurrentDirectory & "\app;" & WshShell.CurrentDirectory & "\python\Lib\site-packages"
WshShell.Run """" & WshShell.CurrentDirectory & "\python\python.exe"" -m qmt_gateway", 0, False
