const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync(__dirname + '/../../testdata/scripts/image_upload_audit.js', 'utf8');

test('CLI audit works without URL global and can restart without duplicate listeners', async () => {
  const listeners = new Map();
  let bindings = 0;
  const page = {
    exposeBinding: async () => {bindings++;}, addInitScript: async () => {}, frames: () => [],
    on: (event, fn) => {assert.equal(listeners.has(event), false); listeners.set(event, fn);},
    off: (event, fn) => {assert.equal(listeners.get(event), fn); listeners.delete(event);},
  };
  const run = phase => vm.runInNewContext('(' + source.replace('/*PHASE*/', JSON.stringify(phase)) + ')')(page);
  for (let i = 0; i < 2; i++) {
    await run('start');
    const request = {url: () => 'https://stream-upload.taobao.com/api/upload.api?token=do-not-record',
      method: () => 'POST', headers: () => ({}), resourceType: () => 'fetch'};
    listeners.get('request')(request);
    await listeners.get('response')({request: () => request, status: () => 200,
      json: async () => ({ret: ['FAIL_SYS_USER_VALIDATE'], token: 'secret', data: {token: 'secret'}})});
    const audit = await run('stop');
    assert.equal(audit.requests.length, 1);
    assert.equal(audit.requests[0].endpoint, 'https://stream-upload.taobao.com/api/upload.api');
    assert.equal(audit.requests[0].fileUpload, true);
    assert.equal(audit.requests[0].names.length, 0);
    assert.equal(audit.requests[0].result.ret, 'FAIL_SYS_USER_VALIDATE');
    assert.doesNotMatch(JSON.stringify(audit), /token|secret/);
    assert.equal(listeners.size, 0);
  }
  assert.equal(bindings, 1);
});
