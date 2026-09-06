@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "CRM=http://5.129.243.246:8080"
set "GITHUB=https://github.com/egurchenkovwallstreet-sys/fulfillment-crm/releases/download/print-agent/FulfillmentCRM-PrintAgent-portable.zip"
set "ZIP=%~dp0FulfillmentCRM-PrintAgent-portable.zip"
set "TARGET_DIR=%LOCALAPPDATA%\FulfillmentCRM\PrintAgent"
set "TARGET=%TARGET_DIR%\FulfillmentCRM-PrintAgent.exe"

echo ============================================
echo  Fulfillment CRM - установка агента печати
echo ============================================
echo.

if not exist "%SystemRoot%\System32\vcruntime140.dll" (
  echo Установите компонент Microsoft:
  start "" "https://aka.ms/vs/17/release/vc_redist.x64.exe"
  echo После установки запустите этот файл снова.
  pause
  exit /b 2
)

if exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
  echo Агент уже распакован рядом с bat - пропускаем скачивание.
  goto :install
)

echo [1/4] Скачивание агента...
del "%ZIP%" 2>nul
set "DL_OK=0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ProgressPreference='SilentlyContinue';" ^
  "try { Invoke-WebRequest -Uri '%CRM%/downloads/FulfillmentCRM-PrintAgent-portable.zip' -OutFile '%ZIP%' -UseBasicParsing; if ((Get-Item '%ZIP%').Length -gt 1000000) { exit 0 } else { exit 1 } } catch { exit 1 }"
if !ERRORLEVEL! equ 0 set "DL_OK=1"

if "!DL_OK!"=="0" (
  echo CRM не отдал файл - пробуем GitHub...
  del "%ZIP%" 2>nul
  powershell -NoProfile -ExecutionPolicy Bypass -Command ^
    "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%GITHUB%' -OutFile '%ZIP%' -UseBasicParsing"
  if exist "%ZIP%" (
    for %%A in ("%ZIP%") do if %%~zA gtr 1000000 set "DL_OK=1"
  )
)

if "!DL_OK!"=="0" (
  echo.
  echo [ОШИБКА] Не удалось скачать агент.
  echo Попросите администратора выполнить на сервере:
  echo cd /opt/fulfillment-crm ^&^& git pull ^&^& bash scripts/deploy.sh
  echo.
  pause
  exit /b 1
)

:install
if not exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
  echo [2/4] Распаковка...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%~dp0' -Force"
)

if not exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
  echo [ОШИБКА] В zip нет агента.
  pause
  exit /b 1
)

echo [3/4] Копирование...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
robocopy "%~dp0FulfillmentCRM-PrintAgent" "%TARGET_DIR%" /MIR /NFL /NDL /NJH /NJS /NC /NS >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%TARGET_DIR%' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
taskkill /F /IM FulfillmentCRM-PrintAgent.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [4/4] Запуск (до 90 сек)...
start "" "%TARGET%"
set "OK=0"
for /L %%i in (1,1,90) do (
  powershell -NoProfile -Command "try{(New-Object Net.WebClient).DownloadString('http://127.0.0.1:9123/health')|Out-Null; exit 0}catch{exit 1}" >nul 2>&1
  if !ERRORLEVEL! equ 0 set "OK=1" & goto :done
  timeout /t 1 /nobreak >nul
)

:done
echo.
if "!OK!"=="1" (
  echo [ГОТОВО] Агент работает. Иконка FF в трее.
) else (
  echo [ОШИБКА] Агент не ответил. Добавьте в исключения антивirus:
  echo %TARGET_DIR%
)
echo.
pause
exit /b 0
