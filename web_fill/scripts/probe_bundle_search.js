async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const urls = await page.evaluate(() => performance.getEntriesByType("resource")
    .map((e) => e.name).filter((u) => /\.js(\?|$)/.test(u) && /g\.alicdn\.com|taobao\.com/.test(u)).slice(0, 60));
  const hits = [];
  for (const url of urls) {
    try {
      const text = await page.evaluate(async (u) => {
        const r = await fetch(u, { credentials: "include" });
        if (!r.ok) return "";
        return await r.text();
      }, url);
      let idx = text.indexOf("importSkuTemplate");
      while (idx >= 0) {
        hits.push({ url: url.slice(-80), at: idx, around: text.slice(Math.max(0, idx - 500), idx + 500) });
        idx = text.indexOf("importSkuTemplate", idx + 1);
      }
      if (hits.length > 6) break;
    } catch (e) { /* skip */ }
  }
  return JSON.stringify({ scanned: urls.length, hits: hits.slice(0, 6) }, null, 1);
}
