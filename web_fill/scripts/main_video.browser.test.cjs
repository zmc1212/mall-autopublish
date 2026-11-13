const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const source = fs.readFileSync(__dirname + '/main_video.js', 'utf8');
const load = payload => new Function('return (' + source.replace('/*PAYLOAD*/', JSON.stringify(payload))
  .replace('/*HELPERS*/', () => helpers) + ')')();
const name = 'qn_61c0d13d85ab11c3420d57fd_主视频.mp4';

for (const mode of ['truncated', 'collision', 'unrelated']) {
  test('video identity: ' + mode, async () => {
    const browser = await chromium.launch({headless: true,
      executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
    try {
      const page = await browser.newPage();
      const titles = mode === 'collision' ? ['qn_61c0d13d85ab11c34', 'qn_61c0d13d85ab11c34']
        : [mode === 'truncated' ? 'qn_61c0d13d85ab11c34' : 'qn_04badffc629a32688'];
      await page.route('**/*', route => route.request().url().includes('videoSelector.htm') ? route.fulfill({contentType: 'text/html; charset=utf-8', body:
        `<div class="VideoList--list">${titles.map(title => `<div class="VideoList--videoItem"><img title="${title}"><div class="VideoList--card-title">${title}</div><input type="checkbox"></div>`).join('')}</div>
         <button>确认上传 (0)</button><input type="file"><script>
         document.querySelectorAll('.VideoList--videoItem').forEach(el => el.onclick = () => {
           el.querySelector('input').checked = true;document.querySelector('button').textContent='确认上传 (1)';
         });
         document.querySelector('button').onclick=()=>{parent.document.querySelector('#sell-field-auctionVideos').innerHTML='<video src="/correct.mp4"></video>';};
         document.querySelector('input[type=file]').onchange=()=>{parent.window.dispatched=true};
         </script>`}) : route.fulfill({contentType:'text/html', body:'<html></html>'}));
      await page.goto('http://video.test/publish');
      await page.setContent('<div id="sell-field-auctionVideos"><div class="emptyVideo">上传视频</div></div><iframe src="http://video.test/videoSelector.htm"></iframe>');
      const frame = page.frames().find(frame => /videoSelector/.test(frame.url()));
      await frame.locator('.VideoList--videoItem').first().waitFor();
      // Keep rejection tests fast, but still exercise every actual DOM decision.
      const fastPage = new Proxy(page, {get(target, key) {
        if (key === 'waitForTimeout') return async () => {};
        const value = Reflect.get(target, key);return typeof value === 'function' ? value.bind(target) : value;
      }});
      const result = JSON.parse(await load({names: [name], files: [], resumeOnly: true})(fastPage));
      assert.equal(await page.evaluate(() => window.dispatched), undefined);
      if (mode === 'truncated') {
        assert.equal(result.uploaded, true, JSON.stringify(result));
        assert.match(result.checkedText, /qn_61c0d13d85ab11c34/);
      } else {
        assert.equal(result.uploaded, false);
        assert.equal(await page.locator('video').count(), 0);
      }
    } finally {await browser.close();}
  });
}
