const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');

// 直接内联真实 _helpers.inc.js（不是 stub）：ensureFront 是并发入库
// "后台页签点击必超时"修复的核心，必须测真实实现。
function helpers(page) {
  const source = fs.readFileSync(path.join(__dirname, '_helpers.inc.js'), 'utf8');
  return eval(`(async (page, PAYLOAD) => { ${source} })`)(page, {});
}

test('ensureFront brings a hidden tab to front and waits with timer polling', async () => {
  const calls = [];
  const page = {
    evaluate: async () => 'hidden',
    bringToFront: async () => { calls.push('front'); },
    waitForFunction: async (_fn, _arg, options) => { calls.push(`wait:${options.polling}`); },
  };
  await helpers(page);
  // waitForFunction 必须用 setTimeout 轮询：默认 rAF 轮询在隐藏页永远不触发。
  assert.deepEqual(calls, ['front', 'wait:100']);
});

test('ensureFront skips an already visible tab', async () => {
  const calls = [];
  const page = {
    evaluate: async () => 'visible',
    bringToFront: async () => { calls.push('front'); },
    waitForFunction: async () => { calls.push('wait'); },
  };
  await helpers(page);
  assert.deepEqual(calls, []);
});

test('ensureFront swallows page errors instead of failing the script', async () => {
  const page = {
    evaluate: async () => { throw new Error('page closed'); },
  };
  await assert.doesNotReject(helpers(page));
});
