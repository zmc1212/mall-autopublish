const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');

function harness(extra = {}) {
  const context = vm.createContext({page: {}, ...extra});
  vm.runInContext(source, context);
  return context;
}

test('material filenames normalize plus without matching another product', () => {
  const c = harness();
  const missing = c.missingPictureNames(['颜色13-1支笔 30支晨光笔芯.jpg 800x800'], ['颜色13-1支笔+30支晨光笔芯.jpg','颜色13-1支笔+20支晨光笔芯.jpg']);
  assert.deepEqual(Array.from(missing), ['颜色13-1支笔+20支晨光笔芯.jpg']);
});

test('absence of upload errors does not prove success', async () => {
  const c = harness();
  c.waitUploadStatus = async () => ({failedNames: [], found: [], success: false});
  c.waitUploadResultClosed = async () => 'CLOSED';
  assert.equal((await c.retryUntilUploaded(null, ['a.jpg'], ['a.jpg'])).uploaded, false);
});

test('receipt verification with zero retries never dispatches a file', async () => {
  const c = harness({page: {waitForTimeout: async () => {}}});
  let submissions = 0;
  c.waitUploadStatus = async () => ({fail: true, failedNames: ['a.jpg'], retryable: true});
  c.setFilesAnywhere = async () => { submissions++; return 'OK'; };
  const result = await c.retryUntilUploaded({}, ['a.jpg'], ['a.jpg'], 0);
  assert.equal(result.uploaded, false);
  assert.equal(submissions, 0);
});

for (const outcome of ['OK', 'TIMEOUT']) {
  test(`an ${outcome} input submission is verified without submitting it again`, async () => {
    const c = harness();
    let submissions = 0;
    c.fileInputs = async () => [{id: 'upload'}];
    c.trySetInputFiles = async () => { submissions++; return outcome; };
    c.retryUntilUploaded = async (_frame, _files, _names, maxTries) => {
      assert.equal(maxTries, 0);
      return {uploaded: false, missing: ['a.jpg'], status: {}};
    };
    const result = await c.finishLocalUploadBatch({}, ['a.jpg'], ['a.jpg']);
    assert.equal(submissions, 1);
    assert.equal(result.dispatched, true);
    assert.equal(result.uploaded, false);
    assert.equal(result.need_cli_upload, false);
    assert.equal(result.dispatchUncertain, outcome === 'TIMEOUT');
  });
}

test('five single-file batches submit each image exactly once', async () => {
  const submitted = [], waits = [];
  const c = harness({page: {waitForTimeout: async ms => waits.push(ms)},
    PAYLOAD: {uploadBatchSize: 1, uploadBatchDelayMinMs: 4000, uploadBatchDelayMaxMs: 9000}});
  c.fileInputs = async () => [{id: 'upload'}];
  c.trySetInputFiles = async (_frame, files) => {submitted.push(Array.from(files)); return 'OK';};
  c.retryUntilUploaded = async () => ({uploaded: true, complete: 'CLOSED'});
  const files = ['a.jpg', 'b.jpg', 'c.jpg', 'd.jpg', 'e.jpg'];
  const result = await c.finishLocalUpload({}, files, files);
  assert.equal(result.uploaded, true);
  assert.deepEqual(submitted, files.map(file => [file]));
  assert.equal(waits.length, 4);
  assert.ok(waits.every(ms => ms >= 4000 && ms <= 9000));
});

test('an unconfirmed first image stops later batches without another submission', async () => {
  const c = harness({PAYLOAD: {uploadBatchSize: 1}});
  const submitted = [];
  c.fileInputs = async () => [{id: 'upload'}];
  c.trySetInputFiles = async (_frame, files) => {submitted.push(Array.from(files)); return 'OK';};
  c.retryUntilUploaded = async () => ({uploaded: false});
  const result = await c.finishLocalUpload({}, ['a.jpg', 'b.jpg'], ['a.jpg', 'b.jpg']);
  assert.deepEqual(submitted, [['a.jpg']]);
  assert.equal(result.dispatched, true);
  assert.equal(result.uploaded, false);
});

test('server frequency limit stops a single upload without retrying it', async () => {
  let closed = 0, retried = 0;
  const c = harness({page: {keyboard: {press: async () => {closed++;}}}});
  c.assertNoSecurityChallenge = async () => {};
  c.waitUploadStatus = async () => ({securityLimit: true, failedNames: ['a.jpg']});
  c.waitUploadResultClosed = async () => {closed++; return 'CLOSED';};
  c.setFilesAnywhere = async () => {retried++; return 'OK';};
  await assert.rejects(() => c.retryUntilUploaded(null, ['a.jpg'], ['a.jpg']), /PAUSE:.*操作过于频繁/);
  assert.equal(closed, 0);
  assert.equal(retried, 0);
});

test('upload status returns promptly when the server requires verification', async () => {
  let reads = 0;
  const c = harness();
  c.assertNoSecurityChallenge = async () => {};
  c.uploadContexts = () => [{}];
  c.readUploadStatus = async () => {reads++; return {securityLimit: true};};
  const status = await c.waitUploadStatus({}, ['a.jpg']);
  assert.equal(status.securityLimit, true);
  assert.equal(reads, 1);
});

test('security challenge pauses instead of waiting forever', async () => {
  const c = harness({page: {frames: () => [], evaluate: async () => '操作过于频繁 请滑动验证码'}});
  c.closeSecurityChallenge = async () => false;
  await assert.rejects(() => c.assertNoSecurityChallenge(), /PAUSE:.*手动完成验证/);
});

test('security challenge is preserved for manual verification', async () => {
  let clicks = 0;
  let open = true;
  const close = {getBoundingClientRect: () => ({width: 20, height: 20}), click() {
    clicks++;
    open = false;
  }};
  const widget = {getBoundingClientRect: () => ({width: open ? 900 : 0, height: open ? 510 : 0}),
    querySelector: () => ({}), querySelectorAll: () => [close]};
  const document = {querySelectorAll: () => [widget]};
  const c = harness({document, getComputedStyle: () => ({display: 'block', visibility: 'visible', opacity: '1'}),
    page: {frames: () => [], evaluate: async fn => fn(), waitForTimeout: async () => {}}});
  await assert.rejects(() => c.assertNoSecurityChallenge(), /PAUSE:.*手动完成验证/);
  assert.equal(clicks, 0);
  assert.equal(open, true);
});

test('existing rate limit stops before any new file is dispatched', async () => {
  const c = harness();
  let dispatched = 0;
  c.collectUploadStatus = async () => ({securityLimit: true, securityEvidence: [{text: ['操作过于频繁']}]});
  c.fileInputs = async () => [{id: 'upload'}];
  c.trySetInputFiles = async () => {dispatched++; return 'OK';};
  await assert.rejects(() => c.finishLocalUploadBatch({}, ['a.jpg'], ['a.jpg']), error => {
    assert.match(error.message, /本次未提交图片/);
    const detail = JSON.parse(error.message.split('UPLOAD_SECURITY_DIAGNOSTIC:')[1]);
    assert.equal(detail.phase, 'before-dispatch');
    assert.deepEqual(detail.names, ['a.jpg']);
    assert.equal(detail.securityEvidence[0].text[0], '操作过于频繁');
    return true;
  });
  assert.equal(dispatched, 0);
});

test('rate limit appearing while input is missing also stops initialization', async () => {
  const c = harness();
  c.collectUploadStatus = async () => ({});
  c.fileInputs = async () => [];
  c.waitUploadStatus = async () => ({securityLimit: true});
  await assert.rejects(() => c.finishLocalUploadBatch({}, ['a.jpg'], ['a.jpg']), /PAUSE:.*本次未提交图片/);
});

test('an in-flight receipt is verified without another input change', async () => {
  const c = harness();
  let dispatched = 0;
  c.collectUploadStatus = async () => ({uploading: true});
  c.fileInputs = async () => [{id: 'upload'}];
  c.trySetInputFiles = async () => {dispatched++; return 'OK';};
  c.retryUntilUploaded = async (_frame, _files, _names, retries) => {
    assert.equal(retries, 0);
    return {uploaded: true};
  };
  const result = await c.finishLocalUploadBatch({}, ['a.jpg'], ['a.jpg']);
  assert.equal(result.uploaded, true);
  assert.equal(result.via, 'pending-receipt');
  assert.equal(dispatched, 0);
});

test('resuming never closes an unresolved visible verification result', async () => {
  const c = harness();
  let clicks = 0;
  c.pictureSpaceFrame = () => ({});
  c.collectUploadStatus = async () => ({securityLimit: true});
  c.clickComplete = async () => {clicks++; return 'OK';};
  await assert.rejects(() => c.waitUploadResultClosed(), /PAUSE:.*操作过于频繁/);
  assert.equal(clicks, 0);
});

test('large uploads are split into throttled batches', async () => {
  const waits = [];
  const c = harness({page: {waitForTimeout: async (ms) => waits.push(ms)},
    PAYLOAD: {uploadBatchSize: 3, uploadBatchDelayMinMs: 5000, uploadBatchDelayMaxMs: 10000}});
  c.assertNoSecurityChallenge = async () => {};
  c.finishLocalUploadBatch = async (_frame, files) => ({uploaded: true, verifiedBy: files.join(',')});
  const files = Array.from({length: 8}, (_, i) => `${i}.jpg`);
  const result = await c.finishLocalUpload({}, files, files);
  assert.equal(result.uploaded, true);
  assert.equal(result.batches.length, 3);
  assert.deepEqual(Array.from(result.batches, item => item.names.length), [3, 3, 2]);
  assert.equal(waits.length, 2);
  assert.ok(waits.every(ms => ms >= 5000 && ms <= 10000));
  assert.equal(result.batches[0].waitBeforeMs, 0);
  assert.deepEqual(Array.from(result.batches.slice(1), item => item.waitBeforeMs), waits);
});

test('spec upload policy sends one image at a time with a delay before each next image', async () => {
  const waits = [];
  const c = harness({page: {waitForTimeout: async ms => waits.push(ms)},
    PAYLOAD: {uploadBatchSize: 1, uploadBatchDelayMinMs: 5000, uploadBatchDelayMaxMs: 10000}});
  c.assertNoSecurityChallenge = async () => {};
  c.finishLocalUploadBatch = async () => ({uploaded: true});
  const files = Array.from({length: 8}, (_, i) => `${i}.jpg`);
  const result = await c.finishLocalUpload({}, files, files);
  assert.equal(result.uploadPolicy.batchSize, 1);
  assert.equal(result.batches.length, files.length);
  assert.ok(result.batches.every(batch => batch.names.length === 1));
  assert.equal(waits.length, files.length - 1);
  assert.ok(waits.every(ms => ms >= 5000 && ms <= 10000));
});

test('fallback upload applies one-file policy when caller omitted it', async () => {
  const uploadSource = fs.readFileSync(__dirname + '/upload_files.js', 'utf8')
    .replace('/*PAYLOAD*/', JSON.stringify({files: ['a.jpg', 'b.jpg']}))
    .replace('/*HELPERS*/', '');
  let received;
  const run = vm.runInNewContext('(' + uploadSource + ')', {
    sucaiFrame: () => ({}), wangpuFrame: () => ({}), fileBase: x => x,
    finishLocalUpload: async (_frame, _files, _names, policy) => {received = policy; return {uploaded: true}},
  });
  await run({});
  assert.equal(received.uploadBatchSize, 1);
});

test('material library queries keep a delay across script calls', async () => {
  const values = new Map(), waits = [];
  const c = harness({sessionStorage: {
    getItem: key => values.get(key), setItem: (key, value) => values.set(key, value),
  }, page: {evaluate: async fn => fn(), waitForTimeout: async ms => waits.push(ms)}});
  assert.equal(await c.paceSucaiSearch(), 0);
  const delay = await c.paceSucaiSearch();
  assert.ok(delay >= 5000 && delay <= 10000);
  assert.deepEqual(waits, [delay]);
});

test('material search supports an optional longer cooldown policy', async () => {
  const values = new Map([
    ['qianniu-last-sucai-query', String(Date.now())],
    ['qianniu-sucai-query-count', '8'],
  ]), waits = [];
  const c = harness({sessionStorage: {
    getItem: key => values.get(key), setItem: (key, value) => values.set(key, value),
  }, page: {evaluate: async (fn, arg) => fn(arg), waitForTimeout: async ms => waits.push(ms)}});
  const delay = await c.paceSucaiSearch({minMs: 20000, maxMs: 30000,
    cooldownEvery: 8, cooldownMs: 90000});
  assert.ok(delay >= 109000 && delay <= 120000);
  assert.deepEqual(waits, [delay]);
  assert.equal(values.get('qianniu-sucai-query-count'), '9');
});

test('challenge appearing during the delay prevents the next batch', async () => {
  let checks = 0, uploaded = 0;
  const c = harness({page: {waitForTimeout: async () => {}},
    PAYLOAD: {uploadBatchSize: 3, uploadBatchDelayMinMs: 5000, uploadBatchDelayMaxMs: 10000}});
  c.assertNoSecurityChallenge = async () => {
    if (++checks === 3) throw Error('PAUSE:请手动完成滑块验证');
  };
  c.finishLocalUploadBatch = async () => {uploaded++; return {uploaded: true}};
  const files = Array.from({length: 6}, (_, i) => `${i}.jpg`);
  await assert.rejects(() => c.finishLocalUpload({}, files, files), /PAUSE/);
  assert.equal(uploaded, 1);
});

test('filenames alone do not prove an upload succeeded', async () => {
  const c = harness();
  c.waitUploadResultClosed = async () => 'CLOSED';
  c.waitUploadStatus = async () => ({failedNames: [], found: ['a.jpg'], success: true});
  assert.equal((await c.retryUntilUploaded(null, [], ['a.jpg','b.jpg'])).uploaded, false);
  c.waitUploadStatus = async () => ({failedNames: [], found: ['a.jpg','b.jpg'], success: true});
  assert.equal((await c.retryUntilUploaded(null, [], ['a.jpg','b.jpg'])).uploaded, false);
  c.waitUploadStatus = async () => ({failedNames: [], okNames: ['a.jpg','b.jpg'], success: true});
  assert.equal((await c.retryUntilUploaded(null, [], ['a.jpg','b.jpg'])).uploaded, true);
  c.waitUploadStatus = async () => ({failedNames: [], okNames: ['a.jpg','b.jpg'], success: true, successCount: 42});
  assert.equal((await c.retryUntilUploaded(null, [], ['a.jpg','b.jpg'])).uploaded, false);
});

test('library search finds images missing from the first visible page', async () => {
  const c = harness();
  const searches = [];
  c.listSucaiPics = async () => searches.length ? [`color-1.jpg`, `color-2.jpg`] : [`color-1.jpg`];
  c.searchSucai = async (_frame, query) => {searches.push(query); return 'OK'};
  const missing = await c.missingSucaiNames({}, ['color-1.jpg', 'color-2.jpg']);
  assert.deepEqual(Array.from(missing), []);
  assert.deepEqual(searches, ['color-2']);
});

test('material search clicks an icon-only accessible search button', async () => {
  let clicked = 0;
  const input = {value: '', focus() {}, dispatchEvent() {}};
  const button = {innerText: '⌕', getAttribute: (name) => name === 'title' ? '搜索' : null,
    click() {clicked++}};
  const c = harness({page: {waitForTimeout: async () => {}},
    document: {querySelector: () => input, querySelectorAll: () => [button]},
    window: {HTMLInputElement: {prototype: {}}}, Event: class {}, KeyboardEvent: class {}});
  const frame = {evaluate: async (fn, value) => fn(value)};
  c.listSucaiPics = async () => clicked ? [`详情18.jpg 800x800`] : [];
  assert.equal(await c.searchSucai(frame, '详情18', 1), 'OK');
  assert.equal(input.value, '详情18');
  assert.equal(clicked, 1);
});

test('material search keeps the existing SKU lookup when it succeeds', async () => {
  const c = harness({page: {waitForTimeout: async () => {}}});
  let realClicked = false;
  const frame = {evaluate: async () => 'OK', locator: () => {realClicked = true; throw Error('unused')}};
  c.listSucaiPics = async () => ['颜色07-【体验-不推荐】1支.jpg 800x800'];
  assert.equal(await c.searchSucai(frame, '颜色07', 1), 'OK');
  assert.equal(realClicked, false);
});

test('material search submits after controlled input state updates', async () => {
  let state = '颜色06', submitted = '';
  const input = {value: '', focus() {}, dispatchEvent(event) {
    if (event.type === 'input') setTimeout(() => {state = this.value}, 20);
  }};
  const button = {innerText: '搜索', getAttribute: () => null, click() {submitted = state}};
  const c = harness({page: {waitForTimeout: (ms) => new Promise(resolve => setTimeout(resolve, ms))},
    document: {querySelector: () => input, querySelectorAll: () => [button]},
    window: {HTMLInputElement: {prototype: {}}},
    Event: class {constructor(type) {this.type = type}}, KeyboardEvent: class {}});
  const frame = {evaluate: async (fn, value) => fn(value)};
  c.listSucaiPics = async () => submitted === '颜色07' ? ['颜色07-目标.jpg'] : ['颜色06-旧图.jpg'];
  assert.equal(await c.searchSucai(frame, '颜色07', 1), 'OK');
  assert.equal(submitted, '颜色07');
});

test('material search clears a stale controlled query before retrying', async () => {
  let state = '颜色20', submitted = '';
  const input = {value: '', focus() {}, dispatchEvent() {}};
  const button = {innerText: '', getAttribute: (name) => name === 'aria-label' ? '搜索' : null,
    click() {submitted = state}};
  const c = harness({page: {waitForTimeout: async () => {}},
    document: {querySelector: () => input, querySelectorAll: () => [button]},
    window: {HTMLInputElement: {prototype: {}}}, Event: class {}, KeyboardEvent: class {}});
  const locator = {first() {return this}, async fill(value) {input.value = value; state = value},
    async press() {submitted = state}};
  const frame = {evaluate: async (fn, value) => fn(value), locator: () => locator};
  c.listSucaiPics = async () => submitted === '颜色21' ? ['颜色21-目标.jpg'] : ['颜色20-旧图.jpg'];
  assert.equal(await c.searchSucai(frame, '颜色21', 1), 'OK');
  assert.equal(submitted, '颜色21');
});

test('SKU search reloads a picker stuck on the previous result', async () => {
  let reloaded = false, clicked = 0;
  const input = {value: '', focus() {}, dispatchEvent() {}};
  const button = {innerText: '搜索', getAttribute: () => null, click() {clicked++}};
  const c = harness({page: {waitForTimeout: async () => {}},
    document: {querySelector: () => input, querySelectorAll: () => [button]},
    window: {HTMLInputElement: {prototype: {}}}, Event: class {}, KeyboardEvent: class {}});
  const locator = {first() {return this}, async fill(value) {input.value = value}, async press() {}};
  const frame = {evaluate: async (fn, value) => fn(value), locator: () => locator,
    url: () => 'https://example.test/picker', async goto() {reloaded = true}};
  c.listSucaiPics = async () => reloaded && clicked > 1 ? ['颜色15-目标.jpg'] : ['颜色14-旧图.jpg'];
  assert.equal(await c.searchSucai(frame, '颜色15', 1, true), 'OK');
  assert.equal(reloaded, true);
});

test('picture space confirms a counted multi-image selection', async () => {
  let clicked = 0;
  const button = {innerText: '确定（22）', click() {clicked++}};
  const c = harness({page: {evaluate: async () => 'NO'},
    document: {querySelectorAll: () => [button], querySelector: () => null}});
  const frame = {evaluate: async (fn) => fn()};
  assert.equal(await c.confirmPictureSpace(frame), 'OK');
  assert.equal(clicked, 1);
});

test('batch success count confirms files hidden in a scrolling result list', async () => {
  const complete = {innerText: '完成', getBoundingClientRect: () => ({width: 60, height: 30})};
  const popup = {
    innerText: '上传结果\n42 个文件 上传成功',
    getBoundingClientRect: () => ({width: 600, height: 500}),
    querySelectorAll: (selector) => selector === 'button' ? [complete] : [],
  };
  const document = {
    body: {innerText: popup.innerText},
    querySelectorAll: (selector) => selector === 'button' ? [complete] : [popup],
  };
  const c = harness({document, getComputedStyle: () => ({display: 'block', visibility: 'visible', opacity: '1'})});
  const frame = {evaluate: async (fn, names) => fn(names)};
  const names = Array.from({length: 42}, (_, i) => `spec-${i}.jpg`);
  const status = await c.readUploadStatus(frame, names);
  assert.equal(status.successCount, 42);
  assert.equal(status.batchComplete, true);
  assert.equal(status.found.length, 0);
  c.waitUploadStatus = async () => status;
  c.waitUploadResultClosed = async () => 'CLOSED';
  assert.equal((await c.retryUntilUploaded(frame, names, names)).uploaded, true);
  assert.equal((await c.readUploadStatus(frame, names.slice(0, 21))).batchComplete, false);
});

test('oversized upload result is accepted only after every target is found in library', async () => {
  const c = harness();
  const frame = {};
  c.waitUploadStatus = async () => ({
    failedNames: [], found: ['main-2.jpg'], success: true,
    hasComplete: true, uploading: false, fail: false, successCount: 6,
  });
  c.waitUploadResultClosed = async () => 'CLOSED';
  c.missingSucaiNames = async () => [];
  const complete = await c.retryUntilUploaded(frame, [], ['main-1.jpg', 'main-2.jpg']);
  assert.equal(complete.uploaded, true);
  assert.equal(complete.verifiedBy, 'library-search');
  c.missingSucaiNames = async () => ['main-1.jpg'];
  const incomplete = await c.retryUntilUploaded(frame, [], ['main-1.jpg', 'main-2.jpg']);
  assert.equal(incomplete.uploaded, false);
  assert.deepEqual(Array.from(incomplete.missing), ['main-1.jpg']);
});

test('popup gone with residual state falls back to library search', async () => {
  const c = harness();
  const frame = {};
  c.waitUploadStatus = async () => ({
    failedNames: [], found: ['main-1.jpg', 'main-2.jpg'], success: false,
    hasComplete: false, uploading: false, fail: false, successCount: 2,
  });
  c.waitUploadResultClosed = async () => 'CLOSED';
  c.missingSucaiNames = async () => [];
  const result = await c.retryUntilUploaded(frame, [], ['main-1.jpg', 'main-2.jpg']);
  assert.equal(result.uploaded, true);
  assert.equal(result.verifiedBy, 'library-search');
  assert.equal(result.complete, 'CLOSED');
});

test('repeated SKU names bind to their own rows', () => {
  const specSource = fs.readFileSync(__dirname + '/spec_images.js', 'utf8');
  const start = specSource.indexOf('const skuClick = await page.evaluate((want) => {');
  const callbackStart = start + 'const skuClick = await page.evaluate('.length;
  const callbackEnd = specSource.indexOf('\n    }, {\n      ...spec,', callbackStart);
  assert.ok(start >= 0 && callbackEnd > callbackStart);
  const rows = Array.from({length: 2}, () => ({
    innerText: '同名规格', clicks: 0,
    querySelector: () => ({innerText: '同名规格'}),
    click() {this.clicks++},
  }));
  const dialog = {querySelectorAll: (selector) => selector === 'li.sku-item' ? rows : []};
  const choose = vm.runInNewContext('(' + specSource.slice(callbackStart, callbackEnd + 6) + ')', {
    document: {querySelector: () => dialog},
  });
  assert.match(choose({name: '同名规格', index: 0, occurrence: 0}), /^OK:0:/);
  assert.match(choose({name: '同名规格', index: 1, occurrence: 1}), /^OK:1:/);
  assert.deepEqual(rows.map(row => row.clicks), [1, 1]);
});

test('spec binding uses an already visible material without another search', async () => {
  const specSource = fs.readFileSync(__dirname + '/spec_images.js', 'utf8');
  const start = specSource.indexOf('async function selectSpec(spec, frame) {');
  const end = specSource.indexOf('\n  if (phase === "open"', start);
  assert.ok(start >= 0 && end > start);
  const spec = {name: '示例', slot: '颜色01', file: '颜色01-示例.jpg'};
  let searches = 0, clicks = 0;
  const c = vm.createContext({specs: [spec], page: {evaluate: async () => 'OK:0'},
    sleep: async () => {}, searchSucai: async () => {searches++},
    assertNoSecurityChallenge: async () => {},
    clickSucaiCard: async () => {clicks++; return {ok: true, target: 'IMG'}},
    confirmCrop: async () => 'NO', specRowImageState: async () => ({found: true, hasImage: true})});
  vm.runInContext(specSource.slice(start, end), c);
  const result = await c.selectSpec(spec, {});
  assert.equal(result.row.hasImage, true);
  assert.equal(searches, 0);
  assert.equal(clicks, 1);
});

test('main images verify all names after a split upload popup has closed', async () => {
  const mainSource = fs.readFileSync(__dirname + '/main_images.js', 'utf8')
    .replace('/*PAYLOAD*/', JSON.stringify({phase: 'after_upload',
      files: ['main-1.jpg', 'main-2.jpg'], names: ['main-1.jpg', 'main-2.jpg']}))
    .replace('/*HELPERS*/', '');
  const frame = {};
  let checked = [];
  const run = vm.runInNewContext('(' + mainSource + ')', {
    dismissKnow: async () => {}, sucaiFrame: () => frame,
    hasUploadResult: async () => false,
    missingSucaiNames: async (_frame, names) => {checked = names; return []},
    retryUntilUploaded: async () => {throw Error('closed popup must not be checked again')},
  });
  const result = JSON.parse(await run({}));
  assert.equal(result.uploaded, true);
  assert.equal(result.verifiedBy, 'library-search');
  assert.deepEqual(Array.from(checked), ['main-1.jpg', 'main-2.jpg']);
});

test('uninitialized uploader reloads once and sets the whole batch', async () => {
  const c = harness();
  const guards = [];
  c.guardLocalFileChooser = async (_frame, enabled) => guards.push(enabled);
  let reloads = 0, waits = 0, uploaded;
  const input = {first(){return this}, async waitFor(){ if (++waits === 1) throw Error('no input'); }, async setInputFiles(files){uploaded=files}};
  const button = {first(){return this}, async waitFor(){}, async evaluate(){}};
  const frame = {url:()=> 'https://example.test/picker', async goto(){reloads++}, locator:()=>input, getByRole:()=>button};
  c.setFilesAnywhere = async () => 'NO_INPUT';
  c.fileInputs = async () => [];
  c.waitUploadStatus = async () => ({found:['old.jpg'], success:false});
  c.retryUntilUploaded = async () => ({uploaded:true});
  const files = ['a.jpg','b.jpg'];
  const result = await c.finishLocalUpload(frame, files, files);
  assert.equal(reloads, 1);
  assert.equal(result.reloaded, true);
  assert.equal(uploaded, files);
  assert.deepEqual(guards, [true, true, false]);
});

test('material cards are clicked once so more than four images remain selected', async () => {
  const cards = Array.from({length: 7}, (_, i) => {
    const card = {innerText: `详情0${i + 1}.jpg`, className: '', clicks: 0};
    const icon = {click() {card.clicks++; card.className = card.className ? '' : 'active'}};
    card.querySelector = () => icon;
    card.click = () => icon.click();
    return card;
  });
  const document = {querySelectorAll: () => cards};
  const c = harness({document});
  const frame = {evaluate: async (fn, names) => fn(names)};
  for (const card of cards) {
    const picked = await c.pickPictureSpaceCards(frame, [card.innerText]);
    assert.equal(picked[0].ok, true);
  }
  assert.equal(cards.filter(card => card.className === 'active').length, 7);
  assert.ok(cards.every(card => card.clicks === 1));
});

test('main image card click does not toggle selection back off', async () => {
  const card = {innerText: '宝贝主图05.jpg', clicks: 0, active: false};
  card.getAttribute = () => null;
  card.querySelectorAll = () => [];
  card.querySelector = selector => selector === 'img' ? {getAttribute: () => 'main.jpg'} : null;
  card.click = () => {card.clicks++; card.active = !card.active};
  const document = {querySelectorAll: () => [card]};
  const c = harness({document});
  const frame = {evaluate: async (fn, name) => fn(name)};
  const selected = await c.clickSucaiCard(frame, '宝贝主图05.jpg');
  assert.equal(selected.ok, true);
  assert.equal(card.clicks, 1);
  assert.equal(card.active, true);
});

test('spec image can retry the clickable image inside a material card', async () => {
  let cardClicks = 0, innerClicks = 0;
  const inner = {className: 'cover', getAttribute: () => 'spec.jpg', click() {innerClicks++}};
  const card = {
    innerText: '颜色01-示例.jpg 800x800',
    getAttribute: () => null,
    querySelectorAll: () => [],
    querySelector: selector => selector === "input[type='checkbox']" ? null : inner,
    click() {cardClicks++},
  };
  const c = harness({document: {querySelectorAll: () => [card]}});
  const frame = {evaluate: async (fn, value) => fn(value)};
  const result = await c.clickSucaiCard(frame, '颜色01-示例.jpg', true);
  assert.equal(result.ok, true);
  assert.equal(cardClicks, 0);
  assert.equal(innerClicks, 1);
});
