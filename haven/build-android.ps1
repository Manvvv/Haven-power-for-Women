#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Build the HAVEN Android APK.

.DESCRIPTION
    Downloads the Gradle wrapper (if needed), resolves the Android SDK location,
    and builds the debug APK.

    Prerequisites (must be installed manually):
      1. Android Studio (https://developer.android.com/studio) OR
         Command-line tools (https://developer.android.com/studio#command-line-tools)
      2. Android SDK Platform 35 and Build-Tools 35.0.0 (via SDK Manager)
      3. JDK 17 (bundled with Android Studio, or install OpenJDK 17 separately)

    The debug APK output path after a successful build:
      android/app/build/outputs/apk/debug/app-debug.apk

.NOTES
    This script does NOT download the Android SDK or JDK.
    Install Android Studio first, which includes all required tools.
#>

param(
    [switch]$Release,
    [string]$BackendUrl = "https://haven-power-for-women.onrender.com",
    [string]$BackendUrlHttps = "https://haven-power-for-women.onrender.com"
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$AndroidDir = Join-Path $ScriptDir "android"

Write-Host "=== HAVEN Android Build Script ===" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Detect Android SDK ───────────────────────────────────────────────
$sdkPaths = @(
    $env:ANDROID_HOME,
    $env:ANDROID_SDK_ROOT,
    "$env:LOCALAPPDATA\Android\Sdk",
    "$env:USERPROFILE\AppData\Local\Android\Sdk",
    "C:\Android\Sdk"
)

$sdkDir = $null
foreach ($path in $sdkPaths) {
    if ($path -and (Test-Path $path)) {
        $sdkDir = $path
        Write-Host "✅ Android SDK found: $sdkDir" -ForegroundColor Green
        break
    }
}

if (-not $sdkDir) {
    Write-Host "❌ Android SDK not found!" -ForegroundColor Red
    Write-Host ""
    Write-Host "Install Android Studio from: https://developer.android.com/studio" -ForegroundColor Yellow
    Write-Host "Then open SDK Manager and install:" -ForegroundColor Yellow
    Write-Host "  • Android SDK Platform 35" -ForegroundColor Yellow
    Write-Host "  • Android SDK Build-Tools 35.0.0" -ForegroundColor Yellow
    Write-Host "  • Google Play services" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "Or set ANDROID_HOME environment variable to your SDK location." -ForegroundColor Yellow
    exit 1
}

# ── Step 2: Detect Java ───────────────────────────────────────────────────────
$javaCmd = $null
$javaHomes = @(
    $env:JAVA_HOME,
    "$env:ProgramFiles\Android\Android Studio\jbr",
    "$env:ProgramFiles\Android\Android Studio\jre"
)

foreach ($jh in $javaHomes) {
    if ($jh -and (Test-Path "$jh\bin\java.exe")) {
        $env:JAVA_HOME = $jh
        $javaCmd = "$jh\bin\java.exe"
        Write-Host "✅ JDK found: $jh" -ForegroundColor Green
        break
    }
}

if (-not $javaCmd) {
    # Try PATH
    try {
        $javaCmd = (Get-Command java -ErrorAction SilentlyContinue).Source
        if ($javaCmd) {
            Write-Host "✅ Java found in PATH: $javaCmd" -ForegroundColor Green
        }
    } catch {}
}

if (-not $javaCmd) {
    Write-Host "❌ Java/JDK not found!" -ForegroundColor Red
    Write-Host "Install JDK 17: https://adoptium.net/en-GB/temurin/releases/?version=17" -ForegroundColor Yellow
    Write-Host "Or install Android Studio which includes a bundled JDK." -ForegroundColor Yellow
    exit 1
}

# ── Step 3: Update local.properties ─────────────────────────────────────────
$localPropsPath = Join-Path $AndroidDir "local.properties"
$sdkEscaped = $sdkDir -replace "\\", "\\\\"
$content = @"
sdk.dir=$sdkEscaped
havenBaseUrl=$BackendUrl
havenBaseUrlHttps=$BackendUrlHttps
"@
Set-Content -Path $localPropsPath -Value $content
Write-Host "✅ local.properties written" -ForegroundColor Green

# ── Step 4: Download Gradle wrapper jar if missing ───────────────────────────
$wrapperJar = Join-Path $AndroidDir "gradle\wrapper\gradle-wrapper.jar"
if (-not (Test-Path $wrapperJar)) {
    Write-Host "Downloading gradle-wrapper.jar..." -ForegroundColor Cyan
    $wrapperUrl = "https://raw.githubusercontent.com/gradle/gradle/v8.9.0/gradle/wrapper/gradle-wrapper.jar"
    try {
        Invoke-WebRequest -Uri $wrapperUrl -OutFile $wrapperJar -UseBasicParsing
        Write-Host "✅ gradle-wrapper.jar downloaded" -ForegroundColor Green
    } catch {
        Write-Host "❌ Could not download gradle-wrapper.jar: $_" -ForegroundColor Red
        Write-Host "Download it manually from: https://github.com/gradle/gradle/blob/master/gradle/wrapper/gradle-wrapper.jar" -ForegroundColor Yellow
        exit 1
    }
}

# ── Step 5: Run Gradle build ─────────────────────────────────────────────────
$gradlew = Join-Path $AndroidDir "gradlew.bat"
if (-not (Test-Path $gradlew)) {
    Write-Host "❌ gradlew.bat not found in $AndroidDir" -ForegroundColor Red
    exit 1
}

Push-Location $AndroidDir
try {
    $task = if ($Release) { "assembleRelease" } else { "assembleDebug" }
    Write-Host ""
    Write-Host "Building: $task" -ForegroundColor Cyan
    Write-Host "This may take several minutes on first run (downloading dependencies)..." -ForegroundColor Yellow
    Write-Host ""

    & cmd /c "$gradlew $task 2>&1"

    if ($LASTEXITCODE -eq 0) {
        $apkPath = if ($Release) {
            Join-Path $AndroidDir "app\build\outputs\apk\release\app-release.apk"
        } else {
            Join-Path $AndroidDir "app\build\outputs\apk\debug\app-debug.apk"
        }

        if (Test-Path $apkPath) {
            if ($Release) {
                $rootReleaseDir = Join-Path $AndroidDir "app\release"
                if (-not (Test-Path $rootReleaseDir)) { New-Item -ItemType Directory -Path $rootReleaseDir -Force | Out-Null }
                Copy-Item -Path $apkPath -Destination (Join-Path $rootReleaseDir "app-release.apk") -Force
            }
            Write-Host ""
            Write-Host "=== BUILD SUCCESSFUL ===" -ForegroundColor Green
            Write-Host "APK: $apkPath" -ForegroundColor Green
            Write-Host ""
            Write-Host "Install on connected device:" -ForegroundColor Cyan
            Write-Host "  adb install `"$apkPath`"" -ForegroundColor White
        } else {
            Write-Host "Build reported success but APK not found at: $apkPath" -ForegroundColor Yellow
        }
    } else {
        Write-Host ""
        Write-Host "=== BUILD FAILED (exit code $LASTEXITCODE) ===" -ForegroundColor Red
        Write-Host "Check the error output above for details." -ForegroundColor Yellow
        exit $LASTEXITCODE
    }
} finally {
    Pop-Location
}
