const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const source = fs.readFileSync(__dirname + '/material_import.js', 'utf8');
const itemId = '1087608952245';
const url = 'https://myseller.taobao.com/home.htm/SellManage/all_skucenter';

test('existing-item repair authorization is scoped to one exact item and host', () => {
  const vm = require('node:vm');
  const helper = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
  const context = vm.createContext({PAYLOAD: {repairItemId: '1085482487262'}});
  vm.runInContext(helper, context);
  for (const [candidate, expected] of [
    ['https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1085482487262&fromAIPublish=true', false],
    ['https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1087608952245', true],
    ['https://evil.test/sell/v2/publish.htm?itemId=1085482487262', true],
    ['https://item.upload.taobao.com/sell/v2/publish.htm?itemId=1085482487262&itemId=other', true],
    ['https://item.upload.taobao.com/sell/v2/publish.htm', true],
  ]) assert.equal(context.unsafeUrl(candidate), expected);
});

async function fixture(run) {
  const browser = await chromium.launch({headless:true,
    executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    // Completely local HTML: no authenticated browser and no Taobao requests.
    await page.route('**/*', route => route.fulfill({contentType:'text/html', body:'<body></body>'}));
    await page.goto(url);
    await run(page);
  } finally { await browser.close(); }
}

function baseline(page) {
  const code = source.replace('/*PAYLOAD*/', JSON.stringify({phase:'baseline', item_id:itemId, title:'测试商品'}));
  return new Function('return (' + code + ')')()(page);
}

function readyGrid() {
  return `<button>素材批量导入</button><table><thead><tr>
    <th>SKU信息</th><th>搜索主图</th><th>搜索标题</th><th>价格</th><th>数量</th>
    </tr></thead><tbody><tr class=sku-group-header-row data-item-id=${itemId}>
    <td colspan=5 class=sku-group-header-title>测试商品</td></tr>
    <tr><td>黑色<br>ID: 6141276652863</td><td></td><td>-</td><td>6.90</td><td>10</td></tr>
    </tbody></table>`;
}

function emptyDrawer(extra = '') {
  return `<div role=dialog class="next-drawer material-batch-import-drawer">
    <h1>素材批量导入</h1><div class=material-batch-upload-zone>
    <input type=file webkitdirectory></div>${extra}
    <button disabled>确认上传</button><button onclick="window.closedCount++;this.closest('[role=dialog]').remove()">取消</button></div>`;
}

test('empty importer and read-only template popup close before baseline without uploading', async () => {
  await fixture(async page => {
    await page.setContent(readyGrid() + emptyDrawer() + `<div role=dialog><h1>下载模版</h1>
      <button onclick="window.closedCount++;this.parentElement.remove()">取消</button></div>`);
    await page.evaluate(() => { window.closedCount=0; });
    const result = JSON.parse(await baseline(page));
    assert.equal(result.rows.length, 1);
    assert.equal(await page.evaluate(() => window.closedCount), 2);
    assert.equal(await page.getByRole('dialog').count(), 0);
  });
});

test('selected files, progress, preview and unknown importer must be preserved', async () => {
  await fixture(async page => {
    for (const extra of ['<img src="selected.jpg">', '<div role=progressbar>上传中</div>',
      '<table><tr><td>素材导入确认</td></tr></table>', '<div>正在识别</div>']) {
      await page.setContent(readyGrid() + emptyDrawer(extra));
      await assert.rejects(baseline(page), /保留页面和断点/);
      assert.equal(await page.getByRole('dialog').count(), 1);
    }
    await page.setContent(readyGrid() + '<div role=dialog class="next-drawer material-batch-import-drawer">未知状态</div>');
    await assert.rejects(baseline(page), /保留页面和断点/);
    await page.setContent(readyGrid() + emptyDrawer());
    await page.evaluate(() => {
      const dt = new DataTransfer(); dt.items.add(new File(['image'], 'sku.jpg'));
      document.querySelector('input[type=file]').files = dt.files;
    });
    await assert.rejects(baseline(page), /保留页面和断点/);
    assert.equal(await page.getByRole('dialog').count(), 1);
  });
});

test('baseline navigates to virtualized target without selecting or uploading', async () => {
  await fixture(async page => {
    await page.setContent(`<button id=upload>素材批量导入</button>
      <div class=sku-table-item><input type=checkbox>
        <span class=sku-table-item-id>商品ID ${itemId}</span></div><div id=grid></div>`);
    await page.evaluate(id => {
      window.actions = [];
      document.querySelector('#upload').onclick = () => window.actions.push('upload');
      document.querySelector('input').onchange = () => window.actions.push('selection');
      document.querySelector('.sku-table-item-id').onclick = () => {
        window.actions.push('navigate');
        document.querySelector('#grid').innerHTML = `<table>
          <thead><tr><th>SKU信息</th><th>搜索主图</th><th>搜索标题</th><th>价格</th><th>数量</th></tr></thead>
          <tbody><tr class=sku-group-header-row data-item-id=${id}>
            <td colspan=5 class=sku-group-header-title>测试商品</td></tr>
          <tr><td>黑色<br>ID: 6141276652863</td><td></td><td>-</td><td>6.90</td><td>10</td></tr></tbody></table>`;
      };
    }, itemId);
    const result = JSON.parse(await baseline(page));
    assert.equal(result.rows.length, 1);
    assert.equal(result.rows[0].sku_id, '6141276652863');
    assert.equal(result.rows[0].image, '');
    assert.deepEqual(await page.evaluate(() => window.actions), ['navigate']);
    assert.equal(await page.locator('input').isChecked(), false);
  });
});

test('the exact frequency and slider prompt prevents all baseline actions', async () => {
  await fixture(async page => {
    await page.setContent('<button>素材批量导入</button><div>操作过于频繁，请滑动验证码</div>');
    await page.evaluate(() => { window.clicks=0; document.onclick=()=>window.clicks++; });
    await assert.rejects(baseline(page), /安全验证阻断/);
    assert.equal(await page.evaluate(() => window.clicks), 0);
  });
});

test('server probe reads the nested checked radio without modifying the form', async () => {
  await fixture(async page => {
    await page.setContent('<label class=next-radio-wrapper><input type=radio checked>放入仓库</label>');
    const script = fs.readFileSync(__dirname + '/probe_state.js', 'utf8')
      .replace('/*PAYLOAD*/', '{}').replace('/*HELPERS*/', '');
    const state = JSON.parse(await new Function('return (' + script + ')')()(page));
    assert.deepEqual(state.warehouse, [{t:'放入仓库', checked:true}]);
    assert.equal(await page.locator('input').isChecked(), true);
  });
});

test('search-main thumbnails never count as specification images', async () => {
  await fixture(async page => {
    await page.setContent(`<table><thead><tr><th>SKU搜索主图</th><th>商品规格</th><th>价格</th><th>库存</th></tr></thead>
      <tbody><tr><td><img width=40 height=40 src="search.jpg"></td>
      <td id="0-custom_-1"><input value="黑色"></td><td>6.9元</td><td>10件</td></tr></tbody></table>`);
    const script = fs.readFileSync(__dirname + '/probe_state.js', 'utf8')
      .replace('/*PAYLOAD*/', '{}').replace('/*HELPERS*/', '');
    const probe = async () => JSON.parse(await new Function('return (' + script + ')')()(page));
    assert.equal((await probe()).specImgs, 0);
    const status = fs.readFileSync(__dirname + '/spec_row_status.js', 'utf8');
    assert.deepEqual(JSON.parse(await new Function('return (' + status + ')')()(page)).missing, [1]);
    await page.locator('td[id="0-custom_-1"]').evaluate(el => {
      el.insertAdjacentHTML('beforeend', '<img class="image-item" width=40 height=40 src="spec.jpg">');
    });
    assert.equal((await probe()).specImgs, 1);
    assert.equal(JSON.parse(await new Function('return (' + status + ')')()(page)).filled, 1);
  });
});
