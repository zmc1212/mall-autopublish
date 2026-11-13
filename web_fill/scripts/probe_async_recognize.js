async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const dump = async () => await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible)
      .map((el) => {
        const loading = [...el.querySelectorAll("button")].some((b) => String(b.className||"").includes("next-btn-loading"));
        return { text: (el.innerText||"").replace(/\s+/g," ").trim().slice(0,320), loading };
      });
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||""))
      .map((tr) => (tr.innerText||"").replace(/\s+/g," ").trim().slice(0,140));
    return { dialogs, tableRows };
  });
  const samples = [];
  for (let i = 0; i < 10; i++) {
    await sleep(6000);
    samples.push(await dump());
    const j = JSON.stringify(samples[samples.length - 1]);
    if (j.split("单个随机盲盒").length > 2 || j.includes("端盒") || j.includes("已成功识别")) break;
  }
  // 若表格仍未更新且弹窗还在，点取消关闭弹窗再看表格
  const closed = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "取消");
    if (!btn) return false;
    btn.click();
    return true;
  });
  await sleep(2500);
  const afterClose = await dump();
  return JSON.stringify({ samples, closed, afterClose }, null, 1);
}
