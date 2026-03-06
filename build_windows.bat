@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo ================================================
echo       FRP Manager - Windows Build Script
echo ================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found
    pause
    exit /b 1
)

echo [INFO] Installing dependencies...
python -m pip install pyinstaller pystray Pillow requests psutil flask -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com --quiet

if errorlevel 1 (
    echo [ERROR] Failed to install dependencies, trying without mirror...
    python -m pip install pyinstaller pystray Pillow requests psutil flask --quiet
)

echo [INFO] Ensuring temp directory exists...
if not exist "temp" mkdir temp

echo [INFO] Building FRP-Manager...
python build_exe.py

if exist "dist\FRP-Manager*" (
    for /d %%d in (dist\FRP-Manager-*) do (
        if exist "%%d\FRP-Manager-*.exe" (
            echo.
            echo [INFO] Creating temp directory in package...
            if not exist "%%d\_internal\temp" mkdir "%%d\_internal\temp"
            
            echo.
            echo ================================================
            echo [SUCCESS] Build complete!
            for /f "tokens=*" %%f in ('dir /b "%%d\*.exe"') do echo [FILE] %%d\%%f
            echo ================================================
        )
    )
) else (
    echo [ERROR] Build failed, check errors above
)

pause
