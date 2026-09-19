@echo off
REM ============================================================
REM  Cluster Manager - WebView2 runtime diagnostic
REM
REM  Double-click this when the app window opens but stays BLANK
REM  (white). It reports whether this machine can use the built-in
REM  native window, and what to do if it cannot.
REM
REM  The result is shown in a popup and also appended to
REM  cluster_manager.log next to this script.
REM
REM  ASCII-only on purpose: Chinese Windows uses the GBK codepage
REM  and mangles UTF-8 text in .bat files.
REM ============================================================

cd /d "%~dp0"
cluster-manager.exe --check
