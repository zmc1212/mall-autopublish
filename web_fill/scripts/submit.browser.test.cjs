const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(path.join(__dirname, '_helpers.inc.js'), 'utf8');
const source = fs.readFileSync(path.join(__dirname, 'submit.js'), 'utf8');
const accelerated = helpers.replace('const sleep = (ms) => page.waitForTimeout(ms);',
  'const sleep = (ms) => page.waitForTimeout(Math.min(ms, 15));');
const submit = new Function('return (' + source.replace('/*PAYLOAD*/', '{}')
  .replace('/*HELPERS*/', accelerated) + ')')();
// helpers 顶层有 await ensureFront()（后台页签前台化），必须用 AsyncFunction 包装。
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor;
const actions = page => new AsyncFunction('page', helpers +
  '\nreturn {confirm: confirmProductAttributeUpdate, cleanup: closeDialogsOnly};')(page);

async function fixture(run, options = {}) {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://submit.test/**', route => route.fulfill({contentType: 'text/html', body: '<meta charset="utf-8">'}));
    await page.goto('http://submit.test/sell/v2/publish.htm');
    await page.setContent(`<div id="form">
      <label><input type="radio" name="listing" checked>放入仓库</label>
      <label><input type="radio" name="listing">立刻上架</label>
      <button id="button-submit">提交宝贝信息</button></div>
      <button id="unrelated">确定</button><div id="outcome"></div>
      <div class="next-dialog" role="dialog" style="display:none">
        <div class="next-dialog-header">商品属性信息更新确定</div>
        <button class="next-dialog-close">关闭</button>
        <p>油墨类型 — 中性墨水</p>
        <label><input type="radio" name="attribute" value="adopt" checked>采纳</label>
        <label><input type="radio" name="attribute" value="keep">不采纳</label>
        <button id="confirm">确定</button>
      </div>`);
    await page.evaluate(options => {
      const modal = document.querySelector('.next-dialog');
      window.counts = {submit: 0, confirm: 0, close: 0, unrelated: 0};
      window.openUpdate = () => { modal.style.display = 'block'; };
      document.querySelector('#button-submit').onclick = () => {
        window.counts.submit++;
        setTimeout(window.openUpdate, 40);
      };
      document.querySelector('#unrelated').onclick = () => window.counts.unrelated++;
      document.querySelector('[value="keep"]').onchange = () => {
        setTimeout(() => {window.keepCommitted = true;}, 150);
      };
      document.querySelector('.next-dialog-close').onclick = () => {
        window.counts.close++;
        modal.style.display = 'none';
      };
      document.querySelector('#confirm').onclick = () => {
        window.counts.confirm++;
        window.adopted = options.delayedChoice ? !window.keepCommitted : document.querySelector('[value="adopt"]').checked;
        if (!options.staysOpen) {
          modal.style.display = 'none';
          setTimeout(() => {
            if (options.navigate) location.href = '/sell/v2/success.htm?primaryId=123456789';
            else if (options.reopens) window.openUpdate();
            else document.querySelector('#outcome').innerText = '商品提交成功 商品ID：123456789';
          }, options.lateSuccess ? 150 : 0);
        }
      };
      if (options.keep) document.querySelector('[value="keep"]').checked = true;
      if (options.existing) {
        window.openUpdate();
        document.querySelector('#form').setAttribute('aria-hidden', 'true');
      }
    }, options);
    await run(page);
  } finally { await browser.close(); }
}

test('submit confirms the delayed attribute update once and preserves adoption choice', async () => {
  await fixture(async page => {
    const result = JSON.parse(await submit(page));
    assert.equal(result.itemId, '123456789');
    assert.equal(result.hasSuccess, true);
    assert.equal(result.attributeUpdates.length, 1);
    assert.equal(await page.evaluate(() => window.adopted), true);
    assert.deepEqual(await page.evaluate(() => window.counts), {submit: 1, confirm: 1, close: 0, unrelated: 0});
  });
});

test('existing update dialog survives cleanup and is confirmed without resubmitting', async () => {
  await fixture(async page => {
    assert.equal(await (await actions(page)).cleanup(), 0);
    const result = JSON.parse(await submit(page));
    assert.equal(result.hasSuccess, true);
    assert.equal(await page.evaluate(() => window.adopted), false);
    assert.deepEqual(await page.evaluate(() => window.counts), {submit: 0, confirm: 1, close: 0, unrelated: 0});
  }, {existing: true, keep: true});
});

test('unrelated material import dialog is not an attribute update confirmation', async () => {
  await fixture(async page => {
    await page.locator('.next-dialog-header').evaluate(el => { el.innerText = '素材导入确认'; });
    assert.equal(await (await actions(page)).confirm(), null);
    assert.equal(await page.evaluate(() => window.counts.confirm), 0);
  }, {existing: true});
});

test('image repair refuses unrelated attribute recommendations', async () => {
  await fixture(async page => {
    const result = await (await actions(page)).confirm({preserveExisting: true});
    assert.equal(result.confirmed, true);
    assert.equal(await page.evaluate(() => window.adopted), false);
    assert.equal(await page.evaluate(() => window.counts.confirm), 1);
  }, {existing: true});
});

test('image repair waits for the controlled attribute choice before confirming', async () => {
  await fixture(async page => {
    const result = await (await actions(page)).confirm({preserveExisting: true});
    assert.equal(result.confirmed, true);
    assert.equal(await page.evaluate(() => window.adopted), false);
    assert.equal(await page.evaluate(() => window.counts.confirm), 1);
  }, {existing: true, delayedChoice: true});
});

test('submit observes a delayed save receipt without clicking submit or confirm twice', async () => {
  await fixture(async page => {
    const result = JSON.parse(await submit(page));
    assert.equal(result.hasSuccess, true);
    assert.deepEqual(await page.evaluate(() => window.counts), {submit: 1, confirm: 1, close: 0, unrelated: 0});
  }, {lateSuccess: true});
});

test('a reopened attribute dialog remains uncertain and is never blindly reconfirmed', async () => {
  await fixture(async page => {
    const result = JSON.parse(await submit(page));
    assert.equal(result.hasSuccess, false);
    assert.equal(result.pendingAttributeUpdate, true);
    assert.match(result.notice, /属性更新弹窗仍未完成/);
    assert.deepEqual(await page.evaluate(() => window.counts), {submit: 1, confirm: 1, close: 0, unrelated: 0});
  }, {reopens: true});
});

test('save outcome observation survives navigation to the success page', async () => {
  await fixture(async page => {
    const result = JSON.parse(await submit(page));
    assert.equal(result.hasSuccess, true);
    assert.equal(result.itemId, '123456789');
    assert.equal(result.attributeUpdates.length, 1);
  }, {navigate: true, lateSuccess: true});
});

test('an itemId on the edit page cannot prove save success', async () => {
  await fixture(async page => {
    await page.evaluate(() => {
      history.replaceState(null, '', '?itemId=123456789');
      document.querySelector('#button-submit').onclick = () => {window.counts.submit++;};
    });
    // The fixture's non-Taobao host is intentional; exercise the result reader
    // with the ordinary publish payload after adding the edit query.
    const result = JSON.parse(await submit(new Proxy(page, {get(target, key) {
      if (key === 'url') return () => 'http://submit.test/sell/v2/publish.htm';
      const value = Reflect.get(target, key);return typeof value === 'function' ? value.bind(target) : value;
    }})));
    assert.equal(result.hasSuccess, false);
    assert.equal(result.hasFail, false);
    assert.equal(await page.evaluate(() => window.counts.submit), 1);
  });
});

test('uncertain confirmation never clicks the same dialog twice', async () => {
  await fixture(async page => {
    const confirm = (await actions(page)).confirm;
    await assert.rejects(confirm(), /确认结果待核实/);
    await assert.rejects(confirm(), /未重复点击/);
    assert.equal(await page.evaluate(() => window.counts.confirm), 1);
    assert.equal(await page.evaluate(() => window.counts.submit), 0);
  }, {existing: true, staysOpen: true});
});

test('a submit timeout after dispatch never falls back to a second click', async () => {
  await fixture(async page => {
    const wrapped = new Proxy(page, {
      get(target, key) {
        if (key === 'locator') return (selector, ...args) => {
          const locator = target.locator(selector, ...args);
          if (selector !== "#button-submit, button[name='button-submit']") return locator;
          return new Proxy(locator, {
            get(value, field) {
              if (field === 'click') return async options => {
                await value.click(options);
                throw new Error('Timeout after click was dispatched');
              };
              const property = Reflect.get(value, field);
              return typeof property === 'function' ? property.bind(value) : property;
            },
          });
        };
        const value = Reflect.get(target, key);
        return typeof value === 'function' ? value.bind(target) : value;
      },
    });
    await assert.rejects(submit(wrapped), /提交结果待核实，未重复点击/);
    assert.equal(await page.evaluate(() => window.counts.submit), 1);
    assert.equal(await page.evaluate(() => window.counts.confirm), 0);
  });
});
