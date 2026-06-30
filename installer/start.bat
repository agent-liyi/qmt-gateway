@echo off
cd /d "%~dp0"
setlocal
set "QMT_GATEWAY_HOME=%~dp0data\home"
set "PYTHONUTF8=1"
set "PYTHONPATH=%~dp0app;%~dp0python\Lib\site-packages"
set "PATH=%~dp0python;%PATH%"

set "GATEWAY_PORT=8130"
if exist "%QMT_GATEWAY_HOME%\.port" (
    set /p GATEWAY_PORT=<"%QMT_GATEWAY_HOME%\.port"
)

:: 如果已有 gateway 在 .port 指向的端口上跑着，就只打开浏览器，不重复启动。
:: 重复启动会让 mini-qmt 同时收到多个 session_id 的连接，互相挤掉，导致
:: UI 一直显示"未连接"。脚本里用纯 PowerShell 探活，避免拉起额外的 exe。
powershell.exe -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', %GATEWAY_PORT%); $c.Close(); exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    start "" "http://localhost:%GATEWAY_PORT%"
    endlocal
    exit /b 0
)

start "" "http://localhost:%GATEWAY_PORT%"
python\python.exe -m qmt_gateway
set "RC=%ERRORLEVEL%"
:: 退出码 2 = 另一个实例已在跑（被单实例锁拒绝）。浏览器已经打开，
:: 不需要提示用户出错。
if not "%RC%"=="2" (
    if not "%RC%"=="0" (
        echo qmt-gateway 启动失败，退出码 %RC%
    )
)
endlocal & exit /b %RC%
