async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  const before = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const label = (el) => (el.innerText || "").replace(/\s+/g, "").trim();
    const candidates = [...document.querySelectorAll("button, a, [role=button], span, div")]
      .filter(visible).filter((el) => /^(批量导入|导入SKU|导入规格|Excel导入)$/.test(label(el)));
    return candidates.map((el) => ({ tag: el.tagName, cls: String(el.className||"").slice(0,120), html: el.outerHTML.slice(0,300) }));
  });
  const clicked = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const label = (el) => (el.innerText || "").replace(/\s+/g, "").trim();
    const heading = [...document.querySelectorAll("h1, h2, h3, span, div")]
      .find((el) => visible(el) && label(el) === "销售信息");
    const cands = [...document.querySelectorAll("button, a, [role=button], span, div")]
      .filter(visible).filter((el) => /^(批量导入|导入SKU|导入规格|Excel导入)$/.test(label(el)));
    cands.sort((a, b) => {
      const score = (el) => {
        const tag = el.tagName.toLowerCase();
        const semantic = /^(button|a)$/.test(tag) || el.getAttribute("role") === "button" ? 0 : 1;
        const distance = heading ? Math.abs(el.getBoundingClientRect().top - heading.getBoundingClientRect().top) : 0;
        return distance + semantic * 8;
      };
      return score(a) - score(b);
    });
    if (!cands.length) return { found: false };
    const t = cands[0];
    t.scrollIntoView({ block: "center" });
    t.click();
    return { found: true, tag: t.tagName, cls: String(t.className||"").slice(0,100) };
  });
  await sleep(2200);
  const after = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const overlays = [...document.querySelectorAll(
      ".next-dialog, [role=dialog], .next-overlay-wrapper, .next-overlay-backdrop, " +
      "[class*='Dialog'], [class*='dialog'], [class*='modal'], [class*='Modal'], [class*='popup'], [class*='Popup'], [class*='drawer'], [class*='Drawer']"
    )].filter(visible).map((el) => ({ cls: String(el.className||"").slice(0,120), text: (el.innerText||"").replace(/\s+/g," ").trim().slice(0,300) }));
    const fileInputs = [...document.querySelectorAll("input[type=file]")].map((el) => ({accept: String(el.accept||""), visible: visible(el)}));
    const btns = [...document.querySelectorAll("button")].filter(visible).map((el) => (el.innerText||"").replace(/\s+/g," ").trim()).filter(Boolean).slice(0,40);
    return { overlays, fileInputs, btns, bodyTail: (document.body.innerText||"").replace(/\s+/g," ").slice(-260) };
  });
  return JSON.stringify({ before, clicked, after }, null, 1);
}
