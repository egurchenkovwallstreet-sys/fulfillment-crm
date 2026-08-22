@echo off
setlocal
cd /d "%~dp0"

if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 (
    echo Install Python 3.11+ from python.org
    pause
    exit /b 1
  )
)

echo Installing dependencies...
venv\Scripts\pip install -r requirements.txt
if errorlevel 1 pause & exit /b 1

if not exist config.json (
  copy config.example.json config.json >nul
  echo Created config.json — set default_printer to your Xprinter name.
)

echo.
echo Starting print bridge on http://127.0.0.1:9123
echo Set this printer as default in Windows or edit config.json
echo.
venv\Scripts\python server.py
pause
