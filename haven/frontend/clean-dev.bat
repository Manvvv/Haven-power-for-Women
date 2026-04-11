@echo off
echo ========================================
echo    Haven - Clean Start
echo ========================================
echo.

echo [1] Killing any running Node processes...
taskkill /f /im node.exe 2>nul
timeout /t 2 /nobreak > nul

echo [2] Deleting .next cache...
if exist .next (
    rmdir /s /q .next
    echo     .next deleted!
) else (
    echo     .next not found, skipping
)

echo [3] Deleting node_modules cache...
if exist node_modules\.cache (
    rmdir /s /q node_modules\.cache
    echo     node_modules\.cache deleted!
) else (
    echo     cache not found, skipping
)

echo.
echo [4] Starting dev server...
echo ========================================
npm run dev