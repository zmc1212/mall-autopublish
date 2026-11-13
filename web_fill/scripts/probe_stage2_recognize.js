async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 阶段2:读取钩子记录(文件上传?)→ 弹窗状态 → 点确认识别 → 再读钩子
  const capturedBefore = await page.evaluate(() => (window.__captured || []).slice(-12));
  await sleep(4000);
  const capturedAfterUpload = await page.evaluate(() => (window.__captured || []).slice(-12));
  const dlgText = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    return dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 380) : null;
  });
  // 清空记录,只抓确认识别的请求
  await page.evaluate(() => { window.__captured.length = 0; });
  let lastBody = "";
  await page.evaluate(() => {
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
      const url = typeof input === "string" ? input : (input && input.url) || "";
      if (/importSkuTemplate/.test(url) && init && init.body) lastBody = String(init.body);
      return origFetch.apply(this, arguments);
    };
  });
  const clicked = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(9000);
  const capturedRecognize = await page.evaluate(() => (window.__captured || []).slice(-6));
  const dlgAfter = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    const rows = [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||"")).length;
    return { dlg: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 260) : null, rows };
  });
  return JSON.stringify({ capturedBefore, capturedAfterUpload, dlgText, clicked, capturedRecognize, dlgAfter }, null, 1);
}
