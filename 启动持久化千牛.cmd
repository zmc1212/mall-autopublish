@echo off
set "PROFILE=%APPDATA%\千牛自动上架\chrome-profile"
if not exist "%PROFILE%" mkdir "%PROFILE%"
set "CHROME=%ProgramFiles%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" set "CHROME=%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"
if not exist "%CHROME%" (
  echo 未找到 Google Chrome，请先安装官方 Chrome。
  exit /b 1
)
start "Taobao Playwright Chrome" "%CHROME%" --user-data-dir="%PROFILE%" --remote-debugging-port=9222 --no-first-run --no-default-browser-check https://myseller.taobao.com/
