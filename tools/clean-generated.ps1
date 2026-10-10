# Preview: ./tools/clean-generated.ps1 -AgentCaches
# Clean:   ./tools/clean-generated.ps1 -AgentCaches -Apply
# Keeps checkout sources, Git history, packs, reports and the main environment.
[CmdletBinding(SupportsShouldProcess)]
param([switch]$Apply, [switch]$AgentCaches)

$ErrorActionPreference = 'Stop'
$cleanupRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path.TrimEnd('\')
$candidates = [Collections.Generic.List[object]]::new()

function Add-Cache([string]$checkout, [string]$relative) {
    $path = Join-Path $checkout $relative
    if (Test-Path -LiteralPath $path -PathType Container) {
        $candidates.Add([pscustomobject]@{Checkout=$checkout; Relative=$relative; Path=$path})
    }
}

foreach ($relative in @('build','.build-review','kriko-gpui/target','kriko-gpui/target-check','kriko-gpui/review-target','kriko-gpui/builds',
                        '.pytest_cache','.mypy_cache','.check-mypy','.ruff_cache','.npm-cache')) {
    Add-Cache $cleanupRoot $relative
}
Get-ChildItem -LiteralPath $cleanupRoot -Directory -Force |
    Where-Object { $_.Name -like '.test-tmp-*' } |
    ForEach-Object { Add-Cache $cleanupRoot $_.Name }

if ($AgentCaches) {
    foreach ($agentDirectory in @('.claude/worktrees','.codex/worktrees')) {
        $parent = Join-Path $cleanupRoot $agentDirectory
        if (-not (Test-Path -LiteralPath $parent -PathType Container)) { continue }
        foreach ($checkout in (Get-ChildItem -LiteralPath $parent -Directory -Force)) {
            if ($checkout.Attributes -band [IO.FileAttributes]::ReparsePoint) { continue }
            foreach ($relative in @('node_modules','ui/node_modules','tauri/node_modules',
                                    'build','kriko-gpui/builds','target',
                                    'tauri/target','tauri/src-tauri/target','src-tauri/target',
                                    '.pytest_cache','.mypy_cache','.ruff_cache','ui/.svelte-kit')) {
                Add-Cache $checkout.FullName $relative
            }
            Get-ChildItem -LiteralPath $checkout.FullName -Directory -Force |
                Where-Object { $_.Name -like '.venv*' } |
                ForEach-Object { Add-Cache $checkout.FullName $_.Name }
            $rust = Join-Path $checkout.FullName 'kriko-gpui'
            if (Test-Path -LiteralPath $rust -PathType Container) {
                Get-ChildItem -LiteralPath $rust -Directory -Force |
                    Where-Object { $_.Name -like 'target*' } |
                    ForEach-Object { Add-Cache $checkout.FullName ('kriko-gpui/' + $_.Name) }
            }
        }
    }
}

$removed = 0
$linked = 0
foreach ($candidate in $candidates) {
    $resolved = (Resolve-Path -LiteralPath $candidate.Path).Path
    if (-not $resolved.StartsWith($cleanupRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Cleanup path escaped workspace: $resolved"
    }
    # Check every ancestor: a junction must not redirect cleanup outside the repo.
    $ancestor = Get-Item -LiteralPath $resolved -Force
    $isLinked = $false
    while ($ancestor.FullName -ne $cleanupRoot) {
        if ($ancestor.Attributes -band [IO.FileAttributes]::ReparsePoint) {
            $isLinked = $true
            break
        }
        $ancestor = $ancestor.Parent
    }
    if ($isLinked) { $linked++; continue }
    $tracked = @(git -C $candidate.Checkout ls-files -- $candidate.Relative)
    if ($LASTEXITCODE -ne 0) { throw "Cannot verify checkout: $($candidate.Checkout)" }
    if ($tracked.Count -gt 0) { throw "Refusing tracked files: $resolved" }
    if ($Apply -and $PSCmdlet.ShouldProcess($resolved, 'Remove generated cache')) {
        Remove-Item -LiteralPath $resolved -Recurse -Force
        $removed++
    } elseif (-not $Apply) {
        Write-Output "Would remove $resolved"
    }
}
Write-Output "Found $($candidates.Count) generated directories; $removed removed; $linked linked paths skipped."
