@echo off
REM Cluster Manager - desktop app launcher
REM Double-click to start. A native window will open (no browser).
REM Logs are written to cluster_manager.log next to this script.

cd /d "%~dp0"

REM Optional: change listening port (defaults to 8000, auto-shifts if busy)
REM set CLUSTER_MANAGER_PORT=8000

start "" cluster-manager.exe
