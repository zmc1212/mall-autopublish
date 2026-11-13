async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const clickText = (text) => page.evaluate((t) => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button, [role=button], a, span, div")].filter(visible)
      .find((el) => (el.innerText||"").replace(/\s+/g,"").trim() === t && el.children.length <= 3);
    if (!btn) return { found: false };
    btn.scrollIntoView({ block: "center" });
    btn.click();
    return { found: true, tag: btn.tagName, cls: String(btn.className||"").slice(0,80) };
  }, text);
  const dump = async () => await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog], .next-overlay-wrapper")].filter(visible)
      .map((el) => (el.innerText||"").replace(/\s+/g," ").trim().slice(0,700));
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||""))
      .map((tr) => (tr.innerText||"").replace(/\s+/g," ").trim().slice(0,120));
    return { dialogs, tableRows };
  });
  const first = await clickText("上传记录");
  await sleep(2500);
  const after1 = await dump();
  const second = await clickText("确认识别");
  await sleep(3000);
  const after2 = await dump();
  return JSON.stringify({ first, after1, second, after2 }, null, 1);
}
