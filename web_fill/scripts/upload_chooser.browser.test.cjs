const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(path.join(__dirname, '_helpers.inc.js'), 'utf8');
const launchBrowser = () => chromium.launch({headless: true,
  executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});

test('local upload initialization submits once without leaving a native chooser', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    for (const [delayed, failReceipt] of [[false, false], [true, false], [true, true]]) {
      const page = await browser.newPage();
      let chooserCount = 0;
      page.on('filechooser', () => { chooserCount++; });
      await page.setContent('<iframe></iframe>');
      const frame = page.frames()[1];
      await frame.setContent(`<button>本地上传</button><script>
        window.uploads = [];
        window.widgetClicks = 0;
        document.querySelector('button').onclick = () => {
          const input = document.createElement('input');
          input.type = 'file';
          input.onclick = () => { window.widgetClicks++; };
          input.onchange = () => window.uploads.push(...Array.from(input.files, file => file.name));
          document.body.append(input);
          ${delayed ? 'setTimeout(() => input.click(), 20);' : 'input.click();'}
        };
      </script>`);
      const run = new Function('page', 'frame', 'files', 'failReceipt', helpers + `
        waitUploadStatus = async () => ({});
        retryUntilUploaded = async () => {
          await frame.waitForFunction(() => window.uploads.length === 1 && window.widgetClicks === 1);
          if (failReceipt) throw new Error('receipt failed');
          return {uploaded: true, complete: 'CLOSED'};
        };
        return finishLocalUploadBatch(frame, files, ['a.jpg']);
      `);
      const pending = run(page, frame, [{name: 'a.jpg', mimeType: 'image/jpeg', buffer: Buffer.from('fixture')}], failReceipt);
      if (failReceipt) {
        await assert.rejects(pending, /receipt failed/);
      } else {
        const result = await pending;
        assert.equal(result.uploaded, true);
        assert.equal(result.dispatched, true);
      }
      assert.equal(chooserCount, 0, `native chooser must not race the upload (delayed=${delayed})`);
      assert.deepEqual(await frame.evaluate(() => window.uploads), ['a.jpg']);
      assert.equal(await frame.evaluate(() => !!document.__qianniuLocalFileChooserGuard), false);
      // Manual file picking must work again after the automation's scoped guard.
      await Promise.all([page.waitForEvent('filechooser'),
        frame.locator('input[type=file]').evaluate(input => input.click())]);
      assert.equal(chooserCount, 1);
      await page.close();
    }
  } finally {
    await browser.close();
  }
});

test('hidden stale picker receipts are ignored but visible frequency errors stop uploads', async () => {
  const browser = await launchBrowser();
  try {
    const page = await browser.newPage();
    await page.setContent('<div id=old style="opacity:0"><iframe></iframe></div><iframe id=active></iframe>');
    const oldFrame = page.frames()[1], frame = page.frames()[2];
    await oldFrame.setContent('<div role=dialog>上传结果：操作过于频繁<button>完成</button></div>');
    await frame.setContent('<button>本地上传</button><input type=file><script>window.uploads=0;document.querySelector("input").onchange=()=>window.uploads++;</script>');
    const inspect = new Function('page', 'frame', helpers + 'return collectUploadStatus(frame, ["a.jpg"]);');
    assert.equal((await inspect(page, frame)).securityLimit, false);
    await page.locator('#old').evaluate(el => {el.style.opacity = '1'; el.style.display = 'none';});
    assert.equal((await inspect(page, frame)).securityLimit, false);
    await page.locator('#old').evaluate(el => {el.style.display = 'block';});
    const visible = await inspect(page, frame);
    assert.equal(visible.securityLimit, true);
    assert.equal(visible.securityEvidence.length, 1);
    await page.locator('#old').evaluate(el => {el.style.display = 'none';});
    await frame.evaluate(() => {
      const dialog = document.createElement('div');
      dialog.setAttribute('role', 'dialog');
      dialog.innerHTML = '上传结果：操作过于频繁<button>完成</button>';
      document.body.append(dialog);
    });
    const run = new Function('page', 'frame', helpers + 'return finishLocalUploadBatch(frame, [], ["a.jpg"]);');
    await assert.rejects(() => run(page, frame), /PAUSE:.*本次未提交图片/);
    assert.equal(await frame.evaluate(() => window.uploads), 0);
    assert.equal(await frame.getByRole('dialog').count(), 1);
  } finally {
    await browser.close();
  }
});

test('real DOM receipts submit five files once and keep a frequency failure visible', async () => {
  const browser = await launchBrowser();
  try {
    for (const blocked of [false, true]) {
      const page = await browser.newPage();
      await page.setContent('<iframe></iframe>');
      const frame = page.frames()[1];
      await frame.setContent('<input type=file multiple>');
      await frame.evaluate(blocked => {
        window.uploads = [];
        document.querySelector('input').onchange = event => {
          const names = Array.from(event.target.files, file => file.name);
          window.uploads.push(...names);
          const result = document.createElement('div');
          result.setAttribute('role', 'dialog');
          result.innerHTML = '上传结果 ' + (blocked ? '操作过于频繁' : names.length + ' 个文件上传成功') + '<button>完成</button>';
          result.querySelector('button').onclick = () => result.remove();
          document.body.append(result);
        };
      }, blocked);
      const names = ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg', 'e.jpg'];
      const files = names.map(name => ({name, mimeType: 'image/jpeg', buffer: Buffer.from('fixture')}));
      const run = new Function('page', 'frame', 'files', 'names', helpers + 'return finishLocalUploadBatch(frame, files, names);');
      if (blocked) {
        await assert.rejects(() => run(page, frame, files, names), error => {
          assert.match(error.message, /PAUSE:.*上传结果尚未确认/);
          const detail = JSON.parse(error.message.split('UPLOAD_SECURITY_DIAGNOSTIC:')[1]);
          assert.equal(detail.phase, 'receipt-check');
          assert.equal(detail.securityEvidence[0].source, 'upload-result');
          return true;
        });
        assert.equal(await frame.getByRole('dialog').count(), 1);
      } else {
        const result = await run(page, frame, files, names);
        assert.equal(result.uploaded, true);
        assert.equal(result.verifiedBy, 'upload-result');
        assert.equal(await frame.getByRole('dialog').count(), 0);
      }
      assert.deepEqual(await frame.evaluate(() => window.uploads), names);
      await page.close();
    }
  } finally {
    await browser.close();
  }
});

test('visible captcha stays open and prevents file dispatch in Chromium', async () => {
  const browser = await launchBrowser();
  try {
    const page = await browser.newPage();
    await page.setContent('<iframe id=picker></iframe>');
    const frame = page.frames()[1];
    await frame.setContent('<input type=file><div class=J_MIDDLEWARE_FRAME_WIDGET>' +
      '<img style="width:20px;height:20px" onclick="window.closeClicks++;this.parentElement.remove()">' +
      '<iframe src="about:blank?action=captcha"></iframe></div><script>window.closeClicks=0;window.uploads=0;' +
      'document.querySelector("input").onchange=()=>window.uploads++;</script>');
    const run = new Function('page', 'frame', helpers + 'return finishLocalUploadBatch(frame, [], ["a.jpg"]);');
    await assert.rejects(() => run(page, frame), /PAUSE:.*手动完成验证/);
    assert.equal(await frame.evaluate(() => window.closeClicks), 0);
    assert.equal(await frame.evaluate(() => window.uploads), 0);
    assert.equal(await frame.locator('.J_MIDDLEWARE_FRAME_WIDGET').count(), 1);
  } finally {
    await browser.close();
  }
});
