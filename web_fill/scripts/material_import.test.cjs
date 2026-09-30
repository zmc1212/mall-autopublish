const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

const row = {name:'蓝杆', sku_id:'6141276652863', price:'6.90', stock:'10', search_title:'-', image:'https://img.alicdn.com/blue.jpg'};
const second = {...row, name:'白杆', sku_id:'6141276652864', image:'https://img.alicdn.com/white.jpg'};
function script(payload) {
  return eval('(' + fs.readFileSync(path.join(__dirname, 'material_import.js'), 'utf8').replace('/*PAYLOAD*/', JSON.stringify(payload)) + ')');
}
function pageWithRows(rows) {
  let clicks = 0, reloads = 0;
  const locator = {count:async () => 0, waitFor:async () => {}, getByRole:() => locator, click:async () => {clicks++;}};
  return {
    url:() => 'https://myseller.taobao.com/home.htm/SellManage/all_skucenter?from=qn_entry',
    locator:() => locator, getByRole:() => locator,
    evaluate:async (fn, args) => typeof args === 'string' ? fn(args) : args ? {ready:true, rows} : false,
    reload:async () => {reloads++;}, waitForTimeout:async () => {},
    clicks:() => clicks, reloads:() => reloads,
  };
}

test('verification reloads and requires per-SKU persisted image identity', async () => {
  const page = pageWithRows([row, second]);
  const result = JSON.parse(await script({phase:'verify', item_id:'1085270103015', baseline:[row, second], preview:[row, second]})(page));
  assert.equal(result.rows.length, 2);
  assert.equal(page.reloads(), 1);
  assert.equal(page.clicks(), 0);
});

test('same image set with swapped SKU assignments is not success', async () => {
  const page = pageWithRows([{...row, image:second.image}, {...second, image:row.image}]);
  await assert.rejects(script({phase:'verify', item_id:'1085270103015', baseline:[row, second], preview:[row, second]})(page),
    /已入库；2 个 SKU 均有搜索主图，但 2 个图片地址不同且内容无法核验.*SKU 6141276652863.*未重新上传或采纳/);
  assert.equal(page.clicks(), 0);
});

function mockImages(page, contents) {
  const requests = [];
  page.request = {get:async url => {
    requests.push(url);
    return {ok:() => true, headers:() => ({'content-type':'image/jpeg'}),
      body:async () => Buffer.from(contents[url]), dispose:async () => {}};
  }};
  return requests;
}

test('different CDN addresses with identical bytes pass per-SKU verification', async () => {
  const actual = {...row, image:'https://img.alicdn.com/copied-blue.jpg'};
  const page = pageWithRows([actual]);
  mockImages(page, {[row.image]:'same image', [actual.image]:'same image'});
  const result = JSON.parse(await script({phase:'verify', item_id:'1085270103015', baseline:[row], preview:[row]})(page));
  assert.equal(result.imageVerification, 'identical-content');
  assert.equal(page.clicks(), 0);
});

test('content verification works in CLI sandbox without a global URL', async () => {
  const actual = {...row, image:'https://img.alicdn.com/octet-stream.jpg'};
  const page = pageWithRows([actual]);
  mockImages(page, {[row.image]:Buffer.from([0xff,0xd8,0xff,0xd9]), [actual.image]:Buffer.from([0xff,0xd8,0xff,0xd9])});
  const vm = require('node:vm');
  const payload = {phase:'verify', item_id:'1085270103015', baseline:[row], preview:[row]};
  const run = vm.runInNewContext('(' + fs.readFileSync(path.join(__dirname, 'material_import.js'), 'utf8')
    .replace('/*PAYLOAD*/', JSON.stringify(payload)) + ')', {});
  // evaluate executes in the page realm, independently of the CLI sandbox.
  const evaluate = page.evaluate;
  page.evaluate = (fn, args) => typeof args === 'string'
    ? new Function('value', 'return (' + fn.toString() + ')(value)')(args)
    : evaluate(fn, args);
  const result = JSON.parse(await run(page));
  assert.equal(result.imageVerification, 'identical-content');
});

test('different bytes remain paused with an exact SKU diagnosis', async () => {
  const actual = {...row, image:second.image};
  const page = pageWithRows([actual]);
  mockImages(page, {[row.image]:'blue image', [second.image]:'white image'});
  await assert.rejects(script({phase:'verify', item_id:'1085270103015', baseline:[row], preview:[row]})(page),
    /1 个与采纳前确认页的图片内容不一致：蓝杆（SKU 6141276652863）/);
  assert.equal(page.clicks(), 0);
});

test('content verification never fetches unexpected hosts', async () => {
  const actual = {...row, image:'https://example.com/image.jpg'};
  const page = pageWithRows([actual]);
  const requests = mockImages(page, {[row.image]:'blue image'});
  await assert.rejects(script({phase:'verify', item_id:'1085270103015', baseline:[row], preview:[row]})(page), /内容无法核验/);
  assert.deepEqual(requests, [row.image]);
});

test('verification distinguishes missing images from different image assignments', async () => {
  const page = pageWithRows([row, {...second, image:''}]);
  await assert.rejects(script({phase:'verify', item_id:'1085270103015', baseline:[row, second], preview:[row, second]})(page),
    /已入库；1\/2 个 SKU 已有搜索主图，1 个缺图：白杆（SKU 6141276652864）/);
  assert.equal(page.clicks(), 0);
});

test('verification distinguishes unread SKU rows from missing uploads', async () => {
  const page = pageWithRows([]);
  await assert.rejects(script({phase:'verify', item_id:'1085270103015', baseline:[row, second], preview:[row, second]})(page),
    /已入库；刷新后仅读取到 0\/2 个 SKU.*核验未完成/);
  assert.equal(page.clicks(), 0);
});

test('adoption rejects AI price changes before clicking', async () => {
  const changed = {...row, price:'99.00'};
  const page = pageWithRows([changed]);
  await assert.rejects(script({phase:'adopt', item_id:'1085270103015', baseline:[row], preview:[changed]})(page), /价格变化/);
  assert.equal(page.clicks(), 0);
});

test('adoption rejects additional SKUs before clicking', async () => {
  const page = pageWithRows([row, second]);
  await assert.rejects(script({phase:'adopt', item_id:'1085270103015', baseline:[row], preview:[row, second]})(page), /数量不符/);
  assert.equal(page.clicks(), 0);
});

test('adoption preserves attributes and merchant code, including missing fields', async () => {
  const original = {...row, attributes_text:'书写粗细: 0.5mm', merchant_code:'SKU-1'};
  for (const changed of [{...original, attributes_text:'-'}, {...original, merchant_code:'SKU-2'}, row]) {
    const page = pageWithRows([changed]);
    await assert.rejects(script({phase:'adopt', item_id:'1085270103015',
      baseline:[original], preview:[changed]})(page), /属性或商家编码/);
    assert.equal(page.clicks(), 0);
  }
});

test('verification pauses on captcha instead of clicking or reloading', async () => {
  const page = pageWithRows([row]);
  page.evaluate = async () => true;
  await assert.rejects(script({phase:'verify'})(page), /安全验证/);
  assert.equal(page.reloads(), 0);
  assert.equal(page.clicks(), 0);
});
