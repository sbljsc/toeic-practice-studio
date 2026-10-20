@echo off
setlocal
cd /d "%~dp0"

set "STUDIO_PYTHON=runtime\python.exe"
if not exist "%STUDIO_PYTHON%" set "STUDIO_PYTHON=.venv\Scripts\python.exe"
if not exist "%STUDIO_PYTHON%" (
  echo ERROR: runtime is missing. Extract the complete Windows release ZIP.
  echo For a source checkout, run Setup.cmd first.
  if "%~1"=="" pause
  exit /b 1
)
if not exist "apps\web\dist\index.html" (
  echo ERROR: web build is missing. Run Setup.cmd or npm run web:build first.
  if "%~1"=="" pause
  exit /b 1
)

echo Starting TOEIC Practice on 127.0.0.1. Press Ctrl+C to stop.
set "PYTHONPATH=%CD%\apps\api\src;%PYTHONPATH%"
"%STUDIO_PYTHON%" -B -X utf8 -m toeic_practice.launcher %*
set "STUDIO_EXIT=%errorlevel%"
if not "%STUDIO_EXIT%"=="0" if "%~1"=="" pause
exit /b %STUDIO_EXIT%
