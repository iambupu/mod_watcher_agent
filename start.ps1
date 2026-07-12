param(
    [switch]$Tray,
    [switch]$DetachedTray,
    [switch]$Stop,
    [switch]$Status,
    [switch]$DevMode
)

# Mod Watcher Agent launcher
$ErrorActionPreference = "Stop"
$host.UI.RawUI.WindowTitle = "Mod Watcher Agent"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$venvDir = Join-Path $root ".venv"
$venvPython = Join-Path $venvDir "Scripts\\python.exe"
$env:LOG_DIR = Join-Path $root "log"
$backendPort = if ($env:MW_BACKEND_PORT) { [int]$env:MW_BACKEND_PORT } else { 17500 }
$frontendDevPort = if ($env:MW_FRONTEND_DEV_PORT) { [int]$env:MW_FRONTEND_DEV_PORT } else { 17501 }
$frontendMode = if ($DevMode) { "dev" } else { "static" }
$nodeCmd = $null
$npmCmd = $null

function Test-LocalPortReady {
    param(
        [int]$Port,
        [int]$TimeoutMilliseconds = 750
    )
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $connect = $tcp.BeginConnect("127.0.0.1", $Port, $null, $null)
        if (-not $connect.AsyncWaitHandle.WaitOne($TimeoutMilliseconds, $false)) {
            $tcp.Close()
            return $false
        }
        $tcp.EndConnect($connect)
        $tcp.Close()
        return $true
    }
    catch {
        return $false
    }
}

function Get-SystemPython {
    if ($env:MW_PYTHON) {
        if (Test-Path $env:MW_PYTHON) {
            & $env:MW_PYTHON -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
            if ($LASTEXITCODE -eq 0) {
                return @($env:MW_PYTHON)
            }
        }
    }
    if (Get-Command py -ErrorAction SilentlyContinue) {
        $oldErrPref = $ErrorActionPreference
        $oldNativePref = $null
        if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
            $oldNativePref = $PSNativeCommandUseErrorActionPreference
            $PSNativeCommandUseErrorActionPreference = $false
        }
        $pyList = @()
        try {
            $ErrorActionPreference = "Continue"
            $pyList = @(& py -0p 2>&1)
        }
        catch {
            $pyList = @()
        }
        finally {
            $ErrorActionPreference = $oldErrPref
            if ($null -ne $oldNativePref) {
                $PSNativeCommandUseErrorActionPreference = $oldNativePref
            }
        }
        if ($LASTEXITCODE -eq 0 -and $pyList) {
            $candidates = @()
            foreach ($line in $pyList) {
                if ($line -match '^\s*-(\d+)\.(\d+)(?:-(32|64))?\s+(.+)$') {
                    $major = [int]$Matches[1]
                    $minor = [int]$Matches[2]
                    $arch = $Matches[3]
                    $selector = if ($arch) { "-$major.$minor-$arch" } else { "-$major.$minor" }
                    $candidates += [PSCustomObject]@{
                        Major    = $major
                        Minor    = $minor
                        Selector = $selector
                    }
                }
            }
            $sorted = $candidates |
            Where-Object { $_.Major -ge 3 } |
            Sort-Object Major, Minor -Descending
            foreach ($candidate in $sorted) {
                & py $candidate.Selector -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
                if ($LASTEXITCODE -eq 0) {
                    return @("py", $candidate.Selector)
                }
            }
        }
    }
    if (Get-Command python -ErrorAction SilentlyContinue) {
        & python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return @("python")
        }
    }
    return $null
}

function Ensure-Venv {
    if (Test-Path $venvPython) {
        & $venvPython -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" *> $null
        if ($LASTEXITCODE -eq 0) {
            return
        }
        Write-Host "[!] Existing .venv is not Python 3.11+; recreating..." -ForegroundColor Yellow
        Remove-Item -Recurse -Force -LiteralPath $venvDir
    }
    $systemPython = Get-SystemPython
    if ($null -eq $systemPython) {
        Write-Host "[X] Python 3.11+ required (Python 3.9 is not supported)." -ForegroundColor Red
        Write-Host "    Install Python 3.11/3.12/3.13 and retry." -ForegroundColor Yellow
        if (-not $Tray) { Pause }
        exit 1
    }
    Write-Host "[0/3] Creating virtual environment (.venv)..." -ForegroundColor Gray
    if ($systemPython.Length -gt 1) {
        & $systemPython[0] $systemPython[1] -m venv $venvDir
    }
    else {
        & $systemPython[0] -m venv $venvDir
    }
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path $venvPython)) {
        throw "Failed to create .venv"
    }
}

function Ensure-EnvFile {
    $envPath = Join-Path $root "backend\\.env"
    $envExample = Join-Path $root "backend\\.env.example"
    if ((-not (Test-Path $envPath)) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envPath
        Write-Host "[!] backend/.env created; configure API keys in Settings page." -ForegroundColor Yellow
    }
}

function Get-BackendDependencyModules {
    $pyprojectPath = Join-Path $root "backend\\pyproject.toml"
    $fallbackModules = @(
        "fastapi",
        "uvicorn",
        "sqlmodel",
        "apscheduler",
        "httpx",
        "feedparser",
        "selectolax",
        "playwright",
        "pydantic",
        "dotenv",
        "pydantic_settings",
        "alembic",
        "langgraph",
        "pystray",
        "PIL"
    )
    $importNameMap = @{
        "pydantic-settings" = "pydantic_settings"
        "python-dotenv" = "dotenv"
        "Pillow" = "PIL"
    }

    if (-not (Test-Path $pyprojectPath)) {
        return $fallbackModules
    }

    $rawDeps = @()
    $inDependencies = $false
    foreach ($line in Get-Content $pyprojectPath) {
        if (-not $inDependencies) {
            if ($line -match "^\s*dependencies\s*=\s*\[") {
                $inDependencies = $true
            }
            continue
        }
        if ($line -match '^\s*\]') {
            break
        }
        if ($line -match '^\s*"(.*?)"') {
            $rawDeps += $Matches[1]
        }
    }

    if (-not $rawDeps) {
        return $fallbackModules
    }

    $modules = @()
    foreach ($dep in $rawDeps) {
        $normalized = $dep.Split(";")[0].Trim()
        $normalized = $normalized.Split("[")[0].Trim()
        $normalized = ($normalized -split '[<>=!~]')[0].Trim()
        if (-not $normalized) {
            continue
        }

        if ($importNameMap.ContainsKey($normalized)) {
            $moduleName = $importNameMap[$normalized]
        }
        else {
            $moduleName = $normalized.ToLower().Replace("-", "_")
        }

        if (-not ($modules -contains $moduleName)) {
            $modules += $moduleName
        }
    }

    if (-not $modules) {
        return $fallbackModules
    }
    $requiredDesktopModules = @("pystray", "PIL")
    foreach ($desktopModule in $requiredDesktopModules) {
        if (-not ($modules -contains $desktopModule)) {
            $modules += $desktopModule
        }
    }
    return $modules
}

function Ensure-BackendDependencies {
    $dependencyModules = Get-BackendDependencyModules
    $missingDependencies = @()
    $oldErrPref = $ErrorActionPreference
    $oldNativePref = $null
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $oldNativePref = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $ErrorActionPreference = "Continue"
        foreach ($module in $dependencyModules) {
            & $venvPython -c "import $module" *> $null
            if ($LASTEXITCODE -ne 0) {
                $missingDependencies += $module
            }
        }
    }
    catch {
        $missingDependencies = @($dependencyModules)
    }
    finally {
        $ErrorActionPreference = $oldErrPref
        if ($null -ne $oldNativePref) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePref
        }
    }
    if (-not $missingDependencies) {
        Write-Host "[1/3] Backend dependencies OK" -ForegroundColor Gray
        return
    }
    Write-Host "[!] Backend dependencies check failed: missing Python modules -> $($missingDependencies -join ', ')" -ForegroundColor Yellow
    Write-Host "[1/3] Installing backend dependencies..." -ForegroundColor Gray
    Push-Location (Join-Path $root "backend")
    try {
        $pipCacheDir = Join-Path $root ".runtime\pip-cache"
        New-Item -ItemType Directory -Force -Path $pipCacheDir | Out-Null
        & $venvPython -m pip install --no-cache-dir --cache-dir $pipCacheDir -e ".[desktop]"
        if ($LASTEXITCODE -ne 0) { throw "Backend install failed" }
    }
    finally {
        Pop-Location
    }
}

function Show-PlaywrightBrowserHint {
    $oldErrPref = $ErrorActionPreference
    $oldNativePref = $null
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $oldNativePref = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $ErrorActionPreference = "Continue"
        & $venvPython -c "from pathlib import Path; from playwright.sync_api import sync_playwright; p=sync_playwright().start(); path=Path(p.chromium.executable_path); p.stop(); raise SystemExit(0 if path.exists() else 1)" *> $null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "[!] LoversLab browser capture needs Playwright Chromium." -ForegroundColor Yellow
            Write-Host "    Run: .venv\\Scripts\\python.exe -m playwright install chromium" -ForegroundColor Yellow
        }
    }
    catch {
        Write-Host "[!] LoversLab browser capture needs Playwright Chromium." -ForegroundColor Yellow
        Write-Host "    Run: .venv\\Scripts\\python.exe -m playwright install chromium" -ForegroundColor Yellow
    }
    finally {
        $ErrorActionPreference = $oldErrPref
        if ($null -ne $oldNativePref) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePref
        }
    }
}

function Ensure-FrontendStaticBuild {
    $distIndex = Join-Path $root "frontend\\dist\\index.html"
    if (Test-Path $distIndex) {
        Write-Host "[2/3] Frontend static bundle OK" -ForegroundColor Gray
        return
    }
    Write-Host "[X] Missing frontend build: frontend/dist/index.html" -ForegroundColor Red
    Write-Host "    Use a release package, or run development mode: start-debug.bat" -ForegroundColor Yellow
    if (-not $Tray) { Pause }
    exit 1
}

function Test-NodeRuntime {
    param([string]$NodePath)

    $script = @"
const cp = require('child_process');
const major = Number(process.versions.node.split('.')[0]);
if (!Number.isFinite(major) || major < 18) {
  console.log('Node.js 18+ required, found ' + process.version);
  process.exit(2);
}
const result = cp.spawnSync(process.execPath, ['-v'], { encoding: 'utf8' });
if (result.error) {
  console.log(String(result.error.code || result.error.message || 'spawn failed'));
  process.exit(3);
}
console.log(process.version);
"@

    $oldErrPref = $ErrorActionPreference
    $oldNativePref = $null
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $oldNativePref = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $ErrorActionPreference = "Continue"
        $output = @(& $NodePath -e $script 2>&1)
        $ok = ($LASTEXITCODE -eq 0)
        $message = ($output | Out-String).Trim()
        return [PSCustomObject]@{
            Ok      = $ok
            Message = $message
            Major   = if ($message -match '^v(\d+)\.') { [int]$Matches[1] } else { 0 }
        }
    }
    catch {
        $message = ($_.Exception.Message -replace "\r?\n", " " -replace "At [A-Za-z]:\\.*$", "").Trim()
        return [PSCustomObject]@{
            Ok      = $false
            Message = $message
            Major   = 0
        }
    }
    finally {
        $ErrorActionPreference = $oldErrPref
        if ($null -ne $oldNativePref) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePref
        }
    }
}

function Get-NpmForNode {
    param([string]$NodePath)

    $nodeDir = Split-Path -Parent $NodePath
    $localNpm = Join-Path $nodeDir "npm.cmd"
    if (Test-Path $localNpm) {
        return $localNpm
    }
    $globalNpm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($globalNpm) {
        return $globalNpm.Source
    }
    return "npm.cmd"
}

function Resolve-NodeRuntime {
    $candidates = New-Object System.Collections.Generic.List[string]

    if ($env:MW_NODE) {
        $candidates.Add($env:MW_NODE)
    }

    foreach ($cmd in @(Get-Command node.exe -All -ErrorAction SilentlyContinue)) {
        if ($cmd.Source) {
            $candidates.Add($cmd.Source)
        }
    }

    $commonPaths = @(
        (Join-Path $env:ProgramFiles "nodejs\node.exe"),
        (Join-Path ${env:ProgramFiles(x86)} "nodejs\node.exe"),
        (Join-Path $env:LOCALAPPDATA "Programs\nodejs\node.exe")
    )
    foreach ($path in $commonPaths) {
        if ($path) {
            $candidates.Add($path)
        }
    }

    $nvmRoots = @(
        (Join-Path $env:APPDATA "nvm"),
        (Join-Path $env:LOCALAPPDATA "nvm")
    )
    foreach ($nvmRoot in $nvmRoots) {
        if (Test-Path $nvmRoot) {
            foreach ($node in @(Get-ChildItem -Path $nvmRoot -Filter node.exe -Recurse -ErrorAction SilentlyContinue)) {
                $candidates.Add($node.FullName)
            }
        }
    }

    $runtimeRoots = @(
        (Join-Path $env:LOCALAPPDATA "JetBrains\acp-agents\.runtimes\node"),
        (Join-Path $env:LOCALAPPDATA "OpenAI\Codex\bin"),
        (Join-Path $env:LOCALAPPDATA "Packages\OpenAI.Codex_2p2nqsd0c76g0\LocalCache\Local\OpenAI\Codex\bin")
    )
    foreach ($runtimeRoot in $runtimeRoots) {
        if (Test-Path $runtimeRoot) {
            foreach ($node in @(Get-ChildItem -Path $runtimeRoot -Filter node.exe -Recurse -ErrorAction SilentlyContinue)) {
                $candidates.Add($node.FullName)
            }
        }
    }

    $seen = New-Object System.Collections.Generic.HashSet[string]
    $failures = New-Object System.Collections.Generic.List[string]
    $working = New-Object System.Collections.Generic.List[object]
    $ordinal = 0
    foreach ($candidate in $candidates) {
        $ordinal += 1
        if (-not $candidate) {
            continue
        }
        $resolved = $candidate
        if (Test-Path $candidate) {
            $resolved = (Resolve-Path -LiteralPath $candidate).Path
        }
        if (-not $seen.Add($resolved.ToLowerInvariant())) {
            continue
        }
        if (-not (Test-Path $resolved)) {
            continue
        }

        $check = Test-NodeRuntime $resolved
        if ($check.Ok) {
            $working.Add([PSCustomObject]@{
                    Node    = $resolved
                    Npm     = Get-NpmForNode $resolved
                    Version = $check.Message
                    Major   = $check.Major
                    Ordinal = $ordinal
                    LtsRank = if ($check.Major -eq 24) { 0 } elseif ($check.Major -eq 22) { 1 } elseif ($check.Major -eq 20) { 2 } else { 3 }
                })
            continue
        }
        $failures.Add("$resolved => $($check.Message)")
    }

    if ($working.Count -gt 0) {
        return $working |
        Sort-Object LtsRank, @{ Expression = "Major"; Descending = $true }, Ordinal |
        Select-Object -First 1
    }

    if ($failures.Count -gt 0) {
        Write-Host "[X] Checked Node candidates, none can run Vite safely:" -ForegroundColor Red
        foreach ($failure in $failures) {
            Write-Host "    $failure" -ForegroundColor Red
        }
    }
    return $null
}

function Ensure-FrontendDevDependencies {
    $runtime = Resolve-NodeRuntime
    if ($null -eq $runtime) {
        Write-Host "[X] Node.js 18+ with working child_process.spawn is required for debug mode" -ForegroundColor Red
        Write-Host "    Install Node.js LTS 20/22, or set MW_NODE to a working node.exe path." -ForegroundColor Yellow
        if (-not $Tray) { Pause }
        exit 1
    }

    $script:nodeCmd = $runtime.Node
    $script:npmCmd = $runtime.Npm
    $env:MW_NODE = $script:nodeCmd
    $env:MW_NPM_CMD = $script:npmCmd
    $nodeDir = Split-Path -Parent $script:nodeCmd
    $env:PATH = "$nodeDir;$env:PATH"
    Write-Host "[2/3] Node runtime OK ($($runtime.Version), $($script:nodeCmd))" -ForegroundColor Gray

    $nodeModules = Join-Path $root "frontend\\node_modules"
    # esbuild ships inside vite's own node_modules in recent npm versions
    $esbuildBin = Join-Path $root "frontend\\node_modules\\vite\\node_modules\\esbuild\\bin\\esbuild"
    if (Test-Path $nodeModules) {
        Push-Location (Join-Path $root "frontend")
        try {
            & $script:nodeCmd $esbuildBin --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[2/3] Frontend dependencies OK" -ForegroundColor Gray
                return
            }
            Write-Host "[2/3] Frontend dependencies need repair..." -ForegroundColor Yellow
            Push-Location (Join-Path $root "frontend\node_modules\vite")
            & $script:npmCmd rebuild esbuild --silent
            Pop-Location
            & $script:nodeCmd $esbuildBin --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[2/3] Frontend dependencies repaired" -ForegroundColor Gray
                return
            }
        }
        finally {
            Pop-Location
        }
    }
    if (Test-Path $nodeModules) {
        Write-Host "[2/3] Reinstalling frontend dependencies..." -ForegroundColor Gray
    }
    else {
        Write-Host "[2/3] Installing frontend dependencies..." -ForegroundColor Gray
    }
    Push-Location (Join-Path $root "frontend")
    try {
        if (Test-Path (Join-Path $root "frontend\\package-lock.json")) {
            & $script:npmCmd ci --silent
        }
        else {
            & $script:npmCmd install --silent
        }
        if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
        & $script:nodeCmd $esbuildBin --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency validation failed" }
        Write-Host "[2/3] Frontend dependencies OK" -ForegroundColor Gray
    }
    finally {
        Pop-Location
    }
}

function Ensure-Prerequisites {
    Ensure-Venv
    Ensure-EnvFile
    Ensure-BackendDependencies
    Show-PlaywrightBrowserHint
    if ($frontendMode -eq "dev") {
        Ensure-FrontendDevDependencies
    }
    else {
        Ensure-FrontendStaticBuild
    }
}

function Wait-ServiceReady {
    param(
        [int]$BackendPort,
        [string]$FrontendMode,
        [int]$FrontendDevPort,
        [int]$MaxWaitSeconds = 150
    )

    $elapsed = 0
    while ($elapsed -lt $MaxWaitSeconds) {
        $backendReady = Test-LocalPortReady $BackendPort
        $frontendReady = $true
        if ($FrontendMode -eq "dev") {
            $frontendReady = Test-LocalPortReady $FrontendDevPort
        }
        if ($backendReady -and $frontendReady) {
            return $true
        }
        Start-Sleep -Seconds 1
        $elapsed += 1
    }
    return $false
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Mod Watcher Agent" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($Stop) {
    Write-Host "[Manager] Stopping managed services..." -ForegroundColor Cyan
    Ensure-Venv
    & $venvPython backend/tray_app.py --stop
    exit $LASTEXITCODE
}

if ($Status) {
    Ensure-Venv
    & $venvPython backend/tray_app.py --status
    exit $LASTEXITCODE
}

$serviceReady = Test-LocalPortReady $backendPort
if ($frontendMode -eq "dev") {
    $serviceReady = $serviceReady -and (Test-LocalPortReady $frontendDevPort)
}
if ($serviceReady) {
    Write-Host "[i] Service already running; delegating to manager." -ForegroundColor Yellow
    if ($Tray) {
        & $venvPython backend/tray_app.py --frontend-mode $frontendMode
    }
    else {
        & $venvPython backend/tray_app.py --no-tray --frontend-mode $frontendMode
    }
    exit $LASTEXITCODE
}

Ensure-Prerequisites

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  App      : http://localhost:$backendPort" -ForegroundColor White
Write-Host "  API Docs : http://localhost:$backendPort/docs" -ForegroundColor White
if ($frontendMode -eq "dev") {
    Write-Host "  Frontend : http://localhost:$frontendDevPort" -ForegroundColor White
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($Tray) {
    if (-not $DetachedTray) {
        $argumentList = @(
            "-NoProfile",
            "-ExecutionPolicy", "Bypass",
            "-WindowStyle", "Hidden",
            "-File", $MyInvocation.MyCommand.Path,
            "-Tray",
            "-DetachedTray"
        )
        if ($DevMode) {
            $argumentList += "-DevMode"
        }
        Start-Process -FilePath "powershell.exe" -ArgumentList $argumentList -WindowStyle Hidden

        Write-Host ""
        Write-Host "[Manager] Starting tray manager and probing service readiness..." -ForegroundColor Cyan
        $ready = Wait-ServiceReady -BackendPort $backendPort -FrontendMode $frontendMode -FrontendDevPort $frontendDevPort -MaxWaitSeconds 150
        if (-not $ready) {
            Write-Host "[X] Service probe timed out. Backend/frontend did not become ready in time." -ForegroundColor Red
            Write-Host "    Check logs: log\\tray.log, log\\backend_service.log, log\\frontend_service.log" -ForegroundColor Yellow
            exit 1
        }

        Write-Host "Startup checks completed and services are healthy." -ForegroundColor Green
        if ($env:MW_WAIT_FOR_KEY_IN_BAT -eq "1") {
            exit 0
        }
        Write-Host "Press any key to close this window and keep running in tray mode..." -ForegroundColor Yellow
        if (-not [System.Console]::IsInputRedirected) {
            [void][System.Console]::ReadKey($true)
        }
        exit 0
    }
    Write-Host "[Manager] Starting tray manager (frontend-mode=$frontendMode)..." -ForegroundColor Cyan
    & $venvPython backend/tray_app.py --frontend-mode $frontendMode
    exit $LASTEXITCODE
}

Write-Host "[Manager] Starting foreground manager. Press Ctrl+C to stop services." -ForegroundColor Cyan
& $venvPython backend/tray_app.py --no-tray --frontend-mode $frontendMode
exit $LASTEXITCODE
