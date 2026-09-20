[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [ValidateSet('install', 'upgrade', 'uninstall', 'doctor')]
    [string]$Action = 'install',

    [string]$InstallDir = (Join-Path $env:LOCALAPPDATA 'Programs\rdc-tool'),

    [switch]$AddToPath,

    [switch]$DryRun
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-SourceRoot {
    $scriptPath = $PSCommandPath
    if (-not $scriptPath) { throw 'script path cannot be resolved' }
    $scriptDir = Split-Path -Parent $scriptPath
    $root = Split-Path -Parent $scriptDir
    if (-not (Test-Path -LiteralPath (Join-Path $root 'bin\rdc-tool.cmd') -PathType Leaf)) {
        throw "bin/rdc-tool.cmd not found under source root: $root"
    }
    return (Resolve-Path -LiteralPath $root).Path
}

function Resolve-InstallDir {
    param([string]$RawPath)
    $expanded = [Environment]::ExpandEnvironmentVariables($RawPath)
    $full = [System.IO.Path]::GetFullPath($expanded)
    if ([string]::IsNullOrWhiteSpace($full)) { throw 'install dir cannot be blank' }
    if ((Split-Path -Leaf $full) -ieq 'rdx-tools') { throw 'outdated layout: install RDC-Tool in Programs\rdc-tool' }
    if ($full.Length -lt 8) { throw "install dir is unsafe: $full" }
    return $full
}

function Get-UserPathEntries {
    $raw = [Environment]::GetEnvironmentVariable('Path', 'User')
    if ([string]::IsNullOrWhiteSpace($raw)) { return @() }
    return @($raw.Split(';') | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
}

function Set-UserPathEntries {
    param([string[]]$Entries)
    [Environment]::SetEnvironmentVariable('Path', ($Entries -join ';'), 'User')
}

function Write-Step {
    param([string]$Message)
    Write-Output "[rdc-tool-install] $Message"
}

function Assert-LinkFreePath {
    param([string]$Path)
    $cursor = [IO.Path]::GetFullPath($Path)
    while ($cursor) {
        if (Test-Path -LiteralPath $cursor) {
            if ((Get-Item -LiteralPath $cursor -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "refusing linked installation path: $cursor" }
        }
        $parent = Split-Path -Parent $cursor
        if ($parent -eq $cursor) { break }
        $cursor = $parent
    }
}

function Copy-RdcToolTools {
    param(
        [string]$SourceRoot,
        [string]$TargetRoot
    )
    $excludeDirNames = @('intermediate', 'dist', '.git', '.venv', '__pycache__', '.agents', '.codex', '.qoder')
    $excludeDirPrefixes = @('pytest-cache-files-')
    if ($DryRun) {
        Write-Step "DRY-RUN copy $SourceRoot -> $TargetRoot"
        return
    }
    Assert-LinkFreePath -Path $SourceRoot
    Assert-LinkFreePath -Path $TargetRoot
    if ($SourceRoot.TrimEnd('\') -ieq $TargetRoot.TrimEnd('\')) { throw 'source and target must differ' }
    if ($TargetRoot.StartsWith($SourceRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase) -or $SourceRoot.StartsWith($TargetRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'source and target must not contain one another' }
    if (Test-Path -LiteralPath $TargetRoot) {
        if ((Get-Item -LiteralPath $TargetRoot).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'installation target must not be a link' }
        if (-not (Test-Path -LiteralPath (Join-Path $TargetRoot 'cli\run_cli.py'))) { throw 'target is not an RDC-Tool installation' }
    }
    New-Item -ItemType Directory -Path $TargetRoot -Force | Out-Null
    Get-ChildItem -LiteralPath $SourceRoot -Recurse -Force | ForEach-Object {
        if ($_.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "refusing source link: $($_.FullName)" }
        $src = $_.FullName
        $rel = $src.Substring($SourceRoot.Length).TrimStart('\', '/')
        $parts = @($rel -split '[\\/]+' | Where-Object { -not [string]::IsNullOrWhiteSpace($_) })
        foreach ($part in $parts) {
            if ($excludeDirNames -contains $part) { return }
            foreach ($prefix in $excludeDirPrefixes) {
                if ($part.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)) { return }
            }
        }
        $dst = Join-Path $TargetRoot $rel
        Assert-LinkFreePath -Path $dst
        if ($_.PSIsContainer) {
            New-Item -ItemType Directory -Path $dst -Force | Out-Null
        }
        else {
            New-Item -ItemType Directory -Path (Split-Path -Parent $dst) -Force | Out-Null
            Copy-Item -LiteralPath $src -Destination $dst -Force
        }
    }
    foreach ($obsolete in @('rdc-tool.bat', 'scripts\rdc_tool_bat_launcher.ps1')) {
        $old = Join-Path $TargetRoot $obsolete
        if (Test-Path -LiteralPath $old) {
            if ((Get-Item -LiteralPath $old).Attributes -band [IO.FileAttributes]::ReparsePoint) { throw "refusing obsolete link: $old" }
            Remove-Item -LiteralPath $old -Force
        }
    }
}

function Add-RdcToolToPath {
    param([string]$TargetRoot)
    $bin = Join-Path $TargetRoot 'bin'
    $entries = @(Get-UserPathEntries)
    $next = @($entries | Where-Object { $_.TrimEnd('\', '/') -ine $TargetRoot.TrimEnd('\', '/') -and $_.TrimEnd('\', '/') -ine $bin.TrimEnd('\', '/') }) + @($bin)
    if ($DryRun) { Write-Step "DRY-RUN PATH converge $TargetRoot -> $bin"; return }
    Set-UserPathEntries -Entries $next
    Write-Step "PATH entry $bin"
}

function Remove-RdcToolFromPath {
    param([string]$TargetRoot)
    $bin = Join-Path $TargetRoot 'bin'
    $entries = @(Get-UserPathEntries)
    $next = @($entries | Where-Object { $_.TrimEnd('\', '/') -ine $TargetRoot.TrimEnd('\', '/') -and $_.TrimEnd('\', '/') -ine $bin.TrimEnd('\', '/') })
    if ($DryRun) { Write-Step "DRY-RUN remove PATH entries $TargetRoot and $bin"; return }
    Set-UserPathEntries -Entries $next
}

function Invoke-RdcToolDoctor {
    param([string]$Root)
    $python = Join-Path $Root 'binaries\windows\x64\python\python.exe'
    $entry = Join-Path $Root 'cli\run_cli.py'
    if ($DryRun) {
        Write-Step "DRY-RUN doctor $python $entry --json doctor"
        return
    }
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw "bundled Python not found: $python"
    }
    & $python $entry --json doctor
    if ($LASTEXITCODE -ne 0) {
        throw "rdc-tool doctor failed with exit code $LASTEXITCODE"
    }
}

$sourceRoot = Resolve-SourceRoot
$targetRoot = Resolve-InstallDir -RawPath $InstallDir
Write-Step "action=$Action"
Write-Step "source=$sourceRoot"
Write-Step "target=$targetRoot"

switch ($Action) {
    'install' {
        Copy-RdcToolTools -SourceRoot $sourceRoot -TargetRoot $targetRoot
        if ($AddToPath -or (@(Get-UserPathEntries | Where-Object { $_.TrimEnd('\', '/') -ieq $targetRoot.TrimEnd('\', '/') }).Count -gt 0)) { Add-RdcToolToPath -TargetRoot $targetRoot }
        Invoke-RdcToolDoctor -Root $targetRoot
    }
    'upgrade' {
        Copy-RdcToolTools -SourceRoot $sourceRoot -TargetRoot $targetRoot
        if ($AddToPath -or (@(Get-UserPathEntries | Where-Object { $_.TrimEnd('\', '/') -ieq $targetRoot.TrimEnd('\', '/') }).Count -gt 0)) { Add-RdcToolToPath -TargetRoot $targetRoot }
        Invoke-RdcToolDoctor -Root $targetRoot
    }
    'uninstall' {
        if ($DryRun) {
            Write-Step "DRY-RUN remove $targetRoot"
        }
        elseif (Test-Path -LiteralPath $targetRoot) {
            if (-not (Test-Path -LiteralPath (Join-Path $targetRoot 'bin\rdc-tool.cmd') -PathType Leaf)) {
                throw "refusing to remove non-rdc-tool directory: $targetRoot"
            }
            Assert-LinkFreePath -Path $targetRoot
            if (@(Get-ChildItem -LiteralPath $targetRoot -Recurse -Force | Where-Object { $_.Attributes -band [IO.FileAttributes]::ReparsePoint }).Count) { throw "refusing installation containing links: $targetRoot" }
            if ($targetRoot -ieq $sourceRoot -or $sourceRoot.StartsWith($targetRoot.TrimEnd('\') + '\', [StringComparison]::OrdinalIgnoreCase)) { throw "refusing removal of source installation" }
            Remove-Item -LiteralPath $targetRoot -Recurse -Force
            Write-Step "removed $targetRoot"
        }
        Remove-RdcToolFromPath -TargetRoot $targetRoot
    }
    'doctor' {
        Invoke-RdcToolDoctor -Root $targetRoot
    }
}

Write-Step 'done'
