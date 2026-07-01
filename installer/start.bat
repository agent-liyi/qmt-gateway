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

:: 端口没响应——可能是 gateway 没启动（用户刚从托盘"停止"过，.port 已被
:: atexit 删掉），也可能是上一个实例崩了。先在后台启动一个"等待就绪并打开
:: 浏览器"的任务，再在前台启动 gateway——这样 gateway 的日志留在当前控制
:: 台窗口，浏览器在 gateway 监听端口后自动弹出。旧实现是在启动 gateway
:: 之前就 start 浏览器，结果浏览器先于 gateway 就绪弹出，显示"无法连接"。
::
:: .port 可能因为 8130 被占用而指向 8131-8139，所以等待结束后重新读取，
:: 而不是沿用启动前的值。
start "" /B powershell.exe -NoProfile -ExecutionPolicy Bypass -Command ^
  "$portFile='%QMT_GATEWAY_HOME%\.port';" ^
  "$w=0;" ^
  "while($w -lt 15){" ^
    "if(Test-Path -LiteralPath $portFile){$r=Get-Content -LiteralPath $portFile -ErrorAction SilentlyContinue; if($r -match '^\d+$'){break}}" ^
    "Start-Sleep -Seconds 1; $w++" ^
  "};" ^
  "$port=8130; if(Test-Path -LiteralPath $portFile){$r=Get-Content -LiteralPath $portFile -ErrorAction SilentlyContinue; if($r -match '^\d+$'){$port=[int]$r}};" ^
  "$w=0;" ^
  "while($w -lt 30){" ^
    "try{$c=New-Object Net.Sockets.TcpClient; $c.Connect('127.0.0.1',$port); $c.Close(); start \"\" \"http://localhost:$port\"; exit 0}catch{}; Start-Sleep -Seconds 1; $w++" ^
  "}"
python\python.exe -m qmt_gateway
set "RC=%ERRORLEVEL%"
:: 退出码 2 = 另一个实例已在跑（被单实例锁拒绝）。浏览器由上面的等待逻辑
:: 打开，不需要提示用户出错。
if not "%RC%"=="2" (
    if not "%RC%"=="0" (
        echo qmt-gateway 启动失败，退出码 %RC%
    )
)
endlocal & exit /b %RC%
