@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"

echo 正在打包最新源码、前端和离线安装包，请勿关闭此窗口。
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0desktop\pack.ps1" %*
set "BUILD_EXIT=%ERRORLEVEL%"

if not "%BUILD_EXIT%"=="0" (
  echo.
  echo 打包失败，退出码：%BUILD_EXIT%。请查看上方错误信息。
  pause
  exit /b %BUILD_EXIT%
)

echo.
echo 打包完成：%~dp0dist\千牛自动上架-Setup.exe
pause
exit /b 0
