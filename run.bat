@echo off
title Something from Everything - Launcher

echo [1/3] Starting KoboldCpp LLM Server...
start "KoboldCpp" cmd /c "C:\Users\User\Desktop\hp\backend\koboldcpp.exe --model C:\Users\User\Desktop\hp\qwen2.5-3b-instruct-q4_k_m.gguf --port 5001"

echo Waiting for LLM to initialize...
timeout /t 5 /nobreak > nul

echo [2/3] Starting Backend Server...
start "SFE Backend" cmd /c "python main.py"

echo Waiting for backend to initialize...
timeout /t 3 /nobreak > nul

echo [3/3] Launching Dashboard in Chrome...
start chrome http://localhost:8000

echo.
echo All services launched successfully!
echo Close this window to keep them running in the background.
pause
