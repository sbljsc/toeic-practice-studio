@echo off
setlocal
cd /d "%~dp0"

if not "%~2"=="" (
  echo Usage: Setup.cmd [python.exe path]
  exit /b 1
)
set "PYTHON_EXE=%~1"
if not defined PYTHON_EXE set "PYTHON_EXE=python"

"%PYTHON_EXE%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3,12) else 1)"
if errorlevel 1 (
  echo ERROR: Python 3.12 or newer is required.
  exit /b 1
)

node -e "process.exit(Number(process.versions.node.split('.')[0]) >= 24 ? 0 : 1)"
if errorlevel 1 (
  echo ERROR: Node.js 24 or newer and npm are required.
  exit /b 1
)

echo Creating project-local Python environment...
"%PYTHON_EXE%" -m venv .venv
if errorlevel 1 exit /b %errorlevel%
echo Installing hash-locked Python dependencies into .venv...
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --require-hashes -r apps\api\requirements.lock
if errorlevel 1 exit /b %errorlevel%

echo Installing locked web dependencies...
call npm ci
if errorlevel 1 exit /b %errorlevel%

echo Building the web interface...
call npm run web:build
if errorlevel 1 exit /b %errorlevel%

echo Setup complete. Run Start.cmd to open the local app.
