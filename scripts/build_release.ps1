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

function Test-NpmEpkgInstallFailure {
    param([string[]]$Output)

    $epmPatterns = @(
        "EPERM",
        "operation is not permitted",
        "unlink",
        "EEXIST",
        "resource is busy",
        "permission denied",
        "spawn"
    )

    foreach ($line in $Output) {
        if ($null -eq $line) {
            continue
        }
        foreach ($pattern in $epmPatterns) {
            if ($line -match $pattern) {
                return $true
            }
        }
    }
    return $false
}

function Stop-FrontendNodeProcesses {
    param([string]$FrontendDir)

    $frontendDirLower = (Resolve-Path $FrontendDir).Path.ToLowerInvariant()
    $stoppedAny = $false

    $frontendMarker = [regex]::Escape($frontendDirLower)
    try {
        $nodeProcesses = Get-CimInstance Win32_Process -Filter "Name='node.exe'" -ErrorAction Stop
        foreach ($process in $nodeProcesses) {
            $commandLine = if ($process.CommandLine) { $process.CommandLine.ToLowerInvariant() } else { "" }
            if (-not $commandLine) {
                continue
            }
            if ($commandLine -match $frontendMarker -or
                $commandLine -match "npm" -or
                $commandLine -match "rollup" -or
                $commandLine -match "vite" ) {
                try {
                    Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
                    $stoppedAny = $true
                    Write-Host "[!] stopped node process PID=$($process.ProcessId) to release frontend npm locks" -ForegroundColor DarkYellow
                } catch {
                    Write-Host "[warn] unable to stop node process PID=$($process.ProcessId): $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
        }
    } catch {
        Write-Host "[warn] cannot enumerate node command-line metadata. Falling back to broad node cleanup." -ForegroundColor Yellow
    }

    if (-not $stoppedAny) {
        $nodeProcesses = Get-Process -Name node -ErrorAction SilentlyContinue
        if ($nodeProcesses) {
            Write-Host "[warn] stopping all node.exe processes as fallback to clear file locks." -ForegroundColor Yellow
            foreach ($process in $nodeProcesses) {
                try {
                    Stop-Process -Id $process.Id -Force -ErrorAction Stop
                    $stoppedAny = $true
                } catch {
                    Write-Host "[warn] unable to stop fallback node PID=$($process.Id): $($_.Exception.Message)" -ForegroundColor Yellow
                }
            }
        }
    }

    return $stoppedAny
}

function Clear-FrontendNpmNativeArtifacts {
    param(
        [string]$FrontendDir,
        [switch]$FullClean
    )

    if ($FullClean) {
        $fullNodeModules = Join-Path $FrontendDir "node_modules"
        if (Test-Path $fullNodeModules) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -LiteralPath $fullNodeModules
        }
        return
    }

    $candidatePaths = @(
        "node_modules\@rollup"
    )
    foreach ($relative in $candidatePaths) {
        $target = Join-Path $FrontendDir $relative
        if (Test-Path $target) {
            Remove-Item -Recurse -Force -ErrorAction SilentlyContinue -LiteralPath $target
        }
    }
}

function Invoke-NpmCommand {
    param(
        [string]$FrontendDir,
        [string]$Command
    )

    $cmdPath = if ($env:ComSpec) { $env:ComSpec } else { "cmd" }
    $cmd = New-Object System.Diagnostics.ProcessStartInfo
    $cmd.FileName = $cmdPath
    $cmd.Arguments = "/c $Command"
    $cmd.WorkingDirectory = $FrontendDir
    $cmd.UseShellExecute = $false
    $cmd.RedirectStandardOutput = $true
    $cmd.RedirectStandardError = $true
    $cmd.CreateNoWindow = $true

    $process = [System.Diagnostics.Process]::Start($cmd)
    $stdOut = $process.StandardOutput.ReadToEnd()
    $stdErr = $process.StandardError.ReadToEnd()
    $process.WaitForExit()
    $exitCode = $process.ExitCode

    $npmOutput = @()
    if ($stdOut) { $npmOutput += $stdOut -split "`r?`n" }
    if ($stdErr) { $npmOutput += $stdErr -split "`r?`n" }
    return @{ ExitCode = $exitCode; Output = $npmOutput }
}

function Invoke-FrontendNpmInstall {
    param(
        [string]$FrontendDir
    )

    $installCmd = if (Test-Path (Join-Path $FrontendDir "package-lock.json")) { "npm ci" } else { "npm install" }
    $fallbackInstallCmd = "${installCmd} --ignore-scripts"
    $npmOutput = @()

    for ($attempt = 1; $attempt -le 2; $attempt++) {
        $cmdToRun = if ($attempt -eq 1) { $installCmd } else { $fallbackInstallCmd }
        Write-Host "[frontend] npm install attempt $attempt/2..." -ForegroundColor Gray
        Push-Location $FrontendDir
        try {
            Write-Host "[frontend] running: $cmdToRun" -ForegroundColor Gray
            $result = Invoke-NpmCommand -FrontendDir $FrontendDir -Command $cmdToRun
            $exitCode = $result.ExitCode
            $npmOutput = $result.Output

            if ($exitCode -eq 0) {
                return $npmOutput
            }
            $LASTEXITCODE = $exitCode
            Write-Host $npmOutput -ForegroundColor Yellow
        }
        finally {
            Pop-Location
        }

        if (-not (Test-NpmEpkgInstallFailure -Output $npmOutput)) {
            break
        }
        $null = Stop-FrontendNodeProcesses -FrontendDir $FrontendDir
        Write-Host "[!] npm install hit file-lock related failure; cleaning frontend native artifacts and retrying..." -ForegroundColor Yellow
        Clear-FrontendNpmNativeArtifacts -FrontendDir $FrontendDir -FullClean:$true
        Start-Sleep -Seconds 1
    }
    if ($LASTEXITCODE -ne 0) {
        throw "npm install failed"
    }
    return $npmOutput
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
    $frontendDir = Join-Path $root "frontend"
    Push-Location $frontendDir
    try {
        Invoke-FrontendNpmInstall -FrontendDir $frontendDir | Out-Null
        $buildResult = Invoke-NpmCommand -FrontendDir $frontendDir -Command "npm run build"
        Write-Host $buildResult.Output -ForegroundColor Yellow
        $LASTEXITCODE = $buildResult.ExitCode
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
Copy-Item -LiteralPath (Join-Path $root "docs\mwlogo.png") -Destination (Join-Path $stagingRoot "mwlogo.png") -Force
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

if (Test-Path (Join-Path $root "chrome-extension")) {
    Copy-TreeFiltered -Src (Join-Path $root "chrome-extension") -Dst (Join-Path $stagingRoot "chrome-extension") -ExcludeRelGlobs @()
}

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
