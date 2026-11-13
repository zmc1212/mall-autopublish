const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const source = fs.readFileSync(__dirname + '/spec_row_status.js', 'utf8');
const load = (payload = {}) => new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify(payload)).replace('/*HELPERS*/', () => helpers) + ')')();

const TOTAL = 37, ROW_H = 60, VIEW_H = 900;

// 合成虚拟滚动表格：td[id=N-custom_-1] 行只在滚动事件触达时渲染视口窗口；
// window.__qnHidden 模拟并发下本页签被其他 worker 的脚本切到后台——后台时
// Chrome 暂停渲染帧，scroll 事件不再触发重渲染（真实事故机制）。
const PAGE_HTML = `<html><body style="margin:0">
<div id="wrap" style="height:${VIEW_H}px;overflow-y:auto;position:relative"></div>
<script>
  Object.defineProperty(document, 'visibilityState', {
    configurable: true,
    get: () => window.__qnHidden ? 'hidden' : 'visible',
  });
  const wrap = document.getElementById('wrap');
  wrap.style.height = '${VIEW_H}px';
  wrap.style.overflowY = 'auto';
  wrap.style.position = 'relative';
  const spacer = document.createElement('div');
  spacer.style.height = ${TOTAL * ROW_H} + 'px';
  wrap.appendChild(spacer);
  let rendered = [];
  function render() {
    const start = Math.floor(wrap.scrollTop / ${ROW_H});
    const end = Math.min(${TOTAL}, Math.ceil((wrap.scrollTop + wrap.clientHeight) / ${ROW_H}) + 1);
    const want = [];
    for (let i = start; i < end; i++) want.push(i);
    if (JSON.stringify(want) === JSON.stringify(rendered)) return;
    rendered = want;
    for (const el of [...wrap.querySelectorAll('td')]) el.remove();
    for (const i of want) {
      const td = document.createElement('td');
      td.id = i + '-custom_-1';
      td.style.cssText = 'display:block;position:absolute;top:' + (i * ${ROW_H}) + 'px;height:${ROW_H}px;width:100%';
      const img = document.createElement('img');
      img.className = 'image-item';
      img.setAttribute('src', '/row-' + (i + 1) + '.jpg');
      td.appendChild(img);
      wrap.appendChild(td);
    }
  }
  wrap.addEventListener('scroll', () => {
    if (window.__qnHidden) return; // 后台页签渲染暂停：滚动不重渲染
    render();
  });
  render();
</script></body></html>`;

const boot = async (page) => {
  await page.setContent(PAGE_HTML);
  await page.waitForFunction(() => document.querySelectorAll('td').length > 0);
};

// bringToFront 置前后台：包装 page，让 ensureFront 的 bringToFront 同时清掉
// __qnHidden，等价于真实浏览器"页签回到前台后渲染恢复"。
const wrapPage = (page) => new Proxy(page, {
  get(target, prop) {
    if (prop === 'bringToFront') {
      return async () => {
        await target.evaluate(() => { window.__qnHidden = false; });
        return target.bringToFront();
      };
    }
    const value = Reflect.get(target, prop);
    return typeof value === 'function' ? value.bind(target) : value;
  },
});

test('full scan collects every virtual row and restores scroll position', async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: VIEW_H}});
    await boot(page);
    // 起始滚动停在列表中部，验证审计从当前窗口出发并还原位置
    await page.evaluate(() => { document.getElementById('wrap').scrollTop = 600; });
    await page.waitForTimeout(200);
    const state = JSON.parse(await load()(page));
    assert.equal(state.total, TOTAL, 'must accumulate all rows across screens');
    assert.equal(state.filled, TOTAL);
    assert.equal(state.missing.length, 0);
    assert.equal(state.sources.length, TOTAL);
    assert.equal(state.sources[0].src, '/row-1.jpg');
    assert.equal(state.sources[TOTAL - 1].src, '/row-' + TOTAL + '.jpg');
    assert.equal(await page.evaluate(() => document.getElementById('wrap').scrollTop), 600,
      'audit must restore the original scroll position');
  } finally {
    await browser.close();
  }
});

test('foreground stolen mid-audit still collects all rows', async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: VIEW_H}});
    await boot(page);
    // 第一次向下滚动后立刻"被切后台"（模拟其他 worker 的 ensureFront 抢前台），
    // 600ms 后自动"回到前台"——兜底模拟其他 worker 完成后不再抢。
    await page.evaluate(() => {
      const wrap = document.getElementById('wrap');
      wrap.addEventListener('scroll', () => {
        if (wrap.scrollTop > 0 && !window.__qnStolen) {
          window.__qnStolen = true;
          window.__qnHidden = true;
          setTimeout(() => { window.__qnAutoBack = true; }, 600);
        }
      });
    });
    const state = JSON.parse(await load()(wrapPage(page)));
    assert.equal(state.total, TOTAL, 'hidden mid-audit must not truncate the scan to one screen');
  } finally {
    await browser.close();
  }
});

test('stays hidden the whole time degrades gracefully instead of hanging', async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: VIEW_H}});
    await boot(page);
    // bringToFront 也抢不回前台（恢复上限 6 次）：应耗尽恢复次数后返回，
    // 而不是卡满 80 轮 guard 烧穿 40s 超时。
    const page2 = wrapPage(page);
    await page.evaluate(() => {
      document.getElementById('wrap').addEventListener('scroll', () => { window.__qnHidden = true; });
    });
    const started = Date.now();
    const state = JSON.parse(await load()(page2));
    const elapsed = Date.now() - started;
    assert.equal(await page.evaluate(() => document.visibilityState), 'hidden');
    assert.ok(elapsed < 25000, 'recovery cap must bound the scan, took ' + elapsed + 'ms');
    assert.ok(state.total >= 1);
  } finally {
    await browser.close();
  }
});

test('table without a scroll container reports visible cells only', async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage({viewport: {width: 1200, height: VIEW_H}});
    await page.setContent(`<html><body>
      <table><tr><td id="0-custom_-1"><img class="image-item" src="/a.jpg"></td></tr>
      <tr><td id="1-custom_-1"></td></tr></table></body></html>`);
    const state = JSON.parse(await load()(page));
    assert.equal(state.total, 2);
    assert.equal(state.filled, 1);
    assert.deepEqual(state.missing, [2]);
  } finally {
    await browser.close();
  }
});
