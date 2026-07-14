param(
    [string]$ExecutablePath = "",
    [int]$TimeoutSeconds = 60
)

$ErrorActionPreference = "Stop"

$repoRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
$packagingCommonScript = Join-Path $PSScriptRoot "desktop_packaging_common.ps1"
. $packagingCommonScript
if ([string]::IsNullOrWhiteSpace($ExecutablePath)) {
    $ExecutablePath = Join-Path $repoRoot "dist-desktop\ModWatcherAgent\ModWatcherAgent.exe"
}
$resolvedExecutablePath = (Resolve-Path -LiteralPath $ExecutablePath).Path
$executableDir = Split-Path -Parent $resolvedExecutablePath
$executableName = Split-Path -Leaf $resolvedExecutablePath

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

    Assert-CleanDesktopBundleTree -Root $BundleRoot -Context "packaged bundle"
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

function Get-AvailableSmokePort {
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        0
    )
    try {
        $listener.Start()
        return [int]$listener.LocalEndpoint.Port
    }
    finally {
        $listener.Stop()
    }
}

Assert-RequiredDesktopRuntimeFiles -BundleRoot $executableDir
Assert-NoRuntimeDataInBundle -BundleRoot $executableDir
Assert-X64PortableExecutable -Path $resolvedExecutablePath
if ((Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath).Count -gt 0) {
    throw "Packaged desktop is already running: $resolvedExecutablePath"
}

$systemTemp = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath())
$smokeRoot = Join-Path $systemTemp "ModWatcherAgent-smoke-$([guid]::NewGuid().ToString('N'))"
$userDataRoot = Join-Path $smokeRoot "user-data"
$stdoutPath = Join-Path $smokeRoot "stdout.txt"
$stderrPath = Join-Path $smokeRoot "stderr.txt"
$smokePort = Get-AvailableSmokePort
$portMarkerPath = Join-Path $userDataRoot "runtime\smoke-port-used.txt"
$previousUserData = $env:MW_USER_DATA_DIR
$hadPreviousUserData = Test-Path Env:MW_USER_DATA_DIR
$process = $null
$processStarted = $false
$stdoutTask = $null
$stderrTask = $null

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
    $startInfo.EnvironmentVariables["MW_SMOKE_PORT"] = [string]$smokePort
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

    $expectedPortMarker = "MW_SMOKE_PORT_USED=$smokePort"
    $stdoutMarkerMatches = @(
        $capturedStdout -split "\r?\n" | Where-Object { $_ -eq $expectedPortMarker }
    ).Count -gt 0
    $fileMarkerMatches = $false
    if (Test-Path -LiteralPath $portMarkerPath -PathType Leaf) {
        $fileMarkerMatches = (
            (Get-Content -LiteralPath $portMarkerPath -Raw).Trim() -eq $expectedPortMarker
        )
    }
    if (-not $stdoutMarkerMatches -and -not $fileMarkerMatches) {
        throw "Packaged smoke test did not report the expected port marker: $expectedPortMarker"
    }

    $remainingProcesses = @(Get-PackagedDesktopProcesses -TargetPath $resolvedExecutablePath)
    if ($remainingProcesses.Count -gt 0) {
        throw "Packaged smoke process residue detected: $($remainingProcesses.ProcessId -join ', ')"
    }
    $listener = [System.Net.Sockets.TcpListener]::new(
        [System.Net.IPAddress]::Loopback,
        $smokePort
    )
    try {
        $listener.Start()
    }
    catch {
        throw "Packaged smoke loopback port was not released: $smokePort"
    }
    finally {
        $listener.Stop()
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
    Write-Host "Smoke port: $smokePort" -ForegroundColor Gray
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
