# Put a built APK on GitHub as the phone app's next update.
#
#   powershell -ExecutionPolicy Bypass -File tools\publish-apk.ps1 -Apk ..\release\kriko-agent-0.12.1.apk
#   powershell -ExecutionPolicy Bypass -File tools\publish-apk.ps1 -Apk ..\release\kriko-agent-0.12.1.apk -Publish
#
# Without -Publish it only checks the file, writes the .sha256 beside it and
# prints what it would do. Publishing is public and the people who have the
# app are offered the file, so it is a press of its own.
#
# Why a tag family of its own: this repository's "Latest" release is the desktop
# installer, and the site's download links read it. A phone release must never
# become "Latest", so it is created with --latest=false and the script checks
# afterwards that "Latest" is still the desktop one. The app finds its updates
# by tag (`mobile-v<version>`) and file name (`kriko-agent-<version>.apk`) in
# the list of releases, see src/engine/appupdate.ts.

param(
    [Parameter(Mandatory = $true)][string]$Apk,
    [string]$NotesFile = '',
    [string]$Repo = 'Berbadov/kriko',
    [switch]$Publish
)

$ErrorActionPreference = 'Stop'

$file = (Resolve-Path $Apk).Path
$name = Split-Path $file -Leaf
if ($name -notmatch '^kriko-agent-(\d+\.\d+\.\d+)\.apk$') {
    throw "The file must be named kriko-agent-<major>.<minor>.<patch>.apk, got '$name'."
}
$version = $Matches[1]
$tag = "mobile-v$version"

# The version inside the file must be the one in its name, or the app would
# offer an update it can never finish.
$aapt = Get-ChildItem 'C:\Android\Sdk\build-tools' -Recurse -Filter aapt2.exe -ErrorAction SilentlyContinue |
    Sort-Object FullName -Descending | Select-Object -First 1
if ($aapt) {
    $badging = & $aapt.FullName dump badging $file 2>$null | Select-String "package: name='app.kriko.mobile'" | Select-Object -First 1
    if (-not $badging) { throw 'The file is not a build of app.kriko.mobile.' }
    if ($badging.Line -notmatch "versionName='$([regex]::Escape($version))'") {
        throw "The file says $($badging.Line) but its name says $version."
    }
}

$hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
$sidecar = "$file.sha256"
Set-Content -NoNewline -Path $sidecar -Value "$hash  $name`n"

$notes = if ($NotesFile) { (Resolve-Path $NotesFile).Path } else {
    $generated = Join-Path ([IO.Path]::GetTempPath()) "kriko-mobile-$version-notes.md"
    @"
Kriko Agent $version for Android.

Phones that already have Kriko offer this from Settings, Updates. A new phone: download the APK below and open it.

SHA-256: ``$hash``
"@ | Set-Content -Path $generated
    $generated
}

$size = (Get-Item $file).Length
Write-Host "tag        $tag"
Write-Host "file       $name  ($([math]::Round($size / 1MB, 1)) MB)"
Write-Host "sha-256    $hash"
Write-Host "notes      $notes"

$existing = gh release view $tag --repo $Repo --json tagName 2>$null
if ($LASTEXITCODE -eq 0 -and $existing) { throw "Release $tag already exists. Bump the version instead of replacing a file phones may have fetched." }

if (-not $Publish) {
    Write-Host ''
    Write-Host 'Dry run. To publish: add -Publish.'
    Write-Host "gh release create $tag `"$file`" `"$sidecar`" --repo $Repo --title `"Kriko Agent $version (Android)`" --notes-file `"$notes`" --latest=false"
    return
}

gh release create $tag $file $sidecar --repo $Repo --title "Kriko Agent $version (Android)" --notes-file $notes --latest=false
if ($LASTEXITCODE -ne 0) { throw 'gh release create failed.' }

$latest = (gh api "repos/$Repo/releases/latest" --jq '.tag_name')
if ($latest -eq $tag) { throw "$tag became the repository's Latest release. Fix it on GitHub before anyone downloads the installer." }
Write-Host "Published $tag. The repository's Latest release is still $latest."
