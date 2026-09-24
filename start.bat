@echo off
setlocal
rem =============================================================
rem  FRP Manager launcher - VISIBLE MODE (no silent/hidden window)
rem  PURE ASCII ONLY (GBK cmd on Chinese Windows)
rem  - Runs main.py in the FOREGROUND, so the panel address
rem    (localhost / LAN URL) is shown LIVE in this window.
rem    No need to open logs\launch.log.
rem  - Window never auto-closes: it pauses at the end.
rem =============================================================

cd /d "%~dp0"
if not exist logs mkdir logs

echo ================================================
echo  FRP Manager  [VISIBLE MODE]
echo  Dir : %CD%
echo ================================================

rem ---- find python ----
set "PY="
where python >nul 2>&1
if not errorlevel 1 set "PY=python"
if not defined PY (
    where py >nul 2>&1
    if not errorlevel 1 set "PY=py"
)
if not defined PY (
    for /d %%P in ("%LOCALAPPDATA%\Programs\Python\Python3*") do (
        if not defined PY if exist "%%P\python.exe" set "PY=%%P\python.exe"
    )
)
if not defined PY (
    if exist "%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe" (
        set "PY=%LOCALAPPDATA%\Microsoft\WindowsApps\python.exe"
    )
)

if not defined PY (
    echo [ERROR] Python not found on this machine.
    echo         Install Python 3.8+ from:
    echo         https://www.python.org/downloads/windows/
    echo Press any key to exit...
    pause
    goto :eof
)

echo [INFO] Python : %PY%
"%PY%" --version
echo [INFO] Checking dependencies...
"%PY%" -c "import flask, requests, psutil" >nul 2>&1
if errorlevel 1 (
    echo [WARN] Missing dependencies; installing now, this may take a while...
    "%PY%" -m pip install flask requests psutil -i https://pypi.tuna.tsinghua.edu.cn/simple
    if errorlevel 1 (
        echo [ERROR] pip install failed. Check network / pip, then run again.
        pause
        goto :eof
    )
) else (
    echo [INFO] Dependencies OK.
)

echo ================================================
echo  PANEL ADDRESS - open one of these in a browser:
echo      http://127.0.0.1:5000        (this computer)
echo      http://YOUR-LAN-IP:5000      (phone / other PC)
echo  The app prints the REAL localhost / LAN URL below.
echo  If 5000 is busy it auto-switches to a free port; the
echo  final address is in the live log right below.
echo  Keep this window OPEN while using FRP Manager.
echo ================================================
echo.

"%PY%" -u main.py
set "RC=%errorlevel%"

echo.
echo ================================================
echo [DONE] FRP Manager exited with code %RC%
if not "%RC%"=="0" echo        (a traceback above shows the reason)
if exist "logs\panel_url.txt" (
    echo  Last panel address:
    type "logs\panel_url.txt"
)
echo ================================================
echo Press any key to close this window...
pause
