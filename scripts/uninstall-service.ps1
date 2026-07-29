<#
.SYNOPSIS
    Remove the Jarvis Windows service installed by install-service.ps1
    (design docs/design/OPERATIONAL-RUNTIME.md Part 6.1, packet P0-F).

.DESCRIPTION
    Stops and removes the NSSM-wrapped service. Idempotent: running this
    against a service that does not exist prints a message and exits 0
    rather than failing. Never touches log files under the install root's
    logs\ directory or the .env file -- both are left in place.

.PARAMETER NssmPath
    Full path to nssm.exe. Mandatory -- must be the same binary (or at least
    the same major version) used at install. Never fetched by this script.

.PARAMETER ServiceName
    Windows service name. Optional, defaults to "JarvisRun" (must match the
    -ServiceName used at install time if it was overridden there).

.EXAMPLE
    .\uninstall-service.ps1 -NssmPath C:\tools\nssm-2.24\win64\nssm.exe

.NOTES
    PowerShell 5.1 compatible. Requires an elevated (Administrator) shell.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$NssmPath,

    [string]$ServiceName = "JarvisRun"
)

$ErrorActionPreference = "Stop"

# ---- Refuse clearly when NSSM is missing. Never download it. --------------
if (-not (Test-Path -LiteralPath $NssmPath -PathType Leaf)) {
    Write-Error "NSSM binary not found at '$NssmPath'. Pass the same nssm.exe path used at install (see docs/DEPLOYMENT.md)."
    exit 1
}

# ---- Idempotent: nothing to do if the service isn't installed. ------------
$existingService = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if (-not $existingService) {
    Write-Host "Service '$ServiceName' is not installed. Nothing to do."
    exit 0
}

Write-Host "Stopping service '$ServiceName' (status: $($existingService.Status))..."
if ($existingService.Status -ne 'Stopped') {
    & $NssmPath stop $ServiceName | Out-Null
}

Write-Host "Removing service '$ServiceName'..."
& $NssmPath remove $ServiceName confirm
if ($LASTEXITCODE -ne 0) {
    Write-Error "nssm remove failed with exit code $LASTEXITCODE"
    exit 1
}

Write-Host ""
Write-Host "Service '$ServiceName' removed. Logs and .env under the install root were left in place."
