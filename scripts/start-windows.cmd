@echo off
setlocal
cd /d "%~dp0.."

where py >nul 2>nul
if exist ".venv\Scripts\python.exe" goto run

echo [Movie Modify] Creating a Windows Python environment...
if %errorlevel%==0 (
  py -3.11 -m venv .venv
  if errorlevel 1 py -3 -m venv .venv
) else (
  python -m venv .venv
)
if errorlevel 1 (
  echo Python 3.11 or later is required. Install Python, then retry.
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 exit /b 1

:run
".venv\Scripts\python.exe" -m movie_modify %*
set "APP_EXIT=%errorlevel%"
if not "%APP_EXIT%"=="0" (
  echo.
  echo Movie Modify exited with error %APP_EXIT%.
  pause
)
exit /b %APP_EXIT%
