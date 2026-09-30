const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');
const load = name => new Function('return (' + fs.readFileSync(path.join(__dirname,name),'utf8').replace('/*PAYLOAD*/','{}').replace('/*HELPERS*/','') + ')')();

test('real Chromium: recover checkpoint after reload and recount remaining SKU images', async () => {
  const browser = await chromium.launch({headless:true, executablePath:process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const context = await browser.newContext();
    const page = await context.newPage();
    let rows = 21;
    await page.route('http://resume.test/**', route => route.fulfill({contentType:'text/html',body:
      '<meta charset="utf-8"><input placeholder="最多允许输入30个汉字（60字符）" value="恢复测试"><table><tbody>' +
      Array.from({length:21},(_,i)=>`<tr><td id="sku-${i}-custom_-1"><input value="规格${i}">${i<rows?'<img class="image-item" width="32" height="32" src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7">':''}</td><td>1元</td><td>1件</td><td><img class="image-item" src="search-main.jpg"></td></tr>`).join('') + '</tbody></table><div id="sell-field-mainImagesGroup"></div>'
    }));
    await page.goto('http://resume.test/publish');
    const code = fs.readFileSync(path.join(__dirname,'checkpoint.js'),'utf8').replace('/*PAYLOAD*/',JSON.stringify({key:'product-21',completed:['attributes','spec_images']}));
    await new Function('return ('+code+')')()(page);
    await page.reload();
    const probe = load('probe_state.js');
    const parse = value => typeof value === 'string' ? JSON.parse(value) : value;
    let state = parse(await probe(page));
    assert.equal(state.checkpoint.key,'product-21');
    assert.equal(state.specImgs,21);
    assert.equal(state.skuRows,21);
    assert.equal(state.mainImgs,0);
    assert.equal(state.skuNames[20],'规格20');
    rows = 20;
    await page.reload();
    state = parse(await probe(page));
    assert.equal(state.specImgs,20);
    await page.goto('http://resume.test/another-product');
    state = parse(await probe(page));
    assert.equal(state.checkpoint,null);
  } finally { await browser.close(); }
});

test('empty detail preview illustrations are not counted as uploaded product images', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://resume.test/**', route => route.fulfill({contentType: 'text/html', body: '<html></html>'}));
    await page.goto('http://resume.test/empty-details');
    await page.setContent('<div id="sell-field-descRepublicOfSell"><div style="display:none">' +
      '<img width="335"><img width="165"><img width="335"><img width="122"></div>' +
      '<div id="lite-decoration-editor"></div></div>');
    const probe = load('probe_state.js');
    assert.equal(JSON.parse(await probe(page)).detailImgs, 0);
    await page.locator('#lite-decoration-editor').evaluate(el => {
      el.innerHTML = '<img width="750"><img width="750">';
    });
    assert.equal(JSON.parse(await probe(page)).detailImgs, 2);
  } finally {
    await browser.close();
  }
});
