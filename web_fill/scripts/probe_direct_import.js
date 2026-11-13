async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 直接协议导入:把模板规格值注入 jsonBody 并 POST importSkuTemplate。
  // 协议(抓包确认):POST jsonBody={saleProp:{p-1627207:[{text,value}]},sku:[当前行...]}
  const result = await page.evaluate(async (payload) => {
    const specKey = payload.specKey || "p-1627207";
    const names = payload.names || [];
    // 先在页面里找一个现有自定义值的 value 形态,新建值用递减负数
    const existing = (payload.existingValues || []).slice();
    const used = new Set(existing.map((v) => Number(v)));
    let next = -46000000;
    while (used.has(next)) next -= 1;
    const values = [];
    for (const name of names) {
      const hit = (payload.knownPairs || []).find((p) => p.text === name);
      values.push(hit ? { text: name, value: hit.value } : { text: name, value: next });
    }
    // 重新分配:每个未知名递减
    let cursor = next - 1;
    for (const v of values) {
      if (v.value === next) { v.value = next; }
    }
    const body = {
      saleProp: { [specKey]: values },
      sku: payload.skuRows || [],
    };
    const post = "jsonBody=" + encodeURIComponent(JSON.stringify(body));
    try {
      const resp = await fetch("/excel/sku/importSkuTemplate?templateType=excel&catId=" + payload.catId, {
        method: "POST",
        credentials: "include",
        headers: { "content-type": "application/x-www-form-urlencoded" },
        body: post,
      });
      const text = await resp.text();
      return { status: resp.status, body: text.slice(0, 500), sentValues: values };
    } catch (e) {
      return { err: String(e).slice(0, 200) };
    }
  }, PAYLOAD);
  await sleep(4000);
  const rows = await page.evaluate(() => ({
    rows: [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||""))
      .map((tr) => (tr.innerText||"").replace(/\s+/g," ").trim().slice(0, 110)).slice(0, 8),
    dlg: (() => {
      const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
      const dlg = [...document.querySelectorAll(".next-dialog, [role=dialog]")].filter(visible)[0];
      return dlg ? (dlg.innerText||"").replace(/\s+/g," ").slice(0, 200) : null;
    })(),
  }));
  return JSON.stringify({ result, rows }, null, 1);
}
