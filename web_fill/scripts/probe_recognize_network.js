async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const responses = [];
  const listener = (resp) => {
    const url = resp.url() || "";
    if (/import|recogni|sku|excel|upload|template/i.test(url)) {
      responses.push({ url: url.slice(0, 160), status: resp.status() });
    }
  };
  page.on("response", listener);
  const clicked = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
    if (!btn) return { found: false };
    btn.click();
    return { found: true, cls: String(btn.className||"").slice(0,100) };
  });
  await sleep(12000);
  // 抓取最后一个 POST 响应体
  let body = "";
  try {
    const candidate = responses[responses.length - 1];
    if (candidate) { /* body 由监听器难取，改用 page.on 已够看状态 */ }
  } catch (e) {}
  page.off("response", listener);
  const after = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)
      .map((el) => (el.innerText||"").replace(/\s+/g," ").trim().slice(0,400));
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||"")).length;
    return { dialogs, tableRows };
  });
  return JSON.stringify({ clicked, responses: responses.slice(-12), after }, null, 1);
}
