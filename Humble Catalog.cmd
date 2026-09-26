@echo off
rem Double-click to open the Humble Catalog viewer (#96).
rem
rem Keep this window open while you use the catalog: Log in, Reset and
rem Restore in the Tasks tab run here. Close it, or press Ctrl+C, to stop
rem the viewer. Everything else -- the venv check, HUMBLE_PORT, opening a
rem viewer that is already running -- is scripts\windows\serve.ps1's job.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\windows\serve.ps1"
if errorlevel 1 (
    echo.
    echo The viewer stopped with an error; the message is above.
    pause
)
