async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 关闭已有弹窗
  await page.evaluate(() => {
    const btn = [...document.querySelectorAll("button")].find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "取消");
    if (btn) btn.click();
  });
  await sleep(1200);
  // 点击批量导入入口
  const opened = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "批量导入");
    if (!btn) return { found: false };
    btn.scrollIntoView({ block: "center" });
    btn.click();
    return { found: true };
  });
  await sleep(2000);
  const state = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    if (!dlg) return { dialog: false };
    const dl = [...dlg.querySelectorAll("button")].find((b) => (b.innerText||"").includes("点此下载模版"));
    return { dialog: true, downloadBtn: dl ? { disabled: dl.disabled, cls: String(dl.className||"").slice(0,120), html: dl.outerHTML.slice(0,300) } : null };
  });
  // 尝试点击下载
  let saved = null;
  if (state.downloadBtn && !state.downloadBtn.disabled) {
    const [download] = await Promise.all([
      page.waitForEvent("download", { timeout: 15000 }).catch(() => null),
      page.evaluate(() => {
        const dl = [...document.querySelectorAll("button")].find((b) => (b.innerText||"").includes("点此下载模版"));
        if (dl) dl.click();
      }),
    ]);
    if (download) {
      const target = PAYLOAD.saveTo;
      await download.saveAs(target);
      saved = { url: download.url().slice(0, 200), filename: download.suggestedFilename(), savedTo: target };
    }
  }
  return JSON.stringify({ opened, state, saved }, null, 1);
}
