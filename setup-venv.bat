@echo off
setlocal
cd /d "%~dp0"

REM ============================================================
REM  setup-venv.bat — Create .venv and install dependencies.
REM
REM  Detects Python automatically from PATH, py launcher, or
REM  common installation directories.  No external tools (uv,
REM  conda) required — uses only the built-in venv + pip.
REM ============================================================

REM --- 1. Find a Python 3.13+ interpreter ----------------------
set "PY_EXE="

REM 1a. Check PATH
for /f "delims=" %%i in ('where python 2^>nul') do (
  if not defined PY_EXE (
    "%%i" -c "import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)" >nul 2>&1
    if not errorlevel 1 set "PY_EXE=%%i"
  )
)

REM 1b. Check py launcher (ships with official Python installer)
if not defined PY_EXE (
  py -3.13 -c "import sys; sys.exit(0)" >nul 2>&1
  if not errorlevel 1 set "PY_EXE=py -3.13"
)

REM 1c. Scan common installation directories
if not defined PY_EXE (
  for %%d in (
    "%LOCALAPPDATA%\Programs\Python\Python313"
    "%LOCALAPPDATA%\Programs\Python\Python314"
    "%ProgramFiles%\Python313"
    "%ProgramFiles%\Python314"
    "C:\Python313"
    "C:\Python314"
  ) do (
    if exist "%%~d\python.exe" (
      if not defined PY_EXE set "PY_EXE=%%~d\python.exe"
    )
  )
)

REM 1d. Scan miniconda / anaconda base environments
if not defined PY_EXE (
  for %%d in (
    "%USERPROFILE%\miniconda3"
    "%USERPROFILE%\anaconda3"
    "%ProgramData%\miniconda3"
    "%ProgramData%\anaconda3"
  ) do (
    if exist "%%~d\python.exe" (
      "%%~d\python.exe" -c "import sys; sys.exit(0 if sys.version_info >= (3,13) else 1)" >nul 2>&1
      if not errorlevel 1 (
        if not defined PY_EXE set "PY_EXE=%%~d\python.exe"
      )
    )
  )
)

if not defined PY_EXE (
  echo [qmt-gateway] ERROR: Python 3.13+ not found.
  echo.
  echo Please install Python 3.13+ from https://www.python.org/downloads/
  echo Make sure to check "Add Python to PATH" during installation.
  exit /b 1
)

echo [qmt-gateway] using Python: %PY_EXE%

REM --- 2. Create venv ------------------------------------------
if not exist ".venv\Scripts\python.exe" (
  echo [qmt-gateway] creating virtual environment...
  %PY_EXE% -m venv .venv
  if errorlevel 1 (
    echo [qmt-gateway] ERROR: failed to create .venv
    exit /b 1
  )
)

REM --- 3. Install / upgrade the package + dependencies ----------
echo [qmt-gateway] installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -e ".[dev]" --quiet
if errorlevel 1 (
  echo [qmt-gateway] WARNING: pip install with [dev] failed, trying without dev deps...
  ".venv\Scripts\python.exe" -m pip install -e . --quiet
  if errorlevel 1 (
    echo [qmt-gateway] ERROR: dependency installation failed
    exit /b 1
  )
)

echo [qmt-gateway] setup complete.
exit /b 0
