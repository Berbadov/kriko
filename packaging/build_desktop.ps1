<#
.SYNOPSIS
    Build the Windows installer on a Windows machine, without GitHub Actions.

.DESCRIPTION
    The same steps `.github/workflows/desktop.yml` runs on its windows leg, in
    the same order, on the box in front of you.

    This exists because the workflow was the *only* path to an installer, and
    that made a reader's copy of Kriko depend on a runner being available. On
    2026-09-09 one wasn't -- every job died in three seconds with no runner
    assigned -- and a tag that produces nothing is not a release. The steps
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

.PARAMETER Version
    Version to stamp into the bundle, e.g. 0.5.0 or v0.5.0. CI passes the tag
    name here and nothing on a pull request. Omit it and the build is not
    stamped, which is what an untagged local build is.

.PARAMETER Repo
    owner/name, for the updater endpoint. Read off `git remote get-url origin`
    when omitted -- derived rather than hardcoded, so a fork's build points at
    the fork's releases.

.EXAMPLE
    powershell -File packaging/build_desktop.ps1
    # -> tauri/src-tauri/target/release/bundle/nsis/Kriko_0.5.0_x64-setup.exe

.EXAMPLE
    powershell -File packaging/build_desktop.ps1 -Python .venv\Scripts\python.exe
    # Build against a venv instead of whatever `python` resolves to. Worth
    # doing: the unqualified interpreter is usually the one the machine's
    # owner uses for everything else, and this installs into it.

.EXAMPLE
    cmd /c "powershell -NoProfile -ExecutionPolicy Bypass -File packaging\build_desktop.ps1 > build.log 2>&1"
    # How to keep a log. Do NOT reach for `... 2>&1 | Out-File` or `*> build.log`
    # instead: those capture the *native* stderr into PowerShell's own pipeline,
    # which turns any tool's ordinary warning into a terminating
    # NativeCommandError. On 2026-09-11 the 0.7.2 build died three lines into
    # `=== Build the UI` because npm printed one deprecation notice about a
    # transitive package -- nothing to do with this repository, and
    # `$ErrorActionPreference = 'Continue'` does not help, because the error is
    # raised by the pipeline rather than by a preference. Redirecting in `cmd`
    # hands the child an OS file handle, so a warning stays a warning. It also
    # catches `Write-Host`, which is the information stream and is missing from
    # any log made by piping.

.NOTES
    Needs, on PATH: node 20+ and a Rust toolchain (rustup), plus a Python that
    satisfies pyproject's `requires-python` -- pass -Python if the default
    `python` is older, which on a machine with several is likely.

    Windows PowerShell 5.1 (`powershell`) is enough; `pwsh` 7 works but is not
    on a stock Windows box. This file is deliberately **ASCII only** for that
    reason: 5.1 decodes a BOM-less script with the system ANSI codepage, not
    UTF-8, so one em-dash in a comment is a parse error on any machine whose
    codepage is not 1252 -- and it fails in the string *after* it, pointing at
    the wrong line. `test_the_installer_can_be_built_by_hand.py` holds that.

    The bundle is unsigned -- SmartScreen will warn on first run, which is a
    policy decision (an EV certificate) rather than a build problem.
#>
[CmdletBinding()]
param(
    [switch]$SkipUi,
    [string]$Python = "python",
    [string]$Version = "",
    [string]$Repo = ""
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

# Run from the repository root whatever directory this was invoked from.
$repo = Split-Path -Parent (Split-Path -Parent $PSCommandPath)
Push-Location $repo

# When this run started, so the report at the end can tell what this run
# produced from what was already lying in the output directory.
# `target/release/bundle` is never cleaned between builds, so the recursive
# listing that used to end this script reported every installer any earlier
# build had left there. On 2026-09-09 that meant printing a 0.5.0 setup.exe
# from four hours and three commits earlier, in green, beside the one this
# run had just made -- and the reader is handed a path out of that list.
$started = Get-Date

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

    # The interpreter is checked apart from the rest, because it is the one
    # "tool" that is usually a *path* rather than a name. Lumping it in with
    # node and rustc meant a -Python that does not exist was reported as "not
    # on PATH", which sends you to look at your PATH -- and on 2026-09-14 the
    # real cause was a .venv built inside WSL, so the tree had .venv/bin/python
    # and no .venv/Scripts/python.exe at all. Right diagnosis, wrong sentence,
    # and the sentence is what someone acts on.
    if ($Python -match '[\\/]') {
        $resolved = Resolve-Path -LiteralPath $Python -ErrorAction SilentlyContinue
        if (-not $resolved) {
            throw ("No interpreter at '$Python' (looked in " + (Get-Location).Path + ").`n" +
                   "  A venv made inside WSL has bin/python, not Scripts/python.exe -- and it" +
                   " is a Linux build in any case, since PyInstaller cannot cross-compile.`n" +
                   "  Make a Windows one:  py -3.13 -m venv .venv`n" +
                   "  Or name a Windows interpreter:  -Python C:\path\to\python.exe")
        }
        $Python = $resolved.Path
    }
    elseif (-not (Get-Command $Python -ErrorAction SilentlyContinue)) {
        throw "$Python is not on PATH. See the .NOTES block in this script."
    }

    foreach ($tool in @("node", "npm", "rustc", "cargo")) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "$tool is not on PATH. See the .NOTES block in this script."
        }
    }

    & $Python --version
    Assert-LastExitCode "python --version"
    node --version
    rustc --version

    # The five committed version strings, before anything else: NSIS names the
    # bundle from tauri.conf.json (by way of Cargo.toml), and nothing above
    # checks that file against pyproject.toml at all -- the -Version guard
    # below only ever compares the *tag* to pyproject, and the installed-
    # distribution check further down only ever compares the *install* to
    # pyproject. A tree where pyproject was bumped by hand and
    # tauri.conf.json was not would sail through both of those and come out
    # the other end as an installer whose name is one version and whose
    # `cargo tauri build` compiled another -- the exact failure `tools/bump.py`
    # exists to make impossible to leave behind, and this is the one place
    # that failure would otherwise go unnoticed until a reader reports it.
    # `tools/bump.py --show` is the same check `test_the_four_version_strings_agree`
    # makes, and it is cheap enough to run before rustc has compiled anything.
    #
    # Plain rather than --strict on purpose. --strict also fails when the
    # *installed* distribution is behind the tree, which is the right check for
    # the gate and the wrong one here: this runs before the `pip install -e .`
    # below, so a stale install is a state this build is about to repair, and
    # refusing over it would be a guard blocking the thing that fixes what it
    # complains about. 0.10.0 was reported from the field doing exactly that,
    # with this message naming a cause it had not checked.
    & $Python tools/bump.py --show
    if ($LASTEXITCODE -ne 0) {
        throw ("the version strings in pyproject.toml, tauri.conf.json, Cargo.toml," +
               " package.json and Cargo.lock disagree (see the table above)." +
               " `python tools/bump.py <version>` sets all of them at once --" +
               " an installer built while they disagree is an installer whose" +
               " name is not its contents.")
    }

    # -Version must be the version this checkout actually is.
    #
    # The stamp only reaches tauri.conf.json, which is what names the bundle.
    # Cargo.toml, pyproject.toml and the frozen sidecar's own metadata all come
    # from the tree. So `-Version 0.8.5` on a checkout at 0.8.0 produced
    # `Kriko_0.8.5_x64-setup.exe` containing 0.8.0 of everything -- the build
    # log said "Compiling kriko v0.8.0" one line above the bundle it named
    # 0.8.5, and the reader installed it, found the fixes missing, and reported
    # that the version number had not been updated. It had: the label had, and
    # nothing else.
    #
    # An installer whose name is not its contents is worse than a failed build,
    # because it is the evidence anyone would reach for. So the two have to
    # agree, and the fix when they do not is `git pull` or
    # `python tools/bump.py <version>` -- both of which move the tree, which is
    # the thing being shipped.
    if ($Version) {
        $want = $Version -replace '^v', ''
        $tree = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"'
                ).Matches[0].Groups[1].Value
        if ($want -ne $tree) {
            throw ("asked to stamp $want and this checkout is $tree. The stamp only" +
                   " names the bundle; Cargo.toml, pyproject and the frozen sidecar" +
                   " come from the tree, so the installer would carry $tree under a" +
                   " $want name. Run ``git pull``, or ``$Python tools/bump.py $want``" +
                   " to move the tree, then build again.")
        }
    }

    # The interpreter is frozen into the sidecar, so its version is the
    # reader's and not just this build's. Two ways that goes wrong, neither of
    # which announces itself until much later:
    #
    #   * Too old for pyproject's floor -- pip fails several steps from here
    #     with a resolver message about the tree rather than about your choice.
    #   * A pre-release. requirements.lock pins a pydantic that raises on
    #     import under 3.14.0rc2 (B110), and PyInstaller freezes that happily:
    #     the build goes green and the reader's sidecar dies on its first
    #     request. The suite runs on 3.13, which is what this should be.
    $floor = (Select-String -Path pyproject.toml -Pattern '^requires-python\s*=\s*"([^"]+)"'
             ).Matches[0].Groups[1].Value -replace '[>=\s"]', ''
    $report = & $Python -c ("import sys;print('.'.join(map(str,sys.version_info[:3])), " +
                            "sys.version_info.releaselevel)")
    $parts = $report.Trim().Split(' ')
    $have = [version]$parts[0]
    if ($have -lt [version]$floor) {
        throw "$Python is $have, and pyproject.toml requires $floor or newer."
    }
    if ($parts[1] -ne 'final') {
        throw ("$Python is a pre-release ($report). requirements.lock pins a pydantic that" +
               " raises on import there, and a frozen sidecar built on it fails on its first" +
               " request. Use a final release; the suite runs on 3.13.")
    }

    Step "The shell's crate graph is the one that was committed"
    Push-Location tauri/src-tauri
    try {
        cargo metadata --locked --format-version 1 | Out-Null
        Assert-LastExitCode "cargo metadata --locked"
    } finally {
        Pop-Location
    }

    # -r first, and it is the point rather than tidiness: the lock is what a
    # reader's sidecar contains, and a floating resolve here is how two builds
    # of one tag stop being the same binary (B57). PyInstaller is a build tool
    # rather than part of that closure, so it is not locked.
    Step "Install the Python side"
    & $Python -m pip install --upgrade pip
    Assert-LastExitCode "pip self-upgrade"
    & $Python -m pip install -r requirements.lock -e "." pyinstaller
    Assert-LastExitCode "pip install"

    # And the install has to be *this* tree. `app_version()` reads the
    # installed distribution's metadata, which is what /api/health reports and
    # what PyInstaller freezes -- so an editable install pointing at another
    # checkout (easy to have: one clone on the Desktop, one elsewhere) would
    # freeze that other checkout's code under this one's name, which is B134
    # again one layer in and with no log line to notice it by.
    $installed = & $Python -c "from app.version import app_version; print(app_version())"
    Assert-LastExitCode "read the installed version"
    $tree = (Select-String -Path pyproject.toml -Pattern '^version\s*=\s*"([^"]+)"'
            ).Matches[0].Groups[1].Value
    if ($installed.Trim() -ne $tree) {
        throw ("the install reports $($installed.Trim()) and this tree is $tree." +
               " The sidecar is frozen from the installed distribution, so it would" +
               " carry the wrong code. Check that $Python's environment has no other" +
               " checkout installed, then re-run.")
    }

    # The UI before the freeze: the spec refuses to freeze without a built
    # bundle rather than shipping an app that 404s on its own frontend.
    if ($SkipUi) {
        Step "UI (skipped -- using the committed bundle)"
    } else {
        Step "Build the UI"
        npm --prefix ui ci --no-audit --no-fund
        Assert-LastExitCode "npm ci (ui)"
        npm --prefix ui run build
        Assert-LastExitCode "npm run build (ui)"
    }

    # The knowledge before the freeze, for the same reason as the UI: the spec
    # refuses to freeze without artifacts rather than shipping a knowledge
    # engine with no knowledge in it. Which packs get built is discovered from
    # packs/, so a third one ships by existing.
    Step "Build the packs"
    & $Python packaging/build_packs.py
    Assert-LastExitCode "build_packs.py"

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
    # The master lives outside src-tauri/icons/ because this command
    # *writes into* that directory, icon.png included. Pointed at a
    # file in there it consumed and replaced its own input, dirtying a
    # committed PNG on every build. See packaging/render_icon.py.
    npm --prefix tauri run tauri icon ../packaging/icon-master.png
    Assert-LastExitCode "tauri icon"

    # Self-update is a build-time decision, because the key that makes it
    # trustworthy lives in a secret. With no key this is a no-op and the build
    # still produces an installer -- it just cannot update itself, which is the
    # honest state of B63/B64.
    Step "Configure self-update"
    if (-not $Repo) {
        $origin = (& git remote get-url origin 2>$null)
        if ($LASTEXITCODE -eq 0 -and $origin -match "[:/]([^/:]+/[^/]+?)(?:\.git)?\s*$") {
            $Repo = $Matches[1]
        } else {
            throw "could not read owner/name from `git remote get-url origin`; pass -Repo"
        }
    }
    # Built as an array, and `--version` is only present when there is one.
    # Passing `--version ""` is what the first run of this script did, and
    # Windows PowerShell *drops* an empty-string argument on its way to a
    # native command -- so argparse saw a bare `--version`, demanded a value
    # and exited 2, nine minutes into the build. pwsh 7.3+ has
    # PSNativeCommandArgumentPassing to fix that; 5.1 does not, and 5.1 is what
    # is on the box. So the empty case is expressed by *absence*, which both
    # shells agree on.
    $updater = @("packaging/configure_updater.py", "--repo", $Repo)
    if ($Version) { $updater += @("--version", $Version) }
    Write-Host ($updater -join " ")
    & $Python $updater
    Assert-LastExitCode "configure_updater.py"

    Step "Bundle"
    npm --prefix tauri run tauri build
    Assert-LastExitCode "tauri build"

    # The installer building is not the app starting. v0.2.4 built green on all
    # three runners and then panicked in `build()` before its first window,
    # because a plugin configured at package time was registered
    # unconditionally -- a failure with nowhere to be seen but a stderr no
    # double-click has. So the shell is launched here, before you trust it.
    Step "The bundled shell opens"
    & $Python packaging/smoke_app.py "tauri/src-tauri/target/release/kriko.exe"
    Assert-LastExitCode "smoke_app.py"

    Step "Done"
    $installers = Get-ChildItem -Recurse -Path "tauri/src-tauri/target/release/bundle" `
        -Include *.exe, *.msi -ErrorAction SilentlyContinue |
        Where-Object { $_.LastWriteTime -ge $started }
    if (-not $installers) {
        throw "tauri build reported success and produced no installer from this run"
    }
    # A stamp that did not take is otherwise invisible: the build is green, the
    # installer is real, and its version is whatever the tree happened to be
    # committed at. Tauri names the bundle from the version configure_updater
    # wrote, so the filename is the evidence that the stamp arrived.
    if ($Version) {
        $stamp = $Version -replace '^v', ''
        if (-not ($installers | Where-Object { $_.Name -like "*$stamp*" })) {
            throw "asked to stamp $stamp and no installer from this run carries it"
        }
    }
    $installers | ForEach-Object {
        Write-Host ("{0}  {1:N1} MB" -f $_.FullName, ($_.Length / 1MB)) -ForegroundColor Green
    }
    Write-Host ""
    Write-Host "Unsigned: SmartScreen will warn on first run (More info -> Run anyway)."
} finally {
    Pop-Location
}
