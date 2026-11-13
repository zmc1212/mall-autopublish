async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const result = await page.evaluate((payload) => {
    const specKey = payload.specKey || "p-1627207";
    const values = (payload.names || []).map((name, i) => ({ text: name, value: -(46000001 + i) }));
    const body = { saleProp: { [specKey]: values }, sku: payload.skuRows || [] };
    const post = "jsonBody=" + encodeURIComponent(JSON.stringify(body));
    return new Promise((resolve) => {
      try {
        const m = document.cookie.match(/XSRF-TOKEN\s*=\s*([^;]+)/i);
        const token = payload.xsrfToken || (m && m[1]) || "";
        const xhr = new XMLHttpRequest();
        xhr.open("POST", "/excel/sku/importSkuTemplate?templateType=excel&catId=" + payload.catId, true);
        xhr.setRequestHeader("content-type", "application/x-www-form-urlencoded");
        if (token) xhr.setRequestHeader("x-xsrf-token", decodeURIComponent(token));
        xhr.setRequestHeader("x-requested-with", "XMLHttpRequest");
        xhr.onreadystatechange = () => {
          if (xhr.readyState === 4) {
            resolve({ status: xhr.status, body: String(xhr.responseText || "").slice(0, 500), tokenUsed: token.slice(0, 12) });
          }
        };
        xhr.onerror = () => resolve({ err: "XHR_ERROR", status: xhr.status });
        xhr.send(post);
      } catch (e) {
        resolve({ err: String(e).slice(0, 200) });
      }
    });
  }, PAYLOAD);
  await sleep(4000);
  const rows = await page.evaluate(() => ({
    rows: [...document.querySelectorAll("table tr")].filter((tr) => /元|件/.test(tr.innerText||""))
      .map((tr) => (tr.innerText||"").replace(/\s+/g," ").trim().slice(0, 110)).slice(0, 8),
  }));
  return JSON.stringify({ result, rows }, null, 1);
}
