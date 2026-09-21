async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  if (/\/sell\/v2\/publish\.htm/i.test(page.url()) && !/category\.htm/i.test(page.url())) {
    throw new Error("REFUSE:当前标签是发布页，禁止覆盖: " + page.url());
  }
  if (!/category\.htm/i.test(page.url())) {
    throw new Error("PAUSE:当前标签不是类目页: " + page.url());
  }

  const leaf = PAYLOAD.leaf || "中性笔";
  const brand = PAYLOAD.brand || "";
  const model = PAYLOAD.model || "";
  await dismissKnow();
  await sleep(400);

  async function pageState() {
    return page.evaluate(() => {
      const text = document.body.innerText || "";
      const buttons = [...document.querySelectorAll("button")].map((el) => ({
        text: (el.innerText || "").replace(/\s+/g, " ").trim(),
        disabled: !!el.disabled,
      }));
      return {
        hub: text.includes("搜索发品") && text.includes("以图发品") && buttons.some((b) => b.text === "开启"),
        hasNext: buttons.some((b) => b.text.includes("确认，下一步")),
        nextDisabled: buttons.some((b) => b.text.includes("确认，下一步") && b.disabled),
        hasLeafTabs: [...document.querySelectorAll("[role=tab], .next-tabs-tab")].length > 0,
      };
    });
  }

  async function openSearchPublish() {
    const state = await pageState();
    if (state.hasNext || state.hasLeafTabs) return "ready";
    if (!state.hub) return "not-hub";
    const clicked = await page.evaluate(() => {
      const buttons = [...document.querySelectorAll("button")].filter((el) => (el.innerText || "").trim() === "开启");
      if (!buttons.length) return "NO";
      buttons[0].click();
      return "OPEN";
    });
    if (clicked === "NO") throw new Error("PAUSE:类目首页未找到搜索发品开启");
    for (let i = 0; i < 20; i++) {
      await sleep(400);
      const now = await pageState();
      if (now.hasNext || now.hasLeafTabs) return clicked;
    }
    throw new Error("PAUSE:已点击搜索发品，但类目选择页未出现");
  }

  async function pickLeaf() {
    await dismissKnow();
    const tab = page.getByRole("tab", { name: leaf });
    if (await tab.count()) {
      await tab.first().click({ force: true, timeout: 5000 }).catch(() => {});
      await sleep(800);
      return "tab";
    }
    const chip = page.getByText(leaf, { exact: true });
    if (await chip.count()) {
      await chip.first().click({ force: true, timeout: 5000 }).catch(() => {});
      await sleep(800);
      return "chip";
    }
    const search = page.getByPlaceholder(/商品名称|类目关键词|条码/);
    if (await search.count()) {
      await search.first().click({ force: true });
      await search.first().fill(leaf);
      const searchBtn = page.getByRole("button", { name: "搜索" });
      if (await searchBtn.count()) await searchBtn.first().click({ force: true });
      else await page.keyboard.press("Enter");
      await sleep(1000);
      const hit = page.getByText(leaf, { exact: true });
      if (await hit.count()) await hit.first().click({ force: true });
      await sleep(600);
      return "search";
    }
    throw new Error("PAUSE:类目页未找到叶子类目 " + leaf);
  }

  async function brandCombos() {
    return page.getByRole("combobox", { name: /^请输入$/ });
  }

  async function waitBrandCombo(tries) {
    for (let i = 0; i < (tries || 20); i++) {
      if (i === 0 || i === 4 || i === 10) {
        await dismissBlockingDialogs();
        await hideDraftOverlays();
      }
      const combos = await brandCombos();
      if (await combos.count()) return combos;
      const plain = page.locator('input[placeholder="请输入"][role="combobox"], input[placeholder="请输入"], input[placeholder*="品牌"]');
      if (await plain.count()) return plain;
      const next = page.getByRole("button", { name: "确认，下一步" });
      if (await next.count() && !(await next.isDisabled())) return page.locator(".qianniu-no-brand-combo");
      await sleep(350);
    }
    return page.locator('input[placeholder="请输入"][role="combobox"], input[placeholder="请输入"], input[placeholder*="品牌"]');
  }

  async function pickBrandOption(want) {
    const exact = page.getByText(want, { exact: true });
    if (await exact.count()) {
      try {
        await exact.first().click({ timeout: 2500, force: true });
        return "exact:" + want;
      } catch (e) {}
    }
    return page.evaluate((value) => {
      const wraps = [...document.querySelectorAll(".next-overlay-wrapper, .next-menu, [role='listbox']")].filter((el) => getComputedStyle(el).display !== "none");
      const wrap = wraps[wraps.length - 1];
      if (!wrap) return "NO_WRAP";
      const nodes = [...wrap.querySelectorAll("li, .next-menu-item, [role='option'], div, span")];
      const hit = nodes.find((el) => (el.innerText || "").trim() === value)
        || nodes.find((el) => (el.innerText || "").includes(value) && (el.innerText || "").trim().length < 40);
      if (!hit) return "NO_OPTION:" + (wrap.innerText || "").replace(/\s+/g, " ").slice(0, 160);
      hit.click();
      return "CLICKED:" + (hit.innerText || "").trim().slice(0, 40);
    }, want);
  }

  const opened = await openSearchPublish();
  const leafHow = await pickLeaf();
  await dismissKnow();
  await sleep(500);
  let brandHow = "";
  let modelHow = "";

  if (brand) {
    let combos = await waitBrandCombo(18);
    if (!(await combos.count())) {
      await page.evaluate((name) => {
        const tab = [...document.querySelectorAll("[role=tab], .next-tabs-tab")].find((el) => (el.innerText || "").trim() === name);
        if (tab) {
          tab.click();
          return;
        }
        const chip = [...document.querySelectorAll("div, span, a, li")].find((el) => (el.innerText || "").trim() === name && (el.innerText || "").trim().length < 12);
        if (chip) chip.click();
      }, leaf).catch(() => {});
      await dismissKnow();
      combos = await waitBrandCombo(10);
    }
    if (!(await combos.count())) {
      const nextReady = page.getByRole("button", { name: "确认，下一步" });
      if (await nextReady.count() && !(await nextReady.isDisabled())) {
        brandHow = "skip-next-ready";
      } else {
        throw new Error("PAUSE:类目页没有品牌输入框，请确认已选择 " + leaf);
      }
    } else {
      await combos.first().click({ force: true, timeout: 5000 });
      await sleep(300);
      const box = page.getByRole("textbox").last();
      if (await box.count()) await box.fill(brand);
      else await page.keyboard.type(brand, { delay: 25 });
      await sleep(800);
      brandHow = await pickBrandOption(brand);
      if (String(brandHow).indexOf("CLICKED") < 0 && String(brandHow).indexOf("exact") < 0) {
        throw new Error("PAUSE:类目页未选中品牌 " + brand + " " + brandHow);
      }
      await sleep(400);
      await page.keyboard.press("Escape");
      await page.keyboard.press("Tab");
      await sleep(400);
    }
  }

  if (model) {
    const combos = await waitBrandCombo(8);
    const count = await combos.count();
    if (count >= 2) {
      await combos.nth(1).click({ force: true, timeout: 8000 });
      try { await combos.nth(1).fill(model); } catch (e) { await page.keyboard.type(model, { delay: 20 }); }
      await page.keyboard.press("Tab");
      modelHow = "combo-2";
    } else if (count === 1 && !brand) {
      await combos.first().click({ force: true, timeout: 8000 });
      await combos.first().fill(model);
      await page.keyboard.press("Tab");
      modelHow = "combo-1";
    } else {
      modelHow = "skip-count-" + count;
    }
    await sleep(400);
  }

  const next = page.getByRole("button", { name: "确认，下一步" });
  for (let i = 0; i < 40; i++) {
    if (await next.count() && !(await next.isDisabled())) break;
    await sleep(400);
  }
  if (!(await next.count())) throw new Error("PAUSE:未找到确认下一步");
  if (await next.isDisabled()) throw new Error("PAUSE:确认下一步仍不可用，请确认品牌和型号");
  await clickUnblocked(next, 12000);
  await page.waitForURL(/\/sell\/v2\/publish\.htm/i, { timeout: 30000 });
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await sleep(1200);
  const text = await page.evaluate(() => document.body.innerText || "");
  if (leaf && text.indexOf(leaf) < 0) throw new Error("PAUSE:发布页未看到类目 " + leaf);
  return JSON.stringify({ url: page.url(), leaf, brand, model, opened, leafHow, brandHow, modelHow });
}
