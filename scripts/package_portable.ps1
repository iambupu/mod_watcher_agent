param(
    [string]$ExecutableDir = "",
    [string]$OutputDir = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ExecutableDir)) {
    $ExecutableDir = Join-Path $repoRoot "dist-desktop\ModWatcherAgent"
}
if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $repoRoot "release"
}

function Get-ProjectVersion {
    param([string]$PyprojectPath)

    foreach ($line in Get-Content -LiteralPath $PyprojectPath) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"\s*$') {
            return $Matches[1]
        }
    }
    throw "Unable to read the project version from $PyprojectPath"
}

function Get-Sha256Hex {
    param([string]$Path)

    if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $sha256.Dispose()
    }
    return ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToLowerInvariant()
}

function Remove-ControlledDirectory {
    param(
        [string]$Path,
        [string]$AllowedRoot,
        [string]$ExpectedLeaf
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $fullRoot = [System.IO.Path]::GetFullPath($AllowedRoot).TrimEnd("\", "/")
    $rootPrefix = "$fullRoot$([System.IO.Path]::DirectorySeparatorChar)"
    $leaf = Split-Path -Leaf $fullPath
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        -not $leaf.Equals($ExpectedLeaf, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing recursive cleanup outside the portable output root: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullPath)) {
        return
    }
    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Refusing recursive cleanup of a reparse point: $fullPath"
    }
    $resolvedPath = (Resolve-Path -LiteralPath $fullPath).Path.TrimEnd("\", "/")
    if (-not $resolvedPath.Equals($fullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved portable cleanup path changed unexpectedly: $resolvedPath"
    }
    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

function Test-ForbiddenPortablePath {
    param(
        [string]$RelativePath,
        [bool]$IsDirectory
    )

    $normalized = $RelativePath.Replace("\", "/").Trim("/")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $false
    }
    $parts = @($normalized.Split("/") | Where-Object { $_ })
    $directoryCount = if ($IsDirectory) { $parts.Count } else { [Math]::Max(0, $parts.Count - 1) }
    $forbiddenDirectories = @(
        "browser_profiles",
        "snapshots",
        "cache",
        "tests",
        "test",
        ".pytest_cache",
        "__pycache__"
    )
    for ($index = 0; $index -lt $directoryCount; $index++) {
        if ($forbiddenDirectories -contains $parts[$index].ToLowerInvariant()) {
            return $true
        }
    }
    if ($IsDirectory) {
        return $false
    }

    $fileName = $parts[-1]
    $fileNameLower = $fileName.ToLowerInvariant()
    if ($fileNameLower -eq ".env" -or $fileNameLower.StartsWith(".env.")) {
        return $true
    }
    if ($fileNameLower -match '\.(db|sqlite|sqlite3)(-.+)?$' -or $fileNameLower.EndsWith(".log")) {
        return $true
    }
    if ($fileNameLower -match '^(id_rsa|id_ed25519|credentials\.json|secrets?\.json|private\.key)$') {
        return $true
    }
    return $false
}

function Assert-CleanPortableTree {
    param([string]$Root)

    $resolvedRoot = (Resolve-Path -LiteralPath $Root).Path.TrimEnd("\", "/")
    $forbidden = @(
        Get-ChildItem -LiteralPath $resolvedRoot -Recurse -Force | Where-Object {
            $relative = $_.FullName.Substring($resolvedRoot.Length).TrimStart("\", "/")
            Test-ForbiddenPortablePath -RelativePath $relative -IsDirectory $_.PSIsContainer
        }
    )
    if ($forbidden.Count -gt 0) {
        $relativeNames = @(
            $forbidden | ForEach-Object {
                $_.FullName.Substring($resolvedRoot.Length).TrimStart("\", "/")
            }
        )
        throw "Forbidden portable content detected: $($relativeNames -join ', ')"
    }
}

$resolvedExecutableDir = (Resolve-Path -LiteralPath $ExecutableDir).Path
$executablePath = Join-Path $resolvedExecutableDir "ModWatcherAgent.exe"
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Missing packaged executable: $executablePath"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-ProjectVersion -PyprojectPath (Join-Path $repoRoot "backend\pyproject.toml")
}

Assert-CleanPortableTree -Root $resolvedExecutableDir
New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$resolvedOutputDir = (Resolve-Path -LiteralPath $OutputDir).Path
$packageName = "ModWatcherAgent-$Version-win-x64-portable"
$zipPath = Join-Path $resolvedOutputDir "$packageName.zip"
$hashPath = "$zipPath.sha256"
$stagingRoot = Join-Path $resolvedOutputDir ".portable-staging"

foreach ($path in @($zipPath, $hashPath)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}
Remove-ControlledDirectory `
    -Path $stagingRoot `
    -AllowedRoot $resolvedOutputDir `
    -ExpectedLeaf ".portable-staging"

try {
    New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null
    Copy-Item -LiteralPath $resolvedExecutableDir -Destination $stagingRoot -Recurse -Force
    $stagedBundle = Join-Path $stagingRoot "ModWatcherAgent"
    Assert-CleanPortableTree -Root $stagedBundle

    Compress-Archive -LiteralPath $stagedBundle -DestinationPath $zipPath -CompressionLevel Optimal

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $forbiddenEntries = @(
            $archive.Entries | Where-Object {
                Test-ForbiddenPortablePath `
                    -RelativePath $_.FullName `
                    -IsDirectory ([string]::IsNullOrEmpty($_.Name))
            }
        )
        if ($forbiddenEntries.Count -gt 0) {
            throw "Forbidden portable ZIP content detected: $($forbiddenEntries.FullName -join ', ')"
        }
    }
    finally {
        $archive.Dispose()
    }

    $hash = Get-Sha256Hex -Path $zipPath
    "$hash  $([System.IO.Path]::GetFileName($zipPath))" | Set-Content `
        -LiteralPath $hashPath `
        -Encoding ascii

    Write-Host "Portable ZIP: $zipPath" -ForegroundColor Green
    Write-Host "SHA256:      $hashPath" -ForegroundColor Green
}
finally {
    Remove-ControlledDirectory `
        -Path $stagingRoot `
        -AllowedRoot $resolvedOutputDir `
        -ExpectedLeaf ".portable-staging"
}
