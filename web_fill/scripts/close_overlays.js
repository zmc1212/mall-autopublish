async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const before = await page.evaluate(() => ({
    sucai: [...document.querySelectorAll("iframe")].some((el) => /sucai/.test(el.src || "")),
    dialog: !!document.querySelector(".next-dialog, .batch-fill-sku-image-dialog, .sku-decouple-drawer, .sell-component-image-v2-media-popup"),
  }));
  await page.mouse.click(40, 80);
  await sleep(300);
  await page.evaluate(() => {
    const confirm = [...document.querySelectorAll(".sku-decouple-drawer button")].find((el) => /确认创建|完成/.test(el.innerText || ""));
    if (confirm) confirm.click();
    const roots = [...document.querySelectorAll(".next-dialog, .batch-fill-sku-image-dialog, .sell-component-image-v2-media-popup")];
    for (const root of roots) {
      const close = root.querySelector(".next-dialog-close, [aria-label='关闭']");
      if (close) {
        try { close.click(); } catch (e) {}
      }
    }
  });
  await sleep(300);
  await page.mouse.click(40, 80);
  await sleep(200);
  const after = await page.evaluate(() => ({
    sucai: [...document.querySelectorAll("iframe")].some((el) => /sucai/.test(el.src || "")),
    dialog: !!document.querySelector(".next-dialog, .batch-fill-sku-image-dialog, .sku-decouple-drawer, .sell-component-image-v2-media-popup"),
  }));
  return JSON.stringify({ before, after });
}
