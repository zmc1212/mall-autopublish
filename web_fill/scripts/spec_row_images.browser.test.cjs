const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const source = fs.readFileSync(__dirname + '/spec_row_images.js', 'utf8');
const load = payload => new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify(payload)).replace('/*HELPERS*/', helpers) + ')')();

for (const stale of [false, true, 'menu', 'covered', 'old-frame', 'nested-empty', 'nested-filled']) {
  test('replace populated SKU row, reject stale confirmation: ' + stale, async () => {
    const browser = await chromium.launch({headless: true, executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    try {
      const page = await browser.newPage();
      await page.route('**/*', route => {
        if (route.request().url().includes('old=1')) return route.fulfill({contentType: 'text/html', body: 'old picker'});
        if (route.request().url().includes('/sucai-selector')) {
          return route.fulfill({contentType: 'text/html; charset=utf-8', body: `<button>本地上传</button><input placeholder="搜索">
            <div class="PicList_PicturesShow_main-show__QVvZn"><img src="/new.jpg_100x100.jpg"><input type="checkbox">qn_target.jpg</div>
            <button class="Footer_selectOk">确定</button><script>
            document.querySelector('button.Footer_selectOk').onclick=()=>{
              ${stale === true ? '' : "let img=parent.document.querySelector('img.image-item');if(!img){img=parent.document.createElement('img');img.className='image-item';parent.document.querySelector('.main-content').append(img);}img.src='/new.jpg_320x320q80_.webp';"}
              parent.document.querySelector('.sell-component-image-v2-media-popup').remove();
            };</script>`});
        }
        return route.fulfill({contentType: 'text/html', body: '<html></html>'});
      });
      await page.goto('http://spec.test/publish');
      await page.setContent(`<table><tr><td id="0-custom_-1"><div class="main-content"><img class="image-item" src="/old.jpg"></div></td></tr></table>`);
      await page.locator('.main-content').evaluate((el, {mode}) => {
        el.style.cssText = 'width:80px;height:80px';
        if (mode === 'covered') {
          el.innerHTML = '';
          const cover = document.createElement('div');
          cover.style.cssText = 'position:fixed;inset:0;z-index:99';
          cover.onclick = () => { window.wrongRowClicked = true; };
          document.body.append(cover);
        }
        if (mode === 'old-frame') {
          const old = document.createElement('iframe');
          old.src = '/sucai-selector?handleId=test&old=1';
          old.style.display = 'none';
          document.body.append(old);
        }
        const open = () => {
        const popup = document.createElement('div');
        popup.className = 'sell-component-image-v2-media-popup';
        popup.innerHTML = '<iframe src="/sucai-selector?handleId=test"></iframe>';
        popup.style.cssText = 'position:fixed;z-index:100;top:100px;left:100px';
        document.body.append(popup);
        };
        if (mode === 'nested-empty' || mode === 'nested-filled') {
          el.innerHTML = '<div class="empty-container" aria-haspopup="true" aria-expanded="false" style="width:100%;height:100%">'
            + (mode === 'nested-empty' ? '<div class="image-empty"><div class="placeholder">图片</div></div>' : '<img class="image-item" src="/old.jpg">') + '</div>';
          el.firstChild.onclick = open;
        } else if (mode === 'menu') {
          el.onmouseenter = () => {
            if (document.querySelector('#replace')) return;
            const menu = document.createElement('button');
            menu.id = 'replace'; menu.textContent = '替换';
            menu.onclick = () => { menu.remove(); open(); };
            document.body.append(menu);
          };
        } else el.onclick = open;
      }, {mode: stale});
      if (stale === 'nested-empty' || stale === 'nested-filled') {
        await page.locator('.main-content').evaluate(el => el.click());
        assert.equal(await page.locator('.sell-component-image-v2-media-popup').count(), 0,
          'clicking the outer container must reproduce the reported failure');
      }
      const payload = {index: 0, image: 'qn_target.jpg', forceReplace: true};
      const opened = JSON.parse(await load({...payload, phase: 'open'})(page));
      assert.equal(opened.ready, true);
      assert.equal(opened.already, undefined);
      assert.equal(await page.evaluate(() => window.wrongRowClicked), undefined);
      if (stale === true) {
        await assert.rejects(load({...payload, phase: 'select'})(page), /选择后未写入SKU表格/);
      } else {
        const result = JSON.parse(await load({...payload, phase: 'select'})(page));
        assert.equal(result.verifiedBy, 'sku-row-source');
        assert.match(result.imageSrc, /new.jpg/);
      }
    } finally { await browser.close(); }
  });
}
