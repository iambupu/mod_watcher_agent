param(
    [switch]$SkipTests,
    [switch]$SkipFrontendBuild,
    [switch]$SkipSmokeTest,
    [switch]$SkipPortable,
    [switch]$SkipInstaller,
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
        Write-Error "$DisplayName failed with exit code $exitCode"
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
    -Arguments @("-c", "import sys; assert sys.version_info >= (3, 11); print(sys.version)") `
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
            $executableDir
        ) `
        -WorkingDirectory $repoRoot `
        -DisplayName "package_portable.ps1"
}

if ($SkipInstaller) {
    Write-Host "[installer] Skipped by -SkipInstaller." -ForegroundColor Gray
}
else {
    Write-Host "[installer] Not produced: installer work belongs to Task 8." -ForegroundColor Yellow
}

Write-Host "Desktop onedir build: $executableDir" -ForegroundColor Green
