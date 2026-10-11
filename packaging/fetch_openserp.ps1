param([Parameter(Mandatory=$true)][string]$Destination)

$ErrorActionPreference = 'Stop'
$taskSerpVersion = '0.8.12'
$taskExeDigest = '336CD54C25F35BF76827E1D88C97E20FD085F219BFDCC7F96ACF541208FC651B'
# Digest published by GitHub's official v0.8.12 release asset API.
$taskArchiveDigest = '9B93DFDB747641FD8EFFBBD88FC852D547A0624BF6F391BB65D0D378416E227B'
$taskDestination = [System.IO.Path]::GetFullPath($Destination)
if (Test-Path -LiteralPath $taskDestination) {
    if ((Get-FileHash -LiteralPath $taskDestination -Algorithm SHA256).Hash -eq $taskExeDigest) {
        Write-Output "Verified OpenSERP $taskSerpVersion already present."
        return
    }
    throw 'Existing OpenSERP executable has an unexpected digest; refusing to overwrite it.'
}
$taskParent = Split-Path $taskDestination -Parent
New-Item -ItemType Directory -Path $taskParent -Force | Out-Null
$taskArchive = Join-Path $taskParent "openserp-windows-amd64-$taskSerpVersion.tgz"
Invoke-WebRequest -Uri "https://github.com/karust/openserp/releases/download/v$taskSerpVersion/openserp-windows-amd64-$taskSerpVersion.tgz" -OutFile $taskArchive
if ((Get-FileHash -LiteralPath $taskArchive -Algorithm SHA256).Hash -ne $taskArchiveDigest) {
    throw 'OpenSERP release archive digest did not match the official asset digest.'
}
$taskExtract = Join-Path $taskParent 'verified-openserp-extract'
New-Item -ItemType Directory -Path $taskExtract -Force | Out-Null
tar -xzf $taskArchive -C $taskExtract
if ($LASTEXITCODE -ne 0) { throw 'OpenSERP archive extraction failed.' }
$taskExe = Get-ChildItem -LiteralPath $taskExtract -Filter openserp.exe -File -Recurse
if (@($taskExe).Count -ne 1) { throw 'Expected one OpenSERP executable in the verified archive.' }
if ((Get-FileHash -LiteralPath $taskExe.FullName -Algorithm SHA256).Hash -ne $taskExeDigest) {
    throw 'Extracted OpenSERP executable digest did not match.'
}
Copy-Item -LiteralPath $taskExe.FullName -Destination $taskDestination
Write-Output "Downloaded and verified OpenSERP $taskSerpVersion."
