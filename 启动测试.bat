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

rem 前端改动（desktop\ui\src）需要重新构建 dist 才会生效；检测到有更新时自动构建
set "UI_DIR=%~dp0desktop\ui"
if not exist "%UI_DIR%\node_modules\.bin\vite.CMD" (
  echo 未安装前端依赖，跳过前端构建；前端改动需先在 desktop\ui 执行 npm install
  goto skip_ui_build
)
powershell -NoProfile -Command "$ui='%UI_DIR%'; if (-not (Test-Path ($ui+'\dist\index.html'))) { exit 1 }; $inputs = @(Get-ChildItem ($ui+'\src') -Recurse -File); $inputs += @(Get-Item ($ui+'\index.html'), ($ui+'\package.json'), ($ui+'\vite.config.ts') -ErrorAction SilentlyContinue); if (-not $inputs) { exit 1 }; $last = ($inputs | Measure-Object LastWriteTime -Maximum).Maximum; exit [int]($last -gt (Get-Item ($ui+'\dist\index.html')).LastWriteTime)"
if not errorlevel 1 (
  echo 前端无更新，直接启动
  goto skip_ui_build
)
echo 检测到前端有更新，构建 UI...
pushd "%UI_DIR%"
call npm run build
if errorlevel 1 echo 前端构建失败，继续使用现有 dist 启动
popd
:skip_ui_build

"%PY%" "%~dp0run_desktop.py"
if errorlevel 1 pause
