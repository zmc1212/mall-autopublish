const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/details.js', 'utf8');
const start = source.indexOf('  async function clearExistingDetails()');
const end = source.indexOf('  if (phase ===', start);

function harness({pending = {}, blocked = false, staysOpen = false} = {}) {
  let visible = true, closed = 0, cleared = 0, probes = 0;
  const close = {first() {return this;}, count: async () => 1, click: async () => {
    closed++; if (!staysOpen) visible = false;
  }};
  const frame = {locator: selector => {assert.equal(selector, '.qn_close_blod'); return close;}};
  const confirm = {or() {return this;}, count: async () => 0};
  const context = vm.createContext({
    editorAfter: async () => ({imgs: probes++ ? 0 : 1}),
    pictureSpaceFrame: () => frame,
    uploadContextVisible: async () => visible,
    assertNoSecurityChallenge: async () => {if (blocked) throw new Error('PAUSE:captcha');},
    collectUploadStatus: async () => pending,
    sleep: async () => {},
    page: {evaluate: async () => {
      assert.equal(visible, false, 'Never clear the editor beneath an open picker');
      cleared++; return {clicked: true};
    }, getByRole: () => confirm},
  });
  vm.runInContext(source.slice(start, end), context);
  return {run: () => context.clearExistingDetails(), counts: () => ({closed, cleared})};
}

test('detail rebuild closes the iframe-owned picker before clearing content', async () => {
  const h = harness();
  assert.equal((await h.run()).cleared, true);
  assert.deepEqual(h.counts(), {closed: 1, cleared: 1});
});

test('detail rebuild leaves active uploads and CAPTCHA untouched', async () => {
  for (const options of [{pending: {uploading: true}}, {pending: {hasComplete: true}}, {blocked: true}]) {
    const h = harness(options);
    await assert.rejects(h.run(), /PAUSE:/);
    assert.deepEqual(h.counts(), {closed: 0, cleared: 0});
  }
});

test('a picker that refuses to close prevents clearing existing details', async () => {
  const h = harness({staysOpen: true});
  await assert.rejects(h.run(), /仍未关闭/);
  assert.deepEqual(h.counts(), {closed: 1, cleared: 0});
});
