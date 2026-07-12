param(
    [string]$ExecutablePath = "",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
    $ExecutablePath = Join-Path $repoRoot "dist-desktop\ModWatcherAgent\ModWatcherAgent.exe"
}
$resolvedExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
$executableDir = Split-Path -Parent $resolvedExecutablePath
$executableName = Split-Path -Leaf $resolvedExecutablePath
$requiredDesktopRuntimeFiles = @(
    "_internal\webview\lib\Microsoft.Web.WebView2.Core.dll",
    "_internal\webview\lib\Microsoft.Web.WebView2.WinForms.dll",
    "_internal\webview\lib\runtimes\win-x64\native\WebView2Loader.dll",
    "_internal\pythonnet\runtime\Python.Runtime.dll"
)

function Get-PackagedDesktopProcesses {
    param([string]$TargetPath)

    $normalizedTarget = [System.IO.Path]::GetFullPath($TargetPath)
    return @(
        Get-CimInstance Win32_Process -Filter "Name='$executableName'" -ErrorAction SilentlyContinue |
            Where-Object {
                $_.ExecutablePath -and
                [System.IO.Path]::GetFullPath($_.ExecutablePath).Equals(
                    $normalizedTarget,
                    [System.StringComparison]::OrdinalIgnoreCase
                )
            }
    )
}

function Assert-NoRuntimeDataInBundle {
    param([string]$BundleRoot)

    $forbidden = @(
        Get-ChildItem -LiteralPath $BundleRoot -Recurse -Force -File | Where-Object {
            $name = $_.Name.ToLowerInvariant()
            $name -eq ".env" -or
            $name.StartsWith(".env.") -or
            $name -match '\.(db|sqlite|sqlite3)(-.+)?$' -or
            $name.EndsWith(".log")
        }
    )
    if ($forbidden.Count -gt 0) {
        throw "Runtime data escaped into the packaged bundle: $($forbidden.FullName -join ', ')"
    }
}

function Remove-SmokeDirectory {
    param(
        [string]$Path,
        [string]$TempRoot
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path).TrimEnd("\", "/")
    $fullRoot = [System.IO.Path]::GetFullPath($TempRoot).TrimEnd("\", "/")
    $rootPrefix = "$fullRoot$([System.IO.Path]::DirectorySeparatorChar)"
    $leaf = Split-Path -Leaf $fullPath
    if (-not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase) -or
        $leaf -notlike "ModWatcherAgent-smoke-*") {
        throw "Refusing recursive cleanup outside the controlled smoke root: $fullPath"
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
        throw "Resolved smoke cleanup path changed unexpectedly: $resolvedPath"
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

Assert-RequiredDesktopRuntimeFiles -BundleRoot $executableDir
if ((Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath).Count -gt 0) {
    throw "Packaged desktop is already running: $resolvedExecutablePath"
}

$systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$smokeRoot = Join-Path $systemTemp "ModWatcherAgent-smoke-$([guid]::NewGuid().ToString('N'))"
$userDataRoot = Join-Path $smokeRoot "user-data"
$stdoutPath = Join-Path $smokeRoot "stdout.txt"
$stderrPath = Join-Path $smokeRoot "stderr.txt"
$previousUserData = $env:MW_USER_DATA_DIR
$hadPreviousUserData = Test-Path Env:MW_USER_DATA_DIR
$process = $null
$processStarted = $false
$stdoutTask = $null
$stderrTask = $null
$observedPorts = [System.Collections.Generic.HashSet[int]]::new()

try {
    New-Item -ItemType Directory -Force -Path $userDataRoot | Out-Null
    $env:MW_USER_DATA_DIR = $userDataRoot

    $startInfo = [System.Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $resolvedExecutablePath
    $startInfo.Arguments = "--smoke-test"
    $startInfo.UseShellExecute = $false
    $startInfo.CreateNoWindow = $true
    $startInfo.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
    $startInfo.RedirectStandardOutput = $true
    $startInfo.RedirectStandardError = $true
    $process = [System.Diagnostics.Process]::new()
    $process.StartInfo = $startInfo
    if (-not $process.Start()) {
        throw "Unable to start packaged smoke executable: $resolvedExecutablePath"
    }
    $processStarted = $true
    $stdoutTask = $process.StandardOutput.ReadToEndAsync()
    $stderrTask = $process.StandardError.ReadToEndAsync()

    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    while (-not $process.HasExited) {
        if ($stopwatch.Elapsed.TotalSeconds -gt $TimeoutSeconds) {
            throw "Packaged smoke test timed out after $TimeoutSeconds seconds"
        }
        $targetPids = @(
            Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath |
                ForEach-Object { [int]$_.ProcessId }
        )
        if ($targetPids.Count -gt 0) {
            Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
                Where-Object { $_.OwningProcess -in $targetPids } |
                ForEach-Object { $null = $observedPorts.Add([int]$_.LocalPort) }
        }
        Start-Sleep -Milliseconds 50
        $process.Refresh()
    }
    $process.WaitForExit()
    $capturedStdout = $stdoutTask.Result
    $capturedStderr = $stderrTask.Result
    $capturedStdout | Set-Content -LiteralPath $stdoutPath -Encoding utf8
    $capturedStderr | Set-Content -LiteralPath $stderrPath -Encoding utf8
    $exitCode = $process.ExitCode
    if ($exitCode -ne 0) {
        throw "Packaged smoke test failed with exit code ${exitCode}: $capturedStderr"
    }

    $remainingProcesses = @(Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath)
    if ($remainingProcesses.Count -gt 0) {
        throw "Packaged smoke process residue detected: $($remainingProcesses.ProcessId -join ', ')"
    }
    if ($observedPorts.Count -eq 0) {
        throw "Packaged smoke test did not expose an observable loopback port"
    }
    foreach ($port in $observedPorts) {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Loopback,
            $port
        )
        try {
            $listener.Start()
        }
        catch {
            throw "Packaged smoke loopback port was not released: $port"
        }
        finally {
            $listener.Stop()
        }
    }

    $databasePath = Join-Path $userDataRoot "data\mod_watcher.db"
    $desktopLogPath = Join-Path $userDataRoot "logs\desktop.log"
    if (-not (Test-Path -LiteralPath $databasePath -PathType Leaf)) {
        throw "Packaged smoke database was not created in the isolated root: $databasePath"
    }
    if (-not (Test-Path -LiteralPath $desktopLogPath -PathType Leaf)) {
        throw "Packaged smoke desktop.log was not created in the isolated root: $desktopLogPath"
    }
    $desktopLog = Get-Content -LiteralPath $desktopLogPath -Raw
    if ($desktopLog -notmatch "Desktop smoke test succeeded" -or
        $desktopLog -notmatch "Desktop smoke shutdown complete") {
        throw "Packaged smoke desktop.log is missing success or shutdown evidence"
    }
    Assert-NoRuntimeDataInBundle -BundleRoot $executableDir

    Write-Host "Packaged smoke test passed." -ForegroundColor Green
    Write-Host "Observed ports: $(@($observedPorts) -join ', ')" -ForegroundColor Gray
    Write-Host "Isolated database: $databasePath" -ForegroundColor Gray
    Write-Host "Isolated desktop log: $desktopLogPath" -ForegroundColor Gray
}
finally {
    if ($processStarted -and -not $process.HasExited) {
        Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue
        $process.WaitForExit(5000) | Out-Null
    }
    foreach ($remaining in @(Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath)) {
        Stop-Process -Id $remaining.ProcessId -Force -ErrorAction SilentlyContinue
    }

    if ($hadPreviousUserData) {
        $env:MW_USER_DATA_DIR = $previousUserData
    }
    else {
        Remove-Item Env:MW_USER_DATA_DIR -ErrorAction SilentlyContinue
    }

    Remove-SmokeDirectory -Path $smokeRoot -TempRoot $systemTemp
}
