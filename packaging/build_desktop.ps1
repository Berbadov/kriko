<#
.SYNOPSIS
    Build the Windows installer on a Windows machine, without GitHub Actions.

.DESCRIPTION
    The same steps `.github/workflows/desktop.yml` runs on its windows leg, in
    the same order, on the box in front of you.

    This exists because the workflow was the *only* path to an installer, and
    that made a reader's copy of Kriko depend on a runner being available. On
    2026-09-09 one wasn't — every job died in three seconds with no runner
    assigned — and a tag that produces nothing is not a release. The steps
    below were never Actions-specific; they were just written down in a place
    only Actions could read.

    Nothing here is a shortcut. PyInstaller cannot cross-compile, so a Windows
    sidecar has to be frozen on Windows: this script is not a convenience over
    the workflow, it is the only alternative to it.

.PARAMETER SkipUi
    Reuse the committed bundle in src/app/web/static instead of rebuilding it.
    Only safe when ui/ has not changed since that bundle was committed.

.PARAMETER Python
    Interpreter to build with. Defaults to `python` on PATH.

.EXAMPLE
    pwsh packaging/build_desktop.ps1
    # -> tauri/src-tauri/target/release/bundle/nsis/Kriko_0.5.0_x64-setup.exe

.NOTES
    Needs, on PATH: python 3.12+, node 20+, and a Rust toolchain (rustup).
    The bundle is unsigned — SmartScreen will warn on first run, which is a
    policy decision (an EV certificate) rather than a build problem.
#>
[CmdletBinding()]
param(
    [switch]$SkipUi,
    [string]$Python = "python"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Run from the repository root whatever directory this was invoked from.
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Push-Location $repo

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

try {
    Step "Tools"
    foreach ($tool in @($Python, "node", "npm", "rustc", "cargo")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "$tool is not on PATH. See the .NOTES block in this script."
        }
    }
    & $Python --version
    node --version
    rustc --version

    # -r first, and it is the point rather than tidiness: the lock is what a
    # reader's sidecar contains, and a floating resolve here is how two builds
    # of one tag stop being the same binary (B57). PyInstaller is a build tool
    # rather than part of that closure, so it is not locked.
    Step "Install the Python side"
    & $Python -m pip install --upgrade pip
    Assert-LastExitCode "pip self-upgrade"
    & $Python -m pip install -r requirements.lock -e "." pyinstaller
    Assert-LastExitCode "pip install"

    # The UI before the freeze: the spec refuses to freeze without a built
    # bundle rather than shipping an app that 404s on its own frontend.
    if ($SkipUi) {
        Step "UI (skipped — using the committed bundle)"
    } else {
        Step "Build the UI"
        npm --prefix ui ci --no-audit --no-fund
        Assert-LastExitCode "npm ci (ui)"
        npm --prefix ui run build
        Assert-LastExitCode "npm run build (ui)"
    }

    Step "Freeze the sidecar"
    & $Python -m PyInstaller --noconfirm packaging/kriko-sidecar.spec
    Assert-LastExitCode "pyinstaller"

    # A frozen binary that cannot print its port is a blank window, so the
    # handshake is checked before it is bundled into anything. This is the
    # check v0.2.4 did not have.
    Step "The frozen sidecar answers"
    & $Python packaging/smoke_sidecar.py "dist/kriko-sidecar.exe"
    Assert-LastExitCode "smoke_sidecar.py"

    # Tauri resolves externalBin as <name>-<target triple>.
    Step "Place the sidecar"
    $triple = (& rustc -Vv | Select-String -Pattern '^host: ' | ForEach-Object {
        $_.Line -replace '^host: ', ''
    })
    if (-not $triple) { throw "could not read the host triple out of rustc -Vv" }
    New-Item -ItemType Directory -Force -Path "tauri/src-tauri/binaries" | Out-Null
    Copy-Item "dist/kriko-sidecar.exe" "tauri/src-tauri/binaries/kriko-sidecar-$triple.exe" -Force
    Write-Host "kriko-sidecar-$triple.exe"

    # `ci`, not `install`: this resolves the Tauri CLI, and a floating `^2` is
    # exactly how v0.2.1 opened while v0.2.4 panicked on an identical tree four
    # hours later.
    Step "Icons"
    npm --prefix tauri ci --no-audit --no-fund
    Assert-LastExitCode "npm ci (tauri)"
    npm --prefix tauri run tauri icon src-tauri/icons/icon.png
    Assert-LastExitCode "tauri icon"

    # Self-update is a build-time decision, because the key that makes it
    # trustworthy lives in a secret. With no key this is a no-op and the build
    # still produces an installer — it just cannot update itself, which is the
    # honest state of B63/B64.
    Step "Configure self-update"
    & $Python packaging/configure_updater.py --repo "Berbadov/kriko" --version ""
    Assert-LastExitCode "configure_updater.py"

    Step "Bundle"
    npm --prefix tauri run tauri build
    Assert-LastExitCode "tauri build"

    # The installer building is not the app starting. v0.2.4 built green on all
    # three runners and then panicked in `build()` before its first window,
    # because a plugin configured at package time was registered
    # unconditionally — a failure with nowhere to be seen but a stderr no
    # double-click has. So the shell is launched here, before you trust it.
    Step "The bundled shell opens"
    & $Python packaging/smoke_app.py "tauri/src-tauri/target/release/kriko.exe"
    Assert-LastExitCode "smoke_app.py"

    Step "Done"
    $installers = Get-ChildItem -Recurse -Path "tauri/src-tauri/target/release/bundle" `
        -Include *.exe, *.msi -ErrorAction SilentlyContinue
    if (-not $installers) {
        throw "tauri build reported success and produced no installer"
    }
    $installers | ForEach-Object {
        Write-Host ("{0}  {1:N1} MB" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Unsigned: SmartScreen will warn on first run (More info -> Run anyway)."
} finally {
    Pop-Location
}
