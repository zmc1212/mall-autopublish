const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const source = fs.readFileSync(__dirname + '/probe_state.js', 'utf8')
  .replace('/*PAYLOAD*/', JSON.stringify({waitForReady: true}))
  .replace('/*HELPERS*/', () => helpers);
const probe = eval('(' + source + ')');
const deleted = '<h2>宝贝发布异常</h2><p>当前商品已被删除无法编辑！</p>';

async function fixture(body, run) {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    // The customer's error page is reproduced locally; no Taobao requests.
    await page.route('https://item.upload.taobao.com/**', route => route.fulfill({
      contentType: 'text/html', body: '<meta charset="utf-8">' + body}));
    await page.goto('https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1087733915888');
    await run(page);
  } finally { await browser.close(); }
}

test('customer deleted-item page returns evidence without the 15-second form timeout or clicks', async () => {
  await fixture(deleted + '<a href="/router/publish.htm">点击这里重新选择其他类目</a>', async page => {
    await page.evaluate(() => { window.clicks = 0; document.addEventListener('click', () => window.clicks++); });
    const state = JSON.parse(await probe(page));
    assert.equal(state.pageError.code, 'item_deleted');
    assert.equal(state.pageError.message, '当前商品已被删除无法编辑！');
    assert.equal(state.title, '');
    assert.match(state.href, /itemId=1087733915888$/);
    assert.equal(await page.evaluate(() => window.clicks), 0);
  });
});

test('a normal editable product mentioning the deleted-page text is not rejected', async () => {
  await fixture('<input placeholder="最多30个汉字" value="HelloKitty苹果派对">' + deleted, async page => {
    const state = JSON.parse(await probe(page));
    assert.equal(state.title, 'HelloKitty苹果派对');
    assert.equal(state.pageError, null);
  });
});

test('hidden deleted-page remnants do not interrupt asynchronous form loading', async () => {
  await fixture('<div hidden>' + deleted + '</div><input aria-label="30个汉字">', async page => {
    await page.evaluate(() => setTimeout(() => { document.querySelector('input').value = '商品加载完成'; }, 600));
    const state = JSON.parse(await probe(page));
    assert.equal(state.title, '商品加载完成');
    assert.equal(state.pageError, null);
  });
});

test('deleted error arriving after navigation is detected without waiting for a title', async () => {
  await fixture('加载中', async page => {
    await page.evaluate(html => setTimeout(() => { document.body.innerHTML = html; }, 600), deleted);
    const state = JSON.parse(await probe(page));
    assert.equal(state.pageError.code, 'item_deleted');
  });
});
