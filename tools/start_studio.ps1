param([switch]$PrepareOnly)

$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $root
$bootstrap = Join-Path $root 'out/studio/bootstrap'
$pythonHome = Join-Path $bootstrap 'python-3.11.18'
$python = Join-Path $pythonHome 'python.exe'
$env:PYTHONUTF8 = '1'

try {
    if (!(Test-Path -LiteralPath $python -PathType Leaf)) {
        if ($env:PROCESSOR_ARCHITECTURE -ne 'AMD64' -and $env:PROCESSOR_ARCHITEW6432 -ne 'AMD64') {
            throw 'This download requires 64-bit Windows on x64.'
        }
        $stage = Join-Path $bootstrap ([guid]::NewGuid().ToString())
        New-Item -ItemType Directory -Path $stage | Out-Null
        try {
            Write-Host 'Downloading Python 3.11.18 (49 MB)...'
            $archive = Join-Path $stage 'python.tar.gz'
            $url = 'https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.11.18%2B20261026-x86_64-pc-windows-msvc-install_only.tar.gz'
            & curl.exe --fail --location --silent --show-error --proto '=https' --proto-redir '=https' --retry 2 --output $archive $url
            if ($LASTEXITCODE -ne 0) { throw 'Python download failed.' }
            $stream = [IO.File]::OpenRead($archive)
            $sha256 = [Security.Cryptography.SHA256]::Create()
            try {
                $hash = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
            } finally {
                $sha256.Dispose()
                $stream.Dispose()
            }
            if ($hash -ne '75cb501dc11c7b55c6b447c58e4910bce5b1f609f1017328b4f3a858dfaf5428') {
                throw 'Python download failed integrity verification.'
            }
            & tar.exe -xf $archive -C $stage
            if ($LASTEXITCODE -ne 0) { throw 'Python extraction failed.' }
            try {
                [IO.Directory]::Move((Join-Path $stage 'python'), $pythonHome)
            } catch {
                if (!(Test-Path -LiteralPath $python -PathType Leaf)) { throw }
            }
        } finally {
            $stagePath = (Resolve-Path -LiteralPath $stage).Path
            $bootstrapPath = (Resolve-Path -LiteralPath $bootstrap).Path
            if ([IO.Path]::GetDirectoryName($stagePath) -eq $bootstrapPath) {
                Remove-Item -LiteralPath $stagePath -Recurse -Force
            }
        }
    }
    $options = @()
    if ($PrepareOnly) { $options += '--prepare-only' }
    & $python -X utf8 (Join-Path $PSScriptRoot 'setup_studio.py') @options
    exit $LASTEXITCODE
} catch {
    Write-Error $_ -ErrorAction Continue
    exit 1
}
