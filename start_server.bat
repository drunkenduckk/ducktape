@echo off
setlocal enabledelayedexpansion
set PORT=8080

echo Checking for stale process on port %PORT%...
for /f "tokens=5" %%p in ('netstat -aon ^| findstr :%PORT% ^| findstr LISTENING') do (
    echo Killing stale PID %%p on port %PORT%
    taskkill /F /PID %%p >nul 2>&1
)

cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo Python not found on PATH. Install Python 3.9+ and re-run.
    pause
    exit /b 1
)

echo Starting LAN Transfer server on port %PORT%...
python server.py

pause
