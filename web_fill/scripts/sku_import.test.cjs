const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

function script(payload) {
  const source = fs.readFileSync(path.join(__dirname, 'sku_import.js'), 'utf8')
    .replace('/*PAYLOAD*/', JSON.stringify(payload))
    .replace('/*HELPERS*/', 'const sleep = async () => {}; async function ensureFront() {} function unsafeUrl() { return false; } async function hideScenarioWidgets() {}');
  return eval(`(${source})`);
}

test('uploaded SKU template clicks confirm recognition before checking rows', async () => {
  let clicks = 0;
  const recognize = {
    last() { return this; },
    async count() { return 1; },
    async isVisible() { return true; },
    async isEnabled() { return true; },
    async click() { clicks += 1; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: () => recognize,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    evaluate: async () => clicks ? [{ text: '甲', values: ['甲'] }] : [],
    waitForTimeout: async () => {},
  };
  const result = JSON.parse(await script({ phase: 'verify', skus: [{ name: '甲' }] })(page));
  assert.equal(clicks, 1);
  assert.equal(result.recognitionClicked, true);
  assert.equal(result.verified, true);
});

test('resume reuses a selected SKU file in the recognition dialog', async () => {
  let evaluations = 0;
  const recognize = {
    last() { return this; },
    async count() { return 1; },
    async isVisible() { return true; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: () => recognize,
    evaluate: async () => ++evaluations === 1 ? [] : true,
  };
  const result = JSON.parse(await script({ phase: 'open', skus: [{ name: '甲' }] })(page));
  assert.equal(result.uploaded, true);
  assert.equal(result.via, 'pending-recognition');
});

test('resume continues from the recognized sales attribute dialog', async () => {
  let evaluations = 0;
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = { last() { return this; }, async count() { return 1; }, async isVisible() { return true; } };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    evaluate: async () => ++evaluations === 1 ? [] : true,
  };
  const result = JSON.parse(await script({ phase: 'open', skus: [{ name: '甲' }] })(page));
  assert.equal(result.uploaded, true);
  assert.equal(result.via, 'pending-add');
});

test('only the complete product specification dimension is added', async () => {
  let stage = 0;
  const clicks = [];
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = {
    last() { return this; },
    async count() { return stage === 0 ? 1 : 0; },
    async isVisible() { return true; },
    async isEnabled() { return true; },
    async click() { clicks.push('商品规格'); stage += 1; },
  };
  const dialog = {
    filter() { return this; }, last() { return this; },
    async count() { return stage === 0 ? 1 : 0; },
    async innerText() { return '批量导入 已成功识别1个销售属性 商品规格 已选择 2 个属性 甲 乙 在当前规格后添加'; },
    getByRole() { return { first() { return this; }, async count() { return 0; } }; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    locator: () => dialog,
    evaluate: async () => stage === 0 ? [] : [
      { text: '甲', values: ['甲'] }, { text: '乙', values: ['乙'] },
    ],
  };
  const result = JSON.parse(await script({ phase: 'verify',
    skus: [{ name: '甲' }, { name: '乙' }] })(page));
  assert.deepEqual(clicks, ['商品规格']);
  assert.equal(result.verified, true);
});

test('template does not include thickness dimension', async () => {
  let clicked = false;
  const clicks = [];
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = {
    last() { return this; },
    async count() { return 1; },
    async isVisible() { return true; },
    async isEnabled() { return true; },
    async click() { clicks.push('商品规格'); clicked = true; },
  };
  const dialog = {
    filter() { return this; },
    last() { return this; },
    async count() { return 1; },
    async innerText() { return '批量导入 已成功识别1个销售属性 商品规格 已选择 2 个属性 甲 乙 在当前规格后添加'; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    locator: () => dialog,
    evaluate: async () => clicked ? [
      { text: '甲', values: ['甲'] }, { text: '乙', values: ['乙'] },
    ] : [],
  };
  const result = JSON.parse(await script({ phase: 'verify',
    skus: [{ name: '甲' }, { name: '乙' }] })(page));
  assert.deepEqual(clicks, ['商品规格']);
  assert.equal(result.verified, true);
});

test('a partial product specification recognition is not added', async () => {
  let clicks = 0;
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = {
    last() { return this; }, async count() { return 1; },
    async isVisible() { return true; }, async isEnabled() { return true; },
    async click() { clicks += 1; },
  };
  const dialog = {
    filter() { return this; }, last() { return this; }, async count() { return 1; },
    async innerText() { return '批量导入 已成功识别1个销售属性 商品规格 已选择 1 个属性 甲 在当前规格后添加'; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=50012720',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    locator: () => dialog,
    evaluate: async () => [],
  };
  const result = JSON.parse(await script({ phase: 'verify',
    skus: [{ name: '甲' }, { name: '乙' }] })(page));
  assert.equal(clicks, 0);
  assert.match(result.error, /识别结果与模板不一致/);
});

test('chaowan multi-dimension recognition is accepted when all spec names appear', async () => {
  const clicks = [];
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = {
    last() { return this; },
    async count() { return 1; },
    async isVisible() { return true; },
    async isEnabled() { return true; },
    async click() { clicks.push('款式描述'); },
  };
  const dialog = {
    filter() { return this; }, last() { return this; }, async count() { return 1; },
    // 潮玩盲盒：款式描述 2 值 + 大小 1 值 = 已选择 3 个属性，不等于规格行数 2。
    async innerText() { return '批量导入 已成功识别2个销售属性 款式描述 大小 已选择 3 个属性 单个随机盲盒 端盒【12个盲盒，款式齐全】 正版发售 在当前规格后添加'; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=122692006',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    locator: () => dialog,
    evaluate: async () => clicks.length ? [
      { text: '单个随机盲盒 正版发售 9.9元 20件', values: ['单个随机盲盒', '正版发售'] },
      { text: '端盒【12个盲盒，款式齐全】 正版发售 9.9元 20件', values: ['端盒【12个盲盒，款式齐全】', '正版发售'] },
    ] : [],
  };
  const result = JSON.parse(await script({ phase: 'verify', spec_name: '款式描述',
    skus: [{ name: '单个随机盲盒' }, { name: '端盒【12个盲盒，款式齐全】' }] })(page));
  assert.deepEqual(clicks, ['款式描述']);
  assert.equal(result.verified, true);
});

test('chaowan recognition missing a spec name is not added', async () => {
  let clicks = 0;
  const hidden = { last() { return this; }, async count() { return 0; } };
  const add = {
    last() { return this; }, async count() { return 1; },
    async isVisible() { return true; }, async isEnabled() { return true; },
    async click() { clicks += 1; },
  };
  const dialog = {
    filter() { return this; }, last() { return this; }, async count() { return 1; },
    async innerText() { return '批量导入 已成功识别2个销售属性 款式描述 大小 已选择 3 个属性 单个随机盲盒 正版发售 在当前规格后添加'; },
  };
  const page = {
    url: () => 'https://item.upload.taobao.com/sell/v2/publish.htm?catId=122692006',
    getByText: (name) => name === '在当前规格后添加' ? add : hidden,
    getByRole: () => ({ last() { return this; }, async count() { return 0; } }),
    locator: () => dialog,
    evaluate: async () => [],
  };
  const result = JSON.parse(await script({ phase: 'verify', spec_name: '款式描述',
    skus: [{ name: '单个随机盲盒' }, { name: '端盒【12个盲盒，款式齐全】' }] })(page));
  assert.equal(clicks, 0);
  assert.match(result.error, /识别结果与模板不一致/);
});
