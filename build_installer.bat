@echo off
setlocal enabledelayedexpansion
goto :main

:find_iscc
set "ISCC="
where iscc >nul 2>&1
if not errorlevel 1 (
    set "ISCC=iscc"
    goto :eof
)
for %%B in ("%ProgramFiles%\Inno Setup 6" "%ProgramFiles (x86)\Inno Setup 6" "%ProgramFiles%\Inno Setup 5") do (
    if exist "%%~B\iscc.exe" if not defined ISCC set "ISCC=%%~B\iscc.exe"
)
goto :eof

:main
echo ============================================================
echo       FRP Manager - Windows Installer Build
echo ============================================================
echo.

call :find_iscc
if defined ISCC goto :have_iscc

echo [ERROR] 未找到 Inno Setup 6 编译器 iscc.exe
echo.
echo   请先安装 Inno Setup 6： https://jrsoftware.org/isinfo.php
echo   安装后重新运行本脚本即可。
echo.
pause
exit /b 1

:have_iscc
echo [INFO] Using Inno Setup: %ISCC%

echo [INFO] Checking build artifact...
set "NEWEST="
for /f "delims=" %%f in ('dir /b /o-n "dist\FRP-Manager-*.exe" 2^>nul') do (
    if not defined NEWEST set "NEWEST=%%f"
)
if not defined NEWEST (
    echo [ERROR] dist\ 下没有找到 FRP-Manager-*.exe
    echo        请先运行： python build_exe.py
    echo.
    pause
    exit /b 1
)
echo [INFO] Artifact: %NEWEST%

set "VER="
for /f "delims=" %%v in ('powershell -NoProfile -Command "(Get-ItemLiteralPath -LiteralPath 'dist\%NEWEST%').VersionInfo.FileVersion"') do (
    if not defined VER set "VER=%%v"
)
if not defined VER set "VER=1.15.0.0"
echo [INFO] Version  : %VER%

echo [INFO] Building installer...
"%ISCC%" "%~dp0installer.iss" /DMyAppVersion=%VER%
if errorlevel 1 (
    echo.
    echo [ERROR] Installer build failed.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo [SUCCESS] Installer ready:
echo     Output\FRP-Manager-%VER%-Setup.exe
echo ============================================================
pause
exit /b 0
