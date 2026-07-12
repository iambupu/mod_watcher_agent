param(
    [switch]$SkipTests,
    [switch]$SkipFrontendBuild,
    [switch]$SkipSmokeTest,
    [switch]$SkipPortable,
    [switch]$SkipInstaller,
    [string]$PythonExecutable = "",
    [string]$IsccPath = "",
    [string]$WebView2BootstrapperPath = ""
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
$installerScript = Join-Path $repoRoot "packaging\installer\ModWatcherAgent.iss"
$releaseRoot = Join-Path $repoRoot "release"
. $packagingCommonScript
$requiredDesktopRuntimeFiles = @(
    "_internal\webview\lib\Microsoft.Web.WebView2.Core.dll",
    "_internal\webview\lib\Microsoft.Web.WebView2.WinForms.dll",
    "_internal\webview\lib\runtimes\win-x64\native\WebView2Loader.dll",
    "_internal\pythonnet\runtime\Python.Runtime.dll"
)

function Resolve-CommandPath {
    param([string]$CommandOrPath)

    if (Test-Path -LiteralPath $CommandOrPath -PathType Leaf) {
        return (Resolve-Path -LiteralPath $CommandOrPath).Path
    }
    $command = Get-Command $CommandOrPath -ErrorAction Stop
    return $command.Source
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

function Resolve-IsccPath {
    param([string]$ExplicitPath)

    if (-not [string]::IsNullOrWhiteSpace($ExplicitPath)) {
        if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
            throw "The explicit ISCC path does not exist: $ExplicitPath"
        }
        $resolvedExplicitPath = (Resolve-Path -LiteralPath $ExplicitPath).Path
        if (-not (Split-Path -Leaf $resolvedExplicitPath).Equals(
            "ISCC.exe",
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            throw "The explicit compiler path must point to ISCC.exe: $resolvedExplicitPath"
        }
        return $resolvedExplicitPath
    }

    $pathCommand = Get-Command ISCC.exe -ErrorAction SilentlyContinue
    if ($null -ne $pathCommand) {
        return $pathCommand.Source
    }

    $candidatePaths = @()
    if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
        $candidatePaths += Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"
    }
    if (-not [string]::IsNullOrWhiteSpace($env:ProgramFiles)) {
        $candidatePaths += Join-Path $env:ProgramFiles "Inno Setup 6\ISCC.exe"
    }
    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidatePaths += Join-Path $programFilesX86 "Inno Setup 6\ISCC.exe"
    }
    foreach ($candidatePath in $candidatePaths) {
        if (Test-Path -LiteralPath $candidatePath -PathType Leaf) {
            return (Resolve-Path -LiteralPath $candidatePath).Path
        }
    }

    throw (
        "ISCC.exe was not found. Install Inno Setup 6 from " +
        "https://jrsoftware.org/isdl.php, pass -IsccPath, or use -SkipInstaller."
    )
}

function Test-WebView2BootstrapperIdentity {
    param(
        [string]$OriginalFilename,
        [string]$ProductName
    )

    if ($OriginalFilename.Equals(
        "MicrosoftEdgeUpdateSetup.exe",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        return $ProductName.Equals(
            "Microsoft Edge Update",
            [System.StringComparison]::OrdinalIgnoreCase
        )
    }
    if ($OriginalFilename.Equals(
        "MicrosoftEdgeWebview2Setup.exe",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        return $ProductName -match '(?i)WebView2'
    }
    return $false
}

function Resolve-WebView2BootstrapperPath {
    param([string]$ExplicitPath)

    if ([string]::IsNullOrWhiteSpace($ExplicitPath)) {
        return $null
    }
    if (-not (Test-Path -LiteralPath $ExplicitPath -PathType Leaf)) {
        throw "The WebView2 bootstrapper does not exist: $ExplicitPath"
    }
    $resolvedPath = (Resolve-Path -LiteralPath $ExplicitPath).Path
    $leaf = Split-Path -Leaf $resolvedPath
    if (-not $leaf.Equals(
        "MicrosoftEdgeWebview2Setup.exe",
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        throw "The bootstrapper must be named MicrosoftEdgeWebview2Setup.exe: $resolvedPath"
    }

    $securityModulePath = Join-Path `
        $PSHOME `
        "Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1"
    Import-Module -Name $securityModulePath -ErrorAction Stop
    $signature = Microsoft.PowerShell.Security\Get-AuthenticodeSignature `
        -LiteralPath $resolvedPath
    $signerSubject = if ($null -ne $signature.SignerCertificate) {
        $signature.SignerCertificate.Subject
    }
    else {
        ""
    }
    if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid -or
        $signerSubject -notmatch '(^|,\s*)O=Microsoft Corporation(,|$)') {
        throw "The WebView2 bootstrapper must have a valid Microsoft Corporation signature."
    }

    $fileVersionInfo = [System.Diagnostics.FileVersionInfo]::GetVersionInfo($resolvedPath)
    $originalFilename = [string]$fileVersionInfo.OriginalFilename
    $productName = [string]$fileVersionInfo.ProductName
    if (-not (Test-WebView2BootstrapperIdentity `
        -OriginalFilename $originalFilename `
        -ProductName $productName
    )) {
        throw (
            "WebView2 bootstrapper identity mismatch: " +
            "OriginalFilename='$originalFilename', ProductName='$productName'."
        )
    }
    return $resolvedPath
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
        Remove-Item -LiteralPath $controlledPath -Force
    }
}

function Assert-CleanInstallerSource {
    param([string]$Root)

    Assert-CleanDesktopBundleTree -Root $Root -Context "installer source"
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
        throw "Refusing recursive cleanup outside the controlled build root: $fullPath"
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
        throw "Resolved build cleanup path changed unexpectedly: $resolvedPath"
    }
    Remove-Item -LiteralPath $resolvedPath -Recurse -Force
}

function Assert-RequiredDesktopRuntimeFiles {
    param([string]$BundleRoot)

    foreach ($relativePath in $requiredDesktopRuntimeFiles) {
        $requiredPath = Join-Path $BundleRoot $relativePath
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Missing required desktop runtime file: $requiredPath"
        }
    }
}

$appVersion = Test-SafeReleaseVersion `
    -Version (Get-ProjectVersion -PyprojectPath (Join-Path $backendRoot "pyproject.toml")) `
    -Label "project"
$resolvedReleaseRoot = $null
if (-not $SkipPortable -or -not $SkipInstaller) {
    $resolvedReleaseRoot = Resolve-ControlledReleaseRoot `
        -RepoRoot $repoRoot `
        -ReleaseRoot $releaseRoot
}
$resolvedIsccPath = $null
$resolvedWebView2BootstrapperPath = $null
if (-not $SkipInstaller) {
    $resolvedIsccPath = Resolve-IsccPath -ExplicitPath $IsccPath
    $resolvedWebView2BootstrapperPath = Resolve-WebView2BootstrapperPath `
        -ExplicitPath $WebView2BootstrapperPath
}
elseif (-not [string]::IsNullOrWhiteSpace($WebView2BootstrapperPath)) {
    throw "-WebView2BootstrapperPath cannot be used together with -SkipInstaller."
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

    $portablePath = Join-Path `
        $resolvedReleaseRoot `
        "ModWatcherAgent-$appVersion-win-x64-portable.zip"
    if (-not (Test-Path -LiteralPath $portablePath -PathType Leaf)) {
        throw "Portable packaging did not produce the expected archive: $portablePath"
    }
    Assert-CleanPortableArchive -ArchivePath $portablePath
}

if ($SkipInstaller) {
    Write-Host "[installer] Skipped by -SkipInstaller." -ForegroundColor Gray
}
else {
    if (-not (Test-Path -LiteralPath $installerScript -PathType Leaf)) {
        throw "Missing Inno Setup script: $installerScript"
    }
    Assert-CleanInstallerSource -Root $executableDir

    $resolvedReleaseRoot = Resolve-ControlledReleaseRoot `
        -RepoRoot $repoRoot `
        -ReleaseRoot $releaseRoot
    $installerLeaf = "ModWatcherAgent-Setup-$appVersion-win-x64.exe"
    $installerPath = Assert-ControlledOutputFile `
        -Path (Join-Path $resolvedReleaseRoot $installerLeaf) `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerLeaf
    $installerHashLeaf = "$installerLeaf.sha256"
    $installerHashPath = Assert-ControlledOutputFile `
        -Path (Join-Path $resolvedReleaseRoot $installerHashLeaf) `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerHashLeaf
    Remove-ControlledFile `
        -Path $installerPath `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerLeaf
    Remove-ControlledFile `
        -Path $installerHashPath `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerHashLeaf

    $isccArguments = @(
        "/DAppVersion=$appVersion",
        "/DSourceDir=$executableDir",
        "/DOutputDir=$resolvedReleaseRoot"
    )
    if ($null -ne $resolvedWebView2BootstrapperPath) {
        $isccArguments += "/DWebView2BootstrapperPath=$resolvedWebView2BootstrapperPath"
    }
    $isccArguments += $installerScript
    Invoke-ExternalCommand `
        -FilePath $resolvedIsccPath `
        -Arguments $isccArguments `
        -WorkingDirectory $repoRoot `
        -DisplayName "ISCC.exe ModWatcherAgent.iss"

    $resolvedReleaseRoot = Resolve-ControlledReleaseRoot `
        -RepoRoot $repoRoot `
        -ReleaseRoot $releaseRoot
    $installerPath = Assert-ControlledOutputFile `
        -Path (Join-Path $resolvedReleaseRoot $installerLeaf) `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerLeaf
    if (-not (Test-Path -LiteralPath $installerPath -PathType Leaf)) {
        throw "Inno Setup did not produce the expected installer: $installerPath"
    }
    Assert-CleanInstallerSource -Root $executableDir
    $installerHash = Get-Sha256Hex -Path $installerPath
    $installerHashPath = Assert-ControlledOutputFile `
        -Path (Join-Path $resolvedReleaseRoot $installerHashLeaf) `
        -ExpectedParent $resolvedReleaseRoot `
        -ExpectedLeaf $installerHashLeaf
    "$installerHash  $installerLeaf" | Set-Content `
        -LiteralPath $installerHashPath `
        -Encoding ascii

    Write-Host "Installer:    $installerPath" -ForegroundColor Green
    Write-Host "SHA256:       $installerHashPath" -ForegroundColor Green
}

Write-Host "Desktop onedir build: $executableDir" -ForegroundColor Green
