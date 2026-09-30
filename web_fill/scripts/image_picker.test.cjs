const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

async function phase(script, payload) {
  let detached = false;
  let dismissOptions;
  let uploads = 0;
  const frame = {};
  const names = payload.names;
  const keepFrame = () => {
    if (detached) throw new Error('frame.evaluate: Frame was detached');
  };
  const context = vm.createContext({
    page: {
      evaluate: async () => ({imgs: names.length, empty: 0, dialog: false}),
      mouse: {click: async () => {}},
    },
    dismissKnow: async options => {
      dismissOptions = options;
      if (!options || options.escape !== false) detached = true;
    },
    sleep: async () => {},
    sucaiFrame: () => frame,
    pictureSpaceFrame: () => frame,
    openMainPicker: async () => 'empty',
    waitFrame: async () => frame,
    listSucaiPics: async () => payload.libraryNames ?? names,
    waitUploadResultClosed: async () => 'CLOSED',
    hasUploadResult: async () => false,
    missingSucaiNames: async () => [],
    pictureIdentityQuery: name => name,
    assertNoSecurityChallenge: async () => {},
    uploadContextVisible: async () => true,
    clearPictureSpaceSelection: async () => {},
    waitUploadStatus: async () => ({}),
    listPictureSpaceNames: async () => { keepFrame(); return names; },
    missingPictureNames: (listed, wanted) => wanted.filter(n => !listed.includes(n)),
    clickSucaiCard: async () => { keepFrame(); return {ok: true}; },
    pickPictureSpaceCards: async (_frame, wanted) => {
      keepFrame(); return wanted.map(name => ({name, ok: true}));
    },
    confirmCrop: async () => 'NO',
    confirmPictureSpace: async () => 'OK',
    finishLocalUpload: async () => { uploads++; throw new Error('unexpected upload'); },
  });
  const source = fs.readFileSync(__dirname + '/' + script, 'utf8')
    .replace('/*PAYLOAD*/', JSON.stringify(payload)).replace('/*HELPERS*/', '');
  const run = vm.runInContext('(' + source + ')', context);
  const result = JSON.parse(await run(context.page));
  assert.equal(dismissOptions.escape, false);
  assert.equal(detached, false);
  assert.equal(uploads, 0, 'Verification/binding must not resubmit files');
  return result;
}

test('main-image binding preserves the picker left open by uploading', async () => {
  const result = await phase('main_images.js', {phase: 'select', names: ['a.jpg', 'b.jpg']});
  assert.equal(result.selected.length, 2);
  assert.equal(result.slot.imgs, 2);
});

test('detail receipt verification preserves the existing picker', async () => {
  const result = await phase('details.js', {phase: 'after_upload', names: ['a.jpg']});
  assert.equal(result.uploaded, true);
  assert.equal(result.hadFrame, true);
});

test('detail binding preserves the picker and does not upload again', async () => {
  const result = await phase('details.js', {phase: 'select', names: ['a.jpg', 'b.jpg']});
  assert.equal(result.after.imgs, 2);
});

test('main images with content-addressed names reuse existing materials', async () => {
  const name = 'qn_' + 'a'.repeat(24) + '_main.jpg';
  const result = await phase('main_images.js', {phase: 'open', contentAddressedMedia: true,
    names: [name], files: [name]});
  assert.equal(result.uploaded, true);
  assert.equal(result.via, 'library');
});

test('library-only mode refuses missing content instead of uploading again', async () => {
  const name = 'qn_' + 'b'.repeat(24) + '_main.jpg';
  const result = await phase('main_images.js', {phase: 'open', contentAddressedMedia: true,
    libraryOnly: true, libraryNames: [], names: [name], files: [name]});
  assert.equal(result.uploaded, false);
  assert.equal(result.error, 'MISSING_LIBRARY_IMAGES');
});
