async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await dismissKnow();
  const thickness = PAYLOAD.thickness || "0.05mm";
  const log = [];
  for (let round = 0; round < 24; round++) {
    const opened = await page.evaluate((already) => {
      function classify(tr) {
        const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
        const yuan = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("元"));
        const jian = inputs.find((el) => ((el.closest("td") && el.closest("td").innerText) || "").includes("件"));
        const rest = inputs.filter((el) => el !== yuan && el !== jian);
        return rest[1] || [...tr.querySelectorAll("input")].find((n) => n.placeholder === "请选择" && !/单品|套餐/.test((n.closest("td") && n.closest("td").innerText) || ""));
      }
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const t = tr.innerText || "";
        return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
      });
      for (const tr of rows) {
        const el = classify(tr);
        if (!el) continue;
        const cell = ((el.closest("td") && el.closest("td").innerText) || "") + (tr.innerText || "");
        if ((el.value || "").trim() === already || cell.includes(already) || el.dataset.tried === "1") continue;
        el.dataset.tried = "1";
        el.scrollIntoView({ block: "center" });
        el.click();
        return true;
      }
      return false;
    }, thickness);
    if (!opened) break;
    await sleep(400);
    log.push(await clickOverlayText(thickness));
    await page.keyboard.press("Escape");
    await sleep(180);
  }
  const after = await page.evaluate((want) => [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件") && !(tr.innerText || "").includes("SKU分类")).map((tr) => {
    const el = [...tr.querySelectorAll("input")].find((n) => /mm/i.test(n.value || "") || n.placeholder === "请选择");
    return {
      val: el ? el.value : "",
      rowHas: (tr.innerText || "").includes(want),
    };
  }), thickness);
  return JSON.stringify({ thickness, log, after, ok: after.filter((v) => v.rowHas || v.val === thickness).length }, null, 2);
}
