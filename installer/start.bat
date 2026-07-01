@echo off
chcp 65001 >nul 2>&1
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

rem 如果已有 gateway 在 .port 指向的端口上跑着，就只打开浏览器，不重复启动。
powershell.exe -NoProfile -Command "try{$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1', %GATEWAY_PORT%); $c.Close(); exit 0}catch{exit 1}" >nul 2>&1
if not errorlevel 1 (
    start "" "http://localhost:%GATEWAY_PORT%"
    endlocal
    exit /b 0
)

rem 端口没响应：gateway 没启动或已停止。先在后台启动等待就绪打开浏览器的
rem 任务，再在前台启动 gateway。浏览器在 gateway 监听端口后自动弹出。
start "" /B powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0wait-and-open-browser.ps1" -PortFile "%QMT_GATEWAY_HOME%\.port"

python\python.exe -m qmt_gateway
set "RC=%ERRORLEVEL%"
rem 退出码 2 = 另一个实例已在跑（被单实例锁拒绝）。
if not "%RC%"=="2" (
    if not "%RC%"=="0" (
        echo qmt-gateway 启动失败，退出码 %RC%
    )
)
endlocal & exit /b %RC%
