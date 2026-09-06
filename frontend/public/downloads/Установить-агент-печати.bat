@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

set "CRM=http://5.129.243.246:8080"
set "ZIP=%~dp0FulfillmentCRM-PrintAgent-portable.zip"
set "TARGET_DIR=%LOCALAPPDATA%\FulfillmentCRM\PrintAgent"
set "TARGET=%TARGET_DIR%\FulfillmentCRM-PrintAgent.exe"

echo ============================================
echo  Fulfillment CRM - установка агента печати
echo  Один файл - скачает и установит сам
echo ============================================
echo.

if not exist "%SystemRoot%\System32\vcruntime140.dll" (
  echo Установите компонент Microsoft:
  start "" "https://aka.ms/vs/17/release/vc_redist.x64.exe"
  echo После установки запустите этот файл снова.
  pause
  exit /b 2
)

echo [1/4] Скачивание агента с CRM...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '%CRM%/downloads/FulfillmentCRM-PrintAgent-portable.zip' -OutFile '%ZIP%' -UseBasicParsing"
if not exist "%ZIP%" (
  echo [ОШИБКА] Не скачался zip. Откройте %CRM% в браузере на этом ПК.
  pause
  exit /b 1
)

echo [2/4] Распаковка...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%ZIP%' -DestinationPath '%~dp0' -Force"
if not exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
  echo [ОШИБКА] В zip нет агента. Скачайте zip заново из CRM.
  pause
  exit /b 1
)

echo [3/4] Копирование в постоянную папку...
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
robocopy "%~dp0FulfillmentCRM-PrintAgent" "%TARGET_DIR%" /MIR /NFL /NDL /NJH /NJS /NC /NS >nul
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%TARGET_DIR%' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1
taskkill /F /IM FulfillmentCRM-PrintAgent.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo [4/4] Запуск агента (подождите до 90 сек)...
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
  echo [ГОТОВО] Агент работает. Иконка FF в трее Windows.
  echo В сборке FBS должно быть: Печать - имя принтера
) else (
  echo [ОШИБКА] Агент не ответил. Антивirus - добавьте в исключения:
  echo %TARGET_DIR%
)
echo.
pause
exit /b 0
