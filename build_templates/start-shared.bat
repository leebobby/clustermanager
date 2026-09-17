@echo off
REM Cluster Manager - SHARED MODE launcher
REM Backend binds 0.0.0.0 so other LAN machines can access via http://<this-pc-ip>:<port>
REM Local desktop window still opens normally.
REM Logs are written to cluster_manager.log next to this script.

cd /d "%~dp0"

REM Bind to all interfaces (default is 127.0.0.1 in start.bat)
set CLUSTER_MANAGER_BIND=0.0.0.0

REM Optional: pin the port (defaults to 8000, auto-shifts if busy)
REM set CLUSTER_MANAGER_PORT=8000

start "" cluster-manager.exe
