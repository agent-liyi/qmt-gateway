@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  call "%~dp0setup-venv.bat"
  if errorlevel 1 exit /b %errorlevel%
)

call ".venv\Scripts\activate.bat"
if not defined QMT_GATEWAY_HOME set "QMT_GATEWAY_HOME=%~dp0data\home"
if not defined QMT_GATEWAY_HOST set "QMT_GATEWAY_HOST=0.0.0.0"
if not defined QMT_GATEWAY_PORT set "QMT_GATEWAY_PORT=8130"
set "PYTHONUTF8=1"

echo [qmt-gateway] home=%QMT_GATEWAY_HOME%
echo [qmt-gateway] starting http://%QMT_GATEWAY_HOST%:%QMT_GATEWAY_PORT%
echo [qmt-gateway] press Ctrl+C to stop
python -m uvicorn qmt_gateway.app:app --host %QMT_GATEWAY_HOST% --port %QMT_GATEWAY_PORT%
set "EXIT_CODE=%ERRORLEVEL%"
endlocal & exit /b %EXIT_CODE%
