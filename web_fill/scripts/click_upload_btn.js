async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const pageClick = await page.evaluate(() => {
    const dlg = document.querySelector(".batch-fill-sku-image-dialog") || document.querySelector(".next-overlay-wrapper.opened") || document;
    const candidates = [...dlg.querySelectorAll("button, a, div, span")].filter((el) => {
      const t = (el.innerText || "").replace(/\s+/g, "");
      return t.includes("批量导入") || t.includes("点击/拖拽") || t.includes("本地上传") || t === "上传图片" || t === "上传文件" || (t.includes("上传文件") && t.length < 40);
    });
    candidates.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const btn = candidates[0];
    if (!btn) return "NO";
    btn.click();
    return "OK";
  });
  if (pageClick === "OK") {
    await sleep(400);
    return JSON.stringify({ clicked: pageClick, via: "page" });
  }
  const frame = sucaiFrame() || wangpuFrame();
  if (!frame) return JSON.stringify({ error: "NO_FRAME" });
  const clicked = await frame.evaluate(() => {
    const btn = document.querySelector("#sucai-tu-upload")
      || [...document.querySelectorAll("button, a, div, span")].find((el) => {
        const t = (el.innerText || "").trim();
        return t === "上传图片" || t === "上传文件" || t.includes("本地上传");
      })
      || [...document.querySelectorAll("button.next-btn-primary")].find((el) => (el.innerText || "").includes("本地上传"));
    if (!btn) return "NO";
    btn.click();
    return "OK";
  });
  await sleep(400);
  return JSON.stringify({ clicked });
}
