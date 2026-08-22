@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Fulfillment CRM - Print Agent build
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install Python 3.11+ from python.org
  pause
  exit /b 1
)

if not exist venv\Scripts\python.exe (
  echo Creating virtual environment...
  python -m venv venv
  if errorlevel 1 pause & exit /b 1
)

echo Installing dependencies...
venv\Scripts\pip install -q -r requirements.txt -r requirements-build.txt
if errorlevel 1 pause & exit /b 1

if not exist assets\icon.ico (
  echo Creating icon...
  venv\Scripts\python create_icon.py
)

echo Building .exe (PyInstaller)...
venv\Scripts\pyinstaller build.spec --noconfirm --clean
if errorlevel 1 pause & exit /b 1

set OUT=dist\FulfillmentCRM-PrintAgent.exe
if not exist "%OUT%" (
  echo Build failed: %OUT% not found
  pause
  exit /b 1
)

set CRM_DL=..\frontend\public\downloads
if not exist "%CRM_DL%" mkdir "%CRM_DL%"
copy /Y "%OUT%" "%CRM_DL%\FulfillmentCRM-PrintAgent.exe" >nul

echo.
echo OK: %OUT%
echo Copied to %CRM_DL%\FulfillmentCRM-PrintAgent.exe
echo.
for %%A in ("%OUT%") do echo Size: %%~zA bytes
echo.
pause
