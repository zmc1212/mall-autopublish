const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const verify = new AsyncFunction('page', 'specs', helpers + '\nreturn verifySkuTableValues(page, specs);');
const specs = [{name: '单个随机盲盒', price: 9.9, stock: 20},
  {name: '端盒【12个盲盒，款式齐全】', price: 19.8, stock: 0}];

async function fixture(run, inputSpecs = specs) {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://sku-values.test/**', route => route.fulfill({contentType: 'text/html', body: '<meta charset="utf-8">'}));
    await page.goto('http://sku-values.test/publish');
    await page.setContent('<table><tbody>' + inputSpecs.map((s, i) => `<tr data-row="${i}"><td>${s.name}</td>
      <td><input data-field="price" value="${s.price}">元</td>
      <td><input type="hidden" value=""><input data-field="stock" value="">件</td></tr>`).join('') + '</tbody></table>');
    await run(page);
  } finally { await browser.close(); }
}

test('SKU values commit on blur, ignore hidden copies and retain zero stock', async () => {
  await fixture(async page => {
    await page.evaluate(() => {
      window.saved = {};
      for (const input of document.querySelectorAll('[data-field="stock"]')) {
        input.addEventListener('blur', () => { window.saved[input.closest('tr').dataset.row] = input.value; });
      }
    });
    assert.deepEqual(await verify(page, specs), []);
    assert.deepEqual(await page.evaluate(() => window.saved), {'0': '20', '1': '0'});
    assert.deepEqual(await page.locator('input[type=hidden]').evaluateAll(xs => xs.map(x => x.value)), ['', '']);
  });
});

test('Apple Party exact customer SKU data passes the complete SKU script without submitting', async () => {
  const customer = [{name: '单个随机盲盒', price: 9.9, stock: 20},
    {name: '端盒【12个盲盒，款式齐全】', price: 9.9, stock: 20}];
  await fixture(async page => {
    await page.evaluate(customer => {
      document.querySelectorAll('input[type=hidden]').forEach(x => x.remove());
      const wrap = document.createElement('div');
      wrap.className = 'common-wrap';
      wrap.innerHTML = '<div class="props-label">款式描述(2)</div>' + customer.map(x => `<input value="${x.name}">`).join('');
      document.body.prepend(wrap);
      for (const row of document.querySelectorAll('tr')) {
        const cell = row.insertCell();
        cell.innerHTML = '<input value="单品">';
      }
      window.submissions = 0;
      const submit = document.createElement('button');
      submit.textContent = '提交宝贝信息';
      submit.onclick = () => window.submissions++;
      document.body.append(submit);
      window.persistedStocks = {};
      for (const input of document.querySelectorAll('[data-field="stock"]')) {
        input.onblur = () => { window.persistedStocks[input.closest('tr').dataset.row] = input.value; };
      }
    }, customer);
    const source = fs.readFileSync(__dirname + '/skus.js', 'utf8');
    const payload = {title: 'HelloKitty苹果派对系列贴贴萌趣豆盲盒摆件萌粒潮玩女生桌面礼物',
      spec_name: '款式描述', skus: customer, skip_thickness: true};
    const run = new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify(payload)).replace('/*HELPERS*/', helpers) + ')')();
    const result = JSON.parse(await run(page));
    assert.equal(result.filled, 4);
    assert.deepEqual(await page.locator('[data-field="stock"]').evaluateAll(xs => xs.map(x => x.value)), ['20', '20']);
    assert.deepEqual(await page.evaluate(() => window.persistedStocks), {'0': '20', '1': '20'});
    assert.equal(await page.evaluate(() => window.submissions), 0);
  }, customer);
});

test('SKU values verify rows beyond the virtual table viewport', async () => {
  const virtualSpecs = Array.from({length: 4}, (_, i) => ({name: '虚拟规格' + i, price: 9.9, stock: 20 + i}));
  await fixture(async page => {
    await page.setContent('<div id="viewport" style="overflow-y:auto;height:100px"><div style="height:600px"><table style="position:sticky;top:0"><tbody></tbody></table></div></div>');
    await page.evaluate(input => {
      const viewport = document.querySelector('#viewport');
      window.saved = {};
      const render = () => {
        const start = Math.min(2, Math.floor(viewport.scrollTop / 200));
        document.querySelector('tbody').innerHTML = input.slice(start, start + 2).map(x => `<tr><td>${x.name}</td>
          <td><input data-name="${x.name}" data-field="price" value="${window.saved[x.name + 'price'] || ''}">元</td>
          <td><input data-name="${x.name}" data-field="stock" value="${window.saved[x.name + 'stock'] || ''}">件</td></tr>`).join('');
        for (const box of document.querySelectorAll('table input')) {
          box.onblur = () => { window.saved[box.dataset.name + box.dataset.field] = box.value; };
        }
      };
      viewport.onscroll = render;
      render();
    }, virtualSpecs);
    assert.deepEqual(await verify(page, virtualSpecs), []);
    for (const s of virtualSpecs) assert.equal(await page.evaluate(name => window.saved[name + 'stock'], s.name), String(s.stock));
    assert.equal(await page.locator('#viewport').evaluate(el => el.scrollTop), 0);
  });
});

test('SKU values re-resolve the correct row after a controlled table rebuild', async () => {
  await fixture(async page => {
    await page.evaluate(() => {
      const input = document.querySelector('[data-field="stock"]');
      input.addEventListener('blur', () => {
        const body = input.closest('tbody');
        const rows = [...body.children];
        rows[0].querySelector('[data-field="stock"]').value = '';
        body.innerHTML = rows.reverse().map(x => x.outerHTML).join('');
        window.rebuilt = true;
      }, {once: true});
    });
    assert.deepEqual(await verify(page, specs), []);
    assert.equal(await page.evaluate(() => window.rebuilt), true);
    assert.deepEqual(await page.locator('tr').evaluateAll(xs => xs.map(x => [
      x.dataset.row, x.querySelector('[data-field="stock"]').value]).sort()), [['0', '20'], ['1', '0']]);
  });
});

test('SKU values require a stable readback after a delayed component reset', async () => {
  await fixture(async page => {
    await page.locator('[data-field="stock"]').first().evaluate(input => {
      input.addEventListener('input', () => { setTimeout(() => { input.value = ''; }, 500); }, {once: true});
    });
    assert.deepEqual(await verify(page, specs), []);
    assert.equal(await page.locator('[data-field="stock"]').first().inputValue(), '20');
  });
});

test('SKU values refuse an empty table and a field that keeps rejecting the input', async () => {
  await fixture(async page => {
    await page.locator('[data-field="stock"]').first().evaluate(input => {
      input.oninput = () => { input.value = ''; };
    });
    const bad = await verify(page, specs);
    assert.ok(bad.some(x => x.name === specs[0].name && x.want === '20'));
    await page.setContent('<table></table>');
    assert.ok((await verify(page, specs)).length, 'missing fields must never pass verification');
  });
});
