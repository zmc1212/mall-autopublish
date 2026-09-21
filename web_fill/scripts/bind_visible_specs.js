async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const specs = PAYLOAD.skus || [];
  await dismissKnow();
  let frame = sucaiFrame() || await waitFrame(sucaiFrame, 10);
  const bindLog = [];
  for (const spec of specs) {
    const skuClick = await page.evaluate((want) => {
      const dlg = [...document.querySelectorAll(".next-dialog, .batch-fill-sku-image-dialog, [class*='sku']")].find((el) => (el.innerText || "").includes("批量填充") && (el.innerText || "").includes(want.name));
      const scope = dlg || document;
      const item = [...scope.querySelectorAll("li, [class*='sku-item'], div")].find((el) => {
        const t = ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "").replace(/\s+/g, " ").trim();
        return t === want.name || t.startsWith(want.name);
      });
      if (!item) return "NO_SKU";
      item.click();
      return (item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40);
    }, spec);
    await sleep(200);
    let pic = { ok: false };
    if (frame) {
      pic = await clickSucaiCard(frame, spec.file);
      if (!pic.ok) {
        const q = spec.slot || spec.file.replace(/\.[^.]+$/, "");
        const searched = await searchSucai(frame, q);
        if (!String(searched).startsWith("STALE")) pic = await clickSucaiCard(frame, spec.file);
        pic.searched = searched;
      }
    }
    bindLog.push({ name: spec.name, skuClick, pic });
    await sleep(280);
  }
  const confirm = await page.evaluate(() => {
    const btn = [...document.querySelectorAll(".next-dialog button, .batch-fill-sku-image-dialog button")].find((el) => (el.innerText || "").trim() === "确定");
    if (!btn) return "NO_OK";
    btn.click();
    return "OK";
  });
  await sleep(700);
  return JSON.stringify({ bindLog, confirm, hasFrame: !!frame }, null, 2);
}
