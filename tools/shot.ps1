# Capture the emulator screen into .preview/shots/<name>.png
param(
  [Parameter(Mandatory = $true)][string]$Name,
  [int]$WaitSeconds = 0
)
$ErrorActionPreference = 'Stop'
$env:ANDROID_HOME = if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { 'C:\Android\Sdk' }
$adb = "$env:ANDROID_HOME\platform-tools\adb.exe"
$out = Join-Path $PSScriptRoot '..\.preview\shots'
New-Item -ItemType Directory -Force -Path $out | Out-Null
if ($WaitSeconds -gt 0) { Start-Sleep -Seconds $WaitSeconds }
# /data/local/tmp is not scanned by the media scanner, unlike /sdcard.
& $adb shell screencap -p /data/local/tmp/shot.png
& $adb pull /data/local/tmp/shot.png (Join-Path $out "$Name.png") 2>&1 | Out-Null
Write-Host "captured $Name.png"
