# Fulfillment CRM - Chrome --kiosk-printing (FBS autoprint without Enter)
param(
  [string]$CrmUrl = 'http://5.129.243.246:8080/?print_mode=kiosk'
)

$ErrorActionPreference = 'Stop'

Write-Host 'Fulfillment CRM - Chrome autoprint FBS'
Write-Host ''

$chromeCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  ${env:ProgramFiles(x86)} + '\Google\Chrome\Application\chrome.exe',
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
)
$chrome = $chromeCandidates | Where-Object { $_ -and (Test-Path -LiteralPath $_) } | Select-Object -First 1
if (-not $chrome) {
  Write-Host 'ERROR: Google Chrome not found.' -ForegroundColor Red
  exit 1
}

$profileDir = Join-Path $env:LOCALAPPDATA 'FulfillmentCRM-Print'
New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

Write-Host "Chrome:  $chrome"
Write-Host "CRM:     $CrmUrl"
Write-Host "Profile: $profileDir"
Write-Host ''

$shortcutName = 'Fulfillment CRM (autoprint).lnk'
$chromeArgs = "--user-data-dir=`"$profileDir`" --disable-extensions --kiosk-printing --new-window `"$CrmUrl`""

$targets = @(
  [Environment]::GetFolderPath('Desktop'),
  [Environment]::GetFolderPath('Programs'),
  $PSScriptRoot
)

$shell = New-Object -ComObject WScript.Shell
$created = @()

foreach ($dir in $targets) {
  if (-not $dir) { continue }
  $path = Join-Path $dir $shortcutName
  $sc = $shell.CreateShortcut($path)
  $sc.TargetPath = $chrome
  $sc.Arguments = $chromeArgs
  $sc.WorkingDirectory = $env:USERPROFILE
  $sc.Description = 'Fulfillment CRM autoprint (отдельный профиль Chrome)'
  $sc.Save()
  if (Test-Path -LiteralPath $path) {
    $created += $path
    Write-Host "OK: $path" -ForegroundColor Green
  }
}

if ($created.Count -eq 0) {
  Write-Host 'ERROR: shortcut was not created.' -ForegroundColor Red
  exit 1
}

Write-Host ''
Write-Host 'IMPORTANT: close ALL Chrome windows first (Task Manager -> end chrome.exe).'
Write-Host 'Then open CRM ONLY via the new shortcut — one tab, no old session.'
Write-Host ''
Write-Host 'Starting CRM...'
Start-Process -FilePath $chrome -ArgumentList @(
  "--user-data-dir=$profileDir",
  '--disable-extensions',
  '--kiosk-printing',
  '--new-window',
  $CrmUrl
)
exit 0
