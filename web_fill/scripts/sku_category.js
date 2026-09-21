async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await dismissKnow();
  const skuCategory = PAYLOAD.sku_category || "单品";
  const log = [];

  for (let round = 0; round < 24; round++) {
    const opened = await page.evaluate((already) => {
      function classify(tr) {
        const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
        const yuan = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("元"));
        const jian = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("件"));
        const rest = inputs.filter((el) => el !== yuan && el !== jian);
        return rest[0];
      }
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const t = tr.innerText || "";
        return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
      });
      for (const tr of rows) {
        const el = classify(tr);
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
    }, skuCategory);
    if (!opened) break;
    if (opened === "NEXT") {
      await sleep(400);
      continue;
    }
    await sleep(400);
    log.push(await clickOverlayText(skuCategory));
    await page.keyboard.press("Escape");
    await sleep(180);
  }

  const after = await page.evaluate(() => [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件") && !(tr.innerText || "").includes("SKU分类")).map((tr) => {
    const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox");
    const rest = inputs.filter((el) => !/元|件/.test((el.closest("td") && el.closest("td").innerText) || ""));
    const el = rest[0];
    return {
      val: el ? el.value : "",
      cell: el ? ((el.closest("td") && el.closest("td").innerText) || "").replace(/\s+/g, " ").trim() : "",
      rowHas: /单品/.test(tr.innerText || ""),
    };
  }));
  return JSON.stringify({ skuCategory, log, after, ok: after.filter((x) => x.rowHas).length }, null, 2);
}
