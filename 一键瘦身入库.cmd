@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
if "%~1"=="" (
  echo Usage: drag a product JSON onto this file, or pass its path.
  exit /b 2
)
python -m web_fill.material_flow --product "%~f1" --execute
exit /b %errorlevel%
