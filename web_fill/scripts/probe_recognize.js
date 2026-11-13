async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const dump = async () => await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible);
    return dialogs.map((el) => ({
      text: (el.innerText||"").replace(/\s+/g," ").trim().slice(0,420),
      buttons: [...el.querySelectorAll("button")].filter(visible).map((b) => ({
        text: (b.innerText||"").replace(/\s+/g," ").trim().slice(0,20),
        disabled: b.disabled,
        cls: String(b.className||"").slice(0,80),
      })),
    }));
  });
  const before = await dump();
  // 用真实 button 元素点击"确认识别"
  const clickState = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll(".next-dialog button, [role=dialog] button, .next-overlay-wrapper button")]
      .filter(visible).find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
    if (!btn) return { found: false };
    btn.scrollIntoView({ block: "center" });
    btn.click();
    return { found: true, disabled: btn.disabled };
  });
  const samples = [];
  for (let i = 0; i < 16; i++) {
    await sleep(3000);
    const d = await dump();
    samples.push(JSON.stringify(d).slice(0, 380));
    const joined = JSON.stringify(d);
    if (joined.includes("已成功识别") || joined.includes("在当前规格后添加")) break;
  }
  return JSON.stringify({ before, clickState, samples }, null, 1);
}
