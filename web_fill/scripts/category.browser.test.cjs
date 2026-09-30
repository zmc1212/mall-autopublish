const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');
const source = fs.readFileSync(path.join(__dirname, 'category.js'), 'utf8');
const functions = source.slice(source.indexOf('  async function pickBrandOption'), source.indexOf('  const opened ='));
const search = new Function('page', 'sleep', functions + '\nreturn searchBrand;');

for (const scenario of ['delayed', 'alias', 'retry', 'missing', 'popup']) {
  test('brand selection: ' + scenario, async () => {
    const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    try {
      const page = await browser.newPage();
      await page.setContent(`<input role="combobox" placeholder="请输入"><input id="model" value="KEEP">
        <div class="next-overlay-wrapper"><ul role="listbox"></ul></div>
        <ul class="next-menu" style="display:none"><li>M＆G/晨光</li></ul>`);
      await page.evaluate(scenario => {
        let input = document.querySelector('input');
        if (scenario === 'popup') {
          input.readOnly = true;
          const searchInput = document.createElement('input');
          document.querySelector('.next-overlay-wrapper').prepend(searchInput);
          input = searchInput;
        }
        const list = document.querySelector('[role=listbox]');
        let searches = 0, timer;
        input.addEventListener('input', () => {
          clearTimeout(timer);
          list.innerHTML = '<li role="option">其他品牌</li>';
          if (!input.value) return;
          searches++;
          if (scenario === 'missing' || (scenario === 'alias' && input.value !== '晨光') || (scenario === 'retry' && searches < 3)) return;
          timer = setTimeout(() => {
            list.innerHTML += '<li role="option">M & G / 晨光</li>';
            list.lastChild.onclick = () => {
              window.selected = list.lastChild.textContent;
              document.querySelector('[role=combobox]').value = window.selected;
              list.innerHTML = '';
            };
          }, scenario === 'delayed' ? 1100 : 20);
        });
      }, scenario);
      const result = await search(page, ms => page.waitForTimeout(scenario === 'delayed' ? ms : 15))(page.getByRole('combobox'), 'M＆G/晨光');
      assert.equal(await page.locator('#model').inputValue(), 'KEEP');
      if (scenario === 'missing') {
        assert.match(result, /^NO_OPTION/);
        assert.equal(await page.evaluate(() => window.selected), undefined);
      } else {
        assert.match(result, /^CLICKED:/);
        assert.equal(await page.evaluate(() => window.selected), 'M & G / 晨光');
      }
    } finally { await browser.close(); }
  });
}

// Based on saved category accessibility snapshots (generic[title] options) and
// the saved options-search/options-item DOM, rather than invented ARIA options.
for (const scenario of ['custom', 'uncommitted', 'similar', 'disabled']) {
  test('custom category popup: ' + scenario, async () => {
    const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    try {
      const page = await browser.newPage();
      await page.setContent(`<input role="combobox" placeholder="请输入" readonly>
        <input id="model" value="KEEP">
        <div class="next-overlay-wrapper opened">
          <div class="options-search"><input></div><div class="options-content"></div>
        </div>
        <div class="next-overlay-wrapper" style="display:none"><div class="options-item" title="M＆G/晨光">M＆G/晨光</div></div>
        <div role="listbox"><div role="option" onclick="window.wrong=true">M＆G/晨光</div></div>`);
      await page.evaluate(scenario => {
        const input = document.querySelector('.options-search input');
        const content = document.querySelector('.options-content');
        input.addEventListener('input', () => {
          const label = scenario === 'similar' ? 'M&G/晨光文具' : 'M & G / 晨光';
          content.innerHTML = `<div class="options-item" title="${label}" ${scenario === 'disabled' ? 'aria-disabled="true"' : ''}>
            <div class="sell-o-info"><div class="info-content">${label}</div></div>
            <div class="rightComponent">品牌信息</div></div>`;
          content.firstChild.onclick = () => {
            window.clicked = true;
            if (scenario === 'uncommitted') return;
            document.querySelector('[role=combobox]').value = label;
            content.innerHTML = '';
          };
        });
      }, scenario);
      const result = await search(page, () => page.waitForTimeout(5))(page.getByRole('combobox'), 'M＆G/晨光');
      assert.equal(await page.locator('#model').inputValue(), 'KEEP');
      assert.equal(await page.evaluate(() => window.wrong), undefined);
      if (scenario === 'custom') {
        assert.match(result, /^CLICKED:.*:verified$/);
        assert.equal(await page.getByRole('combobox').inputValue(), 'M & G / 晨光');
      } else if (scenario === 'uncommitted') {
        assert.match(result, /^NOT_COMMITTED:/);
        assert.equal(await page.getByRole('combobox').inputValue(), '');
      } else {
        assert.match(result, /^NO_OPTION:input=晨光:options=/);
        assert.equal(await page.evaluate(() => window.clicked), undefined);
        assert.match(result, /:attempts=/);
      }
    } finally { await browser.close(); }
  });
}

test('whole category script selects custom brand, fills model and reaches publish form', async () => {
  const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://category.test/**', route => route.fulfill({contentType: 'text/html', body: '<meta charset="utf-8">中性笔'}));
    await page.goto('http://category.test/category.htm');
    await page.setContent(`<button role="tab">中性笔</button><div class="next-select">
      <input id="brand" role="combobox" placeholder="请输入" readonly></div>
      <input id="model" role="combobox" placeholder="请输入">
      <button id="next" disabled>确认，下一步</button>
      <div class="next-overlay-wrapper opened" hidden>
        <div class="options-search"><input></div><div class="options-content"></div>
      </div>`);
    await page.evaluate(() => {
      const popup = document.querySelector('.next-overlay-wrapper');
      const brand = document.querySelector('#brand');
      const model = document.querySelector('#model');
      const next = document.querySelector('#next');
      brand.onclick = () => { popup.hidden = false; };
      document.querySelector('.options-search input').oninput = () => {
        const content = document.querySelector('.options-content');
        content.innerHTML = '<div class="options-item" title="M＆G/晨光"><div class="info-content">M＆G/晨光</div></div>';
        content.firstChild.onclick = () => { brand.value = 'M＆G/晨光'; popup.hidden = true; };
      };
      model.oninput = () => { next.disabled = brand.value !== 'M＆G/晨光' || model.value !== 'AGPK3319'; };
      next.onclick = () => { window.location.href = '/sell/v2/publish.htm'; };
    });
    const code = source.replace('/*PAYLOAD*/', JSON.stringify({leaf: '中性笔', brand: 'M＆G/晨光', model: 'AGPK3319'}))
      .replace('/*HELPERS*/', `const sleep = () => page.waitForTimeout(10);
        const unsafeUrl = () => false;
        const dismissKnow = async () => {};
        const dismissBlockingDialogs = async () => {};
        const hideDraftOverlays = async () => {};
        const clickUnblocked = async el => el.click();`);
    const result = JSON.parse(await new Function('return (' + code + ')')()(page));
    assert.match(result.url, /\/sell\/v2\/publish.htm$/);
    assert.match(result.brandHow, /:verified$/);
    assert.equal(result.modelHow, 'combo-2');
  } finally { await browser.close(); }
});
