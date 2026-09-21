async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await dismissKnow();
  const log = [];

  if (PAYLOAD.ship_time) {
    try {
      await page.getByRole("radio", { name: PAYLOAD.ship_time }).click({ force: true });
      log.push("ship-time");
    } catch (e) { log.push("ship-time-fail:" + e.message); }
  }
  if (PAYLOAD.ship_from) {
    const dest = String(PAYLOAD.ship_from).indexOf("其他") >= 0 ? "其他国家或地区" : "大陆及港澳台";
    try {
      await page.getByRole("radio", { name: dest }).click({ force: true });
      log.push("ship-from");
    } catch (e) { log.push("ship-from-fail:" + e.message); }
  }

  const logistics = page.getByRole("checkbox", { name: /使用物流配送/ });
  if (await logistics.count() && !(await logistics.first().isChecked().catch(() => false))) {
    await logistics.first().click({ force: true });
    log.push("logistics");
  }

  if (PAYLOAD.freight) {
    await page.keyboard.press("Escape");
    await sleep(200);
    const click = await page.evaluate(() => {
      const label = [...document.querySelectorAll("div, span")].find((n) => (n.childNodes.length <= 3) && (n.textContent || "").replace(/\s/g, "").includes("运费模板") && (n.textContent || "").trim().length < 12);
      if (!label) return "NO_LABEL";
      const root = label.parentElement;
      const select = root && (root.querySelector(".next-select") || (root.nextElementSibling && root.nextElementSibling.querySelector(".next-select")));
      if (!select) return "NO_SELECT";
      select.scrollIntoView({ block: "center" });
      select.click();
      return "OK";
    });
    await sleep(500);
    const picked = await clickOverlayText(PAYLOAD.freight);
    log.push("freight:" + click + "/" + picked);
    await page.keyboard.press("Escape");
  }

  if (PAYLOAD.stock_deduction) {
    try {
      await page.getByRole("radio", { name: PAYLOAD.stock_deduction }).click({ force: true });
      log.push("deduction");
    } catch (e) { log.push("deduction-fail"); }
  }

  const state = await selectWarehouseRadio();
  if (!state.warehouseOn || state.instantOn) throw new Error("PAUSE:放入仓库未选中或仍是立刻上架");
  return JSON.stringify({ log, state }, null, 2);
}
