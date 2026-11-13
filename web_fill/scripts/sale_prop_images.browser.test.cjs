const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const {chromium} = require('../../.work/node_modules/playwright-core');
const helpers = fs.readFileSync(__dirname + '/_helpers.inc.js', 'utf8');
const load = (file, payload = {}) => new Function('return (' + fs.readFileSync(__dirname + '/' + file, 'utf8')
  .replace('/*PAYLOAD*/', JSON.stringify(payload)).replace('/*HELPERS*/', () => helpers) + ')')();
const skus = [{name: '单盒', image: 'a.png', file: 'a.png'}, {name: '端盒', image: 'b.png', file: 'b.png'}];
const html = `<div id="sell-field-saleProp"><div class="common-wrap"><span class="props-label">款式描述(2)</span>
  <ul>${['单盒', '端盒'].map(name => `<li><div class="sell-color-option-image-upload"><div class="sell-color-option-image-empty">图片</div></div><input value="${name}"></li>`).join('')}</ul></div></div>
  <table><tr><td id="0-skuPicture"><img src="/search-a.png"></td></tr><tr><td id="1-skuPicture"><img src="/search-b.png"></td></tr></table>`;

test('sales photos are matched by value and never by the populated search-main cells', async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();await page.setContent(html);
    let result = JSON.parse(await load('spec_row_status.js', {skus})(page));
    assert.equal(result.total, 2);assert.equal(result.filled, 0);assert.deepEqual(result.missing, [1, 2]);
    await page.evaluate(() => {const boxes=document.querySelectorAll('.sell-color-option-image-upload');
      boxes[1].innerHTML='<img src="/spec-b.png">';boxes[0].innerHTML='<img src="/spec-a.png">';
      const ul=document.querySelector('ul');ul.prepend(ul.lastElementChild);});
    result = JSON.parse(await load('spec_row_status.js', {skus})(page));
    assert.deepEqual(result.sources.map(row => row.src), ['/spec-a.png', '/spec-b.png']);
    const unknown = JSON.parse(await load('spec_row_status.js', {skus: [{name: '未知'}]})(page));
    assert.equal(unknown.total, 0);assert.deepEqual(unknown.missing, [1]);
  } finally {await browser.close();}
});

for (const shared of [false, true]) test('blind-box batch picker preserves search images; shared photo: ' + shared, async () => {
  const browser = await chromium.launch({headless: true,
    executablePath: process.env.CHROME_PATH || 'C:/Program Files/Google/Chrome/Application/chrome.exe'});
  try {
    const page = await browser.newPage();
    await page.route('**/*', route => route.request().url().includes('sucai-selector') ? route.fulfill({contentType:'text/html; charset=utf-8', body:
      `<input placeholder="搜索"><div class="PicList_PicturesShow_main-show__QVvZn"><img src="/spec-a.png">${shared ? '<input type="checkbox">' : ''}a.png</div>
       <div class="PicList_PicturesShow_main-show__QVvZn"><img src="/spec-b.png">b.png</div><script>
       document.querySelectorAll('${shared ? 'input[type=checkbox]' : 'img'}').forEach(control=>control.on${shared ? 'change' : 'click'}=()=>{
         if (control.type === 'checkbox' && !control.checked) return;
         const img = control.tagName === 'IMG' ? control : control.parentElement.querySelector('img');
         parent.document.querySelector('li.sku-item.focused .sku-images-area').innerHTML='<img src="'+img.getAttribute('src')+'" width="36" height="36">';
       });</script>`}) : route.fulfill({contentType:'text/html', body:'<html></html>'}));
    await page.goto('http://spec.test/publish');await page.setContent(html);
    await page.evaluate(() => {
      document.querySelectorAll('.sell-color-option-image-empty').forEach(box => box.onclick=()=>{
        const dialog=document.createElement('div');dialog.className='batch-fill-sku-image-dialog';
        dialog.innerHTML='<h2>批量填充规格主图</h2><iframe src="/sucai-selector?handleId=test"></iframe>'+['单盒','端盒'].map((name,i)=>
          '<li class="sku-item '+(i===0?'focused':'')+'"><div class="sku-text">'+name+'</div><div class="sku-images-area"></div></li>').join('')+'<button>确定</button>';
        document.body.append(dialog);dialog.querySelectorAll('li').forEach(li=>li.onclick=()=>{
          dialog.querySelectorAll('li').forEach(other=>other.classList.remove('focused'));li.classList.add('focused');});
        dialog.querySelector('button').onclick=()=>{
          dialog.querySelectorAll('li').forEach((li,i)=>document.querySelectorAll('.sell-color-option-image-upload')[i].innerHTML=li.querySelector('.sku-images-area').innerHTML);dialog.remove();};
      });
    });
    const payload={skus: shared ? skus.map(sku => ({...sku, image:'a.png', file:'a.png'})) : skus, phase:'open_library'};
    const opened=JSON.parse(await load('spec_images.js',payload)(page));assert.equal(opened.dialog,true);
    const result=JSON.parse(await load('spec_images.js',{...payload,phase:'bind'})(page));
    assert.equal(result.saved,true,JSON.stringify(result));
    assert.deepEqual(result.persisted.rows.map(row=>row.src),['/spec-a.png',shared ? '/spec-a.png' : '/spec-b.png']);
    assert.deepEqual(await page.locator('td img').evaluateAll(imgs=>imgs.map(img=>img.getAttribute('src'))),['/search-a.png','/search-b.png']);
  } finally {await browser.close();}
});
