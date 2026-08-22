@echo off
setlocal
cd /d "%~dp0"

echo Fulfillment CRM - Print Agent (dev mode)
echo For production .exe run build.bat
echo.

if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 (
    echo Install Python 3.11+ from python.org
    pause
    exit /b 1
  )
)

venv\Scripts\pip install -q -r requirements.txt
if errorlevel 1 pause & exit /b 1

if not exist "%APPDATA%\FulfillmentCRM\PrintAgent\config.json" (
  if not exist config.json copy config.example.json config.json >nul
)

echo Starting agent with tray icon...
venv\Scripts\python agent_main.py --tray
pause
