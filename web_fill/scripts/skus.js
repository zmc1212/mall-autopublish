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
  // 规格维度名按类目取：中性笔=商品规格，潮玩盲盒=款式描述。内联模式
  // （发布页无“编辑规格”抽屉）用它定位销售属性区的维度容器。
  const specName = String(PAYLOAD.spec_name || "").trim();
  let INLINE = false;

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

  // 内联模式探测：潮玩盲盒等类目把规格值直接内联在销售属性区
  // （.props-label 为“款式描述(N)”的维度容器，规格名输入框无统一
  // placeholder），找不到抽屉按钮时按 spec_name 定位容器并打标记。
  async function probeInline() {
    const probe = await page.evaluate((name) => {
      if (!name) return { ok: false, why: "no-spec-name" };
      const label = [...document.querySelectorAll(".props-label")]
        .find((el) => ((el.innerText || "").replace(/\s+/g, "")).startsWith(name));
      if (!label) return { ok: false, why: "no-label" };
      const wrap = label.closest(".common-wrap") || label.parentElement;
      if (!wrap) return { ok: false, why: "no-wrap" };
      const inputs = [...wrap.querySelectorAll("input")].filter((el) => {
        const st = getComputedStyle(el);
        return !el.disabled && el.type !== "checkbox" && el.type !== "radio"
          && st.display !== "none" && st.visibility !== "hidden";
      });
      if (!inputs.length) return { ok: false, why: "no-input" };
      wrap.setAttribute("data-sku-inline", "1");
      return { ok: true };
    }, specName);
    if (probe.ok) INLINE = true;
    return probe;
  }

  // 标记会被 React 重渲染丢失：state 前若发现标记缺失则重新定位。
  async function ensureInlineMark() {
    if (!INLINE) return;
    await page.evaluate((name) => {
      if (document.querySelector('[data-sku-inline="1"]')) return;
      const label = [...document.querySelectorAll(".props-label")]
        .find((el) => ((el.innerText || "").replace(/\s+/g, "")).startsWith(name));
      const wrap = label && (label.closest(".common-wrap") || label.parentElement);
      if (wrap) wrap.setAttribute("data-sku-inline", "1");
    }, specName);
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
  if (opened === "NO") {
    const probe = await probeInline();
    if (!probe.ok) throw new Error("PAUSE:未找到编辑规格/创建规格");
  }
  if (!INLINE) {
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
  }

  async function state() {
    await ensureInlineMark();
    return page.evaluate((inline) => {
      const scope = inline
        ? document.querySelector('[data-sku-inline="1"]')
        : document.querySelector(".sku-decouple-drawer");
      if (!scope) return { open: false, names: [], addDisabled: true, emptyLast: false, count: "", inputs: 0 };
      const names = inline
        ? [...scope.querySelectorAll("input")].filter((el) => {
            const st = getComputedStyle(el);
            return !el.disabled && el.type !== "checkbox" && el.type !== "radio"
              && st.display !== "none" && st.visibility !== "hidden";
          }).map((el) => el.value)
        : [...scope.querySelectorAll('input[placeholder="输入规格"]')].map((el) => el.value);
      const add = scope.querySelector("button.add");
      return {
        open: true,
        names,
        addDisabled: !!(add && add.disabled),
        emptyLast: names.length > 0 && !String(names[names.length - 1] || "").trim(),
        count: (scope.querySelector(".props-label") && scope.querySelector(".props-label").innerText) || "",
        inputs: names.length,
      };
    }, INLINE);
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
    const box = page.locator(INLINE
      ? '[data-sku-inline="1"] input'
      : '.sku-decouple-drawer input[placeholder="输入规格"]').last();
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
        added = await page.evaluate((inline) => {
          const drawerEl = inline
            ? document.querySelector('[data-sku-inline="1"]')
            : document.querySelector(".sku-decouple-drawer");
          if (!drawerEl) return "no-drawer";
          const btn = drawerEl.querySelector("button.add");
          if (!btn) return "no-btn";
          if (btn.disabled) return "disabled";
          btn.click();
          return "clicked";
        }, INLINE);
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

  // 填写、失焦提交、表格重建后的回读统一使用同一套规格定位。
  const unresolved = await verifySkuTableValues(page, specs);
  if (unresolved.length) {
    throw new Error("PAUSE:规格表价格或库存与输入不一致（"
      + unresolved.map((item) => item.name + ": " + (item.got || "空") + "≠" + item.want
        + (item.reason || item.error ? " [" + (item.reason || item.error) + "]" : "")).join("；")
      + "），未继续提交");
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
  // 模板导入补值时厚度列刻意留空（skip_thickness），不能用默认值污染。
  // 其他类目（潮玩盲盒等）表格没有书写粗细列，同样不能按默认值乱填。
  const hasThicknessCol = await page.evaluate(() => {
    const header = [...document.querySelectorAll("table th, table thead td")].map((el) => (el.innerText || "").trim());
    return header.some((t) => t.includes("书写粗细"));
  });
  const thickLog = (PAYLOAD.skip_thickness || !hasThicknessCol) ? [] : await fillRowSelects("thickness", thickness);

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
  return JSON.stringify({ opened, confirm, log, filled: specs.length * 2, catLog, thickLog, after }, null, 2);
}
