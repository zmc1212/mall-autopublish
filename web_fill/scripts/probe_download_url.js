async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 1) hover 下载按钮看是否解锁
  const hoverState = await (async () => {
    const btn = page.locator("button.download-template-btn").first();
    if (!(await btn.count())) return { present: false };
    await btn.hover({ force: true }).catch(() => {});
    await sleep(600);
    return await btn.evaluate((el) => ({ disabled: el.disabled, html: el.outerHTML.slice(0, 200) }));
  })();
  // 2) bundle 搜索模板下载相关字符串
  const urls = await page.evaluate(() => performance.getEntriesByType("resource")
    .map((e) => e.name).filter((u) => /\.js(\?|$)/.test(u)).slice(0, 80));
  const hits = [];
  for (const url of urls) {
    try {
      const text = await page.evaluate(async (u) => {
        const r = await fetch(u, { credentials: "include" });
        if (!r.ok) return "";
        return await r.text();
      }, url);
      for (const key of ["点此下载模版", "downloadTemplate", "templateUrl", "skuTemplateDown", "exportTemplate"]) {
        let idx = text.indexOf(key);
        if (idx >= 0) {
          hits.push({ key, url: url.slice(-70), around: text.slice(Math.max(0, idx - 350), idx + 500) });
          break;
        }
      }
      if (hits.length >= 4) break;
    } catch (e) { /* skip */ }
  }
  return JSON.stringify({ hoverState, hits: hits.slice(0, 4) }, null, 1);
}
