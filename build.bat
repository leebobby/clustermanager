@echo off
REM ============================================================
REM  Cluster Manager - build entry (kept for compatibility)
REM
REM  The real build logic lives in build_app.py (cross-platform,
REM  single implementation). This wrapper just forwards to it in
REM  desktop mode (pywebview native window, no console):
REM
REM      build.bat                    -> python build_app.py --mode desktop
REM      build.bat --skip-frontend    -> extra args are passed through
REM
REM  Output: backend\dist\cluster-manager\cluster-manager.exe
REM          cluster-manager-windows-<arch>.zip
REM
REM  NOTE: ASCII-only on purpose - Chinese Windows uses the GBK
REM        codepage and mangles UTF-8 text in .bat files.
REM ============================================================

where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found. Install Python 3.10+ from https://www.python.org
    exit /b 1
)

python "%~dp0build_app.py" --mode desktop %*
exit /b %errorlevel%
