async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
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
    const existing = await tableState();
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
    if (await chooser.count()) await chooser.click({ timeout: 5000 });
    return JSON.stringify({ uploaded: false, entry: entry.label });
  }

  if (PAYLOAD.phase !== "verify") throw new Error("未知 SKU 导入阶段");
  let recognitionClicked = false;
  let importConfirmed = false;
  const addedDimensions = new Set();
  for (let attempt = 0; attempt < 120; attempt++) {
    const rows = await tableState();
    const matched = matching(rows);
    if (matched.length === expected.length && rows.length === expected.length) {
      return JSON.stringify({ verified: true, count: rows.length, matched: matched.length, recognitionClicked, importConfirmed });
    }
    const recognize = page.getByText("确认识别", { exact: true }).last();
    if (!recognitionClicked && await recognize.count() && await recognize.isVisible() && await recognize.isEnabled()) {
      await recognize.click({ timeout: 5000 });
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
          await addCurrent.click({ timeout: 5000 });
          addedDimensions.add("商品规格");
          importConfirmed = true;
          await sleep(700);
          continue;
        }
      }
    }
    const dialog = page.locator(".next-dialog:visible, [role=dialog]:visible, [class*='Modal']:visible, [class*='modal']:visible")
      .filter({ hasText: /批量导入|识别结果|导入结果|已成功识别/ }).last();
    if (await dialog.count()) {
      const text = await dialog.innerText().catch(() => "");
      if (/导入失败|格式错误|上传失败|解析失败|识别失败|文件类型错误/.test(text)) {
        return JSON.stringify({ verified: false, error: text.slice(0, 300), count: rows.length, matched: matched.length, recognitionClicked });
      }
      if (typeof dialog.getByRole === "function") {
        const confirm = dialog.getByRole("button", { name: /^(确认导入|开始导入|确定导入|应用到商品|确认使用)$/ }).first();
        if (!importConfirmed && await confirm.count() && await confirm.isEnabled()) {
          await confirm.click({ timeout: 5000 });
          importConfirmed = true;
        }
      }
    }
    await sleep(500);
  }
  const rows = await tableState();
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
