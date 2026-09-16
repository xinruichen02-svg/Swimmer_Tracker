[CmdletBinding()]
param(
    [switch]$SetupOnly
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$stamp = Join-Path $PSScriptRoot ".venv\.requirements.sha256"

function Find-CompatiblePython {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        $candidates += ,@($py.Source, "-3.12")
        $candidates += ,@($py.Source, "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += ,@($python.Source)
    }

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefixArgs = @($candidate | Select-Object -Skip 1)
        & $exe @prefixArgs -c "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) else 1)" 2>$null
        if ($LASTEXITCODE -eq 0) {
            return [pscustomobject]@{ Exe = $exe; Args = $prefixArgs }
        }
    }
    return $null
}

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Host "[Swimmer Tracker] First run: creating the project environment..." -ForegroundColor Cyan
    $basePython = Find-CompatiblePython
    if (-not $basePython) {
        throw "Python 3.11-3.14 was not found. Install Python from https://www.python.org/downloads/"
    }
    & $basePython.Exe @($basePython.Args) -m venv (Join-Path $PSScriptRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Failed to create the virtual environment." }
}

$requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
$installedHash = if (Test-Path -LiteralPath $stamp) {
    (Get-Content -LiteralPath $stamp -Raw).Trim()
} else { "" }

& $venvPython -c "import cv2, PIL, can" 2>$null
$dependenciesReady = $LASTEXITCODE -eq 0
if (-not $dependenciesReady -or $installedHash -ne $requirementsHash) {
    Write-Host "[Swimmer Tracker] Installing/updating dependencies..." -ForegroundColor Cyan
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw "Failed to update pip." }
    & $venvPython -m pip install -r $requirements
    if ($LASTEXITCODE -ne 0) { throw "Failed to install project dependencies." }
    [System.IO.File]::WriteAllText($stamp, $requirementsHash)
}

if ($SetupOnly) {
    Write-Host "[Swimmer Tracker] Environment check passed." -ForegroundColor Green
    exit 0
}

Write-Host "[Swimmer Tracker] Starting..." -ForegroundColor Green
& $venvPython (Join-Path $PSScriptRoot "vision_app\swimming_gui.py")
exit $LASTEXITCODE
