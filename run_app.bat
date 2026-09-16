@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0run_app.ps1"
if errorlevel 1 (
    echo.
    echo Swimmer Tracker failed to start. See the error above.
    pause
)
endlocal
