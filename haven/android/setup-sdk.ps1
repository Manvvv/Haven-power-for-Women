#!/usr/bin/env pwsh
<#
.SYNOPSIS
    HAVEN Android SDK Setup Script
    Installs the Android SDK command-line tools and required platform
    without needing Android Studio. Run once after cloning.

.PREREQUISITES
    - Java 17+ must be available (Tableau JRE works, or install via winget)
    - Internet connection (downloads ~600 MB total)

.USAGE
    cd haven\android
    .\setup-sdk.ps1
#>

$ErrorActionPreference = "Stop"

# ─── Configuration ────────────────────────────────────────────────────────────
$JAVA_HOME_TABLEAU = "C:\Program Files\Tableau\Tableau 2025.2\bin\jre"
$SDK_ROOT = "$env:LOCALAPPDATA\Android\Sdk"
$CLT_ZIP = "$env:TEMP\cmdline-tools.zip"
$CLT_URL = "https://dl.google.com/android/repository/commandlinetools-win-11076708_latest.zip"

# ─── Set JAVA_HOME (Tableau JRE or system JDK 17) ────────────────────────────
if (-not $env:JAVA_HOME -or -not (Test-Path "$env:JAVA_HOME\bin\java.exe")) {
    if (Test-Path "$JAVA_HOME_TABLEAU\bin\java.exe") {
        $env:JAVA_HOME = $JAVA_HOME_TABLEAU
        Write-Host "[INFO] Using Tableau-bundled JRE 17 as JAVA_HOME"
    } else {
        Write-Error "Java 17 not found. Install via: winget install Microsoft.OpenJDK.17"
    }
}
$env:PATH = "$env:JAVA_HOME\bin;$env:PATH"
$javaVer = (& java -version 2>&1 | Select-Object -First 1)
Write-Host "[OK] $javaVer"

# ─── Download command-line tools if not present ───────────────────────────────
$sdkManagerPath = "$SDK_ROOT\cmdline-tools\latest\bin\sdkmanager.bat"
if (-not (Test-Path $sdkManagerPath)) {
    Write-Host "[INFO] Android SDK not found. Downloading command-line tools..."
    New-Item -ItemType Directory -Force -Path "$SDK_ROOT\cmdline-tools" | Out-Null

    if (-not (Test-Path $CLT_ZIP)) {
        Invoke-WebRequest -Uri $CLT_URL -OutFile $CLT_ZIP -UseBasicParsing -TimeoutSec 300
        Write-Host "[OK] Downloaded command-line tools: $((Get-Item $CLT_ZIP).Length) bytes"
    }

    Write-Host "[INFO] Extracting..."
    Expand-Archive -Path $CLT_ZIP -DestinationPath "$SDK_ROOT\cmdline-tools\_extracted" -Force
    # Move to expected path: cmdline-tools/latest/
    $extractedDir = Get-ChildItem "$SDK_ROOT\cmdline-tools\_extracted" -Directory | Select-Object -First 1
    Move-Item -Path $extractedDir.FullName -Destination "$SDK_ROOT\cmdline-tools\latest" -Force
    Remove-Item "$SDK_ROOT\cmdline-tools\_extracted" -Force -Recurse -ErrorAction SilentlyContinue
    Write-Host "[OK] Command-line tools installed at $SDK_ROOT\cmdline-tools\latest"
}

# ─── Set ANDROID_HOME ─────────────────────────────────────────────────────────
$env:ANDROID_HOME = $SDK_ROOT
$env:PATH = "$SDK_ROOT\cmdline-tools\latest\bin;$SDK_ROOT\platform-tools;$env:PATH"

# ─── Accept licenses ─────────────────────────────────────────────────────────
Write-Host "[INFO] Accepting SDK licenses..."
"y`ny`ny`ny`ny`ny`ny" | & "$sdkManagerPath" --licenses --sdk_root=$SDK_ROOT 2>&1 | Out-Null
Write-Host "[OK] Licenses accepted"

# ─── Install required SDK components ─────────────────────────────────────────
Write-Host "[INFO] Installing SDK platform 35 (Android 14), build-tools 35.0.0, platform-tools..."
Write-Host "       This will download ~400 MB. Please wait..."
& "$sdkManagerPath" --sdk_root=$SDK_ROOT `
    "platform-tools" `
    "platforms;android-35" `
    "build-tools;35.0.0" `
    "extras;google;m2repository" `
    "extras;android;m2repository" 2>&1

Write-Host "[OK] Android SDK components installed"

# ─── Verify installation ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== SDK Installation Summary ==="
Write-Host "ANDROID_HOME = $SDK_ROOT"
Write-Host "JAVA_HOME    = $env:JAVA_HOME"
Get-ChildItem $SDK_ROOT | Select-Object Name | Format-Table -AutoSize

# ─── Run the Gradle build ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "[INFO] Starting Gradle assembleDebug build..."
$gradleBat = Join-Path $PSScriptRoot "gradlew.bat"
& $gradleBat assembleDebug 2>&1

$apkPath = Join-Path $PSScriptRoot "app\build\outputs\apk\debug\app-debug.apk"
if (Test-Path $apkPath) {
    $size = (Get-Item $apkPath).Length
    Write-Host ""
    Write-Host "=== BUILD SUCCESSFUL ==="
    Write-Host "APK: $apkPath"
    Write-Host "Size: $([math]::Round($size/1MB, 2)) MB"
} else {
    Write-Host ""
    Write-Host "=== BUILD FAILED — APK not found at expected path ==="
    Write-Host "Check the Gradle output above for compilation errors."
}
