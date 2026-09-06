@echo off
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo ============================================
echo  Fulfillment CRM - Print Agent build
echo ============================================
echo.

where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Install Python 3.10+ from python.org
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

echo Building portable folder (recommended)...
venv\Scripts\pyinstaller build.spec --noconfirm --clean
if errorlevel 1 pause & exit /b 1

echo Building one-file (optional)...
venv\Scripts\pyinstaller build-onefile.spec --noconfirm --clean
if errorlevel 1 pause & exit /b 1

set OUT_DIR=dist\FulfillmentCRM-PrintAgent
set OUT_EXE=%OUT_DIR%\FulfillmentCRM-PrintAgent.exe
if not exist "%OUT_EXE%" (
  echo Build failed: %OUT_EXE% not found
  pause
  exit /b 1
)

set CRM_DL=..\frontend\public\downloads
if not exist "%CRM_DL%" mkdir "%CRM_DL%"

powershell -NoProfile -Command "Compress-Archive -Path '%OUT_DIR%' -DestinationPath 'dist\FulfillmentCRM-PrintAgent-portable.zip' -Force"
copy /Y "dist\FulfillmentCRM-PrintAgent-portable.zip" "%CRM_DL%\FulfillmentCRM-PrintAgent-portable.zip" >nul
copy /Y "dist\FulfillmentCRM-PrintAgent-onefile.exe" "%CRM_DL%\FulfillmentCRM-PrintAgent-onefile.exe" >nul
xcopy /E /I /Y "%OUT_DIR%" "%CRM_DL%\FulfillmentCRM-PrintAgent" >nul
copy /Y "install-agent.bat" "%CRM_DL%\install-agent.bat" >nul 2>nul
if exist "..\frontend\public\downloads\install-agent.bat" copy /Y "..\frontend\public\downloads\install-agent.bat" "%CRM_DL%\install-agent.bat" >nul

echo.
echo OK: %OUT_EXE%
echo ZIP: dist\FulfillmentCRM-PrintAgent-portable.zip
echo Copied to %CRM_DL%
echo.
pause
