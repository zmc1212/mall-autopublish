const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');

test('plain attributes use Playwright evaluate arguments and preserve radio attributes', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://attributes.test/**', route => route.fulfill({contentType: 'text/html', body:
      '<meta charset="utf-8">' +
      '<div class="next-form-item"><label class="next-form-item-label">尺寸</label><input id="size"></div>' +
      '<div class="next-form-item"><label class="next-form-item-label">概率描述</label><textarea id="probability"></textarea></div>' +
      '<div class="sell-horizon-layout-info-wrapper"><span class="sell-component-info-wrapper-label">采购地</span>' +
      '<label><input type="radio" checked>中国内地（大陆）</label></div>' +
      '<span class="next-form-item-label">其他一</span><span class="next-form-item-label">其他二</span>' +
      '<span class="next-form-item-label">其他三</span>'
    }));
    await page.goto('http://attributes.test/sell/v2/publish.htm');
    await page.evaluate(() => {
      window.changes = [];
      for (const kind of ['input', 'change'])
        document.addEventListener(kind, event => window.changes.push([kind, event.target.id, event.target.value]));
    });
    const payload = {attributes: {'尺寸': '10 cm', '概率描述': '随机款式', '采购地': '中国内地（大陆）'}};
    const code = fs.readFileSync(path.join(__dirname, 'attributes.js'), 'utf8')
      .replace('/*PAYLOAD*/', JSON.stringify(payload))
      .replace('/*HELPERS*/', fs.readFileSync(path.join(__dirname, '_helpers.inc.js'), 'utf8'));
    const result = JSON.parse(await new Function('return (' + code + ')')()(page));
    assert.deepEqual(result.missing, []);
    assert.equal(await page.locator('#size').inputValue(), '10 cm');
    assert.equal(await page.locator('#probability').inputValue(), '随机款式');
    assert.equal(await page.locator('input[type=radio]').isChecked(), true);
    assert.ok(result.log.includes('采购地=already'));
    const changes = await page.evaluate(() => window.changes);
    for (const id of ['size', 'probability']) {
      assert.ok(changes.some(entry => entry[0] === 'input' && entry[1] === id));
      assert.ok(changes.some(entry => entry[0] === 'change' && entry[1] === id));
    }
  } finally {
    await browser.close();
  }
});
