const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(path.join(__dirname, '_helpers.inc.js'), 'utf8');

test('cooldown survives a real Chromium restart and is shared across tabs', async () => {
  const profile = fs.mkdtempSync(path.join(os.tmpdir(), 'qianniu-pacing-test-'));
  const options = {headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'};
  let context;
  try {
    context = await chromium.launchPersistentContext(profile, options);
    await context.route('http://pacing.test/**', route => route.fulfill({contentType: 'text/html', body: 'Upload pacing fixture'}));
    const first = context.pages()[0];
    await first.goto('http://pacing.test/main');
    const state = {lastDispatchAt: Date.now(), nextAllowedAt: Date.now() + 120000, penalty: 2,
      recent: [{at: Date.now(), count: 1}]};
    await new Function('page', 'state', helpers + 'return writeUploadPacingState(state);')(first, state);
    const second = await context.newPage();
    await second.goto('http://pacing.test/details');
    const read = new Function('page', helpers + 'return readUploadPacingState();');
    assert.equal((await read(second)).nextAllowedAt, state.nextAllowedAt);
    await context.close();
    context = await chromium.launchPersistentContext(profile, options);
    await context.route('http://pacing.test/**', route => route.fulfill({contentType: 'text/html', body: 'Restarted pacing fixture'}));
    const reopened = context.pages()[0];
    await reopened.goto('http://pacing.test/after-restart');
    const actual = await read(reopened);
    assert.equal(actual.nextAllowedAt, state.nextAllowedAt);
    assert.equal(actual.penalty, 2);
    assert.equal(actual.recent.length, 1);
  } finally {
    if (context) await context.close();
    // This is the isolated mkdtemp profile created by this test, never the
    // user's browser profile or any other workspace directory.
    if (path.dirname(profile) === os.tmpdir() && path.basename(profile).startsWith('qianniu-pacing-test-')) {
      fs.rmSync(profile, {recursive: true, force: true});
    }
  }
});

test('visible stream-upload punish frame pauses even without middleware widget class', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('http://pacing.test/**', route => route.fulfill({contentType: 'text/html', body: '请完成验证'}));
    await page.setContent('<div id=challenge style="display:none"><iframe src="http://pacing.test/_____tmd_____/punish"></iframe></div>');
    await page.frames()[1].waitForLoadState();
    const reason = new Function('page', helpers + 'return securityChallengeReason();');
    assert.equal(await reason(page), '');
    await page.locator('#challenge').evaluate(el => {el.style.display = 'block';});
    assert.equal(await reason(page), '滑块验证');
    const check = new Function('page', helpers + 'return assertNoSecurityChallenge();');
    await assert.rejects(() => check(page), /PAUSE:.*手动完成验证/);
  } finally {
    await browser.close();
  }
});
