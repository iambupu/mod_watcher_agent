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

function Test-DesktopPathsOverlap {
    param(
        [string]$FirstPath,
        [string]$SecondPath
    )

    $first = [System.IO.Path]::GetFullPath($FirstPath)
    $second = [System.IO.Path]::GetFullPath($SecondPath)
    $firstRoot = [System.IO.Path]::GetPathRoot($first)
    $secondRoot = [System.IO.Path]::GetPathRoot($second)
    if ($first.Length -gt $firstRoot.Length) {
        $first = $first.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }
    if ($second.Length -gt $secondRoot.Length) {
        $second = $second.TrimEnd(
            [System.IO.Path]::DirectorySeparatorChar,
            [System.IO.Path]::AltDirectorySeparatorChar
        )
    }

    $comparison = [System.StringComparison]::OrdinalIgnoreCase
    if ($first.Equals($second, $comparison)) {
        return $true
    }
    $separator = [System.IO.Path]::DirectorySeparatorChar
    $firstPrefix = if ($first.EndsWith($separator)) { $first } else { "$first$separator" }
    $secondPrefix = if ($second.EndsWith($separator)) { $second } else { "$second$separator" }
    return (
        $first.StartsWith($secondPrefix, $comparison) -or
        $second.StartsWith($firstPrefix, $comparison)
    )
}

function Assert-NoDesktopPathReparsePoints {
    param(
        [string]$Path,
        [string]$Context = "desktop path"
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $root = [System.IO.Path]::GetPathRoot($fullPath)
    if ([string]::IsNullOrWhiteSpace($root)) {
        throw "Unable to determine the root for ${Context}: $fullPath"
    }

    $pathsToCheck = [System.Collections.Generic.List[string]]::new()
    $pathsToCheck.Add($root)
    $relative = $fullPath.Substring($root.Length)
    $separators = [char[]]@(
        [System.IO.Path]::DirectorySeparatorChar,
        [System.IO.Path]::AltDirectorySeparatorChar
    )
    $segments = $relative.Split(
        $separators,
        [System.StringSplitOptions]::RemoveEmptyEntries
    )
    $current = $root
    foreach ($segment in $segments) {
        $current = Join-Path $current $segment
        $pathsToCheck.Add($current)
    }

    foreach ($candidate in $pathsToCheck) {
        if (-not (Test-Path -LiteralPath $candidate)) {
            break
        }
        $item = Get-Item -LiteralPath $candidate -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            throw "Reparse point detected in ${Context}: $candidate"
        }
    }
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
    $isPemLike = $fileNameLower -match '\.pem($|[._~-].*)'
    $isPublicKeyPem = $fileNameLower -match '(^|[._-])public[._-]*key([._-]|$)'
    $isNamedPrivateKeyPem = (
        $isPemLike -and
        -not $isPublicKeyPem -and
        $fileNameLower -match '(^|[._-])(?:private[._-]*)?key([._-]|$)'
    )
    if ($fileNameLower -eq ".env" -or $fileNameLower.StartsWith(".env.")) {
        return $true
    }
    if ($fileNameLower -match '\.(db|sqlite|sqlite3)([-.].*)?$' -or
        $fileNameLower -match '\.log([-.].*)?$') {
        return $true
    }
    if ($fileNameLower -match '^(id_(rsa|dsa|ecdsa|ed25519)|credentials\.json|secrets?\.json)($|[._~-].*)' -or
        $fileNameLower -match '\.key($|[._~-].*)' -or
        $fileNameLower -match '\.(pfx|p12)($|[._~-].*)' -or
        $isNamedPrivateKeyPem) {
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
            if (-not $item.PSIsContainer -and
                $item.Name.ToLowerInvariant() -match '\.pem($|[._~-].*)'
            ) {
                $pemContent = [System.IO.File]::ReadAllText($item.FullName)
                if ($pemContent -match '-----BEGIN(?: [A-Z0-9]+)* PRIVATE KEY-----') {
                    throw "Private key PEM content detected in ${Context}: $relative"
                }
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
        if ($stream.Length -lt 0x40 -or
            $reader.ReadByte() -ne 0x4D -or
            $reader.ReadByte() -ne 0x5A) {
            throw "Expected an x64 PE executable but found an invalid DOS header: $resolvedPath"
        }
        $stream.Position = 0x3C
        $peOffset = [int64]$reader.ReadUInt32()
        $coffHeaderEnd = $peOffset + 24
        if ($peOffset -lt 0x40 -or $coffHeaderEnd -gt $stream.Length) {
            throw "Expected an x64 PE executable but found an invalid PE offset: $resolvedPath"
        }
        $stream.Position = $peOffset
        $signature = $reader.ReadUInt32()
        $machine = $reader.ReadUInt16()
        $numberOfSections = $reader.ReadUInt16()
        $stream.Position = $peOffset + 20
        $sizeOfOptionalHeader = $reader.ReadUInt16()
        $characteristics = $reader.ReadUInt16()
        if ($signature -ne 0x00004550 -or $machine -ne 0x8664) {
            throw (
                "Expected an x64 PE executable (Machine=0x8664), " +
                "found signature=0x$($signature.ToString('X8')) " +
                "machine=0x$($machine.ToString('X4')): $resolvedPath"
            )
        }
        if (($characteristics -band 0x0002) -eq 0) {
            throw "Expected an x64 PE executable image but the COFF flag is missing: $resolvedPath"
        }
        if (($characteristics -band 0x2000) -ne 0) {
            throw "Expected an x64 PE executable but found an IMAGE_FILE_DLL: $resolvedPath"
        }
        if ($numberOfSections -lt 1 -or $numberOfSections -gt 96) {
            throw "Expected an x64 PE executable but found an invalid section count: $resolvedPath"
        }
        $optionalHeaderOffset = $peOffset + 24
        $optionalHeaderEnd = $optionalHeaderOffset + $sizeOfOptionalHeader
        if ($sizeOfOptionalHeader -lt 0x70 -or $optionalHeaderEnd -gt $stream.Length) {
            throw "Expected an x64 PE executable but found an invalid optional header size: $resolvedPath"
        }
        $stream.Position = $optionalHeaderOffset
        $optionalMagic = $reader.ReadUInt16()
        if ($optionalMagic -ne 0x020B) {
            throw (
                "Expected an x64 PE32+ executable (Magic=0x020B), " +
                "found magic=0x$($optionalMagic.ToString('X4')): $resolvedPath"
            )
        }
        $sectionTableEnd = $optionalHeaderEnd + ([int64]$numberOfSections * 40)
        if ($sectionTableEnd -gt $stream.Length) {
            throw "Expected an x64 PE executable but found a truncated section table: $resolvedPath"
        }
    }
    finally {
        $reader.Dispose()
        $stream.Dispose()
    }
}
