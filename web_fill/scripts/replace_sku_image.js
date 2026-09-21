async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const spec = (PAYLOAD.skus || [])[0] || {};
  await dismissKnow();
  let closed = "NO";
  const cancel = page.getByRole("button", { name: "取消" });
  if (await cancel.count()) {
    await cancel.last().click({ force: true }).catch(() => {});
    closed = "ROLE_CANCEL";
  } else {
    closed = await page.evaluate(() => {
      const drawer = document.querySelector(".sku-decouple-drawer");
      if (!drawer) return "NO_DRAWER";
      const btn = [...drawer.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "取消")
        || drawer.querySelector(".next-drawer-close, [aria-label='关闭']");
      if (!btn) return "NO_CANCEL";
      btn.click();
      return "CANCEL";
    });
  }
  await sleep(700);
  const clicked = await page.evaluate((want) => {
    const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
      const t = tr.innerText || "";
      return t.includes(want.name) && t.includes("元") && t.includes("件");
    });
    if (!rows.length) return { ok: false, reason: "NO_ROW" };
    const row = rows[0];
    const first = row.querySelector("td");
    const box = first && (
      first.querySelector("img")
      || first.querySelector("[class*='image']")
      || first.querySelector("[class*='upload']")
      || first.querySelector("[class*='empty']")
      || [...first.querySelectorAll("*")].reverse().find((el) => el.getAttribute("style") || /image|pic|upload/i.test(el.className || ""))
      || first.lastElementChild
    );
    if (!box) return { ok: false, reason: "NO_BOX", html: (first && first.innerHTML || "").slice(0, 220) };
    box.scrollIntoView({ block: "center" });
    box.click();
    return { ok: true, cls: String(box.className || "").slice(0, 100), tag: box.tagName, html: (first && first.innerHTML || "").slice(0, 220) };
  }, spec);
  await sleep(1800);
  let frame = sucaiFrame() || await waitFrame(sucaiFrame, 14);
  if (frame && !(await frame.locator("input[placeholder*='搜索'], input[type=search]").count())) {
    await clickComplete(frame);
    await sleep(700);
    frame = sucaiFrame() || frame;
  }
  if (!frame) {
    return JSON.stringify({
      closed,
      clicked,
      error: "NO_FRAME",
      dialogs: await page.evaluate(() => [...document.querySelectorAll(".next-dialog, .batch-fill-sku-image-dialog, .sku-decouple-drawer")].map((el) => (el.className + " " + (el.innerText || "").slice(0, 40)))),
    });
  }
  const q = spec.slot || "颜色15";
  const searched = await searchSucai(frame, q);
  const pic = String(searched).startsWith("STALE") ? { ok: false, searched } : await clickSucaiCard(frame, spec.file);
  await sleep(400);
  await confirmCrop();
  return JSON.stringify({ closed, clicked, searched, pic }, null, 2);
}
