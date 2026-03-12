@echo off
title Something from Everything - Launcher

set "ROOT=%~dp0"
cd /d "%ROOT%"

set "PY_EXE="
set "PY_ARGS="
set "PY_CMD="

rem Prefer project venv if present
if exist "%ROOT%.venv\Scripts\python.exe" (
    set "PY_EXE=%ROOT%.venv\Scripts\python.exe"
    goto :PY_FOUND
)

rem Try known local installs first
for %%P in (
    "%LocalAppData%\Programs\Python\Python312\python.exe"
    "%LocalAppData%\Programs\Python\Python311\python.exe"
    "%LocalAppData%\Programs\Python\Python310\python.exe"
    "%ProgramFiles%\Python312\python.exe"
    "%ProgramFiles%\Python311\python.exe"
    "%ProgramFiles%\Python310\python.exe"
) do (
    if exist "%%~P" (
        set "PY_EXE=%%~P"
        goto :PY_FOUND
    )
)

rem Probe Python launcher versions explicitly to avoid broken default 3.13 mapping
for %%V in (3.12 3.11 3.10 3.9) do (
    cmd /c "py -%%V -c \"import sys\"" >nul 2>nul
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-%%V"
        goto :PY_FOUND
    )
)

rem Fallback: generic python command if callable
cmd /c "python -c \"import sys\"" >nul 2>nul
if not errorlevel 1 (
    set "PY_EXE=python"
    goto :PY_FOUND
)

:PY_NOT_FOUND
echo [ERROR] No runnable Python interpreter found.
echo Install Python 3.10+ or create .venv\Scripts\python.exe, then rerun.
echo Tip: disable broken Store aliases and install python.org build.
pause
exit /b 1

:PY_FOUND

echo [1/4] Starting KoboldCpp LLM Server...
if exist "C:\Users\User\Desktop\hp\backend\koboldcpp.exe" (
    start "KoboldCpp" cmd /k "C:\Users\User\Desktop\hp\backend\koboldcpp.exe --model C:\Users\User\Desktop\hp\qwen2.5-3b-instruct-q4_k_m.gguf --port 5001"
) else (
    echo [WARN] KoboldCpp executable not found. Skipping LLM server.
)

echo Waiting for LLM to initialize...
timeout /t 5 /nobreak > nul

echo [2/4] Installing dependencies...
"%PY_EXE%" %PY_ARGS% -m pip install -r requirements.txt >nul

echo [3/4] Starting Backend Server...
start "SFE Backend" /D "%ROOT%" cmd /k ""%PY_EXE%" %PY_ARGS% main.py"

echo Waiting for backend to open port 8000...
set "READY=0"
for /L %%I in (1,1,40) do (
    netstat -ano | findstr ":8000" | findstr "LISTENING" >nul
    if not errorlevel 1 (
        set "READY=1"
        goto :BACKEND_READY
    )
    timeout /t 1 /nobreak > nul
)
:BACKEND_READY

echo [4/4] Launching Dashboard in Chrome...
if "%READY%"=="1" (
    start chrome http://localhost:8000
) else (
    echo [WARN] Backend did not open port 8000 yet.
    echo Check the "SFE Backend" window for the exact error.
)

echo.
echo Launcher finished.
echo Close this window to keep them running in the background.
pause
