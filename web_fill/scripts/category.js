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
    // During form transitions an accessible control may still have no rendered
    // area. Restrict both the primary and fallback queries to visible inputs.
    return page.locator('input[role="combobox"][placeholder="请输入"]:visible');
  }

  async function waitBrandCombo(tries) {
    for (let i = 0; i < (tries || 20); i++) {
      if (i === 0 || i === 4 || i === 10) {
        await dismissBlockingDialogs();
        await hideDraftOverlays();
      }
      const combos = await brandCombos();
      if (await combos.count()) return combos;
      const plain = page.locator('input[placeholder="请输入"][role="combobox"]:visible, input[placeholder="请输入"]:visible, input[placeholder*="品牌"]:visible');
      if (await plain.count()) return plain;
      const next = page.getByRole("button", { name: "确认，下一步" });
      if (await next.count() && !(await next.isDisabled())) return page.locator(".qianniu-no-brand-combo");
      await sleep(350);
    }
    return page.locator('input[placeholder="请输入"][role="combobox"]:visible, input[placeholder="请输入"]:visible, input[placeholder*="品牌"]:visible');
  }

  async function pickBrandOption(want, input) {
    return input.evaluate((field, { value }) => {
      const visible = el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== "hidden";
      };
      const norm = text => String(text || "").normalize("NFKC").replace(/\s+/g, "").toLowerCase();
      // Category brands use custom .options-item[title] divs, not ARIA options.
      // Scope to the popup containing this search field; other menus may be open.
      const linked = document.getElementById(field.getAttribute("aria-controls") || field.getAttribute("aria-owns") || "");
      const parent = field.closest('.next-overlay-wrapper, [role="listbox"]');
      const popups = [...document.querySelectorAll('.next-overlay-wrapper, [role="listbox"], .next-menu')]
        .filter(visible);
      const roots = popups.filter(el => !popups.some(other => other !== el && other.contains(el)));
      const root = parent || (linked && visible(linked) ? linked : roots.length === 1 ? roots[0] : null);
      if (!root) return "NO_POPUP:visible=" + roots.length + ":input=" + field.value;
      const nodes = [...root.querySelectorAll(".options-item, .next-menu-item, [role='option'], [role='menuitem'], li")]
        .filter(el => visible(el) && el.getAttribute("aria-disabled") !== "true" && !/disabled/.test(el.className || ""));
      const hit = nodes.find(el => norm(el.getAttribute("title")) === norm(value) || norm(el.innerText) === norm(value));
      if (!hit) return "NO_OPTION:input=" + field.value + ":options="
        + nodes.map(el => el.getAttribute("title") || el.innerText).join("|").slice(0, 180)
        + ":popup=" + (root.innerText || "").replace(/\s+/g, " ").slice(0, 100);
      const label = hit.getAttribute("title") || hit.innerText;
      hit.click();
      return "CLICKED:" + label.trim().slice(0, 40);
    }, { value: want });
  }

  async function brandCommitted(combo, want) {
    return combo.evaluate((el, { value }) => {
      const norm = text => String(text || "").normalize("NFKC").replace(/\s+/g, "").toLowerCase();
      const selected = [el.value, el.getAttribute("aria-valuetext")];
      const wrap = el.closest('.next-select') || el;
      for (const item of wrap.querySelectorAll('.next-select-single, .next-select-values, .next-select-tag')) {
        selected.push(item.textContent, item.getAttribute('title'));
      }
      return selected.some(text => norm(text) === norm(value));
    }, { value: want });
  }

  async function searchBrand(combo, want) {
    // Search aliases only narrow the server query; selection still requires the full brand.
    const queries = [...new Set([want, (want.match(/[\u3400-\u9fff]+/g) || []).join("")].filter(Boolean))];
    let last = "NO_OPTION";
    const attempts = [];
    for (let attempt = 0; attempt < 2; attempt++) {
      for (const query of queries) {
        // Wait for the active form control to finish mounting/scrolling.  Do
        // not force-click here: a security or verification overlay must still
        // stop the flow and leave the page for review.
        await combo.waitFor({ state: "visible", timeout: 8000 });
        await combo.scrollIntoViewIfNeeded({ timeout: 8000 });
        await combo.click({ timeout: 8000 });
        await sleep(200);
        const customInputs = page.locator('.next-overlay-wrapper .options-search input:not([readonly]):visible');
        const popupInputs = page.locator('.next-overlay-wrapper input:not([readonly]):not([type="checkbox"]):not([type="radio"]):visible, [role="listbox"] input:not([readonly]):visible');
        const ownInput = combo.locator('input:visible');
        const input = await customInputs.count() === 1 ? customInputs.first()
          : await popupInputs.count() === 1 ? popupInputs.first()
          : await ownInput.count() ? ownInput.first() : combo;
        // Never type into an unrelated textbox (for example the model field).
        await input.fill("");
        await input.fill(query);
        for (let poll = 0; poll < 12; poll++) {
          await sleep(350);
          last = await pickBrandOption(want, input);
          if (last.startsWith("CLICKED:")) {
            for (let check = 0; check < 5; check++) {
              await sleep(120);
              if (await brandCommitted(combo, want)) return last + ":query=" + query + ":verified";
            }
            last = "NOT_COMMITTED:" + last;
            break;
          }
        }
        attempts.push(query + "=>" + last);
        await page.keyboard.press("Escape");
      }
    }
    return last + ":attempts=" + attempts.join(";").slice(0, 900);
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
      brandHow = await searchBrand(combos.first(), brand);
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

  // 类目页属性面板的必填属性（如潮玩盲盒的品牌/IP/系列名）由模板驱动：
  // 按 label 文本关联面板输入框。品牌/型号上方已处理；搜索选择型（IP 库）
  // 输入后点选精确选项，可自填型（系列名）输入即生效；面板没有的属性
  // （如出售状态）留给发布页 attributes.js 处理。系列名等输入框在上一项
  // 填好后才渲染，逐轮重查；React 重渲染会丢自定义属性，故用坐标点击 +
  // 真实键盘输入，不依赖 DOM 标记。
  const panelLog = [];
  for (const [label, raw] of Object.entries(PAYLOAD.attributes || {})) {
    if (["品牌", "型号"].includes(label)) continue;
    const value = String(Array.isArray(raw) ? (raw[0] || "") : raw || "").trim();
    if (!value) continue;
    let stuck = false;
    for (let attempt = 0; attempt < 2 && !stuck; attempt++) {
      const hit = await page.evaluate((lab) => {
        const norm = (el) => (el.innerText || '').replace(/\s+/g, '');
        const locate = (input) => {
          input.scrollIntoView({ block: 'center' });
          const rect = input.getBoundingClientRect();
          return { x: Math.round(rect.left + rect.width / 2), y: Math.round(rect.top + rect.height / 2) };
        };
        const combos = [...document.querySelectorAll('input[role=combobox], [role=combobox] input')]
          .filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && !el.closest('.next-overlay-wrapper');
          });
        for (const input of combos) {
          // 面板属性 item 容器（类目页 sell-catProp-*）的文本以 label 开头；
          // 属于其他 label 的框直接跳过，避免爬深层祖先后误配。
          const item = input.closest('.sell-catProp-item-common, .sell-component-item-prop-item, .next-form-item');
          if (item) {
            const t = norm(item);
            if (t.startsWith(lab) && t.length < 120) return locate(input);
            continue;
          }
          let root = input;
          for (let k = 0; k < 8 && root; k++) {
            root = root.parentElement;
            const t = root ? norm(root) : '';
            if (t.startsWith(lab) && t.length < 120) return locate(input);
          }
        }
        return null;
      }, label);
      if (!hit) { panelLog.push(label + "=NO_MATCH"); break; }
      await page.mouse.click(hit.x, hit.y).catch(() => {});
      await sleep(300);
      await page.keyboard.insertText(value).catch(() => {});
      await sleep(1400);
      await page.evaluate((val) => {
        const opts = [...document.querySelectorAll('.options-item, [role=option], .next-menu-item')]
          .filter((el) => {
            const t = (el.innerText || '').trim();
            const rect = el.getBoundingClientRect();
            return t === val && rect.width > 0;
          });
        if (opts.length) opts[0].click();
      }, value).catch(() => {});
      await sleep(500);
      const got = await page.evaluate((lab) => {
        const norm = (el) => (el.innerText || '').replace(/\s+/g, '');
        const combos = [...document.querySelectorAll('input[role=combobox], [role=combobox] input')]
          .filter((el) => {
            const rect = el.getBoundingClientRect();
            return rect.width > 0 && rect.height > 0 && !el.closest('.next-overlay-wrapper');
          });
        for (const input of combos) {
          const item = input.closest('.sell-catProp-item-common, .sell-component-item-prop-item, .next-form-item');
          if (item) {
            const t = norm(item);
            if (t.startsWith(lab) && t.length < 120) return input.value.trim();
            continue;
          }
          let root = input;
          for (let k = 0; k < 8 && root; k++) {
            root = root.parentElement;
            const t = root ? norm(root) : '';
            if (t.startsWith(lab) && t.length < 120) return input.value.trim();
          }
        }
        return "";
      }, label).catch(() => "");
      if (got === value) stuck = true;
      else panelLog.push(label + "=lost:" + String(got).slice(0, 20));
    }
    if (stuck) panelLog.push(label + "=stuck");
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
