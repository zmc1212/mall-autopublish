async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const net = [];
  const onResp = (resp) => {
    const req = resp.request();
    if (req.method() === "POST" && !/gm\.mmstat|alog|alicdn/.test(resp.url())) {
      net.push({ url: resp.url().slice(0, 140), status: resp.status(), post: (req.postData() || "").slice(0, 120) });
    }
  };
  page.on("response", onResp);
  try {
    // 打开弹窗
    await page.evaluate(() => {
      const btn = [...document.querySelectorAll("button")]
        .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "批量导入");
      if (btn) btn.click();
    });
    await sleep(1800);
    const dump = await page.evaluate(() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
      if (!dlg) return { dialog: false };
      const drop = [...dlg.querySelectorAll("div, span, a, label")].filter(visible)
        .find((el) => (el.innerText||"").includes("点击或者拖动文件到虚线框内上传") && el.getBoundingClientRect().height > 16);
      const inputs = [...dlg.querySelectorAll("input[type=file]")].map((el) => ({
        accept: el.accept, id: el.id, cls: String(el.className||"").slice(0,80),
        parentCls: String(el.parentElement?.className||"").slice(0,100),
        outer: el.outerHTML.slice(0, 220),
      }));
      return {
        dialog: true,
        dropOuter: drop ? drop.outerHTML.replace(/\s+/g," ").slice(0, 500) : null,
        dropParentCls: drop ? String(drop.parentElement?.className||"").slice(0,140) : null,
        inputs,
      };
    });
    // 尝试 JS click 隐藏 input 触发 filechooser
    let chooser = { attempted: false };
    if (dump.inputs && dump.inputs.length) {
      chooser = { attempted: true };
      try {
        const p = page.waitForEvent("filechooser", { timeout: 6000 });
        await page.evaluate(() => {
          const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0; };
          const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0] || document;
          const input = dlg.querySelector("input[type=file]");
          if (input) input.click();
        });
        const fc = await p;
        await fc.setFiles(PAYLOAD.file);
        chooser = { attempted: true, got: true };
      } catch (e) {
        chooser = { attempted: true, got: false, err: String(e).slice(0, 140) };
      }
    }
    await sleep(6000);
    const after = await page.evaluate(() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
      return { dlgText: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 380) : null };
    });
    // 点确认识别并抓完整请求体
    let recognized = {};
    try {
      const reqPromise = page.waitForRequest((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 20000 });
      const respPromise = page.waitForResponse((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 20000 });
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll("button")]
          .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
        if (btn) btn.click();
      });
      const req = await reqPromise;
      const resp = await respPromise;
      let post = ""; try { post = req.postData() || ""; } catch (e) {}
      // 解码 jsonBody
      let decoded = "";
      try {
        const params = new URLSearchParams(post);
        decoded = (params.get("jsonBody") || "").slice(0, 3000);
      } catch (e) { decoded = "DECODE_ERR:" + String(e).slice(0, 80); }
      let body = ""; try { body = await resp.text(); } catch (e) {}
      recognized = { status: resp.status(), body: body.slice(0, 300), jsonBodyHead: decoded.slice(0, 2600) };
    } catch (e) {
      recognized = { err: String(e).slice(0, 140) };
    }
    return JSON.stringify({ dump, chooser, after, recognized, net: net.slice(-20) }, null, 1);
  } finally {
    page.off("response", onResp);
  }
}
