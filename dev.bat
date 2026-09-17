@echo off
REM ============================================================
REM  Cluster Manager - Dev quick-start (backend + frontend)
REM
REM  Backend:  conda env "myenv" + python main.py  -> :8000
REM  Frontend: npm run dev (Vite, HMR)             -> :3000
REM  Browser:  http://localhost:3000  (auto-opens)
REM
REM  Close the two pop-up CMD windows to stop services.
REM  This script intentionally uses ASCII-only text to avoid the
REM  UTF-8 / GBK codepage trap on Chinese Windows.
REM ============================================================

setlocal
set ROOT=%~dp0
set CONDA_ENV=myenv
set BACKEND_PORT=8000
set FRONTEND_PORT=3000

REM ---- Dependency checks ----
where conda >nul 2>&1
if errorlevel 1 (
    echo [ERROR] "conda" not found on PATH.
    echo         Open "Anaconda Prompt" then run this script,
    echo         OR run once:  conda init cmd.exe   ^&^&  restart CMD.
    pause
    exit /b 1
)
where node >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Node.js not found. Install from https://nodejs.org
    pause
    exit /b 1
)
if not exist "%ROOT%backend\main.py" (
    echo [ERROR] %ROOT%backend\main.py not found
    pause
    exit /b 1
)
if not exist "%ROOT%frontend\package.json" (
    echo [ERROR] %ROOT%frontend\package.json not found
    pause
    exit /b 1
)

REM ---- 1/3 Backend ----
echo.
echo [1/3] Launching BACKEND in a new window (conda env: %CONDA_ENV%) ...
start "cluster-manager backend [%CONDA_ENV%]" cmd /k "call conda activate %CONDA_ENV% && cd /d %ROOT%backend && set CLUSTER_MANAGER_PORT=%BACKEND_PORT% && set CLUSTER_MANAGER_HOST=0.0.0.0 && python main.py"

REM Give backend a few seconds to bind the port before the Vite proxy tries it
timeout /t 3 /nobreak >nul

REM ---- 2/3 Frontend ----
echo [2/3] Launching FRONTEND dev server in a new window ...
start "cluster-manager frontend" cmd /k "cd /d %ROOT%frontend && (if not exist node_modules npm install) && npm run dev"

REM ---- 3/3 Browser ----
echo [3/3] Waiting for Vite, then opening browser http://localhost:%FRONTEND_PORT% ...
timeout /t 5 /nobreak >nul
start "" http://localhost:%FRONTEND_PORT%

echo.
echo ============================================================
echo  Services launched:
echo    Backend:  http://localhost:%BACKEND_PORT%   (API + Swagger /docs)
echo    Frontend: http://localhost:%FRONTEND_PORT%   (HMR, /api -^> backend)
echo.
echo  Tips:
echo    - Backend hot-reload: NOT enabled. Restart the backend CMD
echo      window when you change Python code.
echo    - Frontend hot-reload: enabled. Vue/JS/CSS changes are live.
echo    - To stop: close the two pop-up CMD windows.
echo ============================================================
