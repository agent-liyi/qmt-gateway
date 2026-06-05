@echo off
echo ================================================
echo   QMT Gateway - Uninstall
echo ================================================
echo.

:: Stop running processes
echo Stopping QMT Gateway processes...
taskkill /F /IM "qmt-gateway.exe" 2>nul
taskkill /F /IM "python.exe" /FI "WINDOWTITLE eq QMT*" 2>nul

:: Remove scheduled task
echo Removing auto-start task...
schtasks /delete /tn "QMT Gateway" /f 2>nul

:: Remove firewall rule
echo Removing firewall rule...
netsh advfirewall firewall delete rule name="QMT Gateway" 2>nul

:: Remove shortcuts
echo Removing shortcuts...
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\QMT Gateway"
if exist "%STARTMENU%" (
    rmdir /s /q "%STARTMENU%"
)
if exist "%USERPROFILE%\Desktop\QMT Gateway.lnk" (
    del /q "%USERPROFILE%\Desktop\QMT Gateway.lnk"
)

:: Ask about data directory
echo.
set /p DELDATA="Delete data directory? (y/N): "
if /i "%DELDATA%"=="y" (
    echo Deleting data directory...
    if exist "%~dp0data" rmdir /s /q "%~dp0data"
) else (
    echo Keeping data directory.
)

:: Remove install directory
echo Removing installation directory...
cd /d "%TEMP%"
rmdir /s /q "%~dp0" 2>nul

echo.
echo Uninstall complete.
pause
