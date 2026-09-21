@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "PY="
if defined QIANNIU_PYTHON if exist "%QIANNIU_PYTHON%" set "PY=%QIANNIU_PYTHON%"
if not defined PY if exist "E:\python\python.exe" set "PY=E:\python\python.exe"
if not defined PY if exist "E:\anaconda3\python.exe" set "PY=E:\anaconda3\python.exe"
if not defined PY (
  for /f "delims=" %%I in ('where python 2^>nul') do (
    if not defined PY set "PY=%%I"
  )
)
if not defined PY (
  echo 找不到 python.exe
  pause
  exit /b 1
)

echo 使用源码启动（改完代码直接点这个，不用点 exe）
echo %PY%
"%PY%" "%~dp0run_desktop.py"
if errorlevel 1 pause
