function Test-SafeReleaseVersion {
    param(
        [string]$Version,
        [string]$Label = "release"
    )

    if ($Version -notmatch '^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$') {
        throw "Unsafe $Label version for artifact names: $Version"
    }
    return $Version
}

function Test-ForbiddenDesktopBundlePath {
    param(
        [string]$RelativePath,
        [bool]$IsDirectory
    )

    $normalized = $RelativePath.Replace("\", "/").Trim("/")
    if ([string]::IsNullOrWhiteSpace($normalized)) {
        return $false
    }
    $parts = @($normalized.Split("/") | Where-Object { $_ })
    $directoryCount = if ($IsDirectory) { $parts.Count } else { [Math]::Max(0, $parts.Count - 1) }
    $forbiddenDirectories = @(
        "data",
        "logs",
        "browser_profiles",
        "snapshots",
        "cache",
        "tests",
        "test",
        ".pytest_cache",
        "__pycache__"
    )
    for ($index = 0; $index -lt $directoryCount; $index++) {
        if ($forbiddenDirectories -contains $parts[$index].ToLowerInvariant()) {
            return $true
        }
    }
    if ($IsDirectory) {
        return $false
    }

    $fileNameLower = $parts[-1].ToLowerInvariant()
    if ($fileNameLower -eq ".env" -or $fileNameLower.StartsWith(".env.")) {
        return $true
    }
    if ($fileNameLower -match '\.(db|sqlite|sqlite3)([-.].*)?$' -or
        $fileNameLower -match '\.log([-.].*)?$') {
        return $true
    }
    if ($fileNameLower -match '^(id_rsa|id_ed25519|credentials\.json|secrets?\.json|private\.key)$' -or
        $fileNameLower -match '\.(pfx|p12)$') {
        return $true
    }
    return $false
}

function Assert-CleanDesktopBundleTree {
    param(
        [string]$Root,
        [string]$Context = "desktop bundle"
    )

    $fullRoot = [System.IO.Path]::GetFullPath($Root).TrimEnd("\", "/")
    if (-not (Test-Path -LiteralPath $fullRoot -PathType Container)) {
        throw "Desktop bundle root does not exist: $fullRoot"
    }
    $rootItem = Get-Item -LiteralPath $fullRoot -Force
    if ($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "Reparse point detected at the $Context root: $fullRoot"
    }
    $resolvedRoot = (Resolve-Path -LiteralPath $fullRoot).Path.TrimEnd("\", "/")
    if (-not $resolvedRoot.Equals($fullRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved $Context root changed unexpectedly: $resolvedRoot"
    }

    $pendingDirectories = [System.Collections.Generic.Stack[string]]::new()
    $pendingDirectories.Push($resolvedRoot)
    while ($pendingDirectories.Count -gt 0) {
        $currentDirectory = $pendingDirectories.Pop()
        foreach ($item in @(Get-ChildItem -LiteralPath $currentDirectory -Force)) {
            $relative = $item.FullName.Substring($resolvedRoot.Length).TrimStart("\", "/")
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "Reparse point detected in ${Context}: $relative"
            }
            if (Test-ForbiddenDesktopBundlePath `
                -RelativePath $relative `
                -IsDirectory $item.PSIsContainer
            ) {
                throw "Forbidden ${Context} content detected: $relative"
            }
            if ($item.PSIsContainer) {
                $pendingDirectories.Push($item.FullName)
            }
        }
    }
}

function Assert-X64PortableExecutable {
    param([string]$Path)

    $resolvedPath = (Resolve-Path -LiteralPath $Path).Path
    $stream = [System.IO.File]::OpenRead($resolvedPath)
    $reader = [System.IO.BinaryReader]::new($stream)
    try {
        if ($stream.Length -lt 0x86 -or
            $reader.ReadByte() -ne 0x4D -or
            $reader.ReadByte() -ne 0x5A) {
            throw "Expected an x64 PE executable but found an invalid DOS header: $resolvedPath"
        }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadInt32()
        if ($peOffset -lt 0 -or ($peOffset + 6) -gt $stream.Length) {
            throw "Expected an x64 PE executable but found an invalid PE offset: $resolvedPath"
        }
        $stream.Position = $peOffset
        $signature = $reader.ReadUInt32()
        $machine = $reader.ReadUInt16()
        if ($signature -ne 0x00004550 -or $machine -ne 0x8664) {
            throw (
                "Expected an x64 PE executable (Machine=0x8664), " +
                "found signature=0x$($signature.ToString('X8')) " +
                "machine=0x$($machine.ToString('X4')): $resolvedPath"
            )
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}
