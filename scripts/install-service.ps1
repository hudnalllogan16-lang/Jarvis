<#
.SYNOPSIS
    Install Jarvis as a Windows service under NSSM (design
    docs/design/OPERATIONAL-RUNTIME.md Part 6.1, packet P0-F).

.DESCRIPTION
    Wraps <InstallRoot>\.venv\Scripts\jarvis-run.exe -- the headless platform
    entrypoint (jarvis/shell/service.py::serve_headless) -- as a Windows
    service, using the exact NSSM values Part 6.1 records:

        Application          <InstallRoot>\.venv\Scripts\jarvis-run.exe
        AppDirectory         <InstallRoot>
        AppExit Default      Restart
        AppThrottle          60000   (ms; below this counts as a failed start)
        AppRestartDelay      5000    (ms)
        AppStopMethodConsole 15000   (ms; matches the 15s drain budget)
        AppStdout/AppStderr  <InstallRoot>\logs\jarvis-run.log, rotate at 10MB
        Start                SERVICE_DELAYED_AUTO_START

    This script never downloads NSSM. Install it yourself (see
    docs/DEPLOYMENT.md) and pass its path via -NssmPath. It sets no
    AppEnvironmentExtra values -- per design 9.5, AppDirectory + .env is the
    whole secrets mechanism, and a service's environment carries no secret.

    Re-running this script against an already-installed service is safe: the
    existing service is stopped and removed (nssm remove ... confirm) before
    the fresh install, so the net effect of running it twice is the same as
    running it once.

.PARAMETER NssmPath
    Full path to nssm.exe. Mandatory. Never fetched by this script.

.PARAMETER InstallRoot
    The Jarvis installation root -- the directory holding pyproject.toml,
    alembic.ini, migrations\, .venv\ and .env. Mandatory. Becomes the
    service's AppDirectory and the directory jarvis-run.exe is launched from.

.PARAMETER ServiceName
    Windows service name. Optional, defaults to "JarvisRun".

.EXAMPLE
    .\install-service.ps1 -NssmPath C:\tools\nssm-2.24\win64\nssm.exe -InstallRoot D:\Jarvis

.NOTES
    PowerShell 5.1 compatible. Requires an elevated (Administrator) shell --
    NSSM's service install/configure calls need it; this script does not
    self-elevate.

    NSSM's AppRotateBytes/AppRotateOnline rotate the log by renaming it with a
    timestamp once it crosses the size threshold; NSSM has no native setting
    that caps the number of rotated files it keeps. "Keep 10" (Part 6.1) is
    therefore an operational housekeeping task, not something nssm.exe set
    can express -- see docs/DEPLOYMENT.md's runbook section for pruning
    guidance. This script does not delete log files.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$NssmPath,

    [Parameter(Mandatory = $true)]
    [string]$InstallRoot,

    [string]$ServiceName = "JarvisRun"
)

$ErrorActionPreference = "Stop"

function Invoke-Nssm {
    param([string[]]$NssmArgs)
    & $NssmPath @NssmArgs
    if ($LASTEXITCODE -ne 0) {
        throw "nssm $($NssmArgs -join ' ') failed with exit code $LASTEXITCODE"
    }
}

# ---- Refuse clearly when NSSM is missing. Never download it. --------------
if (-not (Test-Path -LiteralPath $NssmPath -PathType Leaf)) {
    Write-Error "NSSM binary not found at '$NssmPath'. This script never downloads NSSM -- install the pinned version yourself (docs/DEPLOYMENT.md has the version and where to get it) and pass its path via -NssmPath."
    exit 1
}

# ---- Refuse clearly when the install root is missing or incomplete. -------
if (-not (Test-Path -LiteralPath $InstallRoot -PathType Container)) {
    Write-Error "Install root '$InstallRoot' does not exist. Pass the directory Jarvis was deployed into via -InstallRoot."
    exit 1
}
$InstallRoot = (Resolve-Path -LiteralPath $InstallRoot).Path

$venvExe = Join-Path $InstallRoot ".venv\Scripts\jarvis-run.exe"
if (-not (Test-Path -LiteralPath $venvExe -PathType Leaf)) {
    Write-Error "jarvis-run.exe not found at '$venvExe'. Run 'uv sync --all-extras' inside '$InstallRoot' first so the venv and its console scripts exist, then re-run this script."
    exit 1
}

$envFile = Join-Path $InstallRoot ".env"
if (-not (Test-Path -LiteralPath $envFile -PathType Leaf)) {
    Write-Warning "No .env found at '$envFile'. jarvis-run will refuse to start without JARVIS_LLM__MODEL and JARVIS_LLM__API_KEY configured there (design 9.5: AppDirectory + .env is the whole secrets mechanism -- create it before starting the service)."
}

$logsDir = Join-Path $InstallRoot "logs"
if (-not (Test-Path -LiteralPath $logsDir)) {
    New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
}
$logFile = Join-Path $logsDir "jarvis-run.log"

# ---- Idempotent re-install: stop + remove any existing service first. -----
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($existingService) {
    Write-Host "Service '$ServiceName' already exists (status: $($existingService.Status)). Stopping and removing before reinstall..."
    if ($existingService.Status -ne 'Stopped') {
        & $NssmPath stop $ServiceName | Out-Null
    }
    & $NssmPath remove $ServiceName confirm | Out-Null
}

# ---- Install, then set every value from Part 6.1's table. -----------------
Invoke-Nssm @("install", $ServiceName, $venvExe)

Invoke-Nssm @("set", $ServiceName, "AppDirectory", $InstallRoot)
Invoke-Nssm @("set", $ServiceName, "AppExit", "Default", "Restart")
Invoke-Nssm @("set", $ServiceName, "AppThrottle", "60000")
Invoke-Nssm @("set", $ServiceName, "AppRestartDelay", "5000")
Invoke-Nssm @("set", $ServiceName, "AppStopMethodConsole", "15000")
Invoke-Nssm @("set", $ServiceName, "AppStdout", $logFile)
Invoke-Nssm @("set", $ServiceName, "AppStderr", $logFile)
Invoke-Nssm @("set", $ServiceName, "AppRotateFiles", "1")
Invoke-Nssm @("set", $ServiceName, "AppRotateOnline", "1")
Invoke-Nssm @("set", $ServiceName, "AppRotateBytes", "10485760")
Invoke-Nssm @("set", $ServiceName, "Start", "SERVICE_DELAYED_AUTO_START")

Write-Host ""
Write-Host "Service '$ServiceName' installed, pointed at '$venvExe'."
Write-Host "AppDirectory: $InstallRoot"
Write-Host "Logs:         $logFile (rotates at 10MB; NSSM does not cap retained file count -- see docs/DEPLOYMENT.md)"
Write-Host ""
Write-Host "Start it with:   & '$NssmPath' start $ServiceName"
Write-Host "Check readiness: curl http://localhost:8000/api/ready"
