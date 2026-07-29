@echo off
cd /d "%~dp0."

set "TRACE=bat_trace.log"
echo %DATE% %TIME% [run.bat] start args=%* >> "%TRACE%"

set "VENV="
if exist "venv2\Scripts\python.exe" ( set "VENV=venv2" ) else if exist "venv\Scripts\python.exe" ( set "VENV=venv" ) else ( set "VENV=venv" )
echo %TIME% [run.bat] VENV=%VENV% >> "%TRACE%"

if not exist "%VENV%\Scripts\python.exe" (
    echo %TIME% [run.bat] creating venv... >> "%TRACE%"
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo %TIME% [run.bat] venv create failed >> "%TRACE%"
        echo [ERROR] Failed to create venv. Make sure python is in PATH, version >= 3.8.
        pause
        exit /b 1
    )
    "%VENV%\Scripts\python.exe" -m pip install --upgrade pip >> "%TRACE%" 2>&1
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt >> "%TRACE%" 2>&1
    if errorlevel 1 (
        echo %TIME% [run.bat] first install failed >> "%TRACE%"
        echo [ERROR] Dependency install failed. Check network, then run:
        echo   %VENV%\Scripts\pip install -r requirements.txt
        pause
        exit /b 1
    )
    echo done > deps_ok.marker
    echo %TIME% [run.bat] first install done >> "%TRACE%"
)

if not exist deps_ok.marker (
    echo %TIME% [run.bat] topping up deps... >> "%TRACE%"
    "%VENV%\Scripts\python.exe" -m pip install -r requirements.txt >> "%TRACE%" 2>&1
    if not errorlevel 1 ( echo done > deps_ok.marker )
)

echo %TIME% [run.bat] launching bootstrap.py ... >> "%TRACE%"
if "%1"=="silent" (
    "%VENV%\Scripts\pythonw.exe" bootstrap.py
) else (
    "%VENV%\Scripts\python.exe" bootstrap.py
)
set "RC=%errorlevel%"
echo %TIME% [run.bat] bootstrap exit=%RC% >> "%TRACE%"
if not "%1"=="silent" (
    if %RC% neq 0 (
        echo.
        echo Launch failed, exit code %RC%. See launch_trace.log / voice_control_error.log in this folder.
        pause
    )
)
exit /b %RC%
