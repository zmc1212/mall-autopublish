async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const spec = (PAYLOAD.skus || [])[0] || {};
  await dismissKnow();
  if (!(await page.locator(".sku-decouple-drawer, .next-dialog").count())) {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((el) => /编辑规格|创建规格/.test(el.innerText || ""));
      if (btn) btn.click();
    });
    await sleep(900);
  }
  const clicked = await page.evaluate((want) => {
    const scopes = [...document.querySelectorAll(".sku-decouple-drawer, .next-dialog, .batch-fill-sku-image-dialog")];
    const scope = scopes.find((el) => (el.innerText || "").includes(want.name)) || document;
    const items = [...scope.querySelectorAll("li, [class*='sku-item'], tr")];
    const item = items.find((el) => (el.innerText || "").includes(want.name));
    if (!item) return { ok: false, reason: "NO_ITEM" };
    const thumb = item.querySelector("img, [class*='image'], [class*='upload'], [class*='pic']")
      || item.querySelector("[cursor], [class*='empty']");
    const target = thumb || item.children[0];
    if (!target) return { ok: false, reason: "NO_THUMB", t: (item.innerText || "").slice(0, 40) };
    target.click();
    return { ok: true, cls: String(target.className || "").slice(0, 80), tag: target.tagName };
  }, spec);
  await sleep(1600);
  let frame = sucaiFrame() || await waitFrame(sucaiFrame, 12);
  if (frame && !(await frame.locator("input[placeholder*='搜索'], input[type=search]").count())) {
    await clickComplete(frame);
    await sleep(600);
    frame = sucaiFrame() || frame;
  }
  if (!frame) {
    return JSON.stringify({
      clicked,
      error: "NO_FRAME",
      frames: page.frames().map((f) => (f.url() || "").slice(0, 100)),
      fileInputs: await page.evaluate(() => [...document.querySelectorAll("input[type=file]")].map((el) => el.id || el.className)),
    });
  }
  const q = spec.slot || "颜色15";
  const searched = await searchSucai(frame, q);
  const pic = String(searched).startsWith("STALE") ? { ok: false } : await clickSucaiCard(frame, spec.file);
  await sleep(500);
  return JSON.stringify({ clicked, searched, pic }, null, 2);
}
