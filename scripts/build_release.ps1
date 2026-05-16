param(
    [string]$OutDir = "release",
    [string]$Version = "",
    [switch]$SkipFrontendBuild
)

$ErrorActionPreference = "Stop"

function Get-VersionFromBackendPyproject {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "Missing file: $Path"
    }
    $lines = Get-Content $Path
    foreach ($line in $lines) {
        if ($line -match '^\s*version\s*=\s*"(.*)"\s*$') {
            return $Matches[1]
        }
    }
    throw "Could not find [project].version in $Path"
}

function Get-Sha256Hex {
    param([string]$Path)
    if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
        return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLowerInvariant()
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha256.Dispose()
    }
    return ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToLowerInvariant()
}

function Copy-TreeFiltered {
    param(
        [string]$Src,
        [string]$Dst,
        [string[]]$ExcludeRelGlobs
    )
    New-Item -ItemType Directory -Force -Path $Dst | Out-Null

    $srcRoot = (Resolve-Path $Src).Path
    # Some dev machines can accumulate unreadable cache dirs; skip those quietly.
    $items = @(Get-ChildItem -LiteralPath $srcRoot -Recurse -Force -ErrorAction SilentlyContinue)
    foreach ($item in $items) {
        $rel = $item.FullName.Substring($srcRoot.Length).TrimStart('\', '/')
        $skip = $false
        foreach ($glob in $ExcludeRelGlobs) {
            if ($rel -like $glob) {
                $skip = $true
                break
            }
        }
        if ($skip) { continue }
        $target = Join-Path $Dst $rel
        if ($item.PSIsContainer) {
            New-Item -ItemType Directory -Force -Path $target | Out-Null
        } else {
            $parent = Split-Path -Parent $target
            New-Item -ItemType Directory -Force -Path $parent | Out-Null
            Copy-Item -LiteralPath $item.FullName -Destination $target -Force
        }
    }
}

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $root
Set-Location $root

if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = Get-VersionFromBackendPyproject (Join-Path $root "backend\pyproject.toml")
}

$dateTag = Get-Date -Format "yyyyMMdd"
$packageName = "mod-watcher-agent-$Version-$dateTag"
$outDirAbs = Resolve-Path -LiteralPath (Join-Path $root $OutDir) -ErrorAction SilentlyContinue
if ($null -eq $outDirAbs) {
    $outDirAbs = (New-Item -ItemType Directory -Force -Path (Join-Path $root $OutDir)).FullName
} else {
    $outDirAbs = $outDirAbs.Path
}

$stagingRoot = Join-Path $outDirAbs $packageName
$zipPath = Join-Path $outDirAbs "$packageName.zip"

if (Test-Path $stagingRoot) {
    Remove-Item -Recurse -Force -LiteralPath $stagingRoot
}
if (Test-Path $zipPath) {
    Remove-Item -Force -LiteralPath $zipPath
}

Write-Host "[1/4] Building frontend static bundle..." -ForegroundColor Cyan
if (-not $SkipFrontendBuild) {
    if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
        throw "Node.js is required to build the frontend. Install Node 20/22 LTS or pass -SkipFrontendBuild (not recommended)."
    }
    Push-Location (Join-Path $root "frontend")
    try {
        if (Test-Path (Join-Path $root "frontend\package-lock.json")) {
            npm ci
        } else {
            npm install
        }
        if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
        npm run build
        if ($LASTEXITCODE -ne 0) { throw "npm run build failed" }
    } finally {
        Pop-Location
    }
}

$distIndex = Join-Path $root "frontend\dist\index.html"
if (-not (Test-Path $distIndex)) {
    throw "Missing frontend build output: frontend/dist/index.html"
}

Write-Host "[2/4] Creating staging folder..." -ForegroundColor Cyan
New-Item -ItemType Directory -Force -Path $stagingRoot | Out-Null

Write-Host "[3/4] Copying release contents..." -ForegroundColor Cyan
Copy-Item -LiteralPath (Join-Path $root "README.md") -Destination (Join-Path $stagingRoot "README.md") -Force
Copy-Item -LiteralPath (Join-Path $root "mwlogo.png") -Destination (Join-Path $stagingRoot "mwlogo.png") -Force
Copy-Item -LiteralPath (Join-Path $root ".env.example") -Destination (Join-Path $stagingRoot ".env.example") -Force

Copy-Item -LiteralPath (Join-Path $root "start-user.bat") -Destination (Join-Path $stagingRoot "start-user.bat") -Force
Copy-Item -LiteralPath (Join-Path $root "start-debug.bat") -Destination (Join-Path $stagingRoot "start-debug.bat") -Force
Copy-Item -LiteralPath (Join-Path $root "start.bat") -Destination (Join-Path $stagingRoot "start.bat") -Force
Copy-Item -LiteralPath (Join-Path $root "start.ps1") -Destination (Join-Path $stagingRoot "start.ps1") -Force

Copy-TreeFiltered -Src (Join-Path $root "backend") -Dst (Join-Path $stagingRoot "backend") -ExcludeRelGlobs @(
    ".venv\*",
    "__pycache__",
    "__pycache__\*",
    ".pytest_cache",
    ".pytest_cache\*",
    ".mypy_cache",
    ".mypy_cache\*",
    ".ruff_cache",
    ".ruff_cache\*",
    "logs",
    "logs\*",
    "mod_watcher_agent.egg-info",
    "mod_watcher_agent.egg-info\*",
    "tests",
    "tests\*",
    ".env",
    "mod_watcher.db"
)

New-Item -ItemType Directory -Force -Path (Join-Path $stagingRoot "frontend\dist") | Out-Null
Copy-TreeFiltered -Src (Join-Path $root "frontend\dist") -Dst (Join-Path $stagingRoot "frontend\dist") -ExcludeRelGlobs @()

Write-Host "[4/4] Creating zip..." -ForegroundColor Cyan
Compress-Archive -Path (Join-Path $stagingRoot "*") -DestinationPath $zipPath -Force

$hash = Get-Sha256Hex -Path $zipPath
$hashPath = Join-Path $outDirAbs "$packageName.sha256"
"$hash  $([IO.Path]::GetFileName($zipPath))" | Set-Content -LiteralPath $hashPath -Encoding ascii

Write-Host ""
Write-Host "OK" -ForegroundColor Green
Write-Host "Staging : $stagingRoot" -ForegroundColor Gray
Write-Host "Zip     : $zipPath" -ForegroundColor Gray
Write-Host "SHA256  : $hashPath" -ForegroundColor Gray
