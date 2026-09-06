@echo off
setlocal EnableExtensions
chcp 65001 >nul 2>&1

rem URL CRM с флагом режима автопечати (можно изменить под ваш сервер)
set "CRM_URL=http://5.129.243.246:8080/?print_mode=kiosk"

echo ============================================
echo  Fulfillment CRM — Chrome автопечать FBS
echo  (флаг --kiosk-printing, без Enter)
echo ============================================
echo.

set "CHROME="
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if exist "%LocalAppData%\Google\Chrome\Application\chrome.exe" set "CHROME=%LocalAppData%\Google\Chrome\Application\chrome.exe"

if "%CHROME%"=="" (
  echo [ОШИБКА] Google Chrome не найден. Установите Chrome и запустите снова.
  pause
  exit /b 1
)

echo Chrome: %CHROME%
echo CRM:    %CRM_URL%
echo.

set "SHORTCUT_NAME=Fulfillment CRM (автопечать).lnk"
set "DESKTOP=%USERPROFILE%\Desktop\%SHORTCUT_NAME%"
set "STARTMENU=%APPDATA%\Microsoft\Windows\Start Menu\Programs\%SHORTCUT_NAME%"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$chrome = '%CHROME%';" ^
  "$url = '%CRM_URL%';" ^
  "$args = '--kiosk-printing \"' + $url + '\"';" ^
  "$shell = New-Object -ComObject WScript.Shell;" ^
  "foreach ($path in @('%DESKTOP%', '%STARTMENU%')) {" ^
  "  $sc = $shell.CreateShortcut($path);" ^
  "  $sc.TargetPath = $chrome;" ^
  "  $sc.Arguments = $args;" ^
  "  $sc.WorkingDirectory = $env:USERPROFILE;" ^
  "  $sc.Description = 'Fulfillment CRM — стикеры FBS без диалога печати';" ^
  "  $sc.Save();" ^
  "  Write-Host ('Ярлык: ' + $path);" ^
  "}"

if errorlevel 1 (
  echo [ОШИБКА] Не удалось создать ярлык.
  pause
  exit /b 1
)

echo.
echo [УСПЕХ] Ярлыки созданы на рабочем столе и в меню Пуск.
echo.
echo Перед сборкой FBS:
echo  1. В Windows выберите Xprinter ПРИНТЕРОМ ПО УМОЛЧАНИЮ
echo  2. Размер этикетки 58x40 мм, поля минимальные
echo  3. Открывайте CRM ТОЛЬКО через ярлык «Fulfillment CRM (автопечать)»
echo     — в обычном Chrome диалог печати останется
echo.
echo Запуск CRM сейчас...
start "" "%CHROME%" --kiosk-printing "%CRM_URL%"

echo.
pause
endlocal
