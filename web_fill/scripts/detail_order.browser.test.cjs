const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const source = fs.readFileSync(__dirname + '/details.js', 'utf8');

test('detail binding resets upload preselection before inserting in file order', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    for (const preselected of [[5], [8], [8, 3, 5], []]) {
      const names = Array.from({length: 9}, (_, i) => `详情${String(i + 1).padStart(2, '0')}.jpg`);
      await page.setContent('<div id="lite-decoration-editor"></div><iframe width="600" height="400"></iframe>');
      const frame = page.frames()[1];
      await frame.setContent(names.map((name, i) => `<div class="item pic"><img>
        <input type="checkbox" data-name="${name}" ${preselected.includes(i + 1) ? 'checked' : ''}>${name}</div>`).join('') +
        '<button class="btn btn-blue">确定</button>');
      await frame.evaluate(initial => {
        window.queue = initial;
        document.addEventListener('change', event => {
          const name = event.target.dataset.name;
          window.queue = window.queue.filter(item => item !== name);
          if (event.target.checked) window.queue.push(name);
        });
        document.querySelector('button').onclick = () => {
          const editor = parent.document.querySelector('#lite-decoration-editor');
          for (const name of window.queue) {
            const img = parent.document.createElement('img');
            img.width = 120;
            img.dataset.name = name;
            editor.append(img);
          }
          parent.document.querySelector('iframe').style.display = 'none';
        };
      }, preselected.map(i => names[i - 1]));
      const fixtureHelpers = helpers.replace('const sleep = (ms) => page.waitForTimeout(ms);',
        'const sleep = () => page.waitForTimeout(0);') + `
        function pictureSpaceFrame() { return page.frames()[1]; }
        async function dismissKnow() {}
        async function assertNoSecurityChallenge() {}
        async function waitUploadResultClosed() { return 'CLOSED'; }
      `;
      const run = new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify({phase: 'bind', names}))
        .replace('/*HELPERS*/', () => fixtureHelpers) + ')')();
      const result = JSON.parse(await run(page));
      assert.equal(result.after.imgs, names.length);
      assert.equal(result.after.dialog, false);
      assert.deepEqual(await page.locator('#lite-decoration-editor img').evaluateAll(imgs =>
        imgs.map(img => img.dataset.name)), names, `preselected: ${preselected}`);
    }
    await page.setContent('<div class="item pic"><img><input type="checkbox" checked disabled></div>');
    const clear = new Function('page', 'frame', helpers + 'return clearPictureSpaceSelection(frame);');
    await assert.rejects(clear(page, page), /PAUSE:.*预选状态无法清除/);
  } finally { await browser.close(); }
});

test('detail binding reopens the picker when the library deduplicates identical files', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    const hash = 'qn_ad2db96f233a58c527f746b9';
    for (const failure of ['', 'missing-image', 'dialog-open']) {
    const hashes = ['cad0fd62e02f5d6abcf3580e', '26bf7156bdb732cd8aebad27',
      '8698db8124c55d90daaf30a7', 'bd8f3c69d98bfe60ba58a1dd',
      'ad2db96f233a58c527f746b9', 'b0298c9442e265deba18685f',
      'ad2db96f233a58c527f746b9'];
    const names = hashes.map((value, i) => `qn_${value}_详情0${i + 1}.jpg`);
    const assets = hashes.slice(0, 6).map((value, i) =>
      `qn_${value}_${i === 5 ? '详情' : '方图主图'}0${i + 1}.jpg`);
    await page.setContent('<button class="m-editor-content-footer-add">图片</button>'
      + '<div id="lite-decoration-editor"></div><iframe style="display:none" width="600" height="400"></iframe>');
    await page.evaluate(() => { window.opens = 0; });
    const frame = page.frames()[1];
    await frame.setContent('<div class="PicturesShow_list">'
      + assets.map(name => `<div class="item pic"><img><input type="checkbox">${name}</div>`).join('')
      + '</div>'
      + '<button class="btn btn-blue">确定</button>');
    await page.locator('button.m-editor-content-footer-add').evaluate(el => el.onclick = () => {
      window.opens = (window.opens || 0) + 1;
      const iframe = document.querySelector('iframe');
      iframe.style.display = 'block';
    });
    await frame.evaluate(failure => {
      window.queue = [];
      document.addEventListener('change', event => {
        const card = event.target.closest('.item.pic');
        if (event.target.checked) window.queue.push(card.innerText.trim());
        else window.queue = window.queue.filter(item => item !== card.innerText.trim());
      });
      document.querySelector('button').onclick = () => {
        const editor = parent.document.querySelector('#lite-decoration-editor');
        if (failure === 'dialog-open') return;
        for (const name of window.queue) {
          if (failure === 'missing-image') continue;
          const img = parent.document.createElement('img');
          img.width = 120; img.dataset.name = name; editor.append(img);
        }
        window.queue = [];
        document.querySelectorAll('input').forEach(el => el.checked = false);
        parent.document.querySelector('iframe').style.display = 'none';
      };
    }, failure);
    const fixtureHelpers = helpers.replace('const sleep = (ms) => page.waitForTimeout(ms);',
      'const sleep = () => page.waitForTimeout(0);') + `
      function pictureSpaceFrame() { return page.frames()[1]; }
      async function dismissKnow() {}
      async function assertNoSecurityChallenge() {}
      async function waitUploadResultClosed() { return 'CLOSED'; }
      async function uploadContextVisible(ctx) { return ctx === page || await ctx.evaluate(() => {
        const el = window.frameElement; return !el || getComputedStyle(el).display !== 'none';
      }); }
    `;
    const run = new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify({phase: 'bind', names}))
      .replace('/*HELPERS*/', () => fixtureHelpers) + ')')();
    if (failure) {
      await assert.rejects(run(page), /PAUSE:详情图分段写入未确认/);
      assert.equal(await page.evaluate(() => window.opens), 1, 'Do not reopen after an uncertain commit');
    } else {
      const result = JSON.parse(await run(page));
      assert.equal(result.after.imgs, names.length);
      assert.equal(result.after.dialog, false);
      assert.deepEqual(await page.locator('#lite-decoration-editor img').evaluateAll(imgs =>
        imgs.map(img => img.dataset.name)), [...assets, hash + '_方图主图05.jpg']);
      assert.equal(await page.evaluate(() => window.opens), 2);
    }
    }
  } finally { await browser.close(); }
});
