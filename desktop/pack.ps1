<#
.SYNOPSIS
Build the desktop app and offline installer.

.PARAMETER Clean
Discard cached runtime and PyInstaller analysis before building.

.PARAMETER AppOnly
Build and verify the unpacked app, but skip the slow Inno Setup compression step.

.PARAMETER UpdateOnly
Build and verify the app, then create a small updater without browser runtimes.

.EXAMPLE
.\desktop\pack.ps1 -AppOnly

.EXAMPLE
.\desktop\pack.ps1 -Clean
#>
[CmdletBinding()]
param(
  [switch]$Clean,
  [switch]$AppOnly,
  [switch]$UpdateOnly
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

function Sync-File([string]$From, [string]$To) {
  Assert-File $From "source file"
  $source = Get-Item -LiteralPath $From
  $target = Get-Item -LiteralPath $To -ErrorAction SilentlyContinue
  if ($target -and $target.Length -eq $source.Length -and $target.LastWriteTimeUtc -eq $source.LastWriteTimeUtc) { return }
  New-Item -ItemType Directory -Force -Path (Split-Path -Parent $To) | Out-Null
  Copy-Item -LiteralPath $From -Destination $To -Force
}

function Sync-Tree([string]$From, [string]$To) {
  if (-not (Test-Path -LiteralPath $From -PathType Container)) { throw "runtime source directory missing: $From" }
  New-Item -ItemType Directory -Force -Path $To | Out-Null
  & robocopy $From $To /MIR /COPY:DAT /DCOPY:DAT /R:2 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
  $robocopyExit = $LASTEXITCODE
  if ($robocopyExit -ge 8) { throw "runtime sync failed ($robocopyExit): $From -> $To" }
}

function Link-Tree([string]$From, [string]$To) {
  if (-not (Test-Path -LiteralPath $From -PathType Container)) { throw "runtime cache directory missing: $From" }
  $sourceRoot = (Resolve-Path -LiteralPath $From).Path.TrimEnd('\')
  $targetRoot = [System.IO.Path]::GetFullPath($To).TrimEnd('\')
  if ([System.IO.Path]::GetPathRoot($sourceRoot) -ne [System.IO.Path]::GetPathRoot($targetRoot)) {
    Copy-Tree $sourceRoot $targetRoot
    return
  }
  if (Test-Path -LiteralPath $targetRoot) { Remove-Item -LiteralPath $targetRoot -Recurse -Force }
  New-Item -ItemType Directory -Force -Path $targetRoot | Out-Null
  Get-ChildItem -LiteralPath $sourceRoot -Directory -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
    New-Item -ItemType Directory -Force -Path (Join-Path $targetRoot $relative) | Out-Null
  }
  Get-ChildItem -LiteralPath $sourceRoot -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($sourceRoot.Length).TrimStart('\')
    New-Item -ItemType HardLink -Path (Join-Path $targetRoot $relative) -Target $_.FullName | Out-Null
  }
}

function Assert-File([string]$Path, [string]$Label) {
  if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "$Label missing: $Path" }
}

function Resolve-BrowserDirectory([string]$Candidate) {
  if (-not $Candidate) { return $null }
  foreach ($path in @($Candidate, (Join-Path $Candidate "chrome-win64"), (Join-Path $Candidate "chrome-win"))) {
    if (Test-Path -LiteralPath (Join-Path $path "chrome.exe") -PathType Leaf) { return $path }
  }
  return $null
}

function Test-WebViewDirectory([string]$Path) {
  if (-not $Path) { return $false }
  foreach ($name in @("msedgewebview2.exe", "msedge.dll", "resources.pak", "icudtl.dat")) {
    if (-not (Test-Path -LiteralPath (Join-Path $Path $name) -PathType Leaf)) { return $false }
  }
  return Test-Path -LiteralPath (Join-Path $Path "locales") -PathType Container
}

function Resolve-WebViewDirectory([string]$Candidate) {
  if (-not $Candidate -or -not (Test-Path -LiteralPath $Candidate -PathType Container)) { return $null }
  if (Test-WebViewDirectory $Candidate) { return $Candidate }
  $versions = Get-ChildItem -LiteralPath $Candidate -Directory -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -match '^\d+(\.\d+)+$' } |
    Sort-Object { try { [version]$_.Name } catch { [version]'0.0' } } -Descending
  foreach ($version in $versions) {
    if (Test-WebViewDirectory $version.FullName) { return $version.FullName }
  }
  return $null
}

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

Write-Host "==> stage portable Node.js, Playwright, Chromium and WebView2"
$Stage = Join-Path $Root ".work\desktop-runtime"
if ($Clean -and (Test-Path -LiteralPath $Stage)) { Remove-Item -LiteralPath $Stage -Recurse -Force }
New-Item -ItemType Directory -Force -Path $Stage | Out-Null

$NodeSrc = $env:QIANNIU_NODE
if (-not $NodeSrc -or -not (Test-Path -LiteralPath $NodeSrc -PathType Leaf)) {
  $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
  if ($nodeCmd -and $nodeCmd.Source -notmatch "WindowsApps") { $NodeSrc = $nodeCmd.Source }
}
if (-not $NodeSrc -or -not (Test-Path -LiteralPath $NodeSrc -PathType Leaf)) {
  foreach ($item in @("$env:LOCALAPPDATA\Programs\node\node.exe", "C:\Users\Administrator\Tools\node\node-v23.9.0-win-x64\node.exe", "D:\nodejs\node.exe")) {
    if (Test-Path -LiteralPath $item -PathType Leaf) { $NodeSrc = $item; break }
  }
}
Assert-File $NodeSrc "node.exe"
Sync-File $NodeSrc (Join-Path $Stage "node\node.exe")

$PwSrc = Join-Path $Root ".work\node_modules\playwright-core"
Assert-File (Join-Path $PwSrc "package.json") "playwright-core package"
Sync-Tree $PwSrc (Join-Path $Stage "playwright-core")
$PwPackage = Get-Content -LiteralPath (Join-Path $PwSrc "package.json") -Raw | ConvertFrom-Json
$BrowserMetadata = Get-Content -LiteralPath (Join-Path $PwSrc "browsers.json") -Raw | ConvertFrom-Json
$ChromiumMetadata = $BrowserMetadata.browsers | Where-Object { $_.name -eq "chromium" } | Select-Object -First 1
if (-not $ChromiumMetadata) { throw "playwright-core browsers.json has no chromium entry" }
$Revision = [string]$ChromiumMetadata.revision

$BrowserSrc = Resolve-BrowserDirectory $env:QIANNIU_BROWSER_DIR
$BrowserCache = if ($env:PLAYWRIGHT_BROWSERS_PATH) { $env:PLAYWRIGHT_BROWSERS_PATH } else { Join-Path $env:LOCALAPPDATA "ms-playwright" }
if (-not $BrowserSrc) { $BrowserSrc = Resolve-BrowserDirectory (Join-Path $BrowserCache "chromium-$Revision") }
if (-not $BrowserSrc) {
  Write-Host "Chromium revision $Revision missing; downloading it for the build cache"
  $oldBrowserPath = $env:PLAYWRIGHT_BROWSERS_PATH
  $env:PLAYWRIGHT_BROWSERS_PATH = $BrowserCache
  try {
    & $NodeSrc (Join-Path $PwSrc "cli.js") install chromium
    if ($LASTEXITCODE -ne 0) { throw "Playwright Chromium download failed" }
  } finally { $env:PLAYWRIGHT_BROWSERS_PATH = $oldBrowserPath }
  $BrowserSrc = Resolve-BrowserDirectory (Join-Path $BrowserCache "chromium-$Revision")
}
if (-not $BrowserSrc) { throw "Chromium revision $Revision not found; set QIANNIU_BROWSER_DIR" }
foreach ($name in @("chrome.exe", "chrome.dll", "resources.pak", "icudtl.dat")) { Assert-File (Join-Path $BrowserSrc $name) "Chromium $name" }
if (-not (Test-Path -LiteralPath (Join-Path $BrowserSrc "locales") -PathType Container)) { throw "Chromium locales missing" }
Sync-Tree $BrowserSrc (Join-Path $Stage "browser\chromium")

$WebViewSrc = Resolve-WebViewDirectory $env:QIANNIU_WEBVIEW2_DIR
if (-not $WebViewSrc) {
  foreach ($candidate in @(
    "${env:ProgramFiles(x86)}\Microsoft\EdgeWebView\Application",
    "$env:ProgramFiles\Microsoft\EdgeWebView\Application",
    "$env:LOCALAPPDATA\Microsoft\EdgeWebView\Application"
  )) {
    $WebViewSrc = Resolve-WebViewDirectory $candidate
    if ($WebViewSrc) { break }
  }
}
if (-not $WebViewSrc) { throw "fixed WebView2 Runtime not found; set QIANNIU_WEBVIEW2_DIR to the extracted x64 fixed runtime" }
Sync-Tree $WebViewSrc (Join-Path $Stage "webview2")

Write-Host "==> PyInstaller onedir"
$Py = $env:QIANNIU_PYTHON
if (-not $Py) {
  foreach ($item in @("E:\python\python.exe", "E:\anaconda3\python.exe", (Find-Command "python"))) {
    if ($item -and (Test-Path -LiteralPath $item -PathType Leaf)) { $Py = $item; break }
  }
}
if (-not $Py) { throw "python not found" }
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
Link-Tree (Join-Path $Stage "node") (Join-Path $NamedApp "node")
Link-Tree (Join-Path $Stage "playwright-core") (Join-Path $NamedApp "playwright-core")
Link-Tree (Join-Path $Stage "browser") (Join-Path $NamedApp "browser")
Link-Tree (Join-Path $Stage "webview2") (Join-Path $NamedApp "webview2")
Copy-Tree (Join-Path $Root "templates") (Join-Path $NamedApp "templates")
Copy-Tree (Join-Path $Root "web_fill") (Join-Path $NamedApp "web_fill")
foreach ($file in @("千牛字段映射.json", "千牛自动上架.py", "千牛网页执行.py", "商品解析.py", "job_session.py")) {
  Copy-Item -LiteralPath (Join-Path $Root $file) -Destination $NamedApp -Force
}

$BrowserVersion = (Get-Item -LiteralPath (Join-Path $NamedApp "browser\chromium\chrome.exe")).VersionInfo.ProductVersion
$WebViewVersion = (Get-Item -LiteralPath (Join-Path $NamedApp "webview2\msedgewebview2.exe")).VersionInfo.ProductVersion
$NodeVersion = (& (Join-Path $NamedApp "node\node.exe") --version).Trim()
$Manifest = [ordered]@{
  application = "1.1.0"
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

Write-Host $(if ($UpdateOnly) { "==> Inno Setup incremental updater" } else { "==> Inno Setup full offline installer" })
$Iscc = $env:ISCC
if (-not $Iscc) {
  foreach ($item in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe", "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe")) {
    if (Test-Path -LiteralPath $item -PathType Leaf) { $Iscc = $item; break }
  }
}
if (-not $Iscc -or -not (Test-Path -LiteralPath $Iscc -PathType Leaf)) { throw "ISCC.exe missing; install Inno Setup 6 or set ISCC before building" }
$InstallerSpec = if ($UpdateOnly) { Join-Path $Root "desktop\update.iss" } else { Join-Path $Root "desktop\installer.iss" }
& $Iscc $InstallerSpec
if ($LASTEXITCODE -ne 0) { throw "Inno Setup failed" }
$SetupOut = Join-Path $Root $(if ($UpdateOnly) { "dist\千牛自动上架-Update.exe" } else { "dist\千牛自动上架-Setup.exe" })
Assert-File $SetupOut "installer"
Write-Host "OK: $SetupOut"
