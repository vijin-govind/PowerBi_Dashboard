@echo off
setlocal
cd /d "%~dp0"
title PBIX Canvas

rem Find Python 3.10+ (the "py" launcher first, then "python").
set "PY="
py -3 -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=py -3"
if not defined PY python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul && set "PY=python"
if not defined PY goto :nopython

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment in .venv ...
  %PY% -m venv .venv || goto :venvfail
)

echo Installing / checking packages (first run takes a minute) ...
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip >nul 2>nul
".venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q -r backend\requirements.txt || goto :pipfail

".venv\Scripts\python.exe" run.py %*
if errorlevel 1 pause
goto :eof

:nopython
echo.
echo Python 3.10 or newer was not found.
echo Install it from https://www.python.org/downloads/windows/
echo and tick "Add python.exe to PATH" in the installer, then run this file again.
pause
exit /b 1

:venvfail
echo Could not create the virtual environment. Delete the .venv folder and try again.
pause
exit /b 1

:pipfail
echo.
echo Installing packages failed - see the messages above.
echo Behind a company proxy? Set HTTPS_PROXY first, or ask IT to allow pypi.org.
pause
exit /b 1
