$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
    # 先打开不含 & 的首页，避免 npx.cmd 在 Windows 下重新解析查询参数。
    & npx.cmd --yes --package '@playwright/cli' playwright-cli '-s=taobao' open 'https://myseller.taobao.com/' --config '.playwright/cli.config.json'
    if ($LASTEXITCODE -ne 0) { throw 'Playwright 浏览器启动失败，请查看上方错误。' }
} finally {
    Pop-Location
}
