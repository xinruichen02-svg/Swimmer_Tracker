[CmdletBinding()]
param(
    [switch]$SetupOnly,
    [switch]$Repair
)

$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot

$venvDirectory = Join-Path $PSScriptRoot ".venv"
$venvPython = Join-Path $venvDirectory "Scripts\python.exe"
$requirements = Join-Path $PSScriptRoot "requirements.txt"
$stamp = Join-Path $PSScriptRoot ".venv\.requirements.sha256"

function Test-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][object[]]$ArgumentList = @()
    )

    # Windows PowerShell 5.1 turns native stderr into ErrorRecord objects. With
    # ErrorActionPreference=Stop, an expected probe failure would terminate the
    # launcher before we can inspect LASTEXITCODE.
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @ArgumentList 2>$null
        return $LASTEXITCODE -eq 0
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Invoke-NativeCommand {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter()][object[]]$ArgumentList = @()
    )

    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = "Continue"
        & $FilePath @ArgumentList 2>&1 | Out-Host
        return $LASTEXITCODE
    } finally {
        $ErrorActionPreference = $previousErrorActionPreference
    }
}

function Find-CompatiblePython {
    $candidates = @()
    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        # Prefer versions with the broadest third-party wheel availability, but
        # try every version supported by this project.
        foreach ($version in @("3.12", "3.13", "3.11", "3.14")) {
            $candidates += ,@($py.Source, "-$version")
        }
        $candidates += ,@($py.Source, "-3")
    }
    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        $candidates += ,@($python.Source)
    }

    foreach ($candidate in $candidates) {
        $exe = $candidate[0]
        $prefixArgs = @($candidate | Select-Object -Skip 1)
        $probeArgs = $prefixArgs + @("-c", "import sys; raise SystemExit(0 if (3, 11) <= sys.version_info[:2] < (3, 15) and sys.maxsize > 2**32 else 1)")
        if (Test-NativeCommand -FilePath $exe -ArgumentList $probeArgs) {
            return [pscustomobject]@{ Exe = $exe; Args = $prefixArgs }
        }
    }
    return $null
}

function Move-AsideVirtualEnvironment {
    if (-not (Test-Path -LiteralPath $venvDirectory)) { return }

    $backupDirectory = Join-Path $PSScriptRoot (".venv.broken-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff"))
    Move-Item -LiteralPath $venvDirectory -Destination $backupDirectory
    Write-Host "[Swimmer Tracker] The old environment was moved to:" -ForegroundColor Yellow
    Write-Host "  $backupDirectory" -ForegroundColor Yellow
}

function Start-SwimmerTracker {
    if (-not (Test-Path -LiteralPath $requirements -PathType Leaf)) {
        throw "requirements.txt is missing. Please clone or download the complete repository."
    }

    $venvReady = (Test-Path -LiteralPath $venvPython -PathType Leaf) -and
        (Test-NativeCommand -FilePath $venvPython -ArgumentList @(
            "-c",
            "import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix and (3, 11) <= sys.version_info[:2] < (3, 15) and sys.maxsize > 2**32 else 1)"
        ))

    if ($Repair -or ((Test-Path -LiteralPath $venvDirectory) -and -not $venvReady)) {
        Write-Host "[Swimmer Tracker] Repairing the project environment..." -ForegroundColor Yellow
        Move-AsideVirtualEnvironment
        $venvReady = $false
    }

    if (-not $venvReady) {
        Write-Host "[Swimmer Tracker] First run: creating the project environment..." -ForegroundColor Cyan
    $basePython = Find-CompatiblePython
    if (-not $basePython) {
            throw "Python 3.11-3.14 (64-bit) was not found. Install it from https://www.python.org/downloads/windows/ and enable the Python Launcher."
    }
    $createArgs = @($basePython.Args) + @("-m", "venv", (Join-Path $PSScriptRoot ".venv"))
    $createExitCode = Invoke-NativeCommand -FilePath $basePython.Exe -ArgumentList $createArgs
        if ($createExitCode -ne 0) {
            throw "Failed to create the virtual environment. Check write permission and available disk space."
        }
    }

    if (-not (Test-NativeCommand -FilePath $venvPython -ArgumentList @("-c", "import tkinter"))) {
        throw "Tkinter is unavailable. Reinstall Python from python.org with the 'tcl/tk and IDLE' optional feature enabled."
    }

    $requirementsHash = (Get-FileHash -LiteralPath $requirements -Algorithm SHA256).Hash
    $installedHash = if (Test-Path -LiteralPath $stamp) {
        (Get-Content -LiteralPath $stamp -Raw).Trim()
    } else { "" }

    $dependenciesReady = Test-NativeCommand -FilePath $venvPython -ArgumentList @("-c", "import cv2, PIL, can")
    if (-not $dependenciesReady -or $installedHash -ne $requirementsHash) {
        Write-Host "[Swimmer Tracker] Installing/updating dependencies (first run may take a few minutes)..." -ForegroundColor Cyan
        $pipExitCode = Invoke-NativeCommand -FilePath $venvPython -ArgumentList @(
            "-m", "pip", "install", "--disable-pip-version-check", "-r", $requirements
        )
        if ($pipExitCode -ne 0) {
            throw "Failed to install dependencies. Check the network/proxy settings, then run run_app.bat again."
        }

        if (-not (Test-NativeCommand -FilePath $venvPython -ArgumentList @("-c", "import cv2, PIL, can"))) {
            Invoke-NativeCommand -FilePath $venvPython -ArgumentList @("-c", "import cv2, PIL, can") | Out-Null
            throw "Dependencies were installed but could not be imported. Run run_app.bat -Repair to rebuild the environment."
        }
        [System.IO.File]::WriteAllText($stamp, $requirementsHash)
    }

    if ($SetupOnly) {
        Write-Host "[Swimmer Tracker] Environment check passed." -ForegroundColor Green
        return 0
    }

    Write-Host "[Swimmer Tracker] Starting..." -ForegroundColor Green
    return (Invoke-NativeCommand -FilePath $venvPython -ArgumentList @("-m", "vision_app"))
}

try {
    $launcherExitCode = Start-SwimmerTracker
} catch {
    Write-Host ""
    Write-Host "[Swimmer Tracker] Startup failed" -ForegroundColor Red
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host ""
    Write-Host "Troubleshooting:" -ForegroundColor Yellow
    Write-Host "  1. Make sure Python 3.11-3.14 (64-bit) is installed."
    Write-Host "  2. Check the internet connection for the first run."
    Write-Host "  3. Run: run_app.bat -Repair"
    exit 1
}

exit $launcherExitCode
