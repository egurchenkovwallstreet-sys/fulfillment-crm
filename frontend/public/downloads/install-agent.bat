@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================
echo  Fulfillment CRM — установка агента печати
echo ============================================
echo.

set "SOURCE=%~dp0FulfillmentCRM-PrintAgent.exe"
if not exist "%SOURCE%" (
  echo [ОШИБКА] Не найден FulfillmentCRM-PrintAgent.exe в этой папке.
  echo.
  echo 1. Скачайте агент в CRM: Меню - Агент печати - Скачать .exe
  echo 2. Положите exe рядом с этим файлом install-agent.bat
  echo 3. Запустите install-agent.bat от имени обычного пользователя
  echo.
  pause
  exit /b 1
)

set "TARGET_DIR=%LOCALAPPDATA%\FulfillmentCRM\PrintAgent"
set "TARGET=%TARGET_DIR%\FulfillmentCRM-PrintAgent.exe"

echo Копирование в постоянную папку:
echo %TARGET%
if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"
copy /Y "%SOURCE%" "%TARGET%" >nul
if errorlevel 1 (
  echo [ОШИБКА] Не удалось скопировать файл. Закройте агент, если он уже запущен.
  pause
  exit /b 1
)

echo Снятие блокировки Windows (файл из интернета)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Unblock-File -LiteralPath '%TARGET%' -ErrorAction SilentlyContinue" >nul 2>&1

echo Проверка, не запущен ли агент...
tasklist /FI "IMAGENAME eq FulfillmentCRM-PrintAgent.exe" 2>nul | find /I "FulfillmentCRM-PrintAgent.exe" >nul
if not errorlevel 1 (
  echo Агент уже запущен — перезапуск...
  taskkill /F /IM FulfillmentCRM-PrintAgent.exe >nul 2>&1
  timeout /t 2 /nobreak >nul
)

echo Запуск агента...
start "" "%TARGET%"

echo Ожидание ответа http://127.0.0.1:9123/health ...
set "OK=0"
for /L %%i in (1,1,20) do (
  powershell -NoProfile -Command "try { (Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 'http://127.0.0.1:9123/health').StatusCode -eq 200 } catch { $false }" | findstr /I "True" >nul
  if not errorlevel 1 set "OK=1" & goto :health_ok
  timeout /t 1 /nobreak >nul
)

:health_ok
echo.
if "%OK%"=="1" (
  echo [УСПЕХ] Агент печати установлен и работает.
  echo.
  echo - Иконка FF в трее Windows ^(возможно под стрелкой ^^)
  echo - Проверка: http://127.0.0.1:9123/health
  echo - Журнал: %APPDATA%\FulfillmentCRM\PrintAgent\agent.log
  echo - В сборке FBS должно быть: Печать: имя принтера
  echo.
  start "" "http://127.0.0.1:9123/health"
) else (
  echo [ОШИБКА] Агент не отвечает на порту 9123.
  echo.
  echo Частые причины:
  echo  1. Windows SmartScreen — Подробнее - Выполнить в любом случае
  echo  2. Антивирус заблокировал exe — добавьте в исключения:
  echo     %TARGET%
  echo  3. Нет Microsoft Visual C++ Redistributable 2015-2022 x64
  echo     https://aka.ms/vs/17/release/vc_redist.x64.exe
  echo.
  echo Откройте журнал:
  echo %APPDATA%\FulfillmentCRM\PrintAgent\agent.log
  if exist "%APPDATA%\FulfillmentCRM\PrintAgent\agent.log" (
    start notepad "%APPDATA%\FulfillmentCRM\PrintAgent\agent.log"
  )
)

echo.
pause
endlocal
