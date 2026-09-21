async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await hideScenarioWidgets();
  await dismissBlockingDialogs();
  await page.keyboard.press("Escape").catch(() => {});
  await sleep(250);
  const specs = PAYLOAD.skus || [];
  if (!specs.length) return JSON.stringify({ skipped: true });

  async function openDrawer() {
    if (await page.locator(".sku-decouple-drawer").count()) return "already";
    const opened = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")].find((el) => {
        const t = (el.innerText || "").trim();
        return t === "编辑规格" || t.includes("创建规格");
      });
      if (!btn) return "NO";
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return "OPEN";
    });
    await sleep(800);
    return opened;
  }

  async function switchSpecTab() {
    return page.evaluate(() => {
      const drawerEl = document.querySelector(".sku-decouple-drawer");
      if (!drawerEl) return "NO_DRAWER";
      const custom = [...drawerEl.querySelectorAll("*")].find((el) => (el.innerText || "").trim() === "单层展示·自定义填写规格" && el.childNodes.length <= 6);
      if (custom) custom.click();
      const tabs = [...drawerEl.querySelectorAll("[role=tab], .next-tabs-tab, li, button, span, div")];
      const tab = tabs.find((el) => (el.innerText || "").replace(/\s+/g, "") === "商品规格")
        || tabs.find((el) => /颜色分类|^颜色$/.test((el.innerText || "").replace(/\s+/g, "")));
      if (tab) tab.click();
      const clicked = tab ? (tab.innerText || "").trim() : "";
      const label = (drawerEl.querySelector(".props-label") && drawerEl.querySelector(".props-label").innerText) || "";
      const inputs = drawerEl.querySelectorAll('input[placeholder="输入规格"]').length;
      return { clicked, label, inputs };
    });
  }

  const opened = await openDrawer();
  if (opened === "NO") throw new Error("PAUSE:未找到编辑规格/创建规格");
  let switched = await switchSpecTab();
  await sleep(400);
  if (switched === "NO_DRAWER" || (switched && switched.inputs === 0) || /书写粗细/.test((switched && switched.label) || "")) {
    await sleep(500);
    switched = await switchSpecTab();
    await sleep(400);
  }
  if (switched === "NO_DRAWER") throw new Error("PAUSE:规格抽屉未打开");
  if (/书写粗细/.test((switched && switched.label) || "")) {
    throw new Error("PAUSE:规格面板停在书写粗细，请改到商品规格后再试");
  }

  async function state() {
    return page.evaluate(() => {
      const drawerEl = document.querySelector(".sku-decouple-drawer");
      if (!drawerEl) return { open: false, names: [], addDisabled: true, emptyLast: false, count: "" };
      const names = [...drawerEl.querySelectorAll('input[placeholder="输入规格"]')].map((el) => el.value);
      const add = drawerEl.querySelector("button.add");
      return {
        open: true,
        names,
        addDisabled: !!(add && add.disabled),
        emptyLast: names.length > 0 && !String(names[names.length - 1] || "").trim(),
        count: (drawerEl.querySelector(".props-label") && drawerEl.querySelector(".props-label").innerText) || "",
        inputs: names.length,
      };
    });
  }

  async function commitRow(want) {
    await page.keyboard.press("Enter");
    await sleep(200);
    await page.evaluate((value) => {
      const wraps = [...document.querySelectorAll(".next-overlay-wrapper, ul.color-suggest-wrapper")].filter((el) => getComputedStyle(el).display !== "none");
      for (const wrap of wraps) {
        const items = [...wrap.querySelectorAll("li, .next-menu-item")];
        const hit = items.find((el) => (el.innerText || "").trim() === value);
        if (hit) {
          hit.click();
          return;
        }
      }
    }, want);
    await sleep(160);
    await page.keyboard.press("Tab");
    await sleep(150);
    await page.evaluate(() => {
      const drawerEl = document.querySelector(".sku-decouple-drawer");
      const label = drawerEl && drawerEl.querySelector(".props-label");
      if (label) label.click();
      const expanded = drawerEl && drawerEl.querySelector("[aria-expanded=true] input, [aria-expanded=true]");
      if (expanded && expanded.blur) expanded.blur();
    });
    await sleep(280);
  }

  async function typeSpecName(name) {
    const box = page.locator('.sku-decouple-drawer input[placeholder="输入规格"]').last();
    if (!(await box.count())) return { ok: false, how: "NO_INPUT", actual: "" };
    await box.click({ force: true, timeout: 2500 }).catch(() => {});
    const want = String(name);
    // Keyboard events for ASCII digits are intercepted by shortcuts on this drawer.
    // Fill the complete value in one input event so names such as "1弹" stay intact.
    await box.fill(want);
    await sleep(120);
    let actual = await box.inputValue().catch(() => "");
    let how = "fill";
    if (actual !== want) {
      await box.click({ force: true, timeout: 2500 }).catch(() => {});
      await page.keyboard.press("Control+A").catch(() => {});
      await page.keyboard.insertText(want);
      await sleep(120);
      actual = await box.inputValue().catch(() => "");
      how = "insertText";
    }
    return { ok: actual === want, how, actual };
  }

  const log = [];
  for (const spec of specs) {
    const name = spec.name;
    let st = await state();
    if (st.names.includes(name)) {
      log.push(name + ":exists " + st.count);
      continue;
    }
    if (!st.open || !st.inputs) {
      await openDrawer();
      await switchSpecTab();
      st = await state();
    }
    if (!st.emptyLast) {
      let added = "pending";
      for (let i = 0; i < 20; i++) {
        st = await state();
        if (st.emptyLast) {
          added = "empty-row";
          break;
        }
        added = await page.evaluate(() => {
          const drawerEl = document.querySelector(".sku-decouple-drawer");
          if (!drawerEl) return "no-drawer";
          const btn = drawerEl.querySelector("button.add");
          if (!btn) return "no-btn";
          if (btn.disabled) return "disabled";
          btn.click();
          return "clicked";
        });
        if (added === "clicked") break;
        if (added === "no-drawer" || added === "no-btn") break;
        await sleep(350);
      }
      await sleep(280);
      if (added !== "clicked" && added !== "empty-row") {
        throw new Error("PAUSE:无法新增规格行 " + name + " " + added + " " + JSON.stringify(await state()));
      }
    }
    const typed = await typeSpecName(name);
    if (!typed.ok) {
      throw new Error("PAUSE:规格输入被改写 " + name + " => " + typed.actual + " via=" + typed.how);
    }
    await commitRow(name);
    let seen = false;
    for (let i = 0; i < 16; i++) {
      st = await state();
      seen = st.names.includes(name);
      if (seen && !st.addDisabled) break;
      await sleep(280);
    }
    log.push(name + (seen ? ":ok " : ":unconfirmed ") + st.count);
    if (!seen) throw new Error("PAUSE:规格未写入 " + name + " " + JSON.stringify(st));
  }

  const confirm = await page.evaluate(() => {
    const btn = [...document.querySelectorAll(".sku-decouple-drawer button")].find((el) => (el.innerText || "").includes("确认创建"));
    if (!btn) return "NO";
    if (btn.disabled) return "DISABLED";
    btn.click();
    return "CLICKED";
  });
  for (let i = 0; i < 24; i++) {
    const ready = await page.evaluate(() => {
      const drawer = document.querySelector(".sku-decouple-drawer");
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const t = tr.innerText || "";
        return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
      });
      return { drawer: !!drawer, rows: rows.length };
    });
    if (!ready.drawer && ready.rows > 0) break;
    if (ready.drawer && i === 6) {
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll(".sku-decouple-drawer button")].find((el) => (el.innerText || "").includes("确认创建"));
        if (btn && !btn.disabled) btn.click();
      });
    }
    await sleep(400);
  }
  await sleep(400);

  const tableInputs = page.locator("table input");
  const count = await tableInputs.count();
  const filled = [];
  for (let i = 0; i < count; i++) {
    const meta = await tableInputs.nth(i).evaluate((el) => ({
      val: el.value,
      disabled: el.disabled,
      type: el.type,
      cell: (el.closest("td") && el.closest("td").innerText) || "",
      row: (el.closest("tr") && el.closest("tr").innerText) || "",
    }));
    if (meta.disabled || meta.type === "checkbox" || meta.type === "radio") continue;
    const sku = specs.find((item) => meta.row.includes(item.name)) || null;
    const price = sku ? String(sku.price) : String((specs[0] && specs[0].price) || "");
    const stock = sku ? String(sku.stock) : String((specs[0] && specs[0].stock) || "");
    if (/元/.test(meta.cell) && price) {
      await tableInputs.nth(i).fill(price);
      filled.push({ i, as: "price", name: sku && sku.name });
    }
    if (/件/.test(meta.cell) && stock) {
      await tableInputs.nth(i).fill(stock);
      filled.push({ i, as: "qty", name: sku && sku.name });
    }
  }

  async function fillRowSelects(kind, value) {
    const log = [];
    for (let round = 0; round < specs.length + 4; round++) {
      const opened = await page.evaluate(({ wantKind, already }) => {
        function classify(tr) {
          const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
          const yuan = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("元"));
          const jian = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("件"));
          const rest = inputs.filter((el) => el !== yuan && el !== jian);
          return { cat: rest[0], thick: rest[1] };
        }
        const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
          const t = tr.innerText || "";
          return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
        });
        for (const tr of rows) {
          const pair = classify(tr);
          const el = wantKind === "sku_category" ? pair.cat : pair.thick;
          if (!el) continue;
          const cell = ((el.closest("td") && el.closest("td").innerText) || "");
          if ((el.value || "").trim() === already || cell.includes(already)) continue;
          el.scrollIntoView({ block: "center" });
          el.click();
          return true;
        }
        const next = [...document.querySelectorAll("button, a, li")].find((n) => /下一页|下页/.test((n.innerText || "").trim()) && (n.innerText || "").trim().length < 8);
        if (next && !next.disabled && !String(next.className).includes("disabled")) {
          next.click();
          return "NEXT";
        }
        return false;
      }, { wantKind: kind, already: value });
      if (!opened) break;
      if (opened === "NEXT") {
        await sleep(400);
        continue;
      }
      await sleep(400);
      log.push(await clickOverlayText(value));
      await page.keyboard.press("Escape");
      await sleep(200);
    }
    return log;
  }

  const skuCategory = PAYLOAD.sku_category || "单品";
  const thickness = PAYLOAD.thickness || "0.05mm";
  const catLog = await fillRowSelects("sku_category", skuCategory);
  const thickLog = await fillRowSelects("thickness", thickness);

  const after = await page.evaluate(() => {
    const t = document.body.innerText || "";
    return {
      drawer: !!document.querySelector(".sku-decouple-drawer"),
      skuMode: /SKU模式/.test(t),
      cats: [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件")).map((tr) => {
        const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox");
        const rest = inputs.filter((el) => !/元|件/.test((el.closest("td") && el.closest("td").innerText) || ""));
        return { cat: rest[0] && rest[0].value, thick: rest[1] && rest[1].value };
      }),
    };
  });
  return JSON.stringify({ opened, confirm, log, filled: filled.length, catLog, thickLog, after }, null, 2);
}
