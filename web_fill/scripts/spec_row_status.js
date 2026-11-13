async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const sales = await readSalesSpecImages(PAYLOAD.skus || []);
  if (sales) return JSON.stringify(sales);
  // SKU 表格是虚拟滚动（DOM 只渲染视口附近约一屏的行），审计必须逐屏滚动
  // 累加全部行后再还原滚动位置，否则 total/missing 恒为一屏的行数。
  // 并发下其他 worker 的脚本会把本页签切到后台：后台页签渲染帧暂停、真实
  // scroll 事件不派发，虚拟列表永不重渲染，整轮审计只能采到起始一屏
  // （2026-10-04 复现：预期 37 行只读到 17 行）。因此滚动循环放在 Node 层，
  // 每步检测 visibilityState；发现被切后台就 ensureFront 夺回前台，并原地
  // 轻移一格触发真实 scroll 把当前窗口补渲染出来后重采，再写 scrollTop 后
  // 补发一次合成 scroll 事件兜底（对直接挂 scroll 监听的虚拟列表，
  // 后台页签里只有合成事件能同步触发重渲染）。
  // 自定义规格图列为 <n>-custom_-1，0 基行号；<n>-skuPicture 是搜索
  // 主图。销售属性上的规格图已在上面的 readSalesSpecImages 中处理。
  const readCells = () => page.evaluate(() => {
    const cells = [...document.querySelectorAll('td[id$="-custom_-1"]')]
      .filter((el) => /^\d+-custom_-1$/.test(el.id));
    const rows = cells.map((el) => ({
      id: el.id,
      filled: !!el.querySelector('.image-item, img[src]'),
      src: (el.querySelector('img.image-item') || el.querySelector('img[src]'))?.getAttribute('src') || '',
    }));
    let cont = null;
    for (const td of cells) {
      let el = td.parentElement;
      while (el && el !== document.body) {
        const st = getComputedStyle(el);
        if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { cont = el; break; }
        el = el.parentElement;
      }
      if (cont) break;
    }
    return {
      rows,
      hidden: document.visibilityState !== 'visible',
      hasCont: !!cont,
      top: cont ? cont.scrollTop : 0,
      clientHeight: cont ? cont.clientHeight : 0,
      scrollHeight: cont ? cont.scrollHeight : 0,
    };
  });
  const scrollTo = (value) => page.evaluate((top) => {
    let cont = null;
    for (const td of [...document.querySelectorAll('td[id$="-custom_-1"]')])
      if (/^\d+-custom_-1$/.test(td.id)) {
        let el = td.parentElement;
        while (el && el !== document.body) {
          const st = getComputedStyle(el);
          if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { cont = el; break; }
          el = el.parentElement;
        }
        if (cont) break;
      }
    if (!cont) return false;
    cont.scrollTop = top;
    cont.dispatchEvent(new Event('scroll'));
    return true;
  }, value);

  await ensureFront();
  const seen = new Map();
  const first = await readCells();
  for (const row of first.rows) seen.set(row.id, row);
  if (first.hasCont) {
    const startTop = first.top;
    const step = Math.max(200, Math.floor(first.clientHeight * 0.7));
    let guard = 0;
    let lastTop = -1;
    let stuck = 0;
    let recoveries = 0;
    await scrollTo(0);
    while (guard++ < 80) {
      await sleep(400);
      let info = await readCells();
      for (const row of info.rows) seen.set(row.id, row);
      if (info.hidden) {
        if (++recoveries > 6) break;
        // 本步跑在后台：当前窗口大概率没有重渲染。夺回前台并原地轻移一格，
        // 用真实 scroll 事件补渲染当前窗口后重采；本步不推进、不计停滞。
        await ensureFront();
        await sleep(200);
        const probe = await readCells();
        if (!probe.hasCont) break;
        await scrollTo(probe.top > 0 ? probe.top - 1 : probe.top + 1);
        await sleep(120);
        await scrollTo(probe.top);
        await sleep(280);
        const again = await readCells();
        for (const row of again.rows) seen.set(row.id, row);
        continue;
      }
      if (!info.hasCont) break;
      if (info.top >= info.scrollHeight - info.clientHeight - 2) break;
      if (info.top === lastTop) { if (++stuck >= 3) break; } else { stuck = 0; lastTop = info.top; }
      await scrollTo(Math.min(info.top + step, info.scrollHeight));
    }
    await scrollTo(startTop);
    await sleep(300);
    const final = await readCells();
    for (const row of final.rows) seen.set(row.id, row);
  }
  const cells = [...seen.values()]
    .sort((a, b) => Number(a.id.split('-')[0]) - Number(b.id.split('-')[0]));
  return JSON.stringify({
    total: cells.length,
    filled: cells.filter((el) => el.filled).length,
    missing: cells.filter((el) => !el.filled).map((el) => Number(el.id.split('-')[0]) + 1),
    sources: cells.map((el) => ({ index: Number(el.id.split('-')[0]) + 1, src: el.src })),
  });
}
