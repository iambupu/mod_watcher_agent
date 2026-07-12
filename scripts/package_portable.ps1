param(
    [string]$ExecutableDir = "",
    [string]$OutputDir = "",
    [string]$Version = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$packagingCommonScript = Join-Path $PSScriptRoot "desktop_packaging_common.ps1"
. $packagingCommonScript
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

function Resolve-PortableOutputDirectory {
    param([string]$Path)

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    Assert-NoDesktopPathReparsePoints -Path $fullPath -Context "portable output path"
    if (Test-Path -LiteralPath $fullPath) {
        if (-not (Test-Path -LiteralPath $fullPath -PathType Container)) {
            throw "Portable output exists but is not a directory: $fullPath"
        }
    }
    else {
        New-Item -ItemType Directory -Path $fullPath | Out-Null
    }
    Assert-NoDesktopPathReparsePoints -Path $fullPath -Context "portable output path"
    $item = Get-Item -LiteralPath $fullPath -Force
    if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Portable output directory is a reparse point: $fullPath"
    }
    $resolvedPath = (Resolve-Path -LiteralPath $fullPath).Path.TrimEnd("\", "/")
    if (-not $resolvedPath.Equals($fullPath, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved portable output directory changed unexpectedly: $resolvedPath"
    }
    return $resolvedPath
}

function Assert-ControlledPortableOutputFile {
    param(
        [string]$Path,
        [string]$ExpectedParent,
        [string]$ExpectedLeaf
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $fullPath)).TrimEnd("\", "/")
    $fullExpectedParent = [System.IO.Path]::GetFullPath($ExpectedParent).TrimEnd("\", "/")
    $leaf = Split-Path -Leaf $fullPath
    Assert-NoDesktopPathReparsePoints `
        -Path $fullExpectedParent `
        -Context "portable artifact parent path"
    Assert-NoDesktopPathReparsePoints -Path $fullPath -Context "portable artifact path"
    if (-not $fullParent.Equals(
        $fullExpectedParent,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or -not $leaf.Equals(
        $ExpectedLeaf,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing portable artifact outside the controlled output directory: $fullPath"
    }
    $parentItem = Get-Item -LiteralPath $fullExpectedParent -Force
    if ($parentItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Portable output directory is a reparse point: $fullExpectedParent"
    }
    $resolvedParent = (Resolve-Path -LiteralPath $fullExpectedParent).Path.TrimEnd("\", "/")
    if (-not $resolvedParent.Equals(
        $fullExpectedParent,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Resolved portable output directory changed unexpectedly: $resolvedParent"
    }
    return $fullPath
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
    Assert-NoDesktopPathReparsePoints -Path $fullRoot -Context "portable cleanup root"
    Assert-NoDesktopPathReparsePoints -Path $fullPath -Context "portable cleanup path"
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

$resolvedExecutableDir = (Resolve-Path -LiteralPath $ExecutableDir).Path
$executablePath = Join-Path $resolvedExecutableDir "ModWatcherAgent.exe"
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "Missing packaged executable: $executablePath"
}
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-ProjectVersion -PyprojectPath (Join-Path $repoRoot "backend\pyproject.toml")
}
$Version = Test-SafeReleaseVersion -Version $Version

$candidateOutputDir = [System.IO.Path]::GetFullPath($OutputDir)
$candidateStagingRoot = Join-Path $candidateOutputDir ".portable-staging"
Assert-NoDesktopPathReparsePoints -Path $resolvedExecutableDir -Context "portable source path"
Assert-NoDesktopPathReparsePoints -Path $candidateOutputDir -Context "portable output path"
Assert-NoDesktopPathReparsePoints -Path $candidateStagingRoot -Context "portable staging path"
Assert-X64PortableExecutable -Path $executablePath
Assert-CleanDesktopBundleTree -Root $resolvedExecutableDir -Context "portable source"
if (Test-DesktopPathsOverlap `
    -FirstPath $resolvedExecutableDir `
    -SecondPath $candidateOutputDir
) {
    throw (
        "Portable source/output path overlap is not allowed: " +
        "source=$resolvedExecutableDir output=$candidateOutputDir"
    )
}
if (Test-DesktopPathsOverlap `
    -FirstPath $resolvedExecutableDir `
    -SecondPath $candidateStagingRoot
) {
    throw (
        "Portable source/staging path overlap is not allowed: " +
        "source=$resolvedExecutableDir staging=$candidateStagingRoot"
    )
}
$resolvedOutputDir = Resolve-PortableOutputDirectory -Path $OutputDir
$packageName = "ModWatcherAgent-$Version-win-x64-portable"
$zipLeaf = "$packageName.zip"
$hashLeaf = "$zipLeaf.sha256"
$zipPath = Assert-ControlledPortableOutputFile `
    -Path (Join-Path $resolvedOutputDir $zipLeaf) `
    -ExpectedParent $resolvedOutputDir `
    -ExpectedLeaf $zipLeaf
$hashPath = Assert-ControlledPortableOutputFile `
    -Path (Join-Path $resolvedOutputDir $hashLeaf) `
    -ExpectedParent $resolvedOutputDir `
    -ExpectedLeaf $hashLeaf
$stagingRoot = Join-Path $resolvedOutputDir ".portable-staging"

foreach ($path in @($zipPath, $hashPath)) {
    Assert-NoDesktopPathReparsePoints -Path $path -Context "portable artifact path"
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
    Assert-CleanDesktopBundleTree -Root $stagedBundle -Context "portable staging"
    Assert-X64PortableExecutable -Path (Join-Path $stagedBundle "ModWatcherAgent.exe")

    Compress-Archive -LiteralPath $stagedBundle -DestinationPath $zipPath -CompressionLevel Optimal

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $forbiddenEntries = @(
            $archive.Entries | Where-Object {
                Test-ForbiddenDesktopBundlePath `
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

    $zipPath = Assert-ControlledPortableOutputFile `
        -Path $zipPath `
        -ExpectedParent $resolvedOutputDir `
        -ExpectedLeaf $zipLeaf
    $hashPath = Assert-ControlledPortableOutputFile `
        -Path $hashPath `
        -ExpectedParent $resolvedOutputDir `
        -ExpectedLeaf $hashLeaf
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
