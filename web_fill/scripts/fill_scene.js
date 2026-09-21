async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await page.keyboard.press("Escape");
  await sleep(200);
  const value = "日常书写";
  const log = [];
  const combo = page.getByText("适用场景", { exact: true }).locator("xpath=following::input[@role='combobox']");
  const n = await combo.count();
  log.push("combos=" + n);
  for (let i = 0; i < n; i++) {
    const el = combo.nth(i);
    if (!(await el.isVisible().catch(() => false))) continue;
    await el.click({ force: true, timeout: 6000 });
    await sleep(450);
    const dump = await page.evaluate(() => {
      const wraps = [...document.querySelectorAll(".next-overlay-wrapper")].filter((w) => getComputedStyle(w).display !== "none");
      return wraps.map((w) => (w.innerText || "").replace(/\s+/g, " ").slice(0, 180));
    });
    log.push({ i, dump });
    if (dump.some((t) => t.includes(value))) {
      log.push(await clickOverlayText(value));
      await page.keyboard.press("Escape");
      return JSON.stringify({ log }, null, 2);
    }
    await page.keyboard.press("Escape");
    await sleep(200);
  }
  const txt = page.getByText(value, { exact: true });
  if (await txt.count()) {
    await txt.last().click({ force: true });
    log.push("TEXT");
  }
  return JSON.stringify({ log }, null, 2);
}
