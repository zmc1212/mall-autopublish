async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error('UNSAFE:' + page.url());

  const index = Number(PAYLOAD.index);
  const image = PAYLOAD.image;
  const name = fileBase(image);
  const searchKey = name.match(/^qn_[a-f0-9]{24}(?=[_.])/i)?.[0] || name.replace(/\.[^.]+$/, '');
  const phase = PAYLOAD.phase || 'open';
  if (!Number.isInteger(index) || index < 0 || !image) throw new Error('规格行或图片路径无效');
  const cell = page.locator(`td[id="${index}-custom_-1"]`).first();

  // 虚拟滚动表格只渲染视口附近的行；目标行不在 DOM 时逐屏滚动使其渲染，
  // 绑定期间保持该行在视口内；修复轮次里目标行可能在上方，需回顶重扫。
  async function bringRowIntoView(idx) {
    await page.evaluate(async (rowIndex) => {
      const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const cellId = `${rowIndex}-custom_-1`;
      const exists = () => !!document.querySelector(`td[id="${cellId}"]`);
      if (exists()) return;
      let cont = null;
      for (const td of [...document.querySelectorAll('td[id$="-custom_-1"]')]) {
        let el = td.parentElement;
        while (el && el !== document.body) {
          const st = getComputedStyle(el);
          if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { cont = el; break; }
          el = el.parentElement;
        }
        if (cont) break;
      }
      if (!cont) return;
      for (let pass = 0; pass < 2 && !exists(); pass++) {
        if (pass === 1) { cont.scrollTop = 0; await pause(400); }
        let guard = 0;
        while (!exists() && guard++ < 80) {
          const before = cont.scrollTop;
          cont.scrollTop = Math.min(before + Math.max(200, Math.floor(cont.clientHeight * 0.7)), cont.scrollHeight);
          await pause(350);
          if (cont.scrollTop === before) break;
        }
      }
    }, idx);
  }

  if (!(await cell.count())) await bringRowIntoView(index);
  if (!(await cell.count())) throw new Error(`未找到第 ${index + 1} 个商品规格图片单元格`);

  const filled = async () => !!(await cell.locator('.image-item').count());
  const imageSrc = async () => await cell.locator('img.image-item').first().getAttribute('src') || '';
  const popup = page.locator('.sell-component-image-v2-media-popup:visible');
  if (phase === 'open' && !PAYLOAD.forceReplace && await filled()) {
    return JSON.stringify({ index, already: true, saved: true,
      imageSrc: await imageSrc(), verifiedBy: 'existing-sku-row' });
  }
  await assertNoSecurityChallenge();
  if (phase === 'open') {
    if (await popup.count()) throw new Error('单图素材窗仍然打开，无法确认当前规格行');
    const icon = cell.locator('.main-content').first();
    await icon.scrollIntoViewIfNeeded();
    const trigger = icon.locator('[aria-haspopup="true"]').first();
    const clickTarget = await trigger.count() ? trigger : icon;
    await page.keyboard.press('Escape');
    if (await filled()) {
      await icon.hover();
      const replace = page.getByText('替换', { exact: true }).and(page.locator(':visible'));
      for (let poll = 0; poll < 12 && !(await replace.count()); poll++) await sleep(150);
      if (await replace.count() === 1) {
        await replace.evaluate(el => el.click());
      } else if (!(await replace.count())) {
        // Some versions open the picker directly on the image itself.
        await clickTarget.evaluate(el => el.click());
      } else {
        throw new Error(`第 ${index + 1} 行出现多个替换菜单，无法确认目标图片`);
      }
    } else {
      // A menu left by hovering the previous row can cover this cell. Dispatch
      // to this exact element instead of force-clicking through that overlay.
      const empty = icon.locator('.image-empty').first();
      await (await empty.count() ? empty : clickTarget).evaluate(el => el.click());
    }
  }
  try {
    await popup.waitFor({ state: 'visible', timeout: 15000 });
  } catch (error) {
    const diagnostic = await cell.evaluate(el => ({html: el.innerHTML.slice(0, 1800),
      text: el.innerText, id: el.id}));
    throw new Error(`第 ${index + 1} 行规格图素材窗未打开：` + JSON.stringify(diagnostic));
  }
  const iframe = popup.locator('iframe').first();
  await iframe.waitFor({ state: 'attached', timeout: 15000 });
  let frame = null;
  for (let attempt = 0; attempt < 30 && !frame; attempt++) {
    const handle = await iframe.elementHandle();
    try { frame = handle ? await handle.contentFrame() : null; }
    finally { if (handle) await handle.dispose(); }
    if (!frame) await sleep(300);
  }
  if (!frame) throw new Error('单图素材库 iframe 未加载');
  await frame.locator('button').filter({ hasText: '本地上传' }).first()
    .waitFor({ state: 'attached', timeout: 15000 });
  await frame.locator('input[placeholder*="搜索"]').first()
    .waitFor({ state: 'attached', timeout: 15000 });
  await sleep(500);
  if (phase === 'open') return JSON.stringify({ index, ready: true });

  async function selectAndConfirm(allowSearch) {
    let selected = await clickSucaiCard(frame, name, true, true);
    let search = 'VISIBLE';
    const confirm = frame.locator('button[class*="Footer_selectOk"]').last();
    const readyToConfirm = async () => {
      for (let i = 0; i < 12; i++) {
        const ready = await confirm.evaluate(el => !el.disabled).catch(() => false);
        if (ready) return true;
        await sleep(250);
      }
      return false;
    };
    let ready = selected.ok && await readyToConfirm();
    if (!ready && allowSearch && !selected.ok) {
      search = await searchSucai(frame, searchKey, 8, false);
      await assertNoSecurityChallenge();
      selected = await clickSucaiCard(frame, name, true, true);
      ready = selected.ok && await readyToConfirm();
    }
    if (!ready) return { found: false, search, reason: selected.ok ? 'NOT_SELECTED' : (selected.reason || 'NOT_FOUND'),
      selected, target: name, searchKey, candidates: await listSucaiPics(frame) };
    if (!selected.src) throw new Error('目标素材缺少图片地址，无法核验规格图');
    const imageKey = src => String(src || '').replace(/^https?:/i, '').split(/[?#]/)[0]
      .replace(/(\.(?:jpg|jpeg|png|webp))_.*$/i, '$1');
    await assertNoSecurityChallenge();
    await confirm.click({ timeout: 8000 });
    for (let i = 0; i < 40; i++) {
      if (await filled() && !(await popup.count())) {
        const actual = await imageSrc();
        if (imageKey(actual) !== imageKey(selected.src)) {
          await sleep(250);
          continue;
        }
        return { found: true, saved: true, search, imageSrc: await imageSrc(),
          selectedSrc: selected.src, verifiedBy: 'sku-row-source' };
      }
      await sleep(250);
    }
    throw new Error(`第 ${index + 1} 行规格图选择后未写入SKU表格`);
  }

  if (phase === 'finish') {
    if (await hasUploadResult()) {
      const closed = await waitUploadResultClosed(30);
      if (closed !== 'CLOSED') throw new Error('单图上传结果弹窗未关闭');
    }
    const result = await selectAndConfirm(true);
    if (!result.found) throw new Error(`第 ${index + 1} 行上传后素材选择失败：` + JSON.stringify(result));
    return JSON.stringify({ index, ...result, uploaded: true });
  }

  // On retry, query the stable content identity before uploading again.
  const existing = await selectAndConfirm(!!PAYLOAD.forceReplace);
  if (existing.found) return JSON.stringify({ index, ...existing, uploaded: false });
  const uploaded = await finishLocalUpload(frame, [image], [name], { ...PAYLOAD, uploadBatchSize: 1 });
  if (uploaded.uploaded === false && !uploaded.retryable) {
    // The upload result can close before the picker reports completion. The
    // finish phase checks the library and the actual SKU cell before failing.
  }
  return JSON.stringify({ index, needsFinish: true, uploadPolicy: uploaded.uploadPolicy,
    uploaded: uploaded.uploaded, verifiedBy: uploaded.verifiedBy || '' });
}
