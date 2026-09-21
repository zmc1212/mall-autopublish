async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await installAttrDom();
  const lab = "IP联名";
  const before = await page.evaluate((label) => {
    const item = window.__qnItem && window.__qnItem(label);
    if (!item) return { found: false };
    const texts = [...item.querySelectorAll("span, div, a, em, button")].map((el) => ({
      t: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40),
      cls: String(el.className || "").slice(0, 80),
      tag: el.tagName,
    })).filter((x) => x.t && x.t.length < 30).slice(0, 40);
    const rec = [...item.querySelectorAll("*")].filter((el) => /推荐/.test(el.innerText || "")).slice(0, 8).map((el) => ({
      t: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80),
      cls: String(el.className || "").slice(0, 100),
    }));
    return {
      found: true,
      itemCls: String(item.className || ""),
      html: item.innerHTML.replace(/\s+/g, " ").slice(0, 2500),
      texts,
      rec,
      comboPh: (window.__qnCombo(label) && window.__qnCombo(label).getAttribute("placeholder")) || "",
    };
  }, lab);
  await page.evaluate((label) => {
    const el = window.__qnCombo && window.__qnCombo(label);
    if (el) {
      const item = window.__qnItem(label);
      if (item) item.scrollIntoView({ block: "center" });
      const wrap = el.closest(".next-select") || el;
      wrap.click();
      el.click();
      if (el.focus) el.focus();
    }
  }, lab);
  await sleep(600);
  const overlay = await page.evaluate((want) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened, .next-overlay-wrapper")].filter((el) => getComputedStyle(el).display !== "none");
    return wraps.slice(-3).map((el) => {
      const inputs = [...el.querySelectorAll("input")].map((inp) => ({
        ph: inp.getAttribute("placeholder") || "",
        type: inp.getAttribute("type") || "",
        role: inp.getAttribute("role") || "",
        val: inp.value || "",
      }));
      const opts = [...el.querySelectorAll("li, .next-menu-item, .options-item, .info-content")].map((n) => (n.innerText || "").replace(/\s+/g, " ").trim()).filter(Boolean).slice(0, 25);
      return {
        cls: String(el.className || "").slice(0, 120),
        len: (el.innerText || "").length,
        hasWant: (el.innerText || "").includes(want),
        text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 300),
        inputs,
        opts,
      };
    });
  }, "火影忍者");
  return JSON.stringify({ before, overlay }, null, 2);
}
