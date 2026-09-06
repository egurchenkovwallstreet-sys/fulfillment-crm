@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================
echo  Fulfillment CRM - Chrome autoprint FBS
echo ============================================
echo.

set "VBS=%~dp0install-kiosk-chrome.vbs"
set "PS1=%~dp0install-kiosk-chrome.ps1"

if exist "%VBS%" (
  echo Running installer: install-kiosk-chrome.vbs
  echo.
  cscript //nologo "%VBS%"
  set "RC=%ERRORLEVEL%"
  goto :finish
)

if exist "%PS1%" (
  echo Running installer: install-kiosk-chrome.ps1
  echo.
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
  set "RC=%ERRORLEVEL%"
  goto :finish
)

echo [ERROR] install-kiosk-chrome.vbs not found in this folder.
echo.
echo Download BOTH files from CRM into one folder:
echo   - install-kiosk-chrome.bat
echo   - install-kiosk-chrome.vbs
echo.
echo Or double-click install-kiosk-chrome.vbs directly.
echo.
set "RC=1"

:finish
echo.
if not "%RC%"=="0" (
  echo If Windows blocked the file: More info - Run anyway.
  echo Desktop may be synced to OneDrive - check Downloads folder too.
)
pause
exit /b %RC%
endlocal
