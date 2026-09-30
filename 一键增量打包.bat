@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo 正在生成增量更新包，只打包应用文件并复用已安装的浏览器运行环境。
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\pack.ps1" -UpdateOnly %*
set "BUILD_EXIT=%ERRORLEVEL%"

if not "%BUILD_EXIT%"=="0" (
  echo.
  echo 增量打包失败，退出码：%BUILD_EXIT%。请查看上方错误信息。
  pause
  exit /b %BUILD_EXIT%
)

echo.
echo 增量打包完成：%~dp0dist\千牛自动上架-Update.exe
pause
exit /b 0
