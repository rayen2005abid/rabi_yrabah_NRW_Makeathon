@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERROR: .venv not found. Create a Python 3.12 virtual environment first.
  exit /b 1
)
".venv\Scripts\python.exe" -m src.simple_camera --artifact artifacts/core_classifier_simple_v3 --config configs/default.yaml %*
endlocal
