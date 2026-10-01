async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // audit 阶段只读（滚动采集行，不点击不修改），允许在已有商品编辑页执行；
  // 其余阶段会写入/导入，仍然禁止进入已有商品编辑页。
  if (PAYLOAD.phase !== "audit" && unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const file = PAYLOAD.file;
  const expected = (PAYLOAD.skus || []).map((sku) => String(sku.name || "").trim());

  async function tableState() {
    return page.evaluate(() => {
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const text = tr.innerText || "";
        return text.includes("元") && text.includes("件") && !text.includes("SKU分类");
      });
      return rows.map((tr) => ({
        text: (tr.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
        values: [...tr.querySelectorAll("input, textarea")].map((el) => String(el.value || "").trim()),
      }));
    });
  }

  // SKU 表格是虚拟滚动（ver-scroll-wrap，DOM 只渲染可视区约 17 行），
  // 逐屏滚动累加全部行后再还原滚动位置。虚拟窗口的重渲染是异步的且滞后
  // 于滚动（隐藏窗口下更慢），每步必须等渲染追上再采集，否则 union 残缺。
  async function deepRows() {
    return await page.evaluate(async () => {
      const pause = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
      const qualify = (tr) => {
        const text = tr.innerText || "";
        return text.includes("元") && text.includes("件") && !text.includes("SKU分类");
      };
      const readRow = (tr) => ({
        text: (tr.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160),
        values: [...tr.querySelectorAll("input, textarea")].map((el) => String(el.value || "").trim()),
      });
      const allRows = () => [...document.querySelectorAll("table tr")].filter(qualify);
      let cont = null;
      for (const tr of allRows()) {
        let el = tr.parentElement;
        while (el && el !== document.body) {
          const st = getComputedStyle(el);
          if (/(auto|scroll)/.test(st.overflowY) && el.scrollHeight > el.clientHeight + 50) { cont = el; break; }
          el = el.parentElement;
        }
        if (cont) break;
      }
      if (!cont) return allRows().map(readRow);
      const seen = new Map();
      const collect = () => {
        for (const tr of allRows()) {
          const row = readRow(tr);
          // 渲染滞后的瞬间可能采到输入框还没挂值的半渲染行，跳过避免幽灵行。
          if (!row.values.some((v) => v)) continue;
          seen.set(JSON.stringify(row.values) + "|" + row.text, row);
        }
      };
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
      return [...seen.values()];
    });
  }

  function matching(rows) {
    const used = new Set();
    return expected.filter((name) => {
      const index = rows.findIndex((row, i) => !used.has(i)
        && (row.values.includes(name) || row.text.split(/\s+/).includes(name)));
      if (index < 0) return false;
      used.add(index);
      return true;
    });
  }

  if (PAYLOAD.phase === "open") {
    await hideScenarioWidgets();
    const existing = await deepRows();
    if (expected.length && matching(existing).length === expected.length) {
      return JSON.stringify({ uploaded: true, already: true });
    }
    const pendingRecognition = page.getByText("确认识别", { exact: true }).last();
    if (await pendingRecognition.count() && await pendingRecognition.isVisible()) {
      const selected = await page.evaluate(() => {
        const text = (document.body.innerText || "").replace(/\s+/g, " ");
        return /SKU导入_[\da-f]{8}/i.test(text);
      });
      if (selected) return JSON.stringify({ uploaded: true, via: "pending-recognition" });
    }
    const pendingAdd = page.getByText("在当前规格后添加", { exact: true }).last();
    if (await pendingAdd.count() && await pendingAdd.isVisible()) {
      const recognized = await page.evaluate(() => /已成功识别\s*\d+\s*个销售属性/.test(document.body.innerText || ""));
      if (recognized) return JSON.stringify({ uploaded: true, via: "pending-add" });
    }
    const entry = await page.evaluate(() => {
      const visible = (el) => {
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
      };
      const label = (el) => (el.innerText || "").replace(/\s+/g, "").trim();
      const candidates = [...document.querySelectorAll("button, a, [role=button], span, div")]
        .filter(visible)
        .filter((el) => /^(批量导入|导入SKU|导入规格|Excel导入)$/.test(label(el)));
      if (!candidates.length) return { found: false, nearby: [...document.querySelectorAll("button, a, [role=button]")]
        .filter(visible).map(label).filter((text) => /导入|销售|规格/.test(text)).slice(0, 12) };
      const heading = [...document.querySelectorAll("h1, h2, h3, span, div")]
        .find((el) => visible(el) && label(el) === "销售信息");
      const anchor = heading ? heading.getBoundingClientRect().top : null;
      candidates.sort((a, b) => {
        const score = (el) => {
          const tag = el.tagName.toLowerCase();
          const semantic = /^(button|a)$/.test(tag) || el.getAttribute("role") === "button" ? 0 : 1;
          const distance = anchor == null ? 0 : Math.abs(el.getBoundingClientRect().top - anchor);
          return distance + semantic * 8;
        };
        return score(a) - score(b);
      });
      const target = candidates[0];
      target.scrollIntoView({ block: "center" });
      target.click();
      return { found: true, label: label(target), tag: target.tagName, className: String(target.className || "").slice(0, 100) };
    });
    if (!entry.found) return JSON.stringify({ unavailable: true, reason: "未找到销售信息中的批量导入入口", rows: existing.length, nearby: entry.nearby });
    await sleep(350);
    const inputs = page.locator("input[type=file]");
    const count = await inputs.count();
    for (let i = 0; i < count; i++) {
      const info = await inputs.nth(i).evaluate((el) => ({
        accept: String(el.accept || "").toLowerCase(),
        scope: (el.closest(".next-dialog, [role=dialog], [class*='sku'], [class*='Sku']")?.innerText || "").slice(0, 200),
      }));
      if (!/xls|xlsx|excel|spreadsheet|csv/.test(info.accept) && !/批量导入|导入SKU|导入规格/.test(info.scope)) continue;
      await inputs.nth(i).setInputFiles(file, { timeout: 15000 });
      return JSON.stringify({ uploaded: true, via: "input", entry: entry.label });
    }
    const chooser = page.locator(".next-dialog:visible, [role=dialog]:visible")
      .filter({ hasText: /批量导入|导入SKU|导入规格/ }).last()
      .getByRole("button", { name: /^(选择文件|上传文件|选择Excel文件)$/ }).first();
    if (await chooser.count()) {
      try {
        await chooser.click({ timeout: 5000 });
      } catch (error) {
        // 选择器被遮挡/重渲染时放弃点击，交给 pipeline 的 upload_files 兜底
      }
    }
    return JSON.stringify({ uploaded: false, entry: entry.label });
  }

  if (PAYLOAD.phase === "audit") {
    // 提交前审计：逐屏滚动采全规格行（deepRows），核对与输入模板的行数与
    // 名称差异。页面是虚拟滚动表格，可视行数恒约一屏，不能用可视行数判断。
    const rows = await deepRows();
    const used = new Set();
    const missing = expected.filter((name) => {
      const index = rows.findIndex((row, i) => !used.has(i)
        && (row.values.includes(name) || row.text.split(/\s+/).includes(name)));
      if (index < 0) return true;
      used.add(index);
      return false;
    });
    const extra = rows
      .filter((row, i) => !used.has(i))
      .map((row) => (row.values.find((v) => v) || row.text.split(/\s+/)[0] || "").slice(0, 60))
      .filter((name) => name && !name.includes("元") && !name.includes("件"));
    return JSON.stringify({ audit: true, count: rows.length, expected: expected.length, missing, extra });
  }

  if (PAYLOAD.phase !== "verify") throw new Error("未知 SKU 导入阶段");
  let recognitionClicked = false;
  let importConfirmed = false;
  const addedDimensions = new Set();
  // 可视行数在虚拟滚动表格里恒为约一屏（37 行实测恒显示 17 行），不能作为
  // 部分导入的判据；部分判定只看相邻两次深度扫描是否零增长，且弹窗已关闭。
  let lastDeep = null;
  let stableDeep = 0;
  for (let attempt = 0; attempt < 120; attempt++) {
    const deep = attempt % 6 === 0;
    const rows = deep ? await deepRows() : await tableState();
    const matched = matching(rows);
    if (matched.length === expected.length && rows.length === expected.length) {
      return JSON.stringify({ verified: true, count: rows.length, matched: matched.length, recognitionClicked, importConfirmed });
    }
    if (deep) {
      if (lastDeep && importConfirmed && rows.length === lastDeep.count) stableDeep++;
      else stableDeep = 0;
      lastDeep = { count: rows.length, matched: matched.length, at: attempt };
    }
    // 确认识别：识别处理期间父按钮可能禁用/动画中。getByText 会命中按钮内
    // 的文字 span（next-btn-helper），count/isVisible/isEnabled 预检查通过但
    // click 等待可点超时，整个脚本就此崩溃（2026-10-01 TimeoutError 事故）。
    // 因此优先按 role 取按钮、点击失败不抛出，等下一轮按钮恢复可点再点。
    let recognize = page.getByRole("button", { name: "确认识别" }).last();
    if (!(await recognize.count())) {
      recognize = page.getByText("确认识别", { exact: true }).last();
    }
    if (!recognitionClicked && await recognize.count() && await recognize.isVisible() && await recognize.isEnabled()) {
      try {
        await recognize.click({ timeout: 5000 });
      } catch (error) {
        await sleep(700);
        continue;
      }
      recognitionClicked = true;
      await sleep(700);
      continue;
    }
    const addCurrent = page.getByText("在当前规格后添加", { exact: true }).last();
    if (await addCurrent.count() && await addCurrent.isVisible() && await addCurrent.isEnabled()) {
      const bodyText = await page.locator("body").innerText();
      const marker = bodyText.lastIndexOf("已成功识别");
      const text = marker < 0 ? "" : bodyText.slice(marker);
      if (text) {
        const normalized = text.replace(/\s+/g, "");
        const isSpec = normalized.includes("商品规格");
        const counts = [...normalized.matchAll(/已选择(\d+)个属性/g)].map((match) => Number(match[1]));
        if (!isSpec || !counts.includes(expected.length)) {
          return JSON.stringify({ verified: false,
            error: `识别结果与模板不一致，未自动添加：${text.replace(/\s+/g, " ").slice(0, 300)}`,
            count: rows.length, matched: matched.length, expected: expected.length, recognitionClicked });
        }
        if (!addedDimensions.has("商品规格")) {
          try {
            await addCurrent.click({ timeout: 5000 });
          } catch (error) {
            await sleep(500);
            continue;
          }
          addedDimensions.add("商品规格");
          importConfirmed = true;
          stableDeep = 0;
          lastDeep = null;
          await sleep(700);
          continue;
        }
      }
    }
    const dialog = page.locator(".next-dialog:visible, [role=dialog]:visible, [class*='Modal']:visible, [class*='modal']:visible")
      .filter({ hasText: /批量导入|识别结果|导入结果|已成功识别/ }).last();
    let dialogOpen = false;
    if (await dialog.count()) {
      dialogOpen = true;
      const text = await dialog.innerText().catch(() => "");
      if (/导入失败|格式错误|上传失败|解析失败|识别失败|文件类型错误/.test(text)) {
        return JSON.stringify({ verified: false, error: text.slice(0, 300), count: rows.length, matched: matched.length, recognitionClicked });
      }
      if (typeof dialog.getByRole === "function") {
        const confirm = dialog.getByRole("button", { name: /^(确认导入|开始导入|确定导入|应用到商品|确认使用)$/ }).first();
        if (!importConfirmed && await confirm.count() && await confirm.isEnabled()) {
          try {
            await confirm.click({ timeout: 5000 });
            importConfirmed = true;
          } catch (error) {
            // 弹窗重渲染导致点击失败：下一轮重新尝试
          }
        }
      }
    }
    if (importConfirmed && !dialogOpen && stableDeep >= 2 && lastDeep) {
      return JSON.stringify({ verified: false, partial: true, earlyExit: true,
        count: lastDeep.count, matched: lastDeep.matched, expected: expected.length,
        recognitionClicked, importConfirmed, addedDimensions: [...addedDimensions] });
    }
    await sleep(500);
  }
  const rows = await deepRows();
  const diagnostics = await page.evaluate(() => ({
    buttons: [...document.querySelectorAll("button, [role=button]")]
      .filter((el) => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== "hidden";
      })
      .map((el) => (el.innerText || "").replace(/\s+/g, " ").trim())
      .filter((text) => /导入|识别|应用|确认/.test(text)).slice(-12),
    notice: (document.body.innerText || "").replace(/\s+/g, " ").slice(-350),
  }));
  return JSON.stringify({ verified: false, count: rows.length, matched: matching(rows).length,
    expected: expected.length, recognitionClicked, importConfirmed,
    addedDimensions: [...addedDimensions], diagnostics });
}
