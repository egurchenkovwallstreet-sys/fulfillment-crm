@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >nul 2>&1
cd /d "%~dp0"

echo ============================================
echo  Fulfillment CRM — установка агента печати
echo ============================================
echo.

set "TARGET_DIR=%LOCALAPPDATA%\FulfillmentCRM\PrintAgent"
set "TARGET=%TARGET_DIR%\FulfillmentCRM-PrintAgent.exe"
set "LOG=%APPDATA%\FulfillmentCRM\PrintAgent\agent.log"

if not exist "%SystemRoot%\System32\vcruntime140.dll" (
  echo [ВНИМАНИЕ] Не найден Microsoft Visual C++ Redistributable x64.
  echo Скачайте и установите, затем запустите этот файл снова:
  echo https://aka.ms/vs/17/release/vc_redist.x64.exe
  echo.
  start "" "https://aka.ms/vs/17/release/vc_redist.x64.exe"
  pause
  exit /b 2
)

set "SOURCE_EXE="
set "SOURCE_DIR="

if exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
  set "SOURCE_DIR=%~dp0FulfillmentCRM-PrintAgent"
)
if exist "%~dp0FulfillmentCRM-PrintAgent-portable.zip" (
  echo Распаковка FulfillmentCRM-PrintAgent-portable.zip ...
  powershell -NoProfile -ExecutionPolicy Bypass -Command "Expand-Archive -LiteralPath '%~dp0FulfillmentCRM-PrintAgent-portable.zip' -DestinationPath '%~dp0' -Force" >nul 2>&1
  if exist "%~dp0FulfillmentCRM-PrintAgent\FulfillmentCRM-PrintAgent.exe" (
    set "SOURCE_DIR=%~dp0FulfillmentCRM-PrintAgent"
  )
)
if "%SOURCE_DIR%"=="" if exist "%~dp0FulfillmentCRM-PrintAgent.exe" set "SOURCE_EXE=%~dp0FulfillmentCRM-PrintAgent.exe"
if "%SOURCE_DIR%"=="" if exist "%~dp0FulfillmentCRM-PrintAgent-onefile.exe" set "SOURCE_EXE=%~dp0FulfillmentCRM-PrintAgent-onefile.exe"

if "%SOURCE_DIR%"=="" if "%SOURCE_EXE%"=="" (
  echo [ОШИБКА] Не найден агент печати в этой папке.
  echo.
  echo Скачайте в CRM - Агент печати:
  echo   1. FulfillmentCRM-PrintAgent-portable.zip  ^(рекомендуется для старых ПК^)
  echo   2. install-agent.bat
  echo Положите zip и bat в одну папку и запустите install-agent.bat
  echo.
  pause
  exit /b 1
)

echo Установка в:
echo %TARGET_DIR%
echo.

if not exist "%TARGET_DIR%" mkdir "%TARGET_DIR%"

if not "%SOURCE_DIR%"=="" (
  echo Копирование папки агента ^(быстрый запуск на старых ПК^)...
  robocopy "%SOURCE_DIR%" "%TARGET_DIR%" /MIR /NFL /NDL /NJH /NJS /NC /NS >nul
  if errorlevel 8 (
    echo [ОШИБКА] Не удалось скопировать файлы. Закройте агент, если он запущен.
    pause
    exit /b 1
  )
) else (
  echo Копирование одного exe ^(первый запуск может занять до 1 минуты^)...
  copy /Y "%SOURCE_EXE%" "%TARGET%" >nul
  if errorlevel 1 (
    echo [ОШИБКА] Не удалось скопировать exe.
    pause
    exit /b 1
  )
)

echo Снятие блокировки Windows...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-ChildItem -LiteralPath '%TARGET_DIR%' -Recurse | Unblock-File -ErrorAction SilentlyContinue" >nul 2>&1

echo Остановка старого агента, если запущен...
taskkill /F /IM FulfillmentCRM-PrintAgent.exe >nul 2>&1
timeout /t 2 /nobreak >nul

echo Запуск агента...
start "" "%TARGET%"

echo Ожидание ответа http://127.0.0.1:9123/health ^(до 90 сек, на старых ПК дольше^)...
set "OK=0"
for /L %%i in (1,1,90) do (
  powershell -NoProfile -Command "try{(New-Object Net.WebClient).DownloadString('http://127.0.0.1:9123/health')|Out-Null; exit 0}catch{exit 1}" >nul 2>&1
  if !ERRORLEVEL! equ 0 set "OK=1" & goto :health_ok
  timeout /t 1 /nobreak >nul
)

:health_ok
echo.
if "%OK%"=="1" (
  echo [УСПЕХ] Агент печати установлен и работает.
  echo.
  echo - Иконка FF в трее Windows ^(возможно под стрелкой ^^)
  echo - Проверка: http://127.0.0.1:9123/health
  echo - Журнал: %LOG%
  echo - В сборке FBS: Печать - имя принтера
  echo.
  start "" "http://127.0.0.1:9123/health"
) else (
  echo [ОШИБКА] Агент не отвечает на порту 9123 за 90 секунд.
  echo.
  echo Частые причины:
  echo  1. Антивирус удалил или заблокировал exe
  echo     Добавьте в исключения: %TARGET_DIR%
  echo  2. Нет Visual C++ Redistributable x64
  echo     https://aka.ms/vs/17/release/vc_redist.x64.exe
  echo  3. Старый ПК - скачайте portable.zip вместо одного exe
  echo.
  if exist "%LOG%" (
    echo --- agent.log ---
    type "%LOG%"
    echo --- конец ---
    start notepad "%LOG%"
  ) else (
    echo Журнал пока не создан - exe, возможно, не запустился.
    echo Проверьте также: %TEMP%\FulfillmentCRM-PrintAgent-bootstrap.log
    if exist "%TEMP%\FulfillmentCRM-PrintAgent-bootstrap.log" type "%TEMP%\FulfillmentCRM-PrintAgent-bootstrap.log"
  )
)

echo.
pause
exit /b 0
endlocal
