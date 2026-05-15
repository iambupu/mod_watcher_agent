param(
    [switch]$Tray,
    [switch]$Stop,
    [switch]$Status
)

# Mod Watcher Agent - unified Windows service launcher
$ErrorActionPreference = "Stop"
$host.UI.RawUI.WindowTitle = "Mod Watcher Agent"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root
$pythonExe = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $pythonExe)) {
    $pythonExe = "python"
}
$env:LOG_DIR = Join-Path $root "log"

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

function Ensure-Prerequisites {
    if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
        Write-Host "[X] Python 3.11+ required" -ForegroundColor Red
        if (-not $Tray) { Pause }
        exit 1
    }
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        Write-Host "[X] Node.js 18+ required" -ForegroundColor Red
        if (-not $Tray) { Pause }
        exit 1
    }

    $envPath = Join-Path $root "backend\.env"
    $envExample = Join-Path $root "backend\.env.example"
    if ((-not (Test-Path $envPath)) -and (Test-Path $envExample)) {
        Copy-Item $envExample $envPath
        Write-Host "[!] .env created; please configure API keys" -ForegroundColor Yellow
        if (-not $Tray) {
            Start-Process notepad $envPath
        }
    }

    $backendNeedsInstall = $false
    & $pythonExe -c "import uvicorn, pystray, PIL" 2>$null
    if ($LASTEXITCODE -ne 0) {
        $backendNeedsInstall = $true
    }
    if ($backendNeedsInstall) {
        Write-Host "[1/2] Installing backend dependencies..." -ForegroundColor Gray
        Push-Location (Join-Path $root "backend")
        try {
            & $pythonExe -m pip install -e .
            if ($LASTEXITCODE -ne 0) { throw "Backend install failed" }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[1/2] Backend dependencies OK" -ForegroundColor Gray
    }

    $nodeModules = Join-Path $root "frontend\node_modules"
    if (-not (Test-Path $nodeModules)) {
        Write-Host "[2/2] Installing frontend dependencies..." -ForegroundColor Gray
        Push-Location (Join-Path $root "frontend")
        try {
            npm install --silent
            if ($LASTEXITCODE -ne 0) { throw "Frontend install failed" }
        } finally {
            Pop-Location
        }
    } else {
        Write-Host "[2/2] Frontend dependencies OK" -ForegroundColor Gray
    }
}

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Mod Watcher Agent" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($Stop) {
    Write-Host "[Manager] Stopping managed services..." -ForegroundColor Cyan
    & $pythonExe backend/tray_app.py --stop
    exit $LASTEXITCODE
}

if ($Status) {
    & $pythonExe backend/tray_app.py --status
    exit $LASTEXITCODE
}

$servicesReady = (Test-LocalPortReady 7500) -and (Test-LocalPortReady 7501)
if ($servicesReady) {
    Write-Host "[i] Services already respond on 7500/7501; delegating to manager." -ForegroundColor Yellow
    if ($Tray) {
        & $pythonExe backend/tray_app.py
    } else {
        & $pythonExe backend/tray_app.py --no-tray
    }
    exit $LASTEXITCODE
}

Ensure-Prerequisites

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Backend  : http://localhost:7500" -ForegroundColor White
Write-Host "  API Docs : http://localhost:7500/docs" -ForegroundColor White
Write-Host "  Frontend : http://localhost:7501" -ForegroundColor White
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

if ($Tray) {
    Write-Host "[Manager] Starting unified tray manager..." -ForegroundColor Cyan
    & $pythonExe backend/tray_app.py
    exit $LASTEXITCODE
}

Write-Host "[Manager] Starting unified foreground manager. Press Ctrl+C to stop all child services." -ForegroundColor Cyan
& $pythonExe backend/tray_app.py --no-tray
exit $LASTEXITCODE
