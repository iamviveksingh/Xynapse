@echo off
setlocal
title XYNAPSE // IBVAP - Tactical Perimeter Surveillance Command Center
color 0b

echo ===============================================================================
echo        XYNAPSE // INTELLIGENT BORDER VIDEO ANALYTICS PLATFORM (IBVAP)
echo      Tactical Perimeter Defense, Biometric Recognition & ANPR Command Center
echo ===============================================================================
echo.

cd /d "%~dp0"

:: 1. Clean up lingering zombie processes on ports 8000 (Backend) and 5175 (Frontend)
echo [*] Clearing ports 8000 and 5175...
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000,5175 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

:: 2. Locate Python virtual environment (checks local .venv, then parent .venv)
echo [*] Checking Python Virtual Environment (.venv)...
set "PYTHON_EXE="
if exist "%~dp0.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0.venv\Scripts\python.exe"
) else if exist "%~dp0..\.venv\Scripts\python.exe" (
    set "PYTHON_EXE=%~dp0..\.venv\Scripts\python.exe"
) else (
    echo [ERROR] Virtual environment not found.
    echo Please create a virtual environment: python -m venv .venv
    echo and install dependencies: .venv\Scripts\pip install -r requirements.txt
    pause
    exit /b 1
)

:: 3. Start FastAPI AI Backend
echo [*] Launching FastAPI AI Backend on http://127.0.0.1:8000...
start "XYNAPSE Backend Server (FastAPI / AI Pipeline / ANPR)" cmd /k ""%PYTHON_EXE%" -m uvicorn backend.main:app --host 0.0.0.0 --port 8000"

:: 4. Brief delay to allow FastAPI models and database to pre-warm
echo [*] Initializing AI models and database ledger...
timeout /t 3 /nobreak >nul

:: 5. Start Vite React Frontend HUD
echo [*] Launching Vite React Frontend on http://localhost:5175...
cd /d "%~dp0frontend"
start "XYNAPSE Frontend Dashboard (Vite / React HUD)" cmd /k "npm.cmd run dev"

:: 6. Brief delay for Vite HMR server
timeout /t 2 /nobreak >nul

:: 7. Launch browser at Command & Control Dashboard
echo [*] Opening Command & Control HUD in browser...
start http://localhost:5175

echo.
echo ===============================================================================
echo [SUCCESS] XYNAPSE Surveillance System is ONLINE!
echo  - Command Center HUD:     http://localhost:5175
echo  - Backend API & Models:   http://localhost:8000 (Interactive docs at /docs)
echo.
echo Leave the opened terminal windows running during your operation/demo.
echo To shut down all services, close the terminal windows or press Ctrl+C in them.
echo ===============================================================================
echo.
pause
