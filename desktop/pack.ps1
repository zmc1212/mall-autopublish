<#
.SYNOPSIS
Build the desktop app and offline installer.

.PARAMETER Clean
Discard PyInstaller analysis before building; preserve the pinned runtime.

.PARAMETER AppOnly
Build and verify the unpacked app, but skip the slow Inno Setup compression step.

.PARAMETER UpdateOnly
Build and verify the app, then create a small updater without browser runtimes.

.PARAMETER RuntimeSource
Seed the pinned runtime from an existing complete installation matching runtime-baseline.json.

.EXAMPLE
.\desktop\pack.ps1 -AppOnly

.EXAMPLE
.\desktop\pack.ps1 -Clean
#>
[CmdletBinding()]
param(
  [switch]$Clean,
  [switch]$AppOnly,
  [switch]$UpdateOnly,
  [string]$RuntimeSource
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if ($AppOnly -and $UpdateOnly) { throw "-AppOnly and -UpdateOnly cannot be used together" }
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = Resolve-Path (Join-Path $PSScriptRoot "..") }
Set-Location $Root

function Find-Command([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

function Copy-Tree([string]$From, [string]$To) {
  if (-not (Test-Path -LiteralPath $From -PathType Container)) { throw "runtime source directory missing: $From" }
  New-Item -ItemType Directory -Force -Path $To | Out-Null
  Copy-Item -Path (Join-Path $From "*") -Destination $To -Recurse -Force
}

function Assert-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label missing: $Path" }
}

$Py = $env:QIANNIU_PYTHON
if (-not $Py) {
  foreach ($item in @("E:\python\python.exe", "E:\anaconda3\python.exe", (Find-Command "python"))) {
    if ($item -and (Test-Path -LiteralPath $item -PathType Leaf)) { $Py = $item; break }
  }
}
if (-not $Py) { throw "python not found" }

# Resolve and verify before building or deleting any previous distribution.
# -Clean must never refresh the runtime from the packaging machine.
Write-Host "==> verify pinned runtime baseline"
$Stage = Join-Path $Root ".work\desktop-runtime-pinned"
$pinArgs = @((Join-Path $Root "tools\pin_desktop_runtime.py"), "--cache", $Stage)
if ($RuntimeSource) { $pinArgs += @("--source", $RuntimeSource) }
& $Py @pinArgs
if ($LASTEXITCODE -ne 0) { throw "Pinned runtime unavailable; restore the matching runtime with -RuntimeSource. Existing build outputs were not changed." }
$PwPackage = Get-Content -LiteralPath (Join-Path $Stage "playwright-core\package.json") -Raw | ConvertFrom-Json
$PinnedRuntime = Get-Content -LiteralPath (Join-Path $Root "desktop\runtime-baseline.json") -Raw | ConvertFrom-Json
$Revision = [string]$PinnedRuntime.chromium_revision

Write-Host "==> build frontend"
$Ui = Join-Path $Root "desktop\ui"
if (-not (Find-Command "npm")) { throw "npm not found" }
Push-Location $Ui
if (-not (Test-Path "node_modules")) {
  npm install
  if ($LASTEXITCODE -ne 0) { throw "frontend dependencies install failed" }
}
npm run build
if ($LASTEXITCODE -ne 0) { throw "frontend build failed" }
Pop-Location
$UiIndex = Join-Path $Ui "dist\index.html"
Assert-File $UiIndex "frontend entry"

Write-Host "==> PyInstaller onedir"
$AppIcon = Join-Path $Root "logo\40c40691-9747-453a-a1d1-f2c94d393f34.ico"
Assert-File $AppIcon "application icon"
$needPip = $true
try {
  & $Py -c "import fastapi, uvicorn, webview, PyInstaller, openpyxl, PIL, pefile"
  if ($LASTEXITCODE -eq 0) { $needPip = $false }
} catch { $needPip = $true }
if ($needPip) {
  & $Py -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller pefile
  if ($LASTEXITCODE -ne 0) { throw "Python dependencies install failed" }
}

$DistApp = Join-Path $Root "dist\QianniuApp"
$NamedApp = Join-Path $Root "dist\千牛自动上架"
if (Test-Path -LiteralPath $DistApp) { Remove-Item -LiteralPath $DistApp -Recurse -Force }
if (Test-Path -LiteralPath $NamedApp) { Remove-Item -LiteralPath $NamedApp -Recurse -Force }
$pyInstallerArgs = @("-m", "PyInstaller", "--noconfirm")
if ($Clean) { $pyInstallerArgs += "--clean" }
$pyInstallerArgs += (Join-Path $Root "desktop\app.spec")
& $Py @pyInstallerArgs
if ($LASTEXITCODE -ne 0) { throw "PyInstaller failed" }
Assert-File (Join-Path $NamedApp "千牛自动上架.exe") "desktop executable"

Write-Host "==> copy complete runtime next to exe"
Copy-Tree (Join-Path $Ui "dist") (Join-Path $NamedApp "web")
Copy-Tree (Join-Path $Stage "node") (Join-Path $NamedApp "node")
Copy-Tree (Join-Path $Stage "playwright-core") (Join-Path $NamedApp "playwright-core")
Copy-Tree (Join-Path $Stage "browser") (Join-Path $NamedApp "browser")
Copy-Tree (Join-Path $Stage "webview2") (Join-Path $NamedApp "webview2")
Copy-Tree (Join-Path $Root "templates") (Join-Path $NamedApp "templates")
Copy-Tree (Join-Path $Root "web_fill") (Join-Path $NamedApp "web_fill")
foreach ($file in @("千牛字段映射.json", "千牛自动上架.py", "千牛网页执行.py", "商品解析.py", "job_session.py", "workspace.py")) {
  Copy-Item -LiteralPath (Join-Path $Root $file) -Destination $NamedApp -Force
}

$BrowserVersion = (Get-Item -LiteralPath (Join-Path $NamedApp "browser\chromium\chrome.exe")).VersionInfo.ProductVersion
$WebViewVersion = (Get-Item -LiteralPath (Join-Path $NamedApp "webview2\msedgewebview2.exe")).VersionInfo.ProductVersion
$NodeVersion = (& (Join-Path $NamedApp "node\node.exe") --version).Trim()
$BaseVersion = (& $Py -c "from desktop.version import VERSION; print(VERSION)").Trim()
if ($LASTEXITCODE -ne 0) { throw "cannot read application version" }
$ReleaseVersion = "$BaseVersion.$((Get-Date).ToUniversalTime().ToString('yyyyMMddHHmmss'))"
$UpdateFeedUrl = ""
$CloudflareDeployment = Join-Path $Root ".work\cloudflare-updates\deployment.json"
if (Test-Path -LiteralPath $CloudflareDeployment -PathType Leaf) {
  $CloudflareState = Get-Content -LiteralPath $CloudflareDeployment -Raw | ConvertFrom-Json
  if ($CloudflareState.verified -eq $true) { $UpdateFeedUrl = [string]$CloudflareState.feed_url }
  if ($UpdateFeedUrl -and (-not $UpdateFeedUrl.StartsWith("https://"))) { throw "deployed update feed must use HTTPS" }
}
$LicenseServerUrl = ""
$LicenseDeployment = Join-Path $Root ".work\cloudflare-license\deployment.json"
if (Test-Path -LiteralPath $LicenseDeployment -PathType Leaf) {
  $LicenseState = Get-Content -LiteralPath $LicenseDeployment -Raw | ConvertFrom-Json
  if ($LicenseState.verified -eq $true) { $LicenseServerUrl = [string]$LicenseState.url }
  if ($LicenseServerUrl -and (-not $LicenseServerUrl.StartsWith("https://"))) { throw "deployed license service must use HTTPS" }
}
if (-not $LicenseServerUrl) { Write-Host "WARN: 未部署授权服务，本构建不强制联网激活（仅开发/测试可用）" }
$Manifest = [ordered]@{
  application = $ReleaseVersion
  update_feed_url = $UpdateFeedUrl
  license_server_url = $LicenseServerUrl
  architecture = "windows-x64"
  node = $NodeVersion
  playwright = [string]$PwPackage.version
  chromium = $BrowserVersion
  chromium_revision = $Revision
  webview2 = $WebViewVersion
  generated_at = (Get-Date).ToUniversalTime().ToString("o")
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $NamedApp "runtime-manifest.json") -Encoding UTF8

Write-Host "==> verify runtime layout, PE dependencies and bundled Chromium"
& $Py (Join-Path $Root "desktop\verify_runtime.py") --app-dir $NamedApp
if ($LASTEXITCODE -ne 0) { throw "runtime verification failed" }
$SelfTestData = Join-Path $env:TEMP ("qianniu-self-test-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $SelfTestData | Out-Null
$oldAppData = $env:QIANNIU_APPDATA
$env:QIANNIU_APPDATA = $SelfTestData
try {
  $selfTest = Start-Process -FilePath (Join-Path $NamedApp "千牛自动上架.exe") -ArgumentList "--self-test" -Wait -PassThru -WindowStyle Hidden
  if ($selfTest.ExitCode -ne 0) { throw "packaged application self-test failed; see $SelfTestData\logs\self-test.log" }
} finally {
  $env:QIANNIU_APPDATA = $oldAppData
  if (Test-Path -LiteralPath $SelfTestData) { Remove-Item -LiteralPath $SelfTestData -Recurse -Force }
}

if ($AppOnly) {
  Write-Host "OK: $NamedApp (installer skipped)"
  return
}

if ($UpdateOnly) {
  Write-Host "==> program-internal update ZIP and latest.json (no browser runtimes)"
  & $Py (Join-Path $Root "tools\build_inapp_update.py") --app-dir $NamedApp --output (Join-Path $Root "dist\updates")
  if ($LASTEXITCODE -ne 0) { throw "program-internal update package generation failed" }
}

Write-Host $(if ($UpdateOnly) { "==> Inno Setup incremental updater" } else { "==> Inno Setup full offline installer" })
$Iscc = $env:ISCC
if (-not $Iscc) {
  foreach ($item in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path -LiteralPath $item -PathType Leaf) { $Iscc = $item; break }
  }
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc -PathType Leaf)) { throw "ISCC.exe missing; install Inno Setup 6 or set ISCC before building" }
$InstallerSpec = if ($UpdateOnly) { Join-Path $Root "desktop\update.iss" } else { Join-Path $Root "desktop\installer.iss" }
& $Iscc "/DMyAppVersion=$BaseVersion" $InstallerSpec
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
$SetupOut = Join-Path $Root $(if ($UpdateOnly) { "dist\千牛自动上架-Update.exe" } else { "dist\千牛自动上架-Setup.exe" })
Assert-File $SetupOut "installer"
Write-Host "OK: $SetupOut"
