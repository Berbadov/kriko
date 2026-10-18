# Installs the Android testing environment for the KRIKO mobile app.
#   - SDK packages: platform-tools, emulator, android-36 platform + x86_64 image
#   - one AVD named kriko_pixel (Pixel 6 profile)
# The JDK is a portable Temurin 17 build under C:\Android\jdk.
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$env:JAVA_HOME = (Get-ChildItem C:\Android\jdk -Directory | Select-Object -First 1).FullName
$env:ANDROID_HOME = 'C:\Android\Sdk'
$env:ANDROID_SDK_ROOT = $env:ANDROID_HOME
$sdkmanager = Join-Path $env:ANDROID_HOME 'cmdline-tools\latest\bin\sdkmanager.bat'
$avdmanager = Join-Path $env:ANDROID_HOME 'cmdline-tools\latest\bin\avdmanager.bat'

Write-Host "JAVA_HOME=$env:JAVA_HOME"

# Licences: sdkmanager reads them from stdin, so feed it a stream of "y".
$yes = ("y`n" * 40)
$yes | & $sdkmanager --sdk_root=$env:ANDROID_HOME --licenses 2>&1 | Select-Object -Last 5

$packages = @(
  'platform-tools',
  'emulator',
  'platforms;android-36',
  'build-tools;36.0.0',
  'system-images;android-36;google_apis;x86_64'
)
Write-Host "Installing: $($packages -join ', ')"
$yes | & $sdkmanager --sdk_root=$env:ANDROID_HOME --install @packages 2>&1 | Select-Object -Last 20

$image = 'system-images;android-36;google_apis;x86_64'
$avdHome = Join-Path $env:USERPROFILE '.android\avd'
if (-not (Test-Path (Join-Path $avdHome 'kriko_pixel.avd'))) {
  Write-Host 'Creating AVD kriko_pixel'
  'no' | & $avdmanager create avd -n kriko_pixel -k $image -d pixel_6 --force 2>&1 | Select-Object -Last 5
} else {
  Write-Host 'AVD kriko_pixel already exists'
}

& $avdmanager list avd 2>&1 | Select-Object -First 12
Write-Host 'ANDROID SETUP DONE'
