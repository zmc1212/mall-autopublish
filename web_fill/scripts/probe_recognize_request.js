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
  let captured = { got: false };
  try {
    const winner = await Promise.race([
      page.waitForRequest((r) => (r.url() || "").includes("importSkuTemplate"), { timeout: 20000 }).then((req) => ({ kind: "req", req })),
      sleep(20000).then(() => ({ kind: "timeout" })),
    ]);
    if (winner.kind === "req") {
      const req = winner.req;
      let post = "";
      try { post = req.postData() || ""; } catch (e) {}
      captured = { got: true, url: req.url().slice(0, 180), method: req.method(), headers: Object.fromEntries(Object.entries(req.headers()).filter(([k]) => /content-type|file|name/i.test(k))), post: post.slice(0, 900) };
    } else {
      captured = { got: false, reason: "timeout" };
    }
  } catch (e) {
    captured = { got: false, reason: String(e).slice(0, 150) };
  }
  await clickPromise;
  return JSON.stringify(captured, null, 1);
}
