$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = Resolve-Path (Join-Path $PSScriptRoot "..") }
Set-Location $Root

function Find-Command([string]$Name) {
  $cmd = Get-Command $Name -ErrorAction SilentlyContinue
  if ($cmd) { return $cmd.Source }
  return $null
}

Write-Host "==> build frontend"
$Ui = Join-Path $Root "desktop\ui"
if (-not (Find-Command "npm")) { throw "npm not found" }
Push-Location $Ui
if (-not (Test-Path "node_modules")) {
  npm install
}
npm run build
Pop-Location
$UiIndex = Join-Path $Ui "dist\index.html"
if (-not (Test-Path $UiIndex)) {
  throw "frontend build failed: desktop/ui/dist/index.html missing"
}

Write-Host "==> stage portable node.exe and playwright-core (Chrome is NOT bundled)"
$Stage = Join-Path $Root "desktop\runtime"
New-Item -ItemType Directory -Force -Path (Join-Path $Stage "node") | Out-Null
$NodeSrc = $env:QIANNIU_NODE
if (-not $NodeSrc -or -not (Test-Path $NodeSrc)) {
  $nodeCmd = Get-Command node -ErrorAction SilentlyContinue
  if ($nodeCmd -and $nodeCmd.Source -notmatch "WindowsApps") {
    $NodeSrc = $nodeCmd.Source
  }
}
if (-not $NodeSrc -or -not (Test-Path $NodeSrc)) {
  $fallbacks = @(
    "$env:LOCALAPPDATA\Programs\node\node.exe",
    "C:\Users\Administrator\Tools\node\node-v23.9.0-win-x64\node.exe",
    "D:\nodejs\node.exe"
  )
  foreach ($item in $fallbacks) {
    if (Test-Path $item) { $NodeSrc = $item; break }
  }
}
if (-not $NodeSrc -or -not (Test-Path $NodeSrc)) {
  throw "node.exe not found"
}
Copy-Item $NodeSrc (Join-Path $Stage "node\node.exe") -Force
$PwSrc = Join-Path $Root ".work\node_modules\playwright-core"
if (-not (Test-Path $PwSrc)) { throw "playwright-core not found: $PwSrc" }
$PwDst = Join-Path $Stage "playwright-core"
if (Test-Path $PwDst) { Remove-Item $PwDst -Recurse -Force }
Copy-Item $PwSrc $PwDst -Recurse

Write-Host "==> PyInstaller onedir"
$Py = $env:QIANNIU_PYTHON
if (-not $Py) {
  foreach ($item in @("E:\python\python.exe", "E:\anaconda3\python.exe", (Find-Command "python"))) {
    if ($item -and (Test-Path $item)) { $Py = $item; break }
  }
}
if (-not $Py) { throw "python not found" }
$needPip = $true
try {
  & $Py -c "import fastapi, uvicorn, webview, PyInstaller, openpyxl, PIL"
  if ($LASTEXITCODE -eq 0) { $needPip = $false }
} catch {
  $needPip = $true
}
if ($needPip) {
  & $Py -m pip install -r (Join-Path $Root "requirements.txt") pyinstaller
}
$DistApp = Join-Path $Root "dist\QianniuApp"
$NamedApp = Join-Path $Root "dist\千牛自动上架"
if (Test-Path $DistApp) { Remove-Item $DistApp -Recurse -Force }
if (Test-Path $NamedApp) { Remove-Item $NamedApp -Recurse -Force }
& $Py -m PyInstaller --noconfirm --clean (Join-Path $Root "desktop\app.spec")
if (-not (Test-Path (Join-Path $NamedApp "千牛自动上架.exe"))) {
  throw "PyInstaller did not create dist/千牛自动上架/千牛自动上架.exe"
}

function Copy-Tree($From, $To) {
  New-Item -ItemType Directory -Force -Path $To | Out-Null
  Copy-Item -Path (Join-Path $From "*") -Destination $To -Recurse -Force
}

Write-Host "==> copy runtime files next to exe"
Copy-Tree (Join-Path $Ui "dist") (Join-Path $NamedApp "web")
Copy-Tree (Join-Path $Stage "node") (Join-Path $NamedApp "node")
Copy-Tree $PwDst (Join-Path $NamedApp "playwright-core")
Copy-Tree (Join-Path $Root "templates") (Join-Path $NamedApp "templates")
Copy-Tree (Join-Path $Root "web_fill") (Join-Path $NamedApp "web_fill")
Copy-Item (Join-Path $Root "千牛字段映射.json") $NamedApp -Force
Copy-Item (Join-Path $Root "千牛自动上架.py") $NamedApp -Force
Copy-Item (Join-Path $Root "千牛网页执行.py") $NamedApp -Force
Copy-Item (Join-Path $Root "商品解析.py") $NamedApp -Force
Copy-Item (Join-Path $Root "job_session.py") $NamedApp -Force

Write-Host "==> Inno Setup"
$Iscc = $env:ISCC
if (-not $Iscc) {
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($item in $candidates) {
    if (Test-Path $item) { $Iscc = $item; break }
  }
}
if (-not $Iscc -or -not (Test-Path $Iscc)) {
  Write-Host "ISCC.exe missing, installing Inno Setup 6"
  $Setup = Join-Path $env:TEMP "innosetup-6.7.3.exe"
  $urls = @(
    "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe",
    "https://jrsoftware.org/download.php/is.exe"
  )
  $ok = $false
  foreach ($url in $urls) {
    try {
      Invoke-WebRequest -Uri $url -OutFile $Setup -UseBasicParsing
      if ((Get-Item $Setup).Length -gt 1000000) { $ok = $true; break }
    } catch {
      Write-Host "download failed: $url"
    }
  }
  if (-not $ok) {
    winget install --id JRSoftware.InnoSetup -e --accept-package-agreements --accept-source-agreements
  } else {
    $InnoDir = Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6"
    Start-Process -FilePath $Setup -ArgumentList "/VERYSILENT","/NORESTART","/CURRENTUSER","/DIR=`"$InnoDir`"" -Wait
  }
  $candidates = @(
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe"
  )
  foreach ($item in $candidates) {
    if (Test-Path $item) { $Iscc = $item; break }
  }
}
if (-not (Test-Path $Iscc)) { throw "Inno Setup install failed: ISCC.exe not found" }
& $Iscc (Join-Path $Root "desktop\installer.iss")
$SetupOut = Join-Path $Root "dist\千牛自动上架-Setup.exe"
if (-not (Test-Path $SetupOut)) { throw "installer not created: $SetupOut" }
Write-Host "OK: $SetupOut"
