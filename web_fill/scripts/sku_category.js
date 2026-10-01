async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await dismissKnow();
  const skuCategory = PAYLOAD.sku_category || "单品";
  const log = [];

  // 规格表是虚拟滚动表格（DOM 只渲染可视区约一屏，37 行实测恒显示 17 行，
  // 见 sku_import.js deepRows 注释）。逐行设置分类必须配合滚动，否则第 18 行
  // 起的规格行永远不在 DOM 里，提交后会被淘宝整行丢弃（2026-10-01 事故：
  // 37 行输入只处理了可视区 17 行，建出只有 17 行规格的商品）。
  for (let round = 0; round < 150; round++) {
    const action = await page.evaluate((target) => {
      const rows = () => [...document.querySelectorAll("table tr")].filter((tr) => {
        const t = tr.innerText || "";
        return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
      });
      function classify(tr) {
        const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
        const yuan = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("元"));
        const jian = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("件"));
        return inputs.filter((el) => el !== yuan && el !== jian)[0];
      }
      for (const tr of rows()) {
        const el = classify(tr);
        if (!el) continue;
        const cell = ((el.closest("td") && el.closest("td").innerText) || "");
        if ((el.value || "").trim() === target || cell.includes(target)) continue;
        el.scrollIntoView({ block: "center" });
        el.click();
        return "click";
      }
      let cont = null;
      for (const tr of rows()) {
        let node = tr.parentElement;
        while (node && node !== document.body) {
          const st = getComputedStyle(node);
          if (/(auto|scroll)/.test(st.overflowY) && node.scrollHeight > node.clientHeight + 50) { cont = node; break; }
          node = node.parentElement;
        }
        if (cont) break;
      }
      if (cont && cont.scrollTop < cont.scrollHeight - cont.clientHeight - 2) {
        cont.scrollTop = Math.min(cont.scrollTop + Math.max(200, Math.floor(cont.clientHeight * 0.7)), cont.scrollHeight);
        return "scroll";
      }
      const next = [...document.querySelectorAll("button, a, li")].find((n) => /下一页|下页/.test((n.innerText || "").trim()) && (n.innerText || "").trim().length < 8);
      if (next && !next.disabled && !String(next.className).includes("disabled")) {
        next.click();
        return "next";
      }
      return "done";
    }, skuCategory);
    if (action === "click") {
      log.push(await clickOverlayText(skuCategory));
      await page.keyboard.press("Escape");
      await sleep(180);
      continue;
    }
    if (action === "done") break;
    await sleep(400);
  }

  // 终检：逐屏滚动采全所有行（与 sku_import.js deepRows 相同的采集方式），
  // 统计未设置分类的行。missing > 0 时由 pipeline 在建品/提交前判失败并重试，
  // 不允许带着不完整的规格表提交。
  const audit = await page.evaluate(async (target) => {
    const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
    const rowsOf = () => [...document.querySelectorAll("table tr")].filter((tr) => {
      const t = tr.innerText || "";
      return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
    });
    const classify = (tr) => {
      const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
      const yuan = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("元"));
      const jian = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("件"));
      return inputs.filter((el) => el !== yuan && el !== jian)[0];
    };
    const readRow = (tr) => {
      const el = classify(tr);
      const cell = el ? ((el.closest("td") && el.closest("td").innerText) || "") : "";
      return {
        text: (tr.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
        values: [...tr.querySelectorAll("input, textarea")].map((el2) => String(el2.value || "").trim()),
        set: !el || (el.value || "").trim() === target || cell.includes(target),
      };
    };
    let cont = null;
    for (const tr of rowsOf()) {
      let node = tr.parentElement;
      while (node && node !== document.body) {
        const st = getComputedStyle(node);
        if (/(auto|scroll)/.test(st.overflowY) && node.scrollHeight > node.clientHeight + 50) { cont = node; break; }
        node = node.parentElement;
      }
      if (cont) break;
    }
    const seen = new Map();
    const collect = () => {
      for (const tr of rowsOf()) {
        const row = readRow(tr);
        // 渲染滞后的瞬间可能采到输入框还没挂值的半渲染行，跳过避免幽灵行。
        if (!row.values.some((v) => v)) continue;
        seen.set(JSON.stringify(row.values) + "|" + row.text, row);
      }
    };
    if (!cont) {
      collect();
    } else {
      const startTop = cont.scrollTop;
      cont.scrollTop = 0;
      await pause(400);
      collect();
      const step = Math.max(200, Math.floor(cont.clientHeight * 0.7));
      let guard = 0;
      while (guard++ < 80) {
        const before = cont.scrollTop;
        cont.scrollTop = Math.min(before + step, cont.scrollHeight);
        await pause(400);
        collect();
        if (cont.scrollTop >= cont.scrollHeight - cont.clientHeight - 2) break;
        if (cont.scrollTop === before) break;
      }
      cont.scrollTop = startTop;
      await pause(300);
      collect();
    }
    const rows = [...seen.values()];
    const missing = rows.filter((row) => !row.set).length;
    return { total: rows.length, set: rows.length - missing, missing };
  }, skuCategory);

  return JSON.stringify({
    skuCategory,
    log,
    audit: true,
    total: audit.total,
    set: audit.set,
    missing: audit.missing,
    ok: audit.total > 0 && audit.missing === 0,
  }, null, 2);
}
