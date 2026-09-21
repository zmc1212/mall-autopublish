async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await dismissKnow();
  const before = await page.evaluate(() => ({
    drawer: !!document.querySelector(".sku-decouple-drawer"),
    dialog: !!document.querySelector(".batch-fill-sku-image-dialog"),
    sucai: [...document.querySelectorAll("iframe")].map((el) => el.src).filter((s) => /sucai/.test(s)),
    buttons: [...document.querySelectorAll("button")].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).filter((t) => /规格|图片|上传|批量/.test(t)).slice(0, 20),
  }));
  if (!before.drawer) {
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((el) => {
        const t = (el.innerText || "").trim();
        return t === "编辑规格" || t.includes("创建规格") || t.includes("编辑规格");
      });
      if (btn) {
        btn.scrollIntoView({ block: "center" });
        btn.click();
      }
    });
    await sleep(1000);
  }
  if (!(await page.locator(".batch-fill-sku-image-dialog").count())) {
    const clicked = await page.evaluate(() => {
      const drawer = document.querySelector(".sku-decouple-drawer") || document;
      const candidates = [
        ...drawer.querySelectorAll(".sell-color-option-image-empty, .sell-color-option-image-upload, .sell-color-option-image img, [class*='sku-image'], [class*='color-option-image']"),
        ...[...drawer.querySelectorAll("button, div, span")].filter((el) => /批量|上传图片|添加图片|规格图/.test(el.innerText || "")),
      ];
      const el = candidates[0];
      if (!el) return "NO_TARGET";
      el.scrollIntoView({ block: "center" });
      el.click();
      return (el.innerText || el.className || "").toString().slice(0, 80);
    });
    await sleep(1800);
    before.clicked = clicked;
  }
  const after = await page.evaluate(() => ({
    drawer: !!document.querySelector(".sku-decouple-drawer"),
    dialog: !!document.querySelector(".batch-fill-sku-image-dialog"),
    sucai: [...document.querySelectorAll("iframe")].map((el) => (el.src || "").slice(0, 120)),
    skuItems: document.querySelector(".batch-fill-sku-image-dialog")
      ? [...document.querySelector(".batch-fill-sku-image-dialog").querySelectorAll("li.sku-item, li")].map((el) => ({
        t: ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40),
        hasImg: !!el.querySelector("img"),
      })).slice(0, 20)
      : [],
  }));
  return JSON.stringify({ before, after }, null, 2);
}
