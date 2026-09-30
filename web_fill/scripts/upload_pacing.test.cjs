const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');

function harness(custom = {}) {
  let now = 100000;
  const waits = [];
  const math = Object.create(Math);
  math.random = () => 0;
  const payload = {uploadPacing: true, uploadPacingOptions: {
    initialDelayMs: 2000, minGapMs: 1000, maxGapMs: 1000,
    windowMs: 10000, maxFilesPerWindow: 3,
    backoffBaseMs: 2000, backoffMaxMs: 10000, ...custom,
  }};
  const c = vm.createContext({PAYLOAD: payload, Math: math,
    Date: class extends Date {static now() {return now;}},
    page: {waitForTimeout: async ms => {waits.push(ms); now += ms;}}});
  vm.runInContext(helpers, c);
  const productionAssertNoSecurityChallenge = c.assertNoSecurityChallenge;
  c.assertNoSecurityChallenge = async () => {};
  c.collectUploadStatus = async () => ({});
  return {c, waits, payload, productionAssertNoSecurityChallenge,
    now: () => now, advance: ms => {now += ms;}};
}

test('first file waits and a new image phase shares the previous receipt interval', async () => {
  const {c, now, advance} = harness();
  await c.waitForUploadTurn({}, ['main.jpg']);
  assert.equal(now(), 102000);
  advance(5000); // A slow upload is not charged against the post-receipt gap.
  await c.recordUploadPacingResult(true);
  await c.waitForUploadTurn({}, ['detail.jpg']);
  assert.equal(now(), 108000);
  const state = await c.readUploadPacingState();
  assert.equal(state.recent.length, 2);
});

test('rolling window prevents a new phase from bursting past its file budget', async () => {
  const {c, now} = harness({initialDelayMs: 0});
  for (const name of ['main1.jpg', 'main2.jpg', 'main3.jpg', 'detail1.jpg']) {
    await c.waitForUploadTurn({}, [name]);
    await c.recordUploadPacingResult(true);
  }
  assert.equal(now(), 110000);
  const state = await c.readUploadPacingState();
  assert.equal(state.recent.reduce((sum, item) => sum + item.count, 0), 3);
});

test('each failed dispatch increases capped cooldown without repeated-observation inflation', async () => {
  const {c, now} = harness({initialDelayMs: 0});
  for (const delay of [2000, 4000, 8000, 10000]) {
    await c.waitForUploadTurn({}, ['main.jpg']);
    await c.recordUploadPacingResult(false, undefined, 'platform-verification');
    let state = await c.readUploadPacingState();
    assert.equal(state.nextAllowedAt - now(), delay);
    const penalty = state.penalty;
    await c.recordUploadPacingResult(false, undefined, 'platform-verification');
    state = await c.readUploadPacingState();
    assert.equal(state.penalty, penalty);
  }
});

test('a submitted file with an uncertain receipt still consumes its pacing slot', async () => {
  const {c, now} = harness({initialDelayMs: 0});
  c.trySetInputFiles = async () => 'TIMEOUT';
  assert.equal(await c.pacedSetInputFiles({}, ['main.jpg']), 'TIMEOUT');
  const state = await c.readUploadPacingState();
  assert.equal(state.recent[0].count, 1);
  assert.equal(state.nextAllowedAt, now() + 1000);
});

test('a challenge appearing during a local wait prevents dispatch', async () => {
  const {c} = harness();
  let checks = 0, submitted = 0;
  c.assertNoSecurityChallenge = async () => {if (++checks === 2) throw new Error('PAUSE:请手动验证');};
  c.trySetInputFiles = async () => {submitted++; return 'OK';};
  await assert.rejects(() => c.pacedSetInputFiles({}, ['main.jpg']), /PAUSE:/);
  assert.equal(submitted, 0);
});

test('visible rate limits pause immediately rather than waiting and uploading anyway', async () => {
  const {c, waits} = harness();
  let submitted = 0;
  c.collectUploadStatus = async () => ({securityLimit: true, securityEvidence: [{text: ['请滑动验证码']}]});
  c.trySetInputFiles = async () => {submitted++; return 'OK';};
  await assert.rejects(() => c.pacedSetInputFiles({}, ['main.jpg']), /PAUSE:.*本次未提交图片/);
  assert.equal(submitted, 0);
  assert.equal(waits.length, 0);
  assert.equal((await c.readUploadPacingState()).lastFailure, 'platform-verification');
});

test('a direct captcha frame records cooldown even before a frequency receipt appears', async () => {
  const {c, productionAssertNoSecurityChallenge} = harness();
  c.assertNoSecurityChallenge = productionAssertNoSecurityChallenge;
  c.securityChallengeReason = async () => '滑块验证';
  await assert.rejects(() => c.assertNoSecurityChallenge(), /PAUSE:.*手动完成验证/);
  assert.equal((await c.readUploadPacingState()).penalty, 1);
  await assert.rejects(() => c.assertNoSecurityChallenge(), /PAUSE:/);
  assert.equal((await c.readUploadPacingState()).penalty, 1);
});

test('only five distinct verified uploads lower the accumulated penalty', async () => {
  const {c} = harness({initialDelayMs: 0});
  await c.writeUploadPacingState({penalty: 3});
  for (let i = 0; i < 5; i++) {
    await c.waitForUploadTurn({}, [String(i) + '.jpg']);
    await c.recordUploadPacingResult(true);
    await c.recordUploadPacingResult(true); // Re-reading a receipt is not another success.
    assert.equal((await c.readUploadPacingState()).penalty, i < 4 ? 3 : 2);
  }
  await c.waitForUploadTurn({}, ['next.jpg']);
  await c.recordUploadPacingResult(true);
  assert.equal((await c.readUploadPacingState()).penalty, 2);
});

test('recovery stays slow after cooldown and restores speed only after verified receipts', async () => {
  const {c, now} = harness({initialDelayMs: 0});
  await c.writeUploadPacingState({penalty: 2, nextAllowedAt: now() + 8000});
  const first = await c.waitForUploadTurn({}, ['first.jpg']);
  assert.equal(first.gapMs, 4000);
  assert.equal(first.maxFilesPerWindow, 1);
  assert.equal(first.recoveryMultiplier, 4);
  await c.recordUploadPacingResult(true);
  const firstAt = now();
  const second = await c.waitForUploadTurn({}, ['second.jpg']);
  assert.ok(now() - firstAt >= 10000, 'recovery respects the stricter rolling window');
  assert.equal(second.recoveryMultiplier, 4);
  await c.recordUploadPacingResult(true);
  for (let i = 0; i < 3; i++) {
    await c.waitForUploadTurn({}, [i + '.jpg']);
    await c.recordUploadPacingResult(true);
  }
  assert.equal((await c.readUploadPacingState()).penalty, 1);
  assert.equal((await c.waitForUploadTurn({}, ['next.jpg'])).recoveryMultiplier, 2);
});

test('an oversized or empty dispatch cannot bypass the configured rolling budget', async () => {
  const {c} = harness();
  for (const names of [[], ['a.jpg', 'b.jpg'], ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg']]) {
    await assert.rejects(() => c.waitForUploadTurn({}, names), /逐张提交/);
  }
  assert.equal((await c.readUploadPacingState()).lastDispatchAt, undefined);
});

test('configured backoff maximum cannot shorten the base cooldown', () => {
  const {c} = harness({backoffBaseMs: 5000, backoffMaxMs: 1000});
  assert.equal(c.uploadPacingPolicy().backoffMaxMs, 5000);
});

test('paced batches stay single-file even when callers request a larger batch', async () => {
  const {c, payload} = harness();
  const dispatches = [];
  c.finishLocalUploadBatch = async (_frame, files) => {
    dispatches.push([...files]);
    return {uploaded: true, dispatched: true};
  };
  const result = await c.finishLocalUpload({}, ['a.jpg', 'b.jpg', 'c.jpg'],
    ['a.jpg', 'b.jpg', 'c.jpg'], {...payload, uploadBatchSize: 6});
  assert.equal(result.uploaded, true);
  assert.deepEqual(dispatches, [['a.jpg'], ['b.jpg'], ['c.jpg']]);
});

test('2000 seeded dispatches respect cooldown, rolling limits and recovery bounds', async () => {
  for (let seed = 1; seed <= 40; seed++) {
    let value = seed;
    const random = () => {value = (Math.imul(value, 1664525) + 1013904223) >>> 0; return value / 4294967296;};
    const {c, now, advance} = harness({maxGapMs: 6000});
    c.Math.random = random;
    for (let i = 0; i < 50; i++) {
      const before = await c.readUploadPacingState();
      const receipt = await c.waitForUploadTurn({}, [`${seed}-${i}.jpg`]);
      const reserved = await c.readUploadPacingState();
      assert.ok(now() >= (before.nextAllowedAt || 0));
      assert.ok(reserved.recent.reduce((n, event) => n + event.count, 0) <= receipt.maxFilesPerWindow);
      assert.ok(receipt.recoveryMultiplier >= 1 && receipt.recoveryMultiplier <= 8);
      assert.ok(receipt.gapMs >= 1000 * receipt.recoveryMultiplier);
      assert.ok(receipt.gapMs <= 6000 * receipt.recoveryMultiplier);
      advance(Math.floor(random() * 500));
      const success = random() >= 0.25;
      await c.recordUploadPacingResult(success, undefined, success ? undefined : 'network-rejected');
      const finalized = await c.readUploadPacingState();
      assert.ok(finalized.nextAllowedAt >= reserved.nextAllowedAt);
      assert.ok(finalized.penalty >= 0 && finalized.penalty <= 8);
      // Observing the same receipt again cannot shorten the cooldown or
      // inflate the successful streak/failure penalty.
      await c.recordUploadPacingResult(success, undefined, success ? undefined : 'network-rejected');
      const reread = await c.readUploadPacingState();
      assert.equal(reread.nextAllowedAt, finalized.nextAllowedAt);
      assert.equal(reread.penalty, finalized.penalty);
      assert.equal(reread.successStreak, finalized.successStreak);
    }
  }
});
