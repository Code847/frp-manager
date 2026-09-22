@echo off
setlocal enabledelayedexpansion
goto :main

:DETECT
set "PY="
where py >nul 2>&1
if !errorlevel! == 0 set "PY=py"
if not defined PY (
    where python >nul 2>&1
    if !errorlevel! == 0 set "PY=python"
)
if not defined PY (
    where python3 >nul 2>&1
    if !errorlevel! == 0 set "PY=python3"
)
if not defined PY (
    for %%B in ("%LOCALAPPDATA%\Programs\Python" "%ProgramFiles%\Python" "%SystemDrive%\Python") do (
        if not defined PY (
            for /d %%P in ("%%~B\Python3*") do (
                if not defined PY if exist "%%P\python.exe" set "PY=%%P\python.exe"
            )
        )
    )
)
if not defined PY (
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" set "PY=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
)
goto :eof

:main
echo ================================================
echo       FRP Manager - Windows Build Script
echo ================================================
echo.

call :DETECT
if defined PY goto :found

echo [ERROR] Python not found on this machine.
echo.
set /p "CHOICE=Download and install Python 3.12 now? [Y/N]: "
if /i "!CHOICE!"=="Y" (
    echo [INFO] Installing Python 3.12...
    set "DONE=0"
    set "PV=3.12.7"
    set "PU=https://www.python.org/ftp/python/!PV!/python-!PV!-amd64.exe"
    set "PI=%TEMP%\python-!PV!-amd64.exe"

    where winget >nul 2>&1
    if !errorlevel! == 0 (
        echo [INFO] Trying winget...
        winget install -e --id Python.Python.3.12 --accept-package-agreements --accept-license-terms --silent >nul 2>&1
        if !errorlevel! == 0 set "DONE=1"
    )

    if !DONE! == 0 (
        echo [INFO] Downloading Python installer to "!PI!" ...
        if exist "!PI!" del /f /q "!PI!"
        set "DL=0"
        where curl >nul 2>&1
        if !errorlevel! == 0 (
            echo [INFO] Downloading via curl, timeout 180s...
            curl -L --connect-timeout 20 --max-time 180 -# -o "!PI!" "!PU!"
            if exist "!PI!" set "DL=1"
        )
        if !DL! == 0 (
            echo [INFO] Downloading via bitsadmin...
            bitsadmin /transfer frpget /download /priority normal "!PU!" "!PI!" >nul 2>&1
            if exist "!PI!" set "DL=1"
        )
        if !DL! == 0 (
            echo [INFO] Downloading via powershell...
            powershell -NoProfile -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -Uri '!PU!' -OutFile '!PI!' -TimeoutSec 180" >nul 2>&1
            if exist "!PI!" set "DL=1"
        )
        if !DL! == 1 (
            echo [INFO] Running installer, adds Python to PATH...
            start /wait "" "!PI!" /quiet PrependPath=1
            set "DONE=1"
        ) else (
            echo [ERROR] Download failed - check your network or use a proxy.
        )
    )

    if !DONE! == 1 (
        if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" (
            set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
        )
    )
    if not defined PY call :DETECT
)

if not defined PY (
    echo [ERROR] Python still not found.
    echo   Please install it manually from https://www.python.org/downloads/windows/
    echo   and make sure "Add Python to PATH" is checked.
    pause
    exit /b 1
)

:found
echo [INFO] Using Python: %PY%
%PY% --version

echo [INFO] Installing dependencies...
%PY% -m pip install pyinstaller pystray Pillow requests psutil flask -i https://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com --quiet
if errorlevel 1 (
    echo [WARN] Mirror install failed, retrying without mirror...
    %PY% -m pip install pyinstaller pystray Pillow requests psutil flask --quiet
)
if errorlevel 1 (
    echo [ERROR] Failed to install dependencies.
    pause
    exit /b 1
)

echo [INFO] Ensuring temp directory exists...
if not exist "temp" mkdir temp

echo [INFO] Building FRP-Manager...
%PY% build_exe.py
if errorlevel 1 (
    echo [ERROR] Build failed, check errors above.
    pause
    exit /b 1
)

set "BUILT="
for %%f in (dist\FRP-Manager-*.exe) do (
    set "BUILT=%%f"
)
if defined BUILT (
    echo.
    echo ================================================
    echo [SUCCESS] Build complete!
    echo [FILE] %BUILT%
    echo Run: %BUILT%
    echo ================================================
    pause
) else (
    echo [ERROR] Build failed, no exe found in dist/.
    pause
    exit /b 1
)
