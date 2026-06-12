@echo off
:: Internal launcher invoked by start-silent.vbs (which is invoked by the
:: "QMT Gateway" scheduled task at logon).
::
:: This .bat is separate from start.bat because:
::   - start.bat is the user-facing manual / debug launcher that opens
::     the browser and runs in a visible console;
::   - this file never opens a browser, never prints to a console, and
::     appends stdout/stderr to logs\task-launcher.log so logon-time
::     crashes are recoverable.
::
:: Do not invoke directly; use start-silent.vbs.
::
:: This file (and start-silent.vbs) must live in an ASCII-only install
:: path - schtasks-launched cscript/wscript cannot resolve CJK paths
:: through the ANSI filesystem APIs.

setlocal
cd /d "%~dp0"

if not exist "%~dp0logs" mkdir "%~dp0logs"

>> "%~dp0logs\task-launcher.log" echo [%DATE% %TIME%] start-silent.bat entry

set "QMT_GATEWAY_HOME=%~dp0data\home"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0app;%~dp0python\Lib\site-packages"
set "PATH=%~dp0python;%PATH%"

"%~dp0python\python.exe" -m qmt_gateway >> "%~dp0logs\task-launcher.log" 2>&1
set "RC=%ERRORLEVEL%"
>> "%~dp0logs\task-launcher.log" echo [%DATE% %TIME%] start-silent.bat exit rc=%RC%
endlocal & exit /b %RC%
