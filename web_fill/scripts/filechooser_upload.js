async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const VISIBLE_SRC = `const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };`;
  const net = [];
  const onResp = (resp) => {
    const url = resp.url() || "";
    if (/kfupload|upload|excel|sku|import|oss|file/i.test(url) && !/gm\.mmstat|alicdn|\.js|\.css|\.png/.test(url)) {
      net.push({ url: url.slice(0, 150), status: resp.status() });
    }
  };
  page.on("response", onResp);
  try {
    const opened = await page.evaluate(() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const btn = [...document.querySelectorAll("button")].filter(visible)
        .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "批量导入");
      if (!btn) return { found: false };
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return { found: true, disabled: btn.disabled };
    });
    await sleep(2000);
    const dropInfo = await page.evaluate(() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
      if (!dlg) return { dialog: false };
      const drop = [...dlg.querySelectorAll("div, span, a")].filter(visible)
        .find((el) => (el.innerText||"").includes("点击或者拖动文件到虚线框内上传") && el.getBoundingClientRect().height > 16);
      return { dialog: true, dropFound: !!drop, dropTag: drop ? drop.tagName : null };
    });
    let chooserState = { got: false };
    if (dropInfo.dialog) {
      try {
        const chooserPromise = page.waitForEvent("filechooser", { timeout: 12000 });
        await page.evaluate(() => {
          const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
          const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
          const drop = [...dlg.querySelectorAll("div, span, a, label")].filter(visible)
            .find((el) => (el.innerText||"").includes("点击或者拖动文件到虚线框内上传"));
          (drop || dlg).click();
        });
        const chooser = await chooserPromise;
        await chooser.setFiles(PAYLOAD.file);
        chooserState = { got: true };
      } catch (e) {
        chooserState = { got: false, err: String(e).slice(0, 160) };
      }
    }
    await sleep(5000);
    const afterUpload = await page.evaluate(() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
      return { dialogText: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 400) : null };
    });
    let recognized = {};
    try {
      const reqPromise = page.waitForRequest((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 20000 });
      const respPromise = page.waitForResponse((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 20000 });
      const clicked = await page.evaluate(() => {
        const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
        const btn = [...document.querySelectorAll("button")].filter(visible)
          .find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
        if (!btn) return false;
        btn.click();
        return true;
      });
      if (clicked) {
        const req = await reqPromise;
        let post = ""; try { post = req.postData() || ""; } catch (e) {}
        const resp = await respPromise;
        let body = ""; try { body = await resp.text(); } catch (e) { body = "BODY_ERR"; }
        recognized = { post: post.slice(0, 2600), status: resp.status(), body: body.slice(0, 900) };
      } else {
        recognized = { clicked: false };
      }
    } catch (e) {
      recognized = { err: String(e).slice(0, 160) };
    }
    const samples = [];
    for (let i = 0; i < 6; i++) {
      await sleep(3000);
      samples.push(await page.evaluate(() => {
        const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
        const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
        const rows = [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||"")).length;
        return { dlg: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 220) : null, rows };
      }));
      const j = JSON.stringify(samples[samples.length - 1]);
      if (j.includes("已成功识别") || j.includes("在当前规格后添加")) break;
    }
    return JSON.stringify({ opened, dropInfo, chooserState, afterUpload, recognized, net: net.slice(-24), samples }, null, 1);
  } finally {
    page.off("response", onResp);
  }
}
