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
$frontendMode = if ($DevMode) { "dev" } else { "static" }

function Test-LocalPortReady {
    param([int]$Port)
    try {
        $tcp = New-Object System.Net.Sockets.TcpClient
        $tcp.Connect("127.0.0.1", $Port)
        $tcp.Close()
        return $true
    } catch {
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
        } catch {
            $pyList = @()
        } finally {
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
                        Major = $major
                        Minor = $minor
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
    } else {
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

function Ensure-BackendDependencies {
    $depsReady = $false
    $oldErrPref = $ErrorActionPreference
    $oldNativePref = $null
    if (Get-Variable -Name PSNativeCommandUseErrorActionPreference -ErrorAction SilentlyContinue) {
        $oldNativePref = $PSNativeCommandUseErrorActionPreference
        $PSNativeCommandUseErrorActionPreference = $false
    }
    try {
        $ErrorActionPreference = "Continue"
        & $venvPython -c "import uvicorn, pystray, PIL" *> $null
        $depsReady = ($LASTEXITCODE -eq 0)
    } catch {
        $depsReady = $false
    } finally {
        $ErrorActionPreference = $oldErrPref
        if ($null -ne $oldNativePref) {
            $PSNativeCommandUseErrorActionPreference = $oldNativePref
        }
    }
    if ($depsReady) {
        Write-Host "[1/3] Backend dependencies OK" -ForegroundColor Gray
        return
    }
    Write-Host "[1/3] Installing backend dependencies..." -ForegroundColor Gray
    Push-Location (Join-Path $root "backend")
    try {
        $pipCacheDir = Join-Path $root ".runtime\pip-cache"
        New-Item -ItemType Directory -Force -Path $pipCacheDir | Out-Null
        & $venvPython -m pip install --no-cache-dir --cache-dir $pipCacheDir -e .
        if ($LASTEXITCODE -ne 0) { throw "Backend install failed" }
    } finally {
        Pop-Location
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

function Ensure-FrontendDevDependencies {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "[X] Node.js 18+ required for development mode" -ForegroundColor Red
        if (-not $Tray) { Pause }
        exit 1
    }
    node -e "const r=require('child_process').spawnSync(process.execPath,['-v'],{encoding:'utf8'}); if (r.error) { console.error(r.error.code || r.error.message); process.exit(1); }" 2>$null
    if ($LASTEXITCODE -ne 0) {
        Write-Host "[X] Node.js cannot spawn child processes on this machine" -ForegroundColor Red
        Write-Host "    Development mode needs a working Node.js LTS install (recommended: Node 20 or 22)." -ForegroundColor Yellow
        Write-Host "    User mode does not require Node.js: use start-user.bat or start.bat." -ForegroundColor Yellow
        if (-not $Tray) { Pause }
        exit 1
    }
    $nodeModules = Join-Path $root "frontend\\node_modules"
    # esbuild ships inside vite's own node_modules in recent npm versions
    $esbuildBin = Join-Path $root "frontend\\node_modules\\vite\\node_modules\\esbuild\\bin\\esbuild"
    if (Test-Path $nodeModules) {
        Push-Location (Join-Path $root "frontend")
        try {
            & node $esbuildBin --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[2/3] Frontend dependencies OK" -ForegroundColor Gray
                return
            }
            Write-Host "[2/3] Frontend dependencies need repair..." -ForegroundColor Yellow
            Push-Location (Join-Path $root "frontend\node_modules\vite")
            npm rebuild esbuild --silent
            Pop-Location
            & node $esbuildBin --version 2>$null | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Host "[2/3] Frontend dependencies repaired" -ForegroundColor Gray
                return
            }
        } finally {
            Pop-Location
        }
    }
    if (Test-Path $nodeModules) {
        Write-Host "[2/3] Reinstalling frontend dependencies..." -ForegroundColor Gray
    } else {
        Write-Host "[2/3] Installing frontend dependencies..." -ForegroundColor Gray
    }
    Push-Location (Join-Path $root "frontend")
    try {
        if (Test-Path (Join-Path $root "frontend\\package-lock.json")) {
            npm ci --silent
        } else {
            npm install --silent
        }
        if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
        & node $esbuildBin --version 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "Frontend dependency validation failed" }
        Write-Host "[2/3] Frontend dependencies OK" -ForegroundColor Gray
    } finally {
        Pop-Location
    }
}

function Ensure-Prerequisites {
    Ensure-Venv
    Ensure-EnvFile
    Ensure-BackendDependencies
    if ($frontendMode -eq "dev") {
        Ensure-FrontendDevDependencies
    } else {
        Ensure-FrontendStaticBuild
    }
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

$serviceReady = Test-LocalPortReady 7500
if ($frontendMode -eq "dev") {
    $serviceReady = $serviceReady -and (Test-LocalPortReady 7501)
}
if ($serviceReady) {
    Write-Host "[i] Service already running; delegating to manager." -ForegroundColor Yellow
    if ($Tray) {
        & $venvPython backend/tray_app.py --frontend-mode $frontendMode
    } else {
        & $venvPython backend/tray_app.py --no-tray --frontend-mode $frontendMode
    }
    exit $LASTEXITCODE
}

Ensure-Prerequisites

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  App      : http://localhost:7500" -ForegroundColor White
Write-Host "  API Docs : http://localhost:7500/docs" -ForegroundColor White
if ($frontendMode -eq "dev") {
    Write-Host "  Frontend : http://localhost:7501" -ForegroundColor White
}
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($Tray) {
    if (-not $DetachedTray) {
        Write-Host ""
        Write-Host "Startup checks completed." -ForegroundColor Green
        Write-Host "Press any key to continue in tray mode and close this window..." -ForegroundColor Yellow
        [void][System.Console]::ReadKey($true)

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
        exit 0
    }
    Write-Host "[Manager] Starting tray manager (frontend-mode=$frontendMode)..." -ForegroundColor Cyan
    & $venvPython backend/tray_app.py --frontend-mode $frontendMode
    exit $LASTEXITCODE
}

Write-Host "[Manager] Starting foreground manager. Press Ctrl+C to stop services." -ForegroundColor Cyan
& $venvPython backend/tray_app.py --no-tray --frontend-mode $frontendMode
exit $LASTEXITCODE
