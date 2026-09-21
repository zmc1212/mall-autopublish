async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const specs = PAYLOAD.skus || [];
  await dismissKnow();
  if (!(await page.locator(".sku-decouple-drawer").count())) {
    const opened = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((el) => {
        const t = (el.innerText || "").trim();
        return t === "编辑规格" || t.includes("创建规格");
      });
      if (!btn) return "NO";
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return "OPEN";
    });
    await sleep(900);
    if (opened === "NO") throw new Error("PAUSE:未找到编辑规格");
  }
  if (!(await page.locator(".batch-fill-sku-image-dialog").count())) {
    await page.evaluate(() => {
      const box = document.querySelector(".sku-decouple-drawer .sell-color-option-image-empty")
        || document.querySelector(".sku-decouple-drawer .sell-color-option-image-upload")
        || document.querySelector(".sell-color-option-image-empty");
      if (box) {
        box.scrollIntoView({ block: "center" });
        box.click();
      }
    });
    await sleep(1500);
  }
  let frame = sucaiFrame() || await waitFrame(sucaiFrame, 16);
  if (!frame) return JSON.stringify({ error: "NO_FRAME" });
  if (!(await frame.locator("input[placeholder*='搜索'], input[type=search]").count())) {
    await clickComplete(frame);
    await sleep(700);
    frame = sucaiFrame() || frame;
  }
  const bindLog = [];
  for (const spec of specs) {
    const skuClick = await page.evaluate((want) => {
      const dlg = document.querySelector(".batch-fill-sku-image-dialog");
      if (!dlg) return "NO_DIALOG";
      const items = [...dlg.querySelectorAll("li.sku-item, li, [class*='sku-item']")];
      const item = items.find((el) => {
        const t = ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "").replace(/\s+/g, " ").trim();
        return t === want.name || (want.slot && t.includes(want.slot)) || t.includes(want.name);
      });
      if (!item) return "NO_SKU";
      item.click();
      return ((item.querySelector(".sku-text") && item.querySelector(".sku-text").innerText) || item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40);
    }, spec);
    await sleep(280);
    const q = spec.slot || (spec.file || "").replace(/\.[^.]+$/, "").split("-")[0] || spec.file;
    let searched = await searchSucai(frame, q);
    if (String(searched).startsWith("STALE") && spec.file) {
      searched = await searchSucai(frame, spec.file.replace(/\.[^.]+$/, ""));
    }
    let picClick = { ok: false };
    if (!String(searched).startsWith("STALE")) {
      picClick = await clickSucaiCard(frame, spec.file);
    }
    bindLog.push({ name: spec.name, slot: spec.slot, skuClick, searched, picClick });
    await sleep(450);
  }
  const confirm = await page.evaluate(() => {
    const dlg = document.querySelector(".batch-fill-sku-image-dialog");
    if (!dlg) return "NO_DIALOG";
    const filled = [...dlg.querySelectorAll("li.sku-item, li, [class*='sku-item']")].filter((el) => el.querySelector("img")).length;
    const btn = [...dlg.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "确定");
    if (!btn) return "NO_OK:" + filled;
    btn.click();
    return "OK:" + filled;
  });
  await sleep(700);
  const drawerConfirm = await page.evaluate(() => {
    const btn = [...document.querySelectorAll(".sku-decouple-drawer button")].find((el) => (el.innerText || "").includes("确认创建") || (el.innerText || "").includes("确认"));
    if (!btn) return "NO";
    btn.click();
    return "CLICKED";
  });
  await sleep(800);
  return JSON.stringify({ bindLog, confirm, drawerConfirm }, null, 2);
}
