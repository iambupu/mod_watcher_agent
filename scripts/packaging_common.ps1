function Get-ProjectVersion {
    param([string]$PyprojectPath)

    if (-not (Test-Path -LiteralPath $PyprojectPath -PathType Leaf)) {
        throw "Missing project metadata file: $PyprojectPath"
    }
    foreach ($line in Get-Content -LiteralPath $PyprojectPath) {
        if ($line -match '^\s*version\s*=\s*"([^"]+)"\s*$') {
            return $Matches[1]
        }
    }
    throw "Unable to read the project version from $PyprojectPath"
}

function Get-Sha256Hex {
    param([string]$Path)

    if (Get-Command Get-FileHash -ErrorAction SilentlyContinue) {
        return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $sha256 = [System.Security.Cryptography.SHA256]::Create()
    try {
        $stream = [System.IO.File]::OpenRead($Path)
        try {
            $hashBytes = $sha256.ComputeHash($stream)
        }
        finally {
            $stream.Dispose()
        }
    }
    finally {
        $sha256.Dispose()
    }
    return ([System.BitConverter]::ToString($hashBytes) -replace "-", "").ToLowerInvariant()
}
