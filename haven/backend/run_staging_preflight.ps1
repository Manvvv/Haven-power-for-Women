<#
.SYNOPSIS
    Haven — Safe Staging Target Configuration & Read-Only Preflight Helper.

.DESCRIPTION
    Guides an operator through verifying an authorized staging MongoDB target
    and executing the read-only index preflight check.

    Features:
    - Never persists connection strings or secrets to disk or git.
    - Prompts for MongoDB connection string via a hidden (SecureString) input.
    - Validates target identifier, hostname allowlist, and database name offline.
    - Shows the index plan completely offline.
    - Requires explicit operator confirmation ("yes") BEFORE attempting any network connection.
    - Runs preflight_index_check.py (read-only; performs zero writes/drops).
    - NEVER runs setup_indexes.py or mutates data.
    - Clears process-level connection string and staging variables upon completion or abort.

.PARAMETER TargetId
    Optional: Explicit approved staging target identifier (e.g. haven-staging-01).
    If omitted, the script prompts interactively.

.PARAMETER HostAllowlist
    Optional: Comma-separated list of authorized staging hostnames.
    If omitted, the script prompts interactively.

.PARAMETER DatabaseName
    Optional: Application database name (default: Haven).

.PARAMETER SecureEndpoint
    Optional: SecureString containing the MongoDB connection URI.
    If omitted, the script prompts securely with input masked.

.PARAMETER NonInteractive
    Optional: Run without interactive prompts (uses parameters or environment).

.EXAMPLE
    # Interactive mode (recommended for operators):
    .\run_staging_preflight.ps1

.EXAMPLE
    # Automated target check only:
    .\run_staging_preflight.ps1 -TargetId "haven-stage" -HostAllowlist "stage.example.net" -NonInteractive
#>

[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$TargetId,

    [Parameter(Mandatory = $false)]
    [string]$HostAllowlist,

    [Parameter(Mandatory = $false)]
    [string]$DatabaseName = "Haven",

    [Parameter(Mandatory = $false)]
    [System.Security.SecureString]$SecureEndpoint,

    [Parameter(Mandatory = $false)]
    [switch]$NonInteractive
)

# Enforce strict error action preference
$ErrorActionPreference = "Stop"

# Determine canonical python path
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoDir = (Get-Item $ScriptDir).Parent.FullName

$PythonPath = Join-Path $ScriptDir ".venv\Scripts\python.exe"
if (-not (Test-Path $PythonPath)) {
    $PythonPath = Join-Path $RepoDir "backend\.venv\Scripts\python.exe"
}
if (-not (Test-Path $PythonPath)) {
    # Fallback to system python if virtual environment is not in typical folder
    $PythonPath = "python"
}

Write-Host ""
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host " HAVEN — STAGING TARGET CONFIGURATION & PREFLIGHT HELPER         " -ForegroundColor Cyan
Write-Host "=================================================================" -ForegroundColor Cyan
Write-Host "This helper configures memory-only staging variables for this process"
Write-Host "and runs the read-only index preflight check."
Write-Host "No credentials will be written to disk, git, or printed to terminal."
Write-Host ""

# Variable to hold plaintext connection string in memory only during execution
$plainEndpoint = $null
$exitCode = 0

try {
    # ── Step 1: Confirm target environment in MongoDB Atlas ──────────────────
    Write-Host "[Step 1/10] Confirming intended staging target..." -ForegroundColor Yellow
    Write-Host "  CRITICAL SAFETY RULE: You must ONLY run this against an independently"
    Write-Host "  confirmed STAGING cluster in MongoDB Atlas. Never target production."
    Write-Host ""

    # ── Step 2: Target Identifier ───────────────────────────────────────────
    Write-Host "[Step 2/10] Staging target identifier..." -ForegroundColor Yellow
    if ([string]::IsNullOrWhiteSpace($TargetId)) {
        if ($NonInteractive) {
            throw "TargetId parameter is required in NonInteractive mode."
        }
        $TargetId = Read-Host "  Enter approved staging target ID (e.g. haven-staging-01)"
    }
    $TargetId = $TargetId.Trim()
    if ($TargetId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$') {
        throw "Invalid staging target ID '$TargetId'. Must start with alphanumeric and contain only [A-Za-z0-9._-] (1-64 chars)."
    }
    Write-Host "  Target ID accepted: $TargetId" -ForegroundColor Green

    # ── Step 3: MongoDB Hostname Allowlist ──────────────────────────────────
    Write-Host "`n[Step 3/10] Authorized MongoDB hostname allowlist..." -ForegroundColor Yellow
    if ([string]::IsNullOrWhiteSpace($HostAllowlist)) {
        if ($NonInteractive) {
            throw "HostAllowlist parameter is required in NonInteractive mode."
        }
        Write-Host "  Enter the exact MongoDB Atlas cluster hostname(s) approved for staging."
        Write-Host "  Example: staging-cluster.xyz.mongodb.net"
        $HostAllowlist = Read-Host "  Hostname or comma-separated allowlist"
    }
    $HostAllowlist = $HostAllowlist.Trim()
    if ([string]::IsNullOrWhiteSpace($HostAllowlist) -or $HostAllowlist.Contains("*")) {
        throw "An exact host allowlist is required. Wildcards ('*') are strictly prohibited."
    }
    Write-Host "  Host allowlist configured (exact match enforced)." -ForegroundColor Green

    # ── Step 4: Intended Database Name ──────────────────────────────────────
    Write-Host "`n[Step 4/10] Application database name..." -ForegroundColor Yellow
    if ([string]::IsNullOrWhiteSpace($DatabaseName)) {
        $DatabaseName = "Haven"
    }
    $DatabaseName = $DatabaseName.Trim()
    if ($DatabaseName -ne "Haven") {
        Write-Host "  WARNING: Application canonical database name is 'Haven' (case-sensitive)." -ForegroundColor Red
        Write-Host "  Targeting a different database name may fail preflight allowlist check."
    }
    Write-Host "  Database name allowlist: $DatabaseName" -ForegroundColor Green

    # ── Step 5: Secure Endpoint Input ────────────────────────────────────────
    Write-Host "`n[Step 5/10] Staging MongoDB connection string..." -ForegroundColor Yellow
    if ($null -eq $SecureEndpoint) {
        if ($NonInteractive) {
            throw "SecureEndpoint parameter is required in NonInteractive mode."
        }
        Write-Host "  Enter the staging connection string (input is hidden, never echoed):"
        $SecureEndpoint = Read-Host -Prompt "  MONGO_ENDPOINT" -AsSecureString
    }
    
    # Convert SecureString to in-memory plaintext string safely
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($SecureEndpoint)
    try {
        $plainEndpoint = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }

    if ([string]::IsNullOrWhiteSpace($plainEndpoint)) {
        throw "MongoDB endpoint cannot be empty."
    }
    Write-Host "  Connection string received in-memory (not displayed, not written to disk)." -ForegroundColor Green

    # ── Step 6: Set Process Environment Variables ───────────────────────────
    Write-Host "`n[Step 6/10] Configuring memory-only process environment variables..." -ForegroundColor Yellow
    $env:HAVEN_DATABASE_ENVIRONMENT = "staging"
    $env:HAVEN_STAGING_TARGET_ID = $TargetId
    $env:HAVEN_STAGING_MONGO_HOST_ALLOWLIST = $HostAllowlist
    $env:HAVEN_STAGING_DATABASE_ALLOWLIST = $DatabaseName
    $env:MONGO_ENDPOINT = $plainEndpoint
    
    # Ensure ENVIRONMENT is not set to production in this process
    if ($env:ENVIRONMENT -in @("production", "prod")) {
        Write-Host "  Resetting process ENVIRONMENT from '$env:ENVIRONMENT' to 'development'." -ForegroundColor Yellow
        $env:ENVIRONMENT = "development"
    }
    Write-Host "  Process environment variables active." -ForegroundColor Green

    # ── Step 7: Offline Target Validation ───────────────────────────────────
    Write-Host "`n[Step 7/10] Running offline staging target validation (--check-target)..." -ForegroundColor Yellow
    $preflightScript = Join-Path $ScriptDir "preflight_index_check.py"
    
    $checkTargetOutput = & $PythonPath $preflightScript --check-target 2>&1
    $targetCheckCode = $LASTEXITCODE

    foreach ($line in $checkTargetOutput) {
        Write-Host "  $line"
    }

    if ($targetCheckCode -ne 0) {
        Write-Host "`nERROR: Staging target validation failed! Aborting." -ForegroundColor Red
        Write-Host "No database connection was attempted."
        $exitCode = 1
        return
    }
    Write-Host "  Offline target check passed successfully." -ForegroundColor Green

    # ── Step 8: Display Offline Index Plan ──────────────────────────────────
    Write-Host "`n[Step 8/10] Displaying planned indexes (--show-index-plan)..." -ForegroundColor Yellow
    & $PythonPath $preflightScript --show-index-plan
    Write-Host "  Index plan displayed (offline, zero connection)." -ForegroundColor Green

    # ── Step 9: Explicit Operator Confirmation ──────────────────────────────
    Write-Host "`n[Step 9/10] Operator authorization gate..." -ForegroundColor Yellow
    if ($NonInteractive) {
        Write-Host "  NonInteractive mode: skipping live connection step." -ForegroundColor Yellow
        Write-Host "  Target configuration verified offline." -ForegroundColor Green
        return
    }

    Write-Host "  The target has been verified offline as an authorized staging configuration."
    Write-Host "  Read-only preflight will query collections and verify unique constraints."
    Write-Host "  Zero writes or index changes will occur."
    Write-Host ""
    $confirmation = Read-Host "  Do you want to proceed with remote read-only preflight? (Type 'yes' to proceed)"

    if ($confirmation.Trim().ToLower() -ne "yes") {
        Write-Host "`nPreflight cancelled by operator. No remote connection was attempted." -ForegroundColor Yellow
        return
    }

    # ── Step 10: Remote Read-Only Preflight Execution ───────────────────────
    Write-Host "`n[Step 10/10] Connecting to staging database for read-only preflight..." -ForegroundColor Yellow
    & $PythonPath $preflightScript
    $exitCode = $LASTEXITCODE

    if ($exitCode -eq 0) {
        Write-Host "`nSUCCESS: Preflight passed with 0 blockers." -ForegroundColor Green
    } else {
        Write-Host "`nPREFLIGHT RETURNED CODE $exitCode. Resolve reported issues before proceeding." -ForegroundColor Red
    }

} catch {
    Write-Host "`nERROR: $_" -ForegroundColor Red
    $exitCode = 1
} finally {
    # Cleanup memory and process environment
    Write-Host "`nCleaning up process-level sensitive variables..." -ForegroundColor DarkGray
    $env:MONGO_ENDPOINT = $null
    $env:HAVEN_DATABASE_ENVIRONMENT = $null
    $env:HAVEN_STAGING_TARGET_ID = $null
    $env:HAVEN_STAGING_MONGO_HOST_ALLOWLIST = $null
    $env:HAVEN_STAGING_DATABASE_ALLOWLIST = $null
    $plainEndpoint = $null
    [System.GC]::Collect()
    Write-Host "Cleanup complete." -ForegroundColor DarkGray
}

exit $exitCode
