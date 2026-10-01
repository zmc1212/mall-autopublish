async page => JSON.stringify(await page.evaluate(async () => {
  // SKU 表格是虚拟滚动（DOM 只渲染视口附近约一屏的行），审计必须逐屏滚动
  // 累加全部行后再还原滚动位置，否则 total/missing 恒为一屏的行数。
  const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const readCells = () => [...document.querySelectorAll('td[id$="-custom_-1"]')]
    .filter(el => /^\d+-custom_-1$/.test(el.id));
  const snapshot = () => readCells().map(el => ({
    id: el.id,
    filled: !!el.querySelector('.image-item'),
    src: el.querySelector('img.image-item')?.getAttribute('src') || '',
  }));
  const seen = new Map();
  const collect = () => { for (const cell of snapshot()) seen.set(cell.id, cell); };
  let cont = null;
  for (const td of readCells()) {
    let el = td.parentElement;
    while (el && el !== document.body) {
      const st = getComputedStyle(el);
      if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { cont = el; break; }
      el = el.parentElement;
    }
    if (cont) break;
  }
  if (!cont) {
    collect();
  } else {
    const startTop = cont.scrollTop;
    cont.scrollTop = 0;
    await pause(400);
    collect();
    const step = Math.max(200, Math.floor(cont.clientHeight * 0.7));
    let guard = 0;
    while (guard++ < 80) {
      const before = cont.scrollTop;
      cont.scrollTop = Math.min(before + step, cont.scrollHeight);
      await pause(400);
      collect();
      if (cont.scrollTop >= cont.scrollHeight - cont.clientHeight - 2) break;
      if (cont.scrollTop === before) break;
    }
    cont.scrollTop = startTop;
    await pause(300);
    collect();
  }
  const cells = [...seen.values()];
  return {
    total: cells.length,
    filled: cells.filter(el => el.filled).length,
    missing: cells.filter(el => !el.filled).map(el => Number(el.id.split('-')[0]) + 1),
    sources: cells.map(el => ({ index: Number(el.id.split('-')[0]) + 1, src: el.src })),
  };
}))
