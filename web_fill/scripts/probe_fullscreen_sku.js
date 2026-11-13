
async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  const info = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const label = (el) => (el.innerText||"").replace(/\s+/g," ").trim();
    const fullscreen = [...document.querySelectorAll("button, a, div, span")].filter(visible)
      .filter((el) => label(el) === "全屏" && el.getBoundingClientRect().width < 200);
    const importBtns = [...document.querySelectorAll("button")].filter(visible)
      .filter((el) => label(el) === "批量导入")
      .map((el) => ({ cls: String(el.className||"").slice(0,100), top: Math.round(el.getBoundingClientRect().top), html: el.outerHTML.slice(0,150) }));
    return { fullscreenCount: fullscreen.length, importBtns, bodyHasFull: !!document.querySelector("[class*='fullscreen'], [class*='full-screen']") };
  });
  // 点全屏
  const clicked = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button, a, div, span")].filter(visible)
      .find((el) => (el.innerText||"").replace(/\s+/g," ").trim() === "全屏" && el.getBoundingClientRect().width < 200);
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(2500);
  const after = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const label = (el) => (el.innerText||"").replace(/\s+/g," ").trim();
    const importBtns = [...document.querySelectorAll("button")].filter(visible)
      .filter((el) => /批量导入|导入SKU/.test(label(el)))
      .map((el) => ({ text: label(el), cls: String(el.className||"").slice(0,100) }));
    return { importBtns, bodyTail: (document.body.innerText||"").replace(/\s+/g," ").slice(-160) };
  });
  return JSON.stringify({ info, clicked, after }, null, 1);
}
