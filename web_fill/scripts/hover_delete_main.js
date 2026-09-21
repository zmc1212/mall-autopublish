async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  const index = PAYLOAD.index == null ? 1 : PAYLOAD.index;
  await dismissKnow();
  const item = page.locator(field + " .drag-item").nth(index);
  await item.scrollIntoViewIfNeeded();
  await item.hover();
  await sleep(400);
  const menuDel = page.getByRole("menuitem", { name: "删除" });
  let how = "NO_MENU";
  if (await menuDel.count()) {
    await menuDel.last().click({ force: true });
    how = "MENU";
  } else {
    await item.click({ button: "right", force: true }).catch(() => {});
    await sleep(300);
    if (await menuDel.count()) {
      await menuDel.last().click({ force: true });
      how = "RIGHT";
    }
  }
  await sleep(600);
  const after = await page.evaluate((sel) => {
    const root = document.querySelector(sel);
    return {
      imgs: root ? [...root.querySelectorAll(".drag-item img")].map((el) => (el.src || "").slice(-48)) : [],
      empty: root ? root.querySelectorAll(".image-empty").length : -1,
    };
  }, field);
  return JSON.stringify({ how, after }, null, 2);
}
