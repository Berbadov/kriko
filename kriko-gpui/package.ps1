# Build everything a user can install, in one command:
#
#   powershell -ExecutionPolicy Bypass -File package.ps1
#
# Produces, under builds\:
#   kriko-<version>-x86_64.msi          the installer (Start menu + desktop
#                                        shortcuts, PATH entry, brand icon)
#   kriko-<version>-win64-portable.zip  the single self-contained exe
#
# The MSI step needs the WiX 3 toolset (candle.exe + light.exe). If WiX is not
# on PATH, pass its folder:  .\package.ps1 -WixBin C:\path\to\wix314

param(
    [string]$WixBin = ""
)

$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$version = (Select-String -Path Cargo.toml -Pattern '^version\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches.Groups[1].Value
$builds = Join-Path $PSScriptRoot "builds"
New-Item -ItemType Directory -Force -Path $builds | Out-Null

Write-Host "== Kriko ${version}: release build"
cargo build --release
if ($LASTEXITCODE -ne 0) { throw "cargo build --release failed" }

if (-not $WixBin) {
    $candle = Get-Command candle.exe -ErrorAction SilentlyContinue
    if ($candle) { $WixBin = Split-Path $candle.Source }
}

Write-Host "== Kriko ${version}: MSI"
if ($WixBin) {
    cargo wix --bin-path $WixBin
} else {
    cargo wix
}
if ($LASTEXITCODE -ne 0) { throw "cargo wix failed" }

$msi = "target\wix\kriko-gpui-$version-x86_64.msi"
if (-not (Test-Path $msi)) { throw "MSI not found at $msi" }
Copy-Item $msi -Destination (Join-Path $builds "kriko-$version-x86_64.msi") -Force

Write-Host "== Kriko ${version}: portable zip"
$zip = Join-Path $builds "kriko-$version-win64-portable.zip"
Compress-Archive -Path "target\release\kriko.exe" -DestinationPath $zip -Force

Write-Host ""
Write-Host "Done. Artifacts in builds\:"
Get-ChildItem $builds | ForEach-Object {
    Write-Host ("  {0}  {1:N1} MB" -f $_.Name, ($_.Length / 1MB))
}
