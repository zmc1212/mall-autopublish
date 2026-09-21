async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await installAttrDom();
  await page.keyboard.press("Escape").catch(() => {});
  await sleep(200);
  await page.evaluate((lab) => {
    const el = window.__qnCombo && window.__qnCombo(lab);
    const wrap = el && (el.closest(".next-select") || el);
    if (wrap) wrap.click();
  }, "IP联名");
  await sleep(500);
  const box = page.locator(".next-overlay-wrapper.opened .options-search input");
  const n = await box.count();
  if (n) {
    await box.first().click({ force: true, timeout: 2000 });
    await box.first().fill("火影忍者");
    await sleep(800);
  }
  const afterFill = await page.evaluate(() => {
    const wrap = [...document.querySelectorAll(".next-overlay-wrapper.opened")].pop();
    if (!wrap) return { none: true };
    const input = wrap.querySelector(".options-search input");
    return {
      value: input ? input.value : "",
      text: (wrap.innerText || "").replace(/\s+/g, " ").trim().slice(0, 400),
      html: wrap.innerHTML.replace(/\s+/g, " ").slice(0, 1800),
      opts: [...wrap.querySelectorAll(".options-item")].map((el) => el.getAttribute("title") || "").filter(Boolean),
    };
  });
  const applyBtn = page.locator(".next-overlay-wrapper.opened").getByText(/点击申请|申请/);
  let apply = "NO_BTN";
  if (await applyBtn.count()) {
    await applyBtn.last().click({ force: true, timeout: 2000 }).catch(() => {});
    apply = "CLICK";
    await sleep(800);
  }
  const afterApply = await page.evaluate(() => ({
    committed: !!(window.__qnCommitted && window.__qnCommitted("IP联名", "火影忍者")),
    attr: window.__qnAttr && window.__qnAttr("IP联名"),
    dialog: [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened")].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 180)).filter(Boolean).slice(0, 4),
  }));
  return JSON.stringify({ n, afterFill, apply, afterApply }, null, 2);
}
