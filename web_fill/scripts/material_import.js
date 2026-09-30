async page => {
  const P = /*PAYLOAD*/;
  const pause = text => { throw new Error('PAUSE:' + text); };
  const drawerSelector = '.next-drawer[class*=material-batch]:visible';
  const drawer = () => page.locator(drawerSelector);
  const imageKey = value => String(value || '').split('?')[0].replace(/_(?:\d+x\d+).*$/, '');

  const imageBodies = new Map();
  const imageErrors = new Map();
  async function imageBody(value) {
    if (!imageBodies.has(value)) imageBodies.set(value, (async () => {
      try {
        // Playwright CLI's sandbox has no global URL. Parse in the browser,
        // which provides the native URL API, before making any request.
        const allowed = await page.evaluate(value => {
          try {
            const url = new URL(value);
            return url.protocol === 'https:' && !url.username && !url.password
              && (url.hostname === 'alicdn.com' || url.hostname.endsWith('.alicdn.com'));
          } catch (_) { return false; }
        }, value);
        if (!allowed) { imageErrors.set(value, 'invalid-or-disallowed-url'); return null; }
        const response = await page.request.get(value, {timeout:10000, maxRedirects:0});
        try {
          if (!response.ok() || !/^image\//i.test(response.headers()['content-type'] || '')
              || Number(response.headers()['content-length']) > 20 * 1024 * 1024) {
            imageErrors.set(value, `http-or-image-response:${response.status ? response.status() : 'unknown'}`);
            return null;
          }
          const body = await response.body();
          if (!body.length || body.length > 20 * 1024 * 1024) imageErrors.set(value, 'empty-or-oversized-body');
          return body.length && body.length <= 20 * 1024 * 1024 ? body : null;
        } finally { await response.dispose(); }
      } catch (error) {
        imageErrors.set(value, String(error).slice(0, 240));
        return null;
      }
    })());
    return imageBodies.get(value);
  }

  async function imageComparison(expected, actual) {
    if (expected && actual && imageKey(expected) === imageKey(actual)) return 'same';
    const [left, right] = await Promise.all([imageBody(expected), imageBody(actual)]);
    if (!left || !right) return 'unavailable';
    return left.equals(right) ? 'same' : 'different';
  }

  async function guard() {
    if (!/^https:\/\/myseller\.taobao\.com\/home\.htm\/SellManage\/all_skucenter(?:\?|$)/.test(page.url())) pause('不在官方 SKU 管理页');
    const blocked = await page.evaluate(() => {
      const text = document.body?.innerText || '';
      return /请拖动.*滑块|拖动滑块|请滑动验证码|安全验证|(?:访问|操作)过于频繁|请完成验证|请登录|扫码登录/.test(text)
        || [...document.querySelectorAll('iframe')].some(x => x.getBoundingClientRect().width && /captcha|punish|nocaptcha/.test(x.src));
    });
    if (blocked) pause('登录或安全验证阻断，请在浏览器处理后续跑');
  }

  async function state(preview) {
    return page.evaluate(({preview, itemId}) => {
      const visible = x => x.getBoundingClientRect().width > 0 && x.getBoundingClientRect().height > 0;
      const roots = [...document.querySelectorAll('.next-drawer[class*=material-batch]')].filter(visible);
      const root = preview ? roots.find(x => x.innerText.includes('素材导入确认')) : document;
      if (!root) return {ready:false, drawerOpen:roots.length > 0};
      const text = root.innerText || '';
      if (preview) {
        // Product IDs in the confirmation sidebar; SKU IDs are checked separately.
        const ids = [...text.matchAll(/(?:商品ID\s*|ID\s*[:：]\s*)(\d{8,20})/g)].map(x => x[1]);
        if (!ids.includes(itemId)) return {ready:true, wrongItem:true, rows:[]};
      }
      const rows = [];
      for (const table of root.querySelectorAll('table')) {
        if (!preview && table.closest('.next-drawer')) continue;
        const headers = [...table.querySelectorAll('thead th')].map(x => x.innerText.trim());
        const first = [...table.querySelectorAll('tr')].find(tr => tr.querySelector('th'));
        const labels = headers.length ? headers : [...(first?.querySelectorAll('th,td') || [])].map(x => x.innerText.trim());
        const infoIndex = labels.indexOf('SKU信息'), imageIndex = labels.indexOf('搜索主图');
        const priceIndex = labels.indexOf('价格'), stockIndex = labels.findIndex(x => /^(库存|数量)$/.test(x));
        const titleIndex = labels.indexOf('搜索标题');
        const attributesIndex = labels.findIndex(x => x === '属性' || x === 'SKU属性');
        const merchantIndex = labels.indexOf('商家编码');
        if ([infoIndex, imageIndex, priceIndex, stockIndex, titleIndex].some(x => x < 0)) continue;
        let group = '';
        for (const tr of table.querySelectorAll('tbody tr')) {
          if (tr.hasAttribute('data-item-id')) group = tr.getAttribute('data-item-id');
          const cells = [...tr.querySelectorAll(':scope > td')];
          if (cells.length !== labels.length) continue;
          if (!preview && group !== itemId) continue;
          const info = cells[infoIndex].innerText.trim();
          const id = info.match(/ID\s*[:：]\s*(\d{8,20})/);
          if (!id) continue;
          const name = info.slice(0, id.index).trim();
          const images = [...cells[imageIndex].querySelectorAll('img')].filter(x => x.getAttribute('src'));
          const number = index => (cells[index].innerText.replace(/,/g, '').match(/\d+(?:\.\d+)?/) || [])[0] || '';
          rows.push({name, sku_id:id[1], image:images.length === 1 ? images[0].src : '',
            price:number(priceIndex), stock:number(stockIndex), search_title:cells[titleIndex].innerText.trim(),
            ...(attributesIndex >= 0 ? {attributes_text:cells[attributesIndex].innerText.trim()} : {}),
            ...(merchantIndex >= 0 ? {merchant_code:cells[merchantIndex].innerText.trim()} : {})});
        }
      }
      const titleNode = document.querySelector(`tr.sku-group-header-row[data-item-id="${itemId}"] .sku-group-header-title`);
      return {ready:true, rows, title:titleNode?.innerText.trim() || '', drawerOpen:roots.length > 0};
    }, {preview, itemId:P.item_id});
  }

  async function closeEmptyImportDrawer() {
    const opened = drawer();
    if (!await opened.count()) return;
    if (await opened.count() !== 1) pause('存在多个素材导入窗口，请核对原任务');
    const empty = await opened.evaluate(root => {
      const files = [...root.querySelectorAll('input[type=file]')];
      const submit = [...root.querySelectorAll('button')].filter(x => x.innerText.trim() === '确认上传');
      return root.classList.contains('material-batch-import-drawer')
        && !!root.querySelector('.material-batch-upload-zone')
        && files.length === 1 && files[0].files?.length === 0
        && submit.length === 1 && submit[0].disabled
        && !root.querySelector('img, table, [role=progressbar], .next-loading, .next-upload-list-item')
        && !/素材导入确认|正在识别|识别中|正在上传|上传中|已上传|采纳|重试|失败/.test(root.innerText);
    });
    if (!empty) pause('已有素材导入任务或已选文件，保留页面和断点，禁止自动重传');
    // The template picker is read-only and can overlay an otherwise empty drawer.
    const template = page.getByRole('dialog').filter({
      has: page.getByRole('heading', {name:'下载模版', exact:true}),
    });
    if (await template.count() > 1) pause('模板窗口不唯一，请核对');
    if (await template.count()) await template.getByRole('button', {name:'取消', exact:true}).click();
    await guard();
    await opened.getByRole('button', {name:'取消', exact:true}).click();
    await opened.waitFor({state:'hidden', timeout:5000});
  }

  async function baseline() {
    await page.getByRole('button', {name:'素材批量导入', exact:true}).waitFor({timeout:20000});
    await guard();
    await closeEmptyImportDrawer();
    // Exact data-item-id scopes rows independently of duplicate product titles.
    async function locate() {
      let result = await state(false);
      if (result.rows.length) return result;
      // The sidebar can contain the item while its virtualized SKU rows are
      // not mounted yet. Select its read-only navigation entry, never its
      // checkbox or an upload/submit button.
      const entry = page.locator('.sku-table-item-id').filter({
        hasText: new RegExp('^商品ID\\s*' + P.item_id + '$'),
      });
      try { await entry.waitFor({state:'visible', timeout:5000}); } catch (_) { return result; }
      await guard();
      if (await entry.count() !== 1) pause('目标商品导航入口不唯一');
      await entry.click();
      for (let i=0; i<12; i++) {
        await guard();
        result = await state(false);
        if (result.rows.length) return result;
        await page.waitForTimeout(250);
      }
      return result;
    }
    let result = await locate();
    if (!result.rows.length) {
      await page.reload({waitUntil:'domcontentloaded', timeout:20000});
      await page.getByRole('button', {name:'素材批量导入', exact:true}).waitFor({timeout:20000});
      await guard();
      result = await locate();
    }
    if (!result.rows.length) pause('当前列表未找到目标商品，请在 SKU 管理页定位商品后续跑');
    if (result.title !== P.title) pause(`目标商品 ID 的标题与输入不符（页面商品：${result.title || '未知'}）`);
    return result;
  }

  function compare(rows, originals, requireImage) {
    if (rows.length !== originals.length || !rows.length) pause('确认页 SKU 数量不符');
    const used = new Set();
    for (const row of rows) {
      const old = originals.find(x => x.sku_id === row.sku_id && x.name === row.name);
      if (!old || used.has(row.sku_id)) pause('确认页包含额外或重复 SKU');
      used.add(row.sku_id);
      if (row.price !== old.price && Number(row.price) !== Number(old.price)) pause('价格变化');
      if (Number(row.stock) !== Number(old.stock) || row.search_title !== old.search_title) pause('库存或搜索标题变化');
      for (const key of ['attributes_text', 'merchant_code']) {
        if (key in old && row[key] !== old[key]) pause('属性或商家编码变化或无法读取');
      }
      if (requireImage && !row.image) pause('SKU 缺少搜索主图');
    }
  }

  await guard();
  if (P.phase === 'inspect') return JSON.stringify({baseline:await state(false), preview:await state(true)});
  if (P.phase === 'baseline') return JSON.stringify(await baseline());
  if (P.phase === 'upload') {
    const current = await baseline();
    compare(current.rows, P.baseline, false);
    // Restrict selection to this item's sidebar checkbox, clearing prior selection.
    const card = page.locator('.sku-table-item').filter({has:page.locator('.sku-table-item-id', {hasText:new RegExp('^商品ID\\s*' + P.item_id + '$')})});
    if (await card.count() !== 1) pause('商品选择入口不唯一');
    const checked = page.locator('input[type=checkbox]:checked');
    for (let i = await checked.count() - 1; i >= 0; i--) await checked.nth(i).uncheck();
    await card.locator('input[type=checkbox]').check();
    await page.getByRole('button', {name:'素材批量导入', exact:true}).click();
    await drawer().waitFor({timeout:10000});
    const input = drawer().locator('input[type=file][webkitdirectory]');
    if (await input.count() !== 1) pause('未找到唯一文件夹上传控件');
    await input.setInputFiles(P.folder, {timeout:20000});
    await guard();
    await drawer().getByRole('button', {name:'确认上传', exact:true}).click({timeout:15000});
    return JSON.stringify({uploaded:true});
  }
  if (P.phase === 'preview') {
    const result = await state(true);
    if (result.wrongItem) pause('素材确认商品 ID 不符');
    if (!result.ready && !result.drawerOpen) pause('没有待处理素材抽屉；上传结果不明确，停止自动重传');
    return JSON.stringify(result);
  }
  if (P.phase === 'adopt') {
    const result = await state(true);
    if (!result.ready || result.wrongItem) pause('缺少目标商品确认页');
    compare(result.rows, P.baseline, true);
    if (JSON.stringify(result.rows) !== JSON.stringify(P.preview)) pause('预览内容已变化');
    await guard();
    await drawer().getByRole('button', {name:'采纳', exact:true}).click({timeout:10000});
    await drawer().waitFor({state:'hidden', timeout:20000});
    return JSON.stringify({adopted:true});
  }
  if (P.phase === 'verify') {
    if (await drawer().count()) pause('采纳结果待核实，保留确认页');
    // Reload to verify persisted server state, rather than optimistic UI only.
    await page.reload({waitUntil:'domcontentloaded', timeout:20000});
    await page.getByRole('button', {name:'素材批量导入', exact:true}).waitFor({timeout:20000});
    let result;
    for (let i=0; i<8; i++) {
      await guard();
      result = await state(false);
      if (result.rows.length === P.preview.length && result.rows.every(row => {
        const expected = P.preview.find(x => x.sku_id === row.sku_id);
        return expected && imageKey(expected.image) === imageKey(row.image) && row.image;
      })) {
        compare(result.rows, P.baseline, true);
        return JSON.stringify(result);
      }
      await page.waitForTimeout(1000);
    }
    const rows = result?.rows || [];
    if (rows.length !== P.preview.length) {
      pause(`商品 ${P.item_id} 已入库；刷新后仅读取到 ${rows.length}/${P.preview.length} 个 SKU，搜索主图核验未完成，保留断点供复核`);
    }
    compare(rows, P.baseline, false);
    const missing = rows.filter(row => !row.image);
    const examples = list => list.slice(0, 3).map(row => `${row.name}（SKU ${row.sku_id}）`).join('、');
    if (missing.length) {
      pause(`商品 ${P.item_id} 已入库；${rows.length - missing.length}/${rows.length} 个 SKU 已有搜索主图，${missing.length} 个缺图：${examples(missing)}；保留断点，未重新上传或采纳`);
    }
    const comparisons = await Promise.all(rows.map(async row => ({row,
      status:await imageComparison(P.preview.find(x => x.sku_id === row.sku_id)?.image, row.image)})));
    const different = comparisons.filter(x => x.status === 'different').map(x => x.row);
    const unavailable = comparisons.filter(x => x.status === 'unavailable').map(x => x.row);
    if (!different.length && !unavailable.length) {
      return JSON.stringify({...result, imageVerification:'identical-content'});
    }
    const reasons = [];
    if (different.length) reasons.push(`${different.length} 个与采纳前确认页的图片内容不一致：${examples(different)}`);
    if (unavailable.length) reasons.push(`${unavailable.length} 个图片地址不同且内容无法核验：${examples(unavailable)}`);
    const diagnostics = imageErrors.size ? `；核验诊断：${JSON.stringify([...imageErrors].slice(0, 3))}` : '';
    pause(`商品 ${P.item_id} 已入库；${rows.length} 个 SKU 均有搜索主图，但 ${reasons.join('；')}；保留断点，未重新上传或采纳${diagnostics}`);
  }
  pause('未知素材导入阶段');
}
