async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  await dismissKnow();
  const log = [];
  for (let i = 0; i < 8; i++) {
    const hit = await page.evaluate((sel) => {
      const root = document.querySelector(sel);
      if (!root) return "NO_FIELD";
      const imgs = [...root.querySelectorAll("img")].filter((el) => el.width > 40);
      if (!imgs.length) return "EMPTY:" + root.querySelectorAll(".image-empty").length;
      const img = imgs[imgs.length - 1];
      const card = img.closest("[class*='image'], [class*='item'], li, div") || img.parentElement;
      if (card) card.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      img.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      const del = [...(card || root).querySelectorAll("i, button, span, div, a")].find((el) => {
        const t = (el.getAttribute("title") || el.getAttribute("aria-label") || el.innerText || "").trim();
        return t === "删除" || t === "移除" || /close|delete|remove/i.test(el.className || "");
      });
      if (del) {
        del.click();
        return "DEL";
      }
      return "HOVER:" + imgs.length;
    }, field);
    log.push(hit);
    if (String(hit).startsWith("EMPTY") || hit === "NO_FIELD") break;
    if (String(hit).startsWith("HOVER")) {
      const box = page.locator(field);
      await box.locator("img").last().hover().catch(() => {});
      const del = page.getByText("删除", { exact: true });
      if (await del.count()) await del.last().click({ force: true }).catch(() => {});
    }
    await sleep(350);
  }
  const slot = await page.evaluate((sel) => {
    const root = document.querySelector(sel);
    return {
      imgs: root ? [...root.querySelectorAll("img")].filter((el) => el.width > 40).length : -1,
      empty: root ? root.querySelectorAll(".image-empty").length : -1,
    };
  }, field);
  return JSON.stringify({ log, slot });
}
