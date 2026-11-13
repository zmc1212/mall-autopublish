
async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  const headers = await page.evaluate(() => {
    // 触发一次前端自己的确认识别,由 Playwright 侧抓 headers —— 改为在这里读不到;返回提示
    return null;
  });
  // 点确认识别让前端发请求
  const [req] = await Promise.all([
    (async () => {
      const wait = page.waitForRequest((r) => (r.url()||"").includes("importSkuTemplate"), { timeout: 20000 });
      await page.evaluate(() => {
        const btn = [...document.querySelectorAll("button")].find((b) => (b.innerText||"").replace(/\s+/g,"").trim() === "确认识别");
        if (btn) btn.click();
      });
      return wait;
    })(),
  ]);
  const h = req.headers();
  return JSON.stringify({ url: req.url(), headers: h, post: (req.postData()||"").slice(0, 200) }, null, 1);
}
