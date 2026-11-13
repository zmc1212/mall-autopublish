async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  return await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible)
      .map((el) => ({
        fullText: (el.innerText||"").replace(/\s+/g," ").trim(),
        html: el.outerHTML.replace(/\s+/g," ").slice(0, 2500),
      }));
    // 全页面找 message/error/toast 类元素
    const msgs = [...document.querySelectorAll("[class*='message'], [class*='error'], [class*='Error'], [class*='toast'], [class*='Toast'], .next-message")].filter(visible)
      .map((el) => ({ cls: String(el.className||"").slice(0,90), text: (el.innerText||"").replace(/\s+/g," ").trim().slice(0,200) }));
    return { dialogs, msgs };
  });
}
