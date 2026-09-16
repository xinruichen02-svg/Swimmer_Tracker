@echo off
setlocal
chcp 65001 >nul 2>&1
set "PYTHONUTF8=1"
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_app.ps1" %*
if errorlevel 1 (
    echo.
    echo Swimmer Tracker failed to start. See the error above.
    pause
)
endlocal
