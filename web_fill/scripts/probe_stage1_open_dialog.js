async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 阶段1:注入网络钩子 → 打开弹窗 → 点击虚线框(原生对话框将由 CLI 代投)
  await page.evaluate(() => {
    if (window.__captured) return;
    window.__captured = [];
    const origFetch = window.fetch;
    window.fetch = function (input, init) {
      try {
        const url = typeof input === "string" ? input : (input && input.url) || "";
        const method = (init && init.method) || (input && input.method) || "GET";
        const body = init && init.body ? String(init.body).slice(0, 500) : "";
        window.__captured.push({ kind: "fetch", m: method, url: String(url).slice(0, 160), body });
      } catch (e) {}
      return origFetch.apply(this, arguments);
    };
    const OrigOpen = XMLHttpRequest.prototype.open;
    const OrigSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function (m, u) {
      this.__m = m; this.__u = u;
      return OrigOpen.apply(this, arguments);
    };
    XMLHttpRequest.prototype.send = function (body) {
      try {
        window.__captured.push({ kind: "xhr", m: this.__m, url: String(this.__u || "").slice(0, 160), body: body ? String(body).slice(0, 500) : "" });
      } catch (e) {}
      return OrigSend.apply(this, arguments);
    };
  });
  const opened = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const btn = [...document.querySelectorAll("button")].filter(visible)
      .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "批量导入");
    if (!btn) return { found: false };
    btn.scrollIntoView({ block: "center" });
    btn.click();
    return { found: true };
  });
  await sleep(1800);
  await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    if (!dlg) return;
    const drop = [...dlg.querySelectorAll("div, span, a, label")].filter(visible)
      .find((el) => (el.innerText||"").includes("点击或者拖动文件到虚线框内上传"));
    (drop || dlg).click();
  });
  return JSON.stringify({ opened, hookInstalled: true });
}
