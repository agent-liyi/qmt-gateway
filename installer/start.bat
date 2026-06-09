@echo off
cd /d "%~dp0"
set "QMT_GATEWAY_HOME=%~dp0data\home"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0app;%~dp0python\Lib\site-packages"
set "PATH=%~dp0python;%PATH%"
start "" "http://localhost:8130"
python\python.exe -m qmt_gateway
