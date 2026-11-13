async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const clickPromise = page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
    if (!btn) return { found: false };
    btn.click();
    return { found: true };
  });
  let respInfo = { captured: false };
  try {
    const resp = await Promise.race([
      page.waitForResponse((r) => (r.url() || "").includes("importSkuTemplate"), { timeout: 25000 }),
      sleep(25000).then(() => null),
    ]);
    if (resp) {
      let body = "";
      try { body = await resp.text(); } catch (e) { body = "BODY_ERR:" + String(e).slice(0, 100); }
      respInfo = { captured: true, status: resp.status(), url: resp.url().slice(0, 140), body: body.slice(0, 1500) };
    } else {
      respInfo = { captured: false, reason: "timeout" };
    }
  } catch (e) {
    respInfo = { captured: false, reason: String(e).slice(0, 120) };
  }
  const clicked = await clickPromise;
  await sleep(4000);
  const after = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)
      .map((el) => (el.innerText||"").replace(/\s+/g," ").trim().slice(0,400));
    const tableRows = [...document.querySelectorAll("table tr")].filter((tr)=>/元|件/.test(tr.innerText||"")).length;
    return { dialogs, tableRows };
  });
  return JSON.stringify({ clicked, respInfo, after }, null, 1);
}
