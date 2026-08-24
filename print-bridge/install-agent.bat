@echo off
setlocal
cd /d "%~dp0"

echo Fulfillment CRM - установка агента печати
echo.

set "AGENT=%~dp0FulfillmentCRM-PrintAgent.exe"
if not exist "%AGENT%" (
  echo Положите FulfillmentCRM-PrintAgent.exe в эту же папку.
  pause
  exit /b 1
)

echo Запуск агента...
start "" "%AGENT%"

timeout /t 3 /nobreak >nul
echo.
echo Откройте в браузере: http://127.0.0.1:9123/health
echo Журнал: %%APPDATA%%\FulfillmentCRM\PrintAgent\agent.log
echo.
echo В config.json укажите default_printer — точное имя из Windows.
pause
