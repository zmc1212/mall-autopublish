@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"

echo Cloudflare update deployment. Existing ZIPs only; no application build.
python "%~dp0tools\deploy_cf_updates.py" %*
set "DEPLOY_EXIT=%ERRORLEVEL%"
echo.
if not "%DEPLOY_EXIT%"=="0" (
  echo Deployment failed. See details above. Exit code: %DEPLOY_EXIT%
) else (
  echo Finished. See the result above.
)
pause
exit /b %DEPLOY_EXIT%
