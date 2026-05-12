@echo off
setlocal
title Smart Video Monitor Launcher

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "APP_URL=http://127.0.0.1:5000"

echo ========================================
echo Smart Video Monitor
echo ========================================
echo.

if not exist "%PROJECT_DIR%\app.py" (
    echo [ERROR] app.py not found:
    echo %PROJECT_DIR%\app.py
    pause
    exit /b 1
)

echo Project directory: %PROJECT_DIR%
echo.
echo Starting backend service...
start "Smart Video Monitor Backend" /D "%PROJECT_DIR%" python app.py

echo Waiting for server startup...
timeout /t 5 /nobreak >nul

echo Opening browser...
start "" "%APP_URL%"

echo.
echo Startup commands have been executed.
endlocal
