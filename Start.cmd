@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo ERROR: project dependencies are missing. Run Setup.cmd first.
  exit /b 1
)
if not exist "apps\web\dist\index.html" (
  echo ERROR: web build is missing. Run Setup.cmd or npm run web:build first.
  exit /b 1
)

echo Starting TOEIC Practice on 127.0.0.1. Press Ctrl+C to stop.
set "PYTHONPATH=%CD%\apps\api\src;%PYTHONPATH%"
.venv\Scripts\python.exe -m toeic_practice.launcher %*
exit /b %errorlevel%
