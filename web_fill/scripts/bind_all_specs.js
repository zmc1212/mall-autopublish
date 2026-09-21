async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const specs = PAYLOAD.skus || [];
  await dismissKnow();
  const opened = await page.evaluate(() => {
    const empty = document.querySelector(".sell-component-sku-images .empty-container, .sell-component-sku-images-item .empty-container");
    if (!empty) return "NO_EMPTY";
    empty.scrollIntoView({ block: "center" });
    empty.click();
    return "EMPTY";
  });
  await sleep(1600);
  let frame = sucaiFrame() || await waitFrame(sucaiFrame, 16);
  if (!frame && !(await page.locator(".batch-fill-sku-image-dialog").count())) {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "编辑规格");
      if (btn) btn.click();
    });
    await sleep(900);
    await page.evaluate(() => {
      const box = document.querySelector(".sku-decouple-drawer .empty-container, .sku-decouple-drawer .sell-color-option-image-empty, .sell-color-option-image-upload");
      if (box) box.click();
    });
    await sleep(1600);
    frame = sucaiFrame() || await waitFrame(sucaiFrame, 12);
  }
  if (frame && !(await frame.locator("input[placeholder*='搜索'], input[type=search]").count())) {
    await clickComplete(frame);
    await sleep(700);
    frame = sucaiFrame() || frame;
  }
  if (!frame) {
    return JSON.stringify({
      opened,
      error: "NO_FRAME",
      dialog: !!(await page.locator(".batch-fill-sku-image-dialog").count()),
      drawer: !!(await page.locator(".sku-decouple-drawer").count()),
    });
  }
  const bindLog = [];
  for (const spec of specs) {
    if (await page.locator(".batch-fill-sku-image-dialog").count()) {
      await page.evaluate((want) => {
        const dlg = document.querySelector(".batch-fill-sku-image-dialog");
        if (!dlg) return;
        const items = [...dlg.querySelectorAll("li.sku-item, li")];
        const item = items.find((el) => {
          const t = ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "").replace(/\s+/g, " ").trim();
          return t === want.name || (want.slot && t.includes(want.slot)) || t.includes(want.name);
        });
        if (item) item.click();
      }, spec);
      await sleep(220);
    }
    const q = spec.slot || (spec.file || "").split("-")[0];
    let searched = await searchSucai(frame, q);
    if (String(searched).startsWith("STALE")) searched = await searchSucai(frame, spec.file.replace(/\.[^.]+$/, ""));
    const pic = String(searched).startsWith("STALE") ? { ok: false } : await clickSucaiCard(frame, spec.file);
    bindLog.push({ name: spec.name, slot: spec.slot, searched, pic });
    await sleep(400);
    await confirmCrop();
  }
  const confirm = await page.evaluate(() => {
    const dlg = document.querySelector(".batch-fill-sku-image-dialog");
    if (dlg) {
      const btn = [...dlg.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "确定");
      if (btn) {
        btn.click();
        return "DIALOG_OK";
      }
    }
    return "NO_DIALOG";
  });
  await sleep(600);
  return JSON.stringify({ opened, bindLog, confirm }, null, 2);
}
