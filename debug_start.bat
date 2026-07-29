@echo off
cd /d "%~dp0."
REM This batch launches in console mode so any error shows in the black window.
REM Useful for diagnosing "double-click does nothing". The window stays open while the app runs.
call "%~dp0run.bat"
