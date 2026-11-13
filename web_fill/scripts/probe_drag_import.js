async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 拖拽注入:构造 DataTransfer + drop 事件,把文件字节直接交给虚线框。
  const result = await page.evaluate(async (payload) => {
    const bin = atob(payload.b64);
    const bytes = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
    const file = new File([bytes], payload.fileName, { type: "application/vnd.ms-excel" });
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    if (!dlg) return { dialog: false };
    const drop = [...dlg.querySelectorAll("div, span, a, label")].filter(visible)
      .find((el) => (el.innerText||"").includes("点击或者拖动文件到虚线框内上传"));
    const target = drop || dlg;
    const dt = new DataTransfer();
    dt.items.add(file);
    const events = [];
    for (const type of ["dragenter", "dragover", "drop"]) {
      const ev = new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt });
      target.dispatchEvent(ev);
      events.push(type + ":" + ev.defaultPrevented);
    }
    return { dialog: true, dropFound: !!drop, dispatched: events, fileSize: file.size };
  }, { b64: PAYLOAD.b64, fileName: PAYLOAD.fileName });
  await sleep(6000);
  const after = await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
    return { dlg: dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 420) : null };
  });
  return JSON.stringify({ result, after }, null, 1);
}
