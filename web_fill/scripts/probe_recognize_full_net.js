async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const net = [];
  const onResp = (resp) => {
    const req = resp.request();
    const method = req.method();
    if (method === "POST" || /import|excel|sku/i.test(resp.url())) {
      net.push({ m: method, url: resp.url().slice(0, 150), status: resp.status(), post: (req.postData() || "").slice(0, 160) });
    }
  };
  page.on("response", onResp);
  try {
    const reqPromise = page.waitForRequest((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 25000 });
    const respPromise = page.waitForResponse((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 25000 });
    const clicked = await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")]
        .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
      if (!btn) return false;
      btn.click();
      return true;
    });
    if (!clicked) return JSON.stringify({ clicked: false });
    const req = await reqPromise;
    const resp = await respPromise;
    let post = ""; try { post = req.postData() || ""; } catch (e) {}
    let jsonBody = "";
    try { jsonBody = new URLSearchParams(post).get("jsonBody") || ""; } catch (e) {}
    let body = ""; try { body = await resp.text(); } catch (e) {}
    // 识别后等待观察
    const samples = [];
    for (let i = 0; i < 6; i++) {
      await sleep(3000);
      samples.push(await page.evaluate(() => {
        const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
        const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
        const rows = [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||"")).length;
        return { dlg: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 200) : null, rows };
      }));
    }
    return JSON.stringify({ net: net.slice(-25), jsonBodyLen: jsonBody.length,
      jsonBodyTail: jsonBody.slice(-1800), body: body.slice(0, 300), samples }, null, 1);
  } finally {
    page.off("response", onResp);
  }
}
