async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  const index = PAYLOAD.index == null ? 1 : PAYLOAD.index;
  await dismissKnow();
  const before = await page.evaluate((sel) => {
    const root = document.querySelector(sel);
    return root ? [...root.querySelectorAll(".drag-item img")].map((el) => (el.src || "").slice(-48)) : [];
  }, field);
  const box = page.locator(field + " .drag-item").nth(index);
  await box.hover();
  await sleep(400);
  const del = box.locator("i, button, span, div").filter({ hasText: /删除|/ });
  let how = "NONE";
  if (await del.count()) {
    await del.first().click({ force: true });
    how = "TEXT";
  } else {
    how = await page.evaluate(([sel, idx]) => {
      const root = document.querySelector(sel);
      const item = root && root.querySelectorAll(".drag-item")[idx];
      if (!item) return "NO_ITEM";
      item.dispatchEvent(new MouseEvent("mouseover", { bubbles: true }));
      const icon = item.querySelector(".next-icon-close, .next-icon-delete, [class*='close'], [class*='delete'], [class*='remove']")
        || [...item.querySelectorAll("i, span, div")].find((el) => /close|delete|remove/i.test(el.className || ""));
      if (icon) {
        icon.click();
        return "ICON:" + icon.className;
      }
      return "NO_ICON:" + item.className + ":" + item.innerHTML.slice(0, 200);
    }, [field, index]);
  }
  await sleep(500);
  const after = await page.evaluate((sel) => {
    const root = document.querySelector(sel);
    return {
      imgs: root ? [...root.querySelectorAll(".drag-item img")].map((el) => (el.src || "").slice(-48)) : [],
      empty: root ? root.querySelectorAll(".image-empty").length : -1,
    };
  }, field);
  return JSON.stringify({ before, how, after }, null, 2);
}
