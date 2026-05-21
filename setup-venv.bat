@echo off
setlocal
cd /d "%~dp0"

set "UV_EXE=%APPDATA%\Python\Python313\Scripts\uv.exe"
if not exist "%UV_EXE%" set "UV_EXE=C:\Users\aaron\AppData\Roaming\Python\Python313\Scripts\uv.exe"
if not exist "%UV_EXE%" (
  echo [qmt-gateway] uv.exe not found. Install it first with:
  echo C:\Users\aaron\miniconda3\envs\qmt\python.exe -m pip install --user uv
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [qmt-gateway] creating .venv...
  "%UV_EXE%" venv .venv --python C:\Users\aaron\miniconda3\envs\qmt\python.exe
  if errorlevel 1 exit /b %errorlevel%
)

echo [qmt-gateway] syncing dependencies...
"%UV_EXE%" sync --python .venv\Scripts\python.exe --all-groups
exit /b %errorlevel%
