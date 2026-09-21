async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const log = [];

  async function openRow(label) {
    await page.keyboard.press("Escape").catch(() => {});
    await sleep(150);
    return page.evaluate((lab) => {
      const labs = [...document.querySelectorAll("div, span, label")].filter((el) => (el.textContent || "").trim() === lab && el.childNodes.length <= 6);
      for (const labEl of labs) {
        let p = labEl;
        for (let i = 0; i < 8 && p; i++) {
          const text = (p.innerText || "").replace(/\s+/g, " ");
          if (text.includes(lab) && text.length < 140) {
            const input = p.querySelector("input[role='combobox']");
            if (input) {
              input.click();
              return "OK";
            }
          }
          p = p.parentElement;
        }
      }
      return "NO";
    }, label);
  }

  async function pick(value) {
    const item = page.locator(".next-overlay-wrapper.opened .options-item").filter({ hasText: value }).first();
    if (await item.count()) {
      await item.click({ force: true, timeout: 5000 });
      return "ITEM";
    }
    return clickOverlayText(value);
  }

  const del = page.getByRole("button", { name: "考试专用 删除" });
  if (await del.count()) {
    const x = page.locator("button", { hasText: "删除" }).first();
    try { await page.getByRole("button", { name: "删除" }).first().click({ force: true, timeout: 3000 }); log.push("del-func"); } catch (e) { log.push("del-fail"); }
    await sleep(300);
  }

  const pairs = [
    ["笔头类型", "子弹头"],
    ["笔芯颜色", "炭黑"],
    ["功能", "考试专用"],
    ["适用场景", "日常书写"],
    ["适用人群", "通用"],
  ];
  for (const [label, value] of pairs) {
    try {
      const opened = await openRow(label);
      await sleep(400);
      const picked = await pick(value);
      await sleep(350);
      log.push(label + "=" + opened + "/" + picked);
    } catch (err) {
      log.push("FAIL " + label + " " + String(err.message || err).slice(0, 100));
    }
  }

  await page.getByRole("radio", { name: "放入仓库" }).click({ force: true }).catch(() => {});
  await sleep(300);
  const state = await warehouseState();
  if (!state.warehouseOn || state.instantOn) throw new Error("PAUSE:放入仓库未选中或仍是立刻上架");

  await page.keyboard.press("Escape").catch(() => {});
  await page.mouse.click(40, 80);
  await sleep(300);
  let clicked = "NO";
  try {
    await page.getByRole("button", { name: "提交宝贝信息" }).click({ force: true, timeout: 6000 });
    clicked = "ROLE";
  } catch (e1) {
    clicked = await page.evaluate(() => {
      const el = document.querySelector("#button-submit")
        || document.querySelector("button[name='button-submit']")
        || [...document.querySelectorAll("button")].find((b) => (b.innerText || "").trim() === "提交宝贝信息");
      if (!el) return "NO";
      el.click();
      return "DOM";
    });
  }
  log.push("submit=" + clicked);
  await sleep(4500);
  const after = await page.evaluate(() => ({
    href: location.href,
    itemId: /itemid=/i.test(location.href),
    pct: ((document.body.innerText || "").match(/已填写\s*\d+%/) || [""])[0],
    errors: ((document.body.innerText || "").match(/错误 \(\d+\)/) || [""])[0],
    empty: ((document.body.innerText || "").match(/[^。]{0,8}不能为空/g) || []).slice(0, 8),
    hasSuccess: /发布成功|提交成功|已经提交到仓库|已放入仓库/.test(document.body.innerText || ""),
    text: (document.body.innerText || "").replace(/\s+/g, " ").slice(0, 500),
  }));
  return JSON.stringify({ log, state, after }, null, 2);
}
