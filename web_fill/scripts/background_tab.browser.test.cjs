// 后台页签 rAF 冻结回归：镜像生产路径（自起 Chrome + connectOverCDP attach）。
// Chromium 页签进入后台约 20-30 秒后 rAF 停止/深度节流，Playwright 的 stable
// 检查依赖连续两帧 rAF，未打补丁时 scrollIntoViewIfNeeded/click 会拖慢到
// 数秒甚至烧满超时（见 后台页签rAF冻结超时修复说明.md）。补丁后 stable 检查
// 由 setTimeout 驱动，冻结页签上仍应在亚秒级完成。
// 断言：等待页签 rAF 真正冻结（ticks <= 3，否则 skip），scrollIntoViewIfNeeded
// 与 click 合计须在 2 秒内完成（未打补丁的运行时在同条件下 >2.4 秒或超时）。
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {execFile} = require('node:child_process');
const fs = require('node:fs');
const http = require('node:http');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');

const CHROME = process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe';
const PAGE_HTML = 'data:text/html,<div id="box" style="width:80px;height:80px">A</div>'
  + '<button id="btn" onclick="window.clicked=(window.clicked||0)+1">go</button>'
  + '<script>window.raf=0;const loop=()=>{window.raf++;requestAnimationFrame(loop)};'
  + 'requestAnimationFrame(loop);</script>';

function cdp(port, p, method = 'GET') {
  return new Promise((resolve, reject) => {
    const req = (method === 'PUT' ? http.request : http.get)({host: '127.0.0.1', port, path: p, method}, res => {
      let data = '';
      res.on('data', c => data += c);
      res.on('end', () => resolve(data));
    });
    req.on('error', reject);
    req.end();
  });
}

test('background tab: actionability ops survive frozen rAF', async () => {
  const port = 9700 + (process.pid % 200);
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'qn-bgtab-'));
  const args = [
    `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, '--no-first-run',
    '--no-default-browser-check', '--window-size=800,600',
    // 与 千牛网页执行.py CHROME_ANTI_THROTTLE_ARGS 保持一致。
    '--disable-background-timer-throttling', '--disable-renderer-backgrounding',
    '--disable-backgrounding-occluded-windows', 'about:blank',
  ];
  const chrome = execFile(CHROME, args, () => {});
  chrome.stdout.on('data', () => {});
  chrome.stderr.on('data', () => {});
  let browser;
  try {
    for (let i = 0; i < 50; i++) {
      try { await cdp(port, '/json/version'); break; } catch (_) { await new Promise(r => setTimeout(r, 200)); }
    }
    await cdp(port, '/json/new?' + encodeURIComponent(PAGE_HTML), 'PUT');
    await new Promise(r => setTimeout(r, 800));
    const tabs = JSON.parse(await cdp(port, '/json/list'));
    const mine = tabs.find(t => t.type === 'page' && t.url.startsWith('data:text/html'));
    const other = tabs.find(t => t.type === 'page' && t.id !== mine.id);
    await cdp(port, '/json/activate/' + other.id, 'PUT');

    browser = await chromium.connectOverCDP(`http://127.0.0.1:${port}`, {timeout: 20000});
    const page = browser.contexts()[0].pages().find(p => p.url().startsWith('data:text/html'));
    assert.ok(page, '应能找到后台测试页签');

    // 等待页签 rAF 冻结（生产实测约 20-30 秒宽限；超过 60 秒仍不冻结则本
    // 环境无法复现，跳过而不是误报）。
    let frozen = false;
    for (let i = 0; i < 12; i++) {
      await page.waitForTimeout(5000);
      const ticks = await page.evaluate(() => {
        if (!window.__qnRafProbe) {
          window.__qnRafProbe = {ticks: 0};
          const loop = () => { window.__qnRafProbe.ticks++; requestAnimationFrame(loop); };
          requestAnimationFrame(loop);
        }
        window.__qnRafProbe.ticks = 0;
      }).then(() => page.waitForTimeout(1200)).then(() => page.evaluate(() => window.__qnRafProbe.ticks));
      if (ticks <= 3) { frozen = true; break; }
    }
    if (!frozen) {
      console.log('skip: 本环境后台页签 rAF 未冻结，无法复现冻结条件');
      return;
    }

    // 冻结页签上操作必须快速完成；未打补丁的 rAF 调度在同条件下至少 2.4 秒。
    const t0 = Date.now();
    await page.locator('#box').scrollIntoViewIfNeeded({timeout: 8000});
    await page.locator('#btn').click({timeout: 8000});
    const elapsed = Date.now() - t0;
    assert.equal(await page.evaluate(() => window.clicked || 0), 1);
    assert.ok(elapsed < 2000, `冻结页签上的操作应在 2 秒内完成，实际 ${elapsed}ms`);
  } finally {
    if (browser) await browser.close().catch(() => {});
    try { process.platform === 'win32' ? execFile('taskkill', ['/F', '/T', '/PID', String(chrome.pid)], () => {}) : chrome.kill(); } catch (_) {}
    setTimeout(() => { try { fs.rmSync(profile, {recursive: true, force: true}); } catch (_) {} }, 500);
  }
}, {timeout: 180000});
