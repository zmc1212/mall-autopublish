async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 给表格每个规格行填价格(元列)/库存(件列)——与 skus.js 表格补值逻辑一致
  const filled = await page.evaluate(({ price, stock }) => {
    const out = [];
    const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
      const t = tr.innerText || "";
      return t.includes("元") && t.includes("件") && !t.includes("SKU分类");
    });
    for (const tr of rows) {
      const inputs = [...tr.querySelectorAll("input")].filter((el) => !el.disabled && el.type !== "checkbox" && el.type !== "radio");
      for (const el of inputs) {
        const cell = (el.closest("td") && el.closest("td").innerText) || "";
        if (/元/.test(cell) && !el.value) { el.focus(); el.value = String(price); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); el.blur(); out.push({ cell: cell.slice(0, 12), as: "price" }); }
        else if (/件/.test(cell) && !el.value) { el.focus(); el.value = String(stock); el.dispatchEvent(new Event("input", { bubbles: true })); el.dispatchEvent(new Event("change", { bubbles: true })); el.blur(); out.push({ cell: cell.slice(0, 12), as: "qty" }); }
      }
    }
    return out;
  }, { price: PAYLOAD.price || 9.9, stock: PAYLOAD.stock || 20 });
  await sleep(600);
  const tableRows = await page.evaluate(() => [...document.querySelectorAll("table tr")]
    .filter((tr) => /元|件/.test(tr.innerText || ""))
    .map((tr) => [...tr.querySelectorAll("input")].map((el) => el.value).join("|")));
  // 检查页面通知是否消失
  const notice = await page.evaluate(() => {
    const el = [...document.querySelectorAll(".next-message-content")].filter((e) => e.getBoundingClientRect().width > 0)
      .map((e) => (e.innerText || "").trim()).find((t) => t.includes("价格"));
    return el || "";
  });
  return JSON.stringify({ filled, tableRows, notice }, null, 1);
}
