# Build the friends-test APK from a short staging root.
#
# Android's CMake mirrors every source path into the object directory, and this
# checkout's node_modules path is long enough that one worklets object directory
# passes MAX_PATH. CMAKE_OBJECT_PATH_MAX shortens object names, not the mirrored
# directories, so the only reliable fix is a short build root. This script does
# that staging for you and puts the APK in release/.
#
#   powershell -ExecutionPolicy Bypass -File tools\build-apk.ps1
#
# Nothing here is committed under android/ — prebuild regenerates it.

param(
    [string]$Stage = 'C:\a',
    [string]$Architectures = 'arm64-v8a,x86_64',
    [string]$AndroidHome = $(if ($env:ANDROID_HOME) { $env:ANDROID_HOME } else { 'C:\Android\Sdk' }),
    [string]$JavaHome = $(if ($env:JAVA_HOME) { $env:JAVA_HOME } else { 'C:\Android\jdk\jdk-17.0.20.1+1' })
)

$ErrorActionPreference = 'Stop'

$mobile = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $mobile -Parent

if (-not (Test-Path (Join-Path $mobile 'src\engine\secrets.ts'))) {
    throw "src/engine/secrets.ts is missing. Run tools/make-secrets.py first."
}
if ($Stage.Length -gt 10) {
    throw "The staging path must be short (10 characters or fewer), got '$Stage'."
}
if ((Resolve-Path $Stage -ErrorAction SilentlyContinue).Path -eq (Resolve-Path $mobile).Path) {
    throw 'The staging path must be different from the checkout.'
}

$env:ANDROID_HOME = $AndroidHome
$env:ANDROID_SDK_ROOT = $AndroidHome
$env:JAVA_HOME = $JavaHome
$env:PATH = "$JavaHome\bin;$AndroidHome\platform-tools;$env:PATH"
$env:CI = '1'

# The packages live wherever they already live. Chain the stage's junction to
# the final target so Gradle canonicalises to a short path, not back to the
# checkout.
$packages = (Get-Item (Join-Path $mobile 'node_modules') -Force).Target
if (-not $packages) {
    throw "Move node_modules to a short path first (see README), or make it a junction."
}
if ($packages -is [array]) { $packages = $packages[0] }
if (-not (Test-Path $packages)) { throw "The packages target '$packages' does not exist." }
$relocated = @{ 'react-native-reanimated' = 'C:\r'; 'react-native-safe-area-context' = 'C:\sa'; 'react-native-screens' = 'C:\sc'; 'react-native-svg' = 'C:\sv' }
foreach ($name in $relocated.Keys) {
    $item = Get-Item (Join-Path $mobile "node_modules\$name") -Force -ErrorAction SilentlyContinue
    $target = if ($item) { $item.Target } else { $null }
    if ($target -is [array]) { $target = $target[0] }
    if (-not $item -or $item.LinkType -ne 'Junction' -or -not $target -or $target.Length -gt 6) {
        throw "node_modules\$name must be a junction to a short root such as $($relocated[$name]) (see README)."
    }
}

New-Item -ItemType Directory -Path (Split-Path $Stage -Parent) -Force | Out-Null
if (Test-Path $Stage) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Path $Stage | Out-Null

Write-Host "Staging source in $Stage"
robocopy $mobile $Stage /E /XD node_modules android .expo .git /XF *.apk *.aab | Out-Null
if ($LASTEXITCODE -ge 8) { throw "robocopy failed with $LASTEXITCODE" }

cmd /c mklink /J "$Stage\node_modules" "$packages" | Out-Null
if ($LASTEXITCODE -ne 0) { throw 'Could not create the node_modules junction.' }

Write-Host 'Running expo prebuild'
Push-Location $Stage
try {
    npx expo prebuild --platform android --no-install
    if ($LASTEXITCODE -ne 0) { throw 'expo prebuild failed' }

    Push-Location (Join-Path $Stage 'android')
    try {
        & .\gradlew.bat ':app:assembleRelease' "-PreactNativeArchitectures=$Architectures" --no-daemon --console=plain
        if ($LASTEXITCODE -ne 0) { throw 'Gradle failed' }
    } finally {
        Pop-Location
    }

    $apk = Join-Path $Stage 'android\app\build\outputs\apk\release\app-release.apk'
    if (-not (Test-Path $apk)) { throw "No APK at $apk" }

    $version = (Get-Content (Join-Path $mobile 'app.json') -Raw | ConvertFrom-Json).expo.version
    $outDir = Join-Path $repo 'release'
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
    $out = Join-Path $outDir "kriko-agent-$version.apk"
    Copy-Item -LiteralPath $apk -Destination $out -Force
    $size = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "APK: $out ($size MB)"
} finally {
    Pop-Location
}
