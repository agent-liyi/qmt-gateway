@echo off
cd /d "%~dp0"
set "QMT_GATEWAY_HOME=%~dp0data\home"
set "PYTHONUTF8=1"
start "" "http://localhost:8130"
.venv\Scripts\python.exe -m qmt_gateway
