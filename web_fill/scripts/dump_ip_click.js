async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await installAttrDom();
  const lab = "IP联名";
  const want = "火影忍者";
  const recClick = await page.evaluate(([label, val]) => {
    const item = window.__qnItem && window.__qnItem(label);
    if (!item) return "NO_ITEM";
    const rec = item.querySelector(".sell-component-item-prop-item-recommend, .recommend-text");
    if (!rec) return "NO_REC";
    rec.scrollIntoView({ block: "center" });
    rec.click();
    return "CLICK:" + (rec.innerText || "").replace(/\s+/g, " ").trim();
  }, [lab, want]);
  await sleep(500);
  const afterRec = await page.evaluate(([label, val]) => ({
    committed: !!(window.__qnCommitted && window.__qnCommitted(label, val)),
    attr: window.__qnAttr && window.__qnAttr(label),
    overlay: [...document.querySelectorAll(".next-overlay-wrapper.opened")].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 200)),
  }), [lab, want]);
  if (!afterRec.committed) {
    await page.evaluate((label) => {
      const el = window.__qnCombo && window.__qnCombo(label);
      const wrap = el && (el.closest(".next-select") || el);
      if (wrap) wrap.click();
    }, lab);
    await sleep(700);
  }
  const overlay = await page.evaluate((wantVal) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened")].filter((el) => getComputedStyle(el).display !== "none");
    return wraps.map((el) => ({
      cls: String(el.className || "").slice(0, 120),
      len: (el.innerText || "").length,
      hasWant: (el.innerText || "").includes(wantVal),
      text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 400),
      inputs: [...el.querySelectorAll("input")].map((inp) => ({
        ph: inp.getAttribute("placeholder") || "",
        readonly: inp.hasAttribute("readonly"),
        role: inp.getAttribute("role") || "",
      })),
      opts: [...el.querySelectorAll("li, .next-menu-item, .options-item")].map((n) => (n.innerText || "").replace(/\s+/g, " ").trim()).filter(Boolean).slice(0, 30),
    }));
  }, want);
  return JSON.stringify({ recClick, afterRec, overlay }, null, 2);
}
