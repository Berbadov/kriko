<#
.SYNOPSIS
    The one recipe that builds everything a reader can install, on Windows.

.DESCRIPTION
    Kriko is two programs: kriko.exe, the desktop app (this crate, GPUI), and
    kriko-sidecar.exe, the engine it starts (Python, frozen by PyInstaller).
    This script builds both, proves each one starts, and packs them:

        builds\kriko-<version>-x86_64.msi         per-user installer
        builds\kriko-<version>-win64-portable.zip  both exes, no install

    In order: preflight (versions agree), the Python side, the packs,
    OpenSERP, the frozen sidecar and its handshake, the app, the MSI, and the app's own
    start-up check. `.github/workflows/desktop.yml` runs the same steps in the
    same order; there is one recipe, and this is it. PyInstaller cannot
    cross-compile, so a Windows sidecar has to be frozen on Windows.

    The installer is per-user: it installs under
    %LOCALAPPDATA%\Programs\Kriko, needs no administrator prompt, creates the
    Start-menu shortcuts "Kriko" and "Kriko Console" and a desktop shortcut,
    and stops a running Kriko before it replaces files.

    Output: the Rust release tree goes to %LOCALAPPDATA%\Kriko\cargo-target, one
    per machine, rather than into the checkout (CARGO_TARGET_DIR moves it).
    PyInstaller's scratch is deleted after the freeze. dist\ and builds\ stay in
    the checkout, because they are what the build hands over.

.PARAMETER Python
    Interpreter to build with. Defaults to .venv\Scripts\python.exe in the
    repository, which is created when it is missing.

.PARAMETER Version
    The version this build is meant to be, e.g. 1.0.0 or v1.0.0. CI passes the
    tag here. It is a check, not a stamp: it must equal pyproject.toml, because
    the installer's name and contents both come from the tree.

.PARAMETER WixBin
    Folder holding candle.exe and light.exe (WiX 3.x). Found from the WIX
    environment variable or PATH when omitted.

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File kriko-gpui\package.ps1 -WixBin C:\path\to\wix314

.NOTES
    Needs on PATH: a Rust toolchain and `cargo install cargo-wix`.

    ASCII only, on purpose: Windows PowerShell 5.1 decodes a BOM-less script
    with the system codepage, so one em-dash in a comment is a parse error on
    a machine whose codepage is not 1252, and it points at the wrong line.
    `test_the_installer_can_be_built_by_hand.py` holds that.

    The installer is unsigned: SmartScreen will warn on first run, which is a
    policy decision (a certificate) and not a build problem.
#>
[CmdletBinding()]
param(
    [string]$Python = "",
    [string]$Version = "",
    [string]$WixBin = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Run from the repository root whatever directory this was invoked from.
$crate = $PSScriptRoot
$repo = Split-Path -Parent $crate
Push-Location $repo

# The Rust release tree is about 2 GB. It used to sit in kriko-gpui\target, so
# every checkout and worktree that packaged kept a copy inside the project
# folder. It lives in one cache per machine instead, shared by every checkout.
# CARGO_TARGET_DIR overrides it, as it does for cargo itself.
$cargoTarget = if ($env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR } else { Join-Path $env:LOCALAPPDATA "Kriko\cargo-target" }
$cargoTarget = [IO.Path]::GetFullPath($cargoTarget)
$env:CARGO_TARGET_DIR = $cargoTarget

function Step {
    param([string]$Name)
    Write-Host ""
    Write-Host "=== $Name" -ForegroundColor Cyan
}

function Assert-LastExitCode {
    param([string]$What)
    if ($LASTEXITCODE -ne 0) {
        throw "$What failed with exit code $LASTEXITCODE"
    }
}

function Read-Setting {
    param([string]$File, [string]$Pattern)
    $hit = Select-String -Path $File -Pattern $Pattern | Select-Object -First 1
    if (-not $hit) { throw "no match for $Pattern in $File" }
    return $hit.Matches[0].Groups[1].Value
}

# Anything this script started that is still alive and lives inside this tree
# or in the release cache it builds into. A frozen engine holds its own image
# mapped, so a leftover one fails the next build's copy. By path and not by
# name: a Kriko the reader has open from somewhere else is not ours to end. A
# copy running out of the cache is this machine's build output, so it is ended.
function Stop-OurProcesses {
    $cache = $cargoTarget.TrimEnd('\') + '\'
    foreach ($name in @("kriko", "kriko-sidecar")) {
        foreach ($p in @(Get-Process -Name $name -ErrorAction SilentlyContinue)) {
            $where = ""
            try { $where = [string]$p.Path } catch { $where = "" }
            $ours = $where -and (
                $where.StartsWith($repo, [System.StringComparison]::OrdinalIgnoreCase) -or
                $where.StartsWith($cache, [System.StringComparison]::OrdinalIgnoreCase))
            if ($ours) {
                & taskkill /F /T /PID $p.Id 2>&1 | Out-Null
            }
        }
    }
}

try {
    Step "Tools"

    if (-not $Python) {
        $venvPython = Join-Path $repo ".venv\Scripts\python.exe"
        if (-not (Test-Path -LiteralPath $venvPython)) {
            Write-Host "no .venv here; creating one"
            if (Get-Command py -ErrorAction SilentlyContinue) {
                & py -3.13 -m venv (Join-Path $repo ".venv")
            } else {
                & python -m venv (Join-Path $repo ".venv")
            }
            Assert-LastExitCode "venv creation"
        }
        $Python = $venvPython
    }
    if ($Python -match '[\\/]') {
        $resolved = Resolve-Path -LiteralPath $Python -ErrorAction SilentlyContinue
        if (-not $resolved) {
            throw ("No interpreter at '$Python'. A venv made inside WSL has bin/python," +
                   " not Scripts/python.exe, and is a Linux build in any case.`n" +
                   "  Make a Windows one:  py -3.13 -m venv .venv")
        }
        $Python = $resolved.Path
    }
    elseif (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        throw "$Python is not on PATH. See the .NOTES block in this script."
    }

    foreach ($tool in @("rustc", "cargo")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "$tool is not on PATH. See the .NOTES block in this script."
        }
    }

    # WiX 3 (candle + light). WIX is what its own installer sets.
    if (-not $WixBin -and $env:WIX) {
        $fromEnv = Join-Path $env:WIX "bin"
        if (Test-Path -LiteralPath (Join-Path $fromEnv "candle.exe")) { $WixBin = $fromEnv }
    }
    if (-not $WixBin) {
        $candle = Get-Command candle.exe -ErrorAction SilentlyContinue
        if ($candle) { $WixBin = Split-Path -Parent $candle.Source }
    }
    if (-not $WixBin -or -not (Test-Path -LiteralPath (Join-Path $WixBin "candle.exe"))) {
        throw ("WiX 3 not found: pass -WixBin <folder with candle.exe>, or set WIX." +
               " (https://github.com/wixtoolset/wix3/releases)")
    }
    cargo wix --version
    Assert-LastExitCode "cargo wix --version (cargo install cargo-wix)"

    & $Python --version
    Assert-LastExitCode "python --version"
    rustc --version

    # The three committed version strings, before anything is compiled. Plain
    # and not --strict: this runs before the `pip install -e .` below, and a
    # stale install is a state that step is about to repair.
    & $Python tools/bump.py --show
    if ($LASTEXITCODE -ne 0) {
        throw ("the version strings in pyproject.toml, kriko-gpui/Cargo.toml and" +
               " kriko-gpui/Cargo.lock disagree (see the table above)." +
               " `python tools/bump.py <version>` sets all of them at once." +
               " An installer built while they disagree has a name that is not its contents.")
    }

    $tree = Read-Setting "pyproject.toml" '^version\s*=\s*"([^"]+)"'
    if ($Version) {
        $want = $Version -replace '^v', ''
        if ($want -ne $tree) {
            throw ("asked for $want and this checkout is $tree. The installer's name and" +
                   " contents both come from the tree. Run ``git pull``, or" +
                   " ``python tools/bump.py $want`` to move the tree, then build again.")
        }
    }
    $ver = $tree

    # The interpreter is frozen into the sidecar, so its version is the
    # reader's. Too old fails several steps later with a resolver message; a
    # pre-release can freeze a pydantic that raises on import, and the build
    # goes green on a sidecar that dies on its first request.
    $floor = (Read-Setting "pyproject.toml" '^requires-python\s*=\s*"([^"]+)"') -replace '[>=\s"]', ''
    $report = & $Python -c ("import sys;print('.'.join(map(str,sys.version_info[:3])), " +
                            "sys.version_info.releaselevel)")
    $parts = $report.Trim().Split(' ')
    if ([version]$parts[0] -lt [version]$floor) {
        throw "$Python is $($parts[0]), and pyproject.toml requires $floor or newer."
    }
    if ($parts[1] -ne 'final') {
        throw ("$Python is a pre-release ($report). A sidecar frozen on it can fail on" +
               " its first request. Use a final release; the suite runs on 3.13.")
    }

    Step "The app's crate graph is the one that was committed"
    Push-Location $crate
    try {
        cargo metadata --locked --format-version 1 | Out-Null
        Assert-LastExitCode "cargo metadata --locked"
    } finally {
        Pop-Location
    }

    # -r first: the lock is what a reader's sidecar contains, and a floating
    # resolve here is how two builds of one tag stop being the same binary.
    # PyInstaller is a build tool and not part of that closure.
    Step "Install the Python side"
    & $Python -m pip install --upgrade pip
    Assert-LastExitCode "pip self-upgrade"
    & $Python -m pip install -r requirements.lock -e "." pyinstaller
    Assert-LastExitCode "pip install"

    # The install has to be *this* tree: the sidecar is frozen from the
    # installed distribution, so an editable install pointing at another
    # checkout would freeze that checkout's code under this one's name.
    $installed = (& $Python -c "from app.version import app_version; print(app_version())").Trim()
    Assert-LastExitCode "read the installed version"
    if ($installed -ne $tree) {
        throw ("the install reports $installed and this tree is $tree. Check that" +
               " $Python's environment has no other checkout installed, then re-run.")
    }

    Step "Fetch the pinned OpenSERP release"
    $bin = Join-Path $cargoTarget "release"
    & (Join-Path $repo "packaging\fetch_openserp.ps1") -Destination (Join-Path $bin "OpenSERP.exe")
    if (-not (Test-Path -LiteralPath (Join-Path $bin "OpenSERP.exe"))) { throw "OpenSERP executable was not produced." }
    if ((Get-FileHash -LiteralPath (Join-Path $bin "OpenSERP.exe") -Algorithm SHA256).Hash -ne "336CD54C25F35BF76827E1D88C97E20FD085F219BFDCC7F96ACF541208FC651B") { throw "OpenSERP executable digest did not match the pinned release." }
    Copy-Item (Join-Path $crate "third-party\OpenSERP-LICENSE.txt") (Join-Path $bin "OpenSERP-LICENSE.txt") -Force

    # PyInstaller's scratch is rebuilt on every freeze, so it gets a folder of
    # its own in temp and is removed here. Its default, build\ beside the spec,
    # was a second copy inside the checkout. The sidecar and the packs stay in
    # dist\, which the placement step and the spec read.
    Step "Freeze the sidecar"
    $work = Join-Path ([IO.Path]::GetTempPath()) "kriko-pyinstaller-$PID"
    & $Python -m PyInstaller --noconfirm --workpath $work packaging/kriko-sidecar.spec
    Assert-LastExitCode "pyinstaller"
    Remove-Item -LiteralPath $work -Recurse -Force -ErrorAction SilentlyContinue

    # A frozen binary that cannot print its port is a blank window, so the
    # handshake is checked before it is bundled into anything.
    Step "The frozen sidecar answers"
    & $Python packaging/smoke_sidecar.py "dist/kriko-sidecar.exe"
    Assert-LastExitCode "smoke_sidecar.py"

    Step "Build the app"
    Push-Location $crate
    try {
        cargo build --release --locked
        Assert-LastExitCode "cargo build --release"
    } finally {
        Pop-Location
    }

    # Beside kriko.exe, which is where the app looks for its engine and where
    # main.wxs picks both programs up.
    Step "Place the sidecar"
    Copy-Item (Join-Path $repo "dist\kriko-sidecar.exe") (Join-Path $bin "kriko-sidecar.exe") -Force
    Write-Host (Join-Path $bin "kriko-sidecar.exe")

    # The release folder is shared by every checkout on this machine, so another
    # build can replace these two files while this one is still packing. The
    # digests are taken here and checked before WiX reads the folder: a mismatch
    # stops the run, rather than an MSI that carries code nobody smoke-tested.
    $packed = @{}
    foreach ($name in @("kriko.exe", "kriko-sidecar.exe")) {
        $packed[$name] = (Get-FileHash -LiteralPath (Join-Path $bin $name) -Algorithm SHA256).Hash
    }

    $builds = Join-Path $crate "builds"
    New-Item -ItemType Directory -Force -Path $builds | Out-Null
    $msi = Join-Path $builds "kriko-$ver-x86_64.msi"

    Step "The MSI"
    foreach ($name in $packed.Keys) {
        $now = (Get-FileHash -LiteralPath (Join-Path $bin $name) -Algorithm SHA256).Hash
        if ($now -ne $packed[$name]) {
            throw "$name in $bin changed while this build was packing: another build shares that folder. Run the script again."
        }
    }
    if (Test-Path -LiteralPath $msi) { Remove-Item -LiteralPath $msi -Force }
    Push-Location $crate
    try {
        $wix = @("wix", "--no-build", "--nocapture", "--bin-path", $WixBin, "--output", $msi)
        Write-Host ("cargo " + ($wix -join " "))
        & cargo $wix
        Assert-LastExitCode "cargo wix"
    } finally {
        Pop-Location
    }
    if (-not (Test-Path -LiteralPath $msi)) { throw "cargo wix reported success and made no MSI at $msi" }

    # Building the installer is not the app starting. The exe is launched,
    # held, and asked whether it is still up and did not panic.
    Step "The app opens"
    & $Python packaging/smoke_app.py (Join-Path $bin "kriko.exe")
    Assert-LastExitCode "smoke_app.py"

    # What a reader gets: the MSI installed, every screen of the installed
    # app photographed, then the MSI removed. Screenshots in builds/windows-look.
    Step "The installed app, looked at"
    & $Python packaging/windows_look.py $msi (Join-Path $builds "windows-look")
    Assert-LastExitCode "windows_look.py"

    Step "The portable zip"
    $zip = Join-Path $builds "kriko-$ver-win64-portable.zip"
    if (Test-Path -LiteralPath $zip) { Remove-Item -LiteralPath $zip -Force }
    Compress-Archive -Path (Join-Path $bin "kriko.exe"), (Join-Path $bin "kriko-sidecar.exe"), `
        (Join-Path $bin "OpenSERP.exe"), (Join-Path $bin "OpenSERP-LICENSE.txt") `
        -DestinationPath $zip -Force

    $checksums = Join-Path $builds "SHA256SUMS.txt"
    @($msi, $zip) | ForEach-Object {
        $file = Get-Item -LiteralPath $_
        $digest = (Get-FileHash -LiteralPath $_ -Algorithm SHA256).Hash.ToLowerInvariant()
        "$digest  $($file.Name)"
    } | Set-Content -LiteralPath $checksums -Encoding Ascii

    Step "Done"
    foreach ($item in @($msi, $zip, $checksums)) {
        $f = Get-Item -LiteralPath $item
        Write-Host ("{0}  {1:N1} MB" -f $f.FullName, ($f.Length / 1MB)) -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Unsigned: SmartScreen will warn on first run (More info -> Run anyway)."
} finally {
    Stop-OurProcesses
    Pop-Location
    $global:LASTEXITCODE = 0
}
exit 0
