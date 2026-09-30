const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');

test('verification searches off-page reused assets by hash and preserves genuine misses', async () => {
  const old = 'qn_5f8dbf429a1fc797ab4e11e6_详情22.png';
  const absent = 'qn_aaaaaaaaaaaaaaaaaaaaaaaa_详情23.png';
  const recent = 'qn_bbbbbbbbbbbbbbbbbbbbbbbb_详情21.jpg';
  const searchLog = [];
  const frame = {};
  const verify = new Function('frame', 'names', 'searchLog', helpers + `
    let listed = ['${recent}'];
    listSucaiPics = async () => listed;
    searchSucai = async (_frame, query) => {
      searchLog.push(query);
      listed = query === 'qn_5f8dbf429a1fc797ab4e11e6'
        ? ['qn_5f8dbf429a1fc797ab4e11e6_详情12.png'] : [];
      return listed.length ? 'OK' : 'STALE';
    };
    return missingSucaiNames(frame, names, 1);
  `);
  assert.deepEqual(await verify(frame, [recent, old, absent], searchLog), [absent]);
  assert.deepEqual(searchLog, ['qn_5f8dbf429a1fc797ab4e11e6', 'qn_aaaaaaaaaaaaaaaaaaaaaaaa']);
});

test('detail verification and binding reuse identical content despite name and extension changes', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const hash = 'qn_7d2d8578e802045afde0e911';
    const wanted = hash + '_详情01.png';
    await page.setContent(`<div class="item pic"><img><input id="wrong" type="checkbox">
      ${hash}0_详情01.png</div><div class="item pic"><img><input id="right" type="checkbox">
      <span title="${hash}_宝贝主图01.jpg">qn_…</span></div>`);
    const list = new Function('frame', helpers + 'return listPictureSpaceNames(frame);');
    const missing = new Function('listed', 'names', helpers + 'return missingPictureNames(listed, names);');
    const pick = new Function('frame', 'names', helpers + 'return pickPictureSpaceCards(frame, names);');
    const listed = await list(page);
    assert.deepEqual(missing(listed, [wanted]), []);
    assert.deepEqual(missing([hash + '0_详情01.png'], [wanted]), [wanted]);
    assert.deepEqual(missing(['qn_aaaaaaaaaaaaaaaaaaaaaaaa_详情01.png'], [wanted]), [wanted]);
    assert.deepEqual(missing(['详情01.jpg'], ['详情01.png']), ['详情01.png']);
    assert.equal((await pick(page, [wanted]))[0].ok, true);
    assert.equal(await page.locator('#right').isChecked(), true);
    assert.equal(await page.locator('#wrong').isChecked(), false);
    assert.equal((await pick(page, [wanted]))[0].alreadySelected, true);
  } finally { await browser.close(); }
});

test('material selection keeps an upload-preselected image and never toggles twice', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.setContent('<iframe></iframe>');
    const frame = page.frames()[1];
    await frame.setContent(`<div class=PicList_PicturesShow_main-show__QVvZn>
        <img><label><input id=first type=checkbox>first.jpg</label></div>
      <div class=PicList_PicturesShow_main-show__QVvZn>
        <img><label><input id=last type=checkbox checked>last.png</label></div>
      <div class=PicList_PicturesShow_main-show__QVvZn>
        <img><label><input id=blocked type=checkbox disabled>blocked.jpg</label></div>
      <script>window.changes=[];document.addEventListener('change',e=>window.changes.push(e.target.id));</script>`);
    const pick = new Function('page', 'frame', 'names', helpers +
      'return pickPictureSpaceCards(frame, names);');
    const main = new Function('page', 'frame', 'name', helpers +
      'return clickSucaiCard(frame, name, true);');
    const result = await pick(page, frame, ['first.jpg', 'last.png']);
    assert.equal(result[1].alreadySelected, true);
    await pick(page, frame, ['first.jpg', 'last.png']);
    assert.equal((await main(page, frame, 'last.png')).alreadySelected, true);
    assert.equal((await pick(page, frame, ['blocked.jpg']))[0].ok, false);
    assert.equal((await main(page, frame, 'blocked.jpg')).ok, false);
    assert.deepEqual(await frame.evaluate(() => window.changes), ['first']);
    assert.deepEqual(await frame.evaluate(() =>
      Array.from(document.querySelectorAll('input'), el => el.checked)), [true, true, false]);
    await frame.locator('#last').evaluate(el => el.closest('div').querySelector('img').src = 'https://fixture.test/last.png');
    const single = new Function('page', 'frame', 'name', helpers +
      'return clickSucaiCard(frame, name, true, true);');
    const chosen = await single(page, frame, 'last.png');
    assert.equal(chosen.src, 'https://fixture.test/last.png');
    assert.deepEqual(await frame.evaluate(() =>
      Array.from(document.querySelectorAll('input'), el => el.checked)), [false, true, false]);
  } finally {
    await browser.close();
  }
});

test('hash identity selects truncated names from title and rejects near matches', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const hash = 'qn_e7191c0ce2b71844cb9cf46c';
    await page.setContent(`<div class="PicList_PicturesShow_main-show__new"><img src="/wrong.jpg">
      <input id="wrong" type="checkbox"><span title="${hash}0.jpg">qn_…</span></div>
      <div class="PicList_PicturesShow_main-show__new"><img src="/correct.jpg">
      <input id="correct" type="checkbox"><span title="${hash}_颜色08-【两个月推荐】1支笔 10支晨光笔芯.jpg">qn_…</span></div>`);
    const pick = new Function('page', 'frame', 'name', helpers + 'return clickSucaiCard(frame, name, true, true);');
    const result = await pick(page, page, hash + '.jpg');
    const listed = await new Function('page', 'frame', helpers + 'return listSucaiPics(frame);')(page, page);
    assert.ok(listed.some(label => label.includes(hash + '_颜色08')));
    assert.equal(result.ok, true);
    assert.equal(result.src, '/correct.jpg');
    assert.equal(await page.locator('#correct').isChecked(), true);
    assert.equal(await page.locator('#wrong').isChecked(), false);
  } finally { await browser.close(); }
});

test('duplicate content hashes select distinct uploaded filenames in detail order', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const hash = 'qn_ad2db96f233a58c527f746b9';
    await page.setContent(`<div class="item pic"><img><input id="five" type="checkbox">
      ${hash}_详情05.jpg</div><div class="item pic"><img><input id="seven" type="checkbox">
      ${hash}_详情07.jpg</div>`);
    const pick = new Function('frame', 'names', helpers +
      'return pickPictureSpaceCards(frame, names);');
    assert.equal((await pick(page, [hash + '_详情05.jpg']))[0].ok, true);
    assert.equal((await pick(page, [hash + '_详情07.jpg']))[0].ok, true);
    assert.equal(await page.locator('#five').isChecked(), true);
    assert.equal(await page.locator('#seven').isChecked(), true);
  } finally { await browser.close(); }
});

test('detail cards allow icon images and nested wrappers without selecting a neighbour or hidden card', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const hash = 'qn_cad0fd62e02f5d6abcf3580e';
    await page.setContent(`<div class="PicturesShow_list">
      <div class="PicturesShow_card" style="display:none"><img><input id="hidden" type="checkbox">${hash}_详情01.jpg</div>
      <div class="PicturesShow_card"><img><input id="neighbour" type="checkbox">other.jpg</div>
      <div class="PicturesShow_wrapper"><div class="PicturesShow_card"><img src="/material.jpg"><img src="/icon.svg">
        <input id="target" type="checkbox" value="1221808846728672035"><span title="${hash}_方图主图01.jpg">qn_…</span></div></div></div>`);
    await page.locator('#target').evaluate(el => el.addEventListener('change', () => {
      el.closest('.PicturesShow_card').querySelector('img').src = '/loaded-material.jpg';
      el.closest('.PicturesShow_card').querySelector('span').textContent += ' 1280x1280';
    }));
    const pick = new Function('frame', 'names', helpers + 'return pickPictureSpaceCards(frame, names);');
    const result = (await pick(page, [hash + '_详情01.jpg']))[0];
    assert.equal(result.ok, true);
    assert.equal(result.n, 1, 'Nested wrappers describe one material');
    assert.equal(await page.locator('#target').isChecked(), true);
    assert.equal(await page.locator('#neighbour').isChecked(), false);
    assert.equal(await page.locator('#hidden').isChecked(), false);
  } finally { await browser.close(); }
});

test('detail selection waits for delayed state and reports rejected clicks without toggling again', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const pick = new Function('frame', 'names', helpers + 'return pickPictureSpaceCards(frame, names);');
    for (const accepted of [true, false]) {
      await page.setContent('<div class="item pic"><img><input type="checkbox">one.jpg</div>');
      await page.evaluate(accepted => {
        window.clicks = 0;
        document.querySelector('input').onclick = event => {
          window.clicks++;
          event.preventDefault();
          if (accepted) setTimeout(() => { document.querySelector('input').checked = true; }, 300);
        };
      }, accepted);
      const result = (await pick(page, ['one.jpg']))[0];
      assert.equal(result.ok, accepted);
      if (!accepted) assert.equal(result.reason, 'selection-unconfirmed');
      assert.equal(await page.evaluate(() => window.clicks), 1);
    }
    await page.setContent('<div class="item pic"><img>one.jpg</div>');
    assert.equal((await pick(page, ['one.jpg']))[0].reason, 'unsupported-card');
    assert.equal((await pick(page, ['absent.jpg']))[0].reason, 'not-found');
  } finally { await browser.close(); }
});
