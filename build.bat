@echo off
setlocal enabledelayedexpansion

REM ============================================================
REM  Cluster Manager - Windows desktop app build script
REM  Target  : Windows x64 management station (remote ARM cluster)
REM  Entry   : backend\desktop.py  (pywebview native window, no browser)
REM  Output  : backend\dist\cluster-manager\cluster-manager.exe
REM            cluster-manager-windows.zip
REM ============================================================
REM  NOTE: this script is intentionally ASCII-only to avoid the
REM        UTF-8 / GBK codepage trap on Chinese Windows. Localized
REM        text for end users lives in build_templates\README.txt
REM        and is copied verbatim into the release.
REM ============================================================

REM ---- Prerequisite checks ----
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    exit /b 1
)
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org
    exit /b 1
)

REM ---- 1/5 Build frontend ----
echo.
echo [1/5] Building frontend (npm run build) ...
pushd frontend
call npm install
if errorlevel 1 ( echo [ERROR] npm install failed & popd & exit /b 1 )
call npm run build
if errorlevel 1 ( echo [ERROR] npm run build failed & popd & exit /b 1 )
popd
echo   -^> frontend assets at backend\static\

REM ---- 2/5 Install Python deps + PyInstaller ----
echo.
echo [2/5] Installing Python dependencies ...
pushd backend
python -m pip install --upgrade pip --quiet
python -m pip install -r requirements.txt --quiet
if errorlevel 1 ( echo [ERROR] requirements.txt install failed & popd & exit /b 1 )
python -m pip install pyinstaller --quiet
if errorlevel 1 ( echo [ERROR] pyinstaller install failed & popd & exit /b 1 )
echo   -^> python deps ready

REM ---- 3/5 Clean old artifacts ----
echo.
echo [3/5] Cleaning old artifacts ...
if exist build rmdir /s /q build 2>nul

REM Explicit unlock pass: AV scanners may still hold the .jar / dlls from a
REM previous run. Delete known offenders first, then retry the recursive rmdir.
if exist "dist\cluster-manager\_internal\webview\lib\pywebview-android.jar" (
    del /f /q "dist\cluster-manager\_internal\webview\lib\pywebview-android.jar" 2>nul
)
if exist dist rmdir /s /q dist 2>nul
if exist dist (
    echo   -^> dist still locked, waiting 3s for AV to release ...
    timeout /t 3 /nobreak >nul
    rmdir /s /q dist 2>nul
)
if exist dist (
    echo [ERROR] Could not remove dist\, a file is still locked.
    echo         Close any running cluster-manager.exe or pause your antivirus and retry.
    popd & exit /b 1
)
popd
if exist cluster-manager-windows.zip del /f cluster-manager-windows.zip

REM ---- 4/5 PyInstaller + copy runtime resources ----
echo.
echo [4/5] Running PyInstaller ...
pushd backend
pyinstaller cluster_manager.spec --clean --noconfirm
if errorlevel 1 ( echo [ERROR] PyInstaller failed & popd & exit /b 1 )

set DIST=dist\cluster-manager

echo   -^> copying static\
xcopy /e /i /q /y static %DIST%\static\ >nul

if exist scripts_bundle.json (
    echo   -^> copying scripts_bundle.json
    copy /y scripts_bundle.json %DIST%\ >nul
)

if exist pxe_data (
    echo   -^> copying pxe_data\
    xcopy /e /i /q /y pxe_data %DIST%\pxe_data\ >nul
)

if not exist %DIST%\iso mkdir %DIST%\iso

popd

echo   -^> copying launcher templates (start.bat, start-shared.bat)
copy /y build_templates\start.bat        backend\dist\cluster-manager\start.bat        >nul
copy /y build_templates\start-shared.bat backend\dist\cluster-manager\start-shared.bat >nul

echo   -^> copying README.txt
copy /y build_templates\README.txt backend\dist\cluster-manager\README.txt >nul

REM ---- 5/5 Zip the release ----
echo.
echo [5/5] Packaging ZIP ...

REM Defensive: remove any platform-only files still left behind (in case the
REM spec filter missed something or this run reuses a stale dist directory).
if exist "backend\dist\cluster-manager\_internal\webview\lib\pywebview-android.jar" (
    del /f /q "backend\dist\cluster-manager\_internal\webview\lib\pywebview-android.jar" 2>nul
)

REM Compress-Archive with retry: AV scanners (esp. Windows Defender on .jar /
REM .dll just written) can hold a file handle for a couple of seconds.
powershell -NoProfile -Command ^
    "$src='backend\dist\cluster-manager'; $dst='cluster-manager-windows.zip';" ^
    "for($i=1;$i -le 4;$i++){ try { Compress-Archive -Path $src -DestinationPath $dst -Force; break }" ^
    "catch { Write-Host \"  zip attempt $i failed: $($_.Exception.Message.Split([Environment]::NewLine)[0])\"; if($i -ge 4){throw}; Start-Sleep -Seconds 3 } }"

if not exist cluster-manager-windows.zip (
    echo [ERROR] ZIP packaging failed
    exit /b 1
)

for %%F in (cluster-manager-windows.zip) do set SIZE=%%~zF
set /a SIZE_MB=!SIZE! / 1048576
echo   -^> cluster-manager-windows.zip  (!SIZE_MB! MB)

REM ---- Done ----
echo.
echo ============================================================
echo  BUILD COMPLETE
echo ============================================================
echo.
echo  Artifacts:
echo    backend\dist\cluster-manager\   (runnable directory)
echo    cluster-manager-windows.zip     (distributable archive)
echo.
echo  Deploy on target Windows machine:
echo    1. Unzip cluster-manager-windows.zip
echo    2. (optional) drop PXE Host ISO into iso\
echo    3. Double-click cluster-manager.exe (or start.bat)
echo    4. A native "Cluster Manager" window opens automatically
echo.
echo  Note: Edge WebView2 Runtime is required (built-in on Win11,
echo        installer for Win10: https://aka.ms/webview2)
echo ============================================================
