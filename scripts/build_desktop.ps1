param(
    [switch]$SkipTests,
    [switch]$SkipFrontendBuild,
    [switch]$SkipSmokeTest,
    [switch]$SkipPortable,
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$backendRoot = Join-Path $repoRoot "backend"
$frontendRoot = Join-Path $repoRoot "frontend"
$specPath = Join-Path $repoRoot "packaging\mod_watcher_agent.spec"
$distRoot = Join-Path $repoRoot "dist-desktop"
$workRoot = Join-Path $repoRoot "build-desktop"
$smokeScript = Join-Path $PSScriptRoot "smoke_test_desktop.ps1"
$portableScript = Join-Path $PSScriptRoot "package_portable.ps1"
$packagingCommonScript = Join-Path $PSScriptRoot "desktop_packaging_common.ps1"
$releaseRoot = Join-Path $repoRoot "release"
. $packagingCommonScript

function Resolve-CommandPath {
    param([string]$CommandOrPath)

    if (Test-Path -LiteralPath $CommandOrPath -PathType Leaf) {
        return (Resolve-Path -LiteralPath $CommandOrPath).Path
    }
    $command = Get-Command $CommandOrPath -ErrorAction Stop
    return $command.Source
}

function Resolve-ControlledReleaseRoot {
    param(
        [string]$RepoRoot,
        [string]$ReleaseRoot
    )

    $fullRepoRoot = [System.IO.Path]::GetFullPath($RepoRoot).TrimEnd("\", "/")
    $fullReleaseRoot = [System.IO.Path]::GetFullPath($ReleaseRoot).TrimEnd("\", "/")
    $expectedReleaseRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $fullRepoRoot "release")
    ).TrimEnd("\", "/")
    if (-not $fullReleaseRoot.Equals(
        $expectedReleaseRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Release output must be the repository's direct release directory: $fullReleaseRoot"
    }
    if (-not (Test-Path -LiteralPath $fullRepoRoot -PathType Container)) {
        throw "Repository root does not exist: $fullRepoRoot"
    }

    $repoItem = Get-Item -LiteralPath $fullRepoRoot -Force
    if ($repoItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Repository root is a reparse point and cannot anchor release output: $fullRepoRoot"
    }
    $resolvedRepoRoot = (Resolve-Path -LiteralPath $fullRepoRoot).Path.TrimEnd("\", "/")
    if (-not $resolvedRepoRoot.Equals(
        $fullRepoRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Resolved repository root changed unexpectedly: $resolvedRepoRoot"
    }

    if (Test-Path -LiteralPath $fullReleaseRoot) {
        if (-not (Test-Path -LiteralPath $fullReleaseRoot -PathType Container)) {
            throw "Release output exists but is not a directory: $fullReleaseRoot"
        }
    }
    else {
        New-Item -ItemType Directory -Path $fullReleaseRoot | Out-Null
    }

    $releaseItem = Get-Item -LiteralPath $fullReleaseRoot -Force
    if ($releaseItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Release output directory is a reparse point: $fullReleaseRoot"
    }
    $resolvedReleaseRoot = (Resolve-Path -LiteralPath $fullReleaseRoot).Path.TrimEnd("\", "/")
    $resolvedReleaseParent = (Split-Path -Parent $resolvedReleaseRoot).TrimEnd("\", "/")
    if (-not $resolvedReleaseRoot.Equals(
        $fullReleaseRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or -not $resolvedReleaseParent.Equals(
        $resolvedRepoRoot,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or -not (Split-Path -Leaf $resolvedReleaseRoot).Equals(
        "release",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Resolved release output is not the repository's direct release directory."
    }
    return $resolvedReleaseRoot
}

function Assert-ControlledOutputFile {
    param(
        [string]$Path,
        [string]$ExpectedParent,
        [string]$ExpectedLeaf
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $fullParent = [System.IO.Path]::GetFullPath((Split-Path -Parent $fullPath)).TrimEnd("\", "/")
    $fullExpectedParent = [System.IO.Path]::GetFullPath($ExpectedParent).TrimEnd("\", "/")
    $leaf = Split-Path -Leaf $fullPath
    if (-not $fullParent.Equals(
        $fullExpectedParent,
        [System.StringComparison]::OrdinalIgnoreCase
    ) -or -not $leaf.Equals(
        $ExpectedLeaf,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Refusing release file outside the controlled output directory: $fullPath"
    }
    if (-not (Test-Path -LiteralPath $fullExpectedParent -PathType Container)) {
        throw "Controlled release output directory does not exist: $fullExpectedParent"
    }
    $parentItem = Get-Item -LiteralPath $fullExpectedParent -Force
    if ($parentItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Controlled release output directory is a reparse point: $fullExpectedParent"
    }
    $resolvedParent = (Resolve-Path -LiteralPath $fullExpectedParent).Path.TrimEnd("\", "/")
    if (-not $resolvedParent.Equals(
        $fullExpectedParent,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "Resolved release output directory changed unexpectedly: $resolvedParent"
    }
    return $fullPath
}

function Remove-ControlledFile {
    param(
        [string]$Path,
        [string]$ExpectedParent,
        [string]$ExpectedLeaf
    )

    $controlledPath = Assert-ControlledOutputFile `
        -Path $Path `
        -ExpectedParent $ExpectedParent `
        -ExpectedLeaf $ExpectedLeaf
    if (Test-Path -LiteralPath $controlledPath) {
        $item = Get-Item -LiteralPath $controlledPath -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Controlled release artifact is a reparse point: $controlledPath"
        }
        if ($item.PSIsContainer) {
            throw "Controlled release artifact is not a file: $controlledPath"
        }
        $resolvedPath = (Resolve-Path -LiteralPath $controlledPath).Path
        if (-not $resolvedPath.Equals(
            $controlledPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Resolved release artifact changed unexpectedly: $resolvedPath"
        }
        Remove-Item -LiteralPath $controlledPath -Force
    }
}

function Clear-ControlledPortableArtifacts {
    param(
        [string]$RepoRoot,
        [string]$ReleaseRoot
    )

    $resolvedReleaseRoot = Resolve-ControlledReleaseRoot `
        -RepoRoot $RepoRoot `
        -ReleaseRoot $ReleaseRoot
    $semanticVersion = '(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)'
    $portablePattern = "^ModWatcherAgent-$semanticVersion-win-x64-portable\.zip(?:\.sha256)?$"
    $artifactsToRemove = @(
        Get-ChildItem -LiteralPath $resolvedReleaseRoot -Force |
            Where-Object { $_.Name -match $portablePattern }
    )

    # Validate the complete removal set before deleting anything. This keeps a
    # matching junction or other reparse point from causing a partial cleanup.
    foreach ($artifact in $artifactsToRemove) {
        if ($artifact.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Controlled release artifact is a reparse point: $($artifact.FullName)"
        }
        if ($artifact.PSIsContainer) {
            throw "Controlled release artifact is not a file: $($artifact.FullName)"
        }
        $controlledPath = Assert-ControlledOutputFile `
            -Path $artifact.FullName `
            -ExpectedParent $resolvedReleaseRoot `
            -ExpectedLeaf $artifact.Name
        $resolvedArtifactPath = (Resolve-Path -LiteralPath $controlledPath).Path
        if (-not $resolvedArtifactPath.Equals(
            $controlledPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "Resolved release artifact changed unexpectedly: $resolvedArtifactPath"
        }
    }

    foreach ($artifact in $artifactsToRemove) {
        Remove-ControlledFile `
            -Path $artifact.FullName `
            -ExpectedParent $resolvedReleaseRoot `
            -ExpectedLeaf $artifact.Name
    }
}

function Assert-CleanPortableArchive {
    param([string]$ArchivePath)

    Add-Type -AssemblyName System.IO.Compression.FileSystem
    $archive = [System.IO.Compression.ZipFile]::OpenRead($ArchivePath)
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
}

function Invoke-ExternalCommand {
    param(
        [string]$FilePath,
        [string[]]$Arguments,
        [string]$WorkingDirectory,
        [string]$DisplayName
    )

    Write-Host "[$DisplayName] $FilePath $($Arguments -join ' ')" -ForegroundColor Cyan
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments
        $exitCode = $LASTEXITCODE
    }
    finally {
        Pop-Location
    }
    if ($exitCode -ne 0) {
        [Console]::Error.WriteLine("$DisplayName failed with exit code $exitCode")
        exit $exitCode
    }
}

$appVersion = Test-SafeReleaseVersion `
    -Version (Get-ProjectVersion -PyprojectPath (Join-Path $backendRoot "pyproject.toml")) `
    -Label "project"
$portableLeaf = "ModWatcherAgent-$appVersion-win-x64-portable.zip"
$resolvedReleaseRoot = $null
if (-not $SkipPortable) {
    $resolvedReleaseRoot = Resolve-ControlledReleaseRoot `
        -RepoRoot $repoRoot `
        -ReleaseRoot $releaseRoot
    Clear-ControlledPortableArtifacts `
        -RepoRoot $repoRoot `
        -ReleaseRoot $resolvedReleaseRoot `
}

if ([string]::IsNullOrWhiteSpace($PythonExecutable)) {
    $buildVenv = Join-Path $repoRoot ".venv-desktop-build"
    $venvPython = Join-Path $buildVenv "Scripts\python.exe"
    if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
        $bootstrapPython = Resolve-CommandPath -CommandOrPath "python"
        Write-Host "[python] Creating isolated build environment: $buildVenv" -ForegroundColor Cyan
        Invoke-ExternalCommand `
            -FilePath $bootstrapPython `
            -Arguments @("-m", "venv", $buildVenv) `
            -WorkingDirectory $repoRoot `
            -DisplayName "python venv"
    }
    $PythonExecutable = $venvPython
    Write-Host "[python] Reusing repository build venv: $PythonExecutable" -ForegroundColor Gray
}
else {
    $PythonExecutable = Resolve-CommandPath -CommandOrPath $PythonExecutable
    Write-Host "[python] Using caller-supplied interpreter: $PythonExecutable" -ForegroundColor Gray
}

Invoke-ExternalCommand `
    -FilePath $PythonExecutable `
    -Arguments @(
        "-c",
        "import struct, sys; assert sys.platform == 'win32'; assert struct.calcsize('P') == 8; assert sys.version_info >= (3, 11); print(sys.version)"
    ) `
    -WorkingDirectory $repoRoot `
    -DisplayName "python version"

$editableRequirement = "${backendRoot}[dev,desktop,packaging]"
Invoke-ExternalCommand `
    -FilePath $PythonExecutable `
    -Arguments @(
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "-e",
        $editableRequirement
    ) `
    -WorkingDirectory $repoRoot `
    -DisplayName "pip install [dev,desktop,packaging]"

Invoke-ExternalCommand `
    -FilePath $PythonExecutable `
    -Arguments @(
        "-c",
        "import importlib.metadata as m; print('PyInstaller=' + m.version('pyinstaller')); print('pywebview=' + m.version('pywebview')); print('pystray=' + m.version('pystray')); print('Pillow=' + m.version('Pillow'))"
    ) `
    -WorkingDirectory $repoRoot `
    -DisplayName "desktop dependency versions"

if (-not $SkipTests) {
    Invoke-ExternalCommand `
        -FilePath $PythonExecutable `
        -Arguments @("-m", "pytest", "backend", "-q") `
        -WorkingDirectory $repoRoot `
        -DisplayName "python -m pytest backend"
    Invoke-ExternalCommand `
        -FilePath $PythonExecutable `
        -Arguments @("-m", "ruff", "check", "backend") `
        -WorkingDirectory $repoRoot `
        -DisplayName "python -m ruff check backend"
}

if (-not $SkipFrontendBuild) {
    $nodeExecutable = Resolve-CommandPath -CommandOrPath "node.exe"
    $npmExecutable = Resolve-CommandPath -CommandOrPath "npm.cmd"
    Invoke-ExternalCommand `
        -FilePath $nodeExecutable `
        -Arguments @("--version") `
        -WorkingDirectory $frontendRoot `
        -DisplayName "node version"
    Invoke-ExternalCommand `
        -FilePath $npmExecutable `
        -Arguments @("ci") `
        -WorkingDirectory $frontendRoot `
        -DisplayName "npm ci"
    Invoke-ExternalCommand `
        -FilePath $npmExecutable `
        -Arguments @("run", "typecheck") `
        -WorkingDirectory $frontendRoot `
        -DisplayName "npm run typecheck"
    Invoke-ExternalCommand `
        -FilePath $npmExecutable `
        -Arguments @("test") `
        -WorkingDirectory $frontendRoot `
        -DisplayName "npm test"
    Invoke-ExternalCommand `
        -FilePath $npmExecutable `
        -Arguments @("run", "build") `
        -WorkingDirectory $frontendRoot `
        -DisplayName "npm run build"
}

$frontendIndex = Join-Path $frontendRoot "dist\index.html"
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "Missing frontend build output: $frontendIndex"
}

Remove-ControlledDirectory `
    -Path $distRoot `
    -AllowedRoot $repoRoot `
    -ExpectedLeaf "dist-desktop"
Remove-ControlledDirectory `
    -Path $workRoot `
    -AllowedRoot $repoRoot `
    -ExpectedLeaf "build-desktop"

Invoke-ExternalCommand `
    -FilePath $PythonExecutable `
    -Arguments @(
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--distpath",
        $distRoot,
        "--workpath",
        $workRoot,
        $specPath
    ) `
    -WorkingDirectory $repoRoot `
    -DisplayName "python -m PyInstaller --clean --distpath --workpath"

$executablePath = Join-Path $distRoot "ModWatcherAgent\ModWatcherAgent.exe"
if (-not (Test-Path -LiteralPath $executablePath -PathType Leaf)) {
    throw "PyInstaller did not produce the expected executable: $executablePath"
}
$executableDir = Split-Path -Parent $executablePath
Assert-X64PortableExecutable -Path $executablePath
Assert-RequiredDesktopRuntimeFiles -BundleRoot $executableDir

$powershellExecutable = Resolve-CommandPath -CommandOrPath "powershell.exe"
if (-not $SkipSmokeTest) {
    Invoke-ExternalCommand `
        -FilePath $powershellExecutable `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $smokeScript,
            "-ExecutablePath",
            $executablePath
        ) `
        -WorkingDirectory $repoRoot `
        -DisplayName "packaged smoke_test_desktop.ps1"
}

if (-not $SkipPortable) {
    Invoke-ExternalCommand `
        -FilePath $powershellExecutable `
        -Arguments @(
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            $portableScript,
            "-ExecutableDir",
            $executableDir,
            "-OutputDir",
            $resolvedReleaseRoot,
            "-Version",
            $appVersion
        ) `
        -WorkingDirectory $repoRoot `
        -DisplayName "package_portable.ps1"

    $portablePath = Join-Path $resolvedReleaseRoot $portableLeaf
    if (-not (Test-Path -LiteralPath $portablePath -PathType Leaf)) {
        throw "Portable packaging did not produce the expected archive: $portablePath"
    }
    Assert-CleanPortableArchive -ArchivePath $portablePath
}

Write-Host "Desktop onedir build: $executableDir" -ForegroundColor Green
