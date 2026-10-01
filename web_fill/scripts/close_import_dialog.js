async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  // 批量导入弹窗可能停留在上传/识别/结果任一状态，优先取消，其次右上角关闭。
  for (let round = 0; round < 6; round++) {
    const closed = await page.evaluate(() => {
      const roots = [...document.querySelectorAll(".next-overlay-wrapper, .next-dialog, [role=dialog]")]
        .filter((el) => el.offsetWidth || el.offsetHeight);
      let acted = null;
      for (const root of roots) {
        const text = (root.innerText || "").replace(/\s+/g, " ");
        if (!/批量导入|识别结果|导入结果|已成功识别|确认识别/.test(text)) continue;
        const cancel = [...root.querySelectorAll("button")]
          .find((el) => /^(取消|关闭)$/.test((el.innerText || "").trim()));
        if (cancel) { cancel.click(); acted = "cancel"; return acted; }
        const close = root.querySelector(".next-dialog-close, [aria-label='关闭'], .next-icon-close");
        if (close) { close.click(); acted = "close-x"; return acted; }
      }
      return acted;
    });
    if (!closed) break;
    await sleep(600);
  }
  const remaining = await page.evaluate(() => [...document.querySelectorAll(".next-overlay-wrapper, .next-dialog, [role=dialog]")]
    .filter((el) => (el.offsetWidth || el.offsetHeight)
      && /批量导入|识别结果|导入结果|已成功识别/.test(el.innerText || "")).length);
  if (remaining) {
    await page.keyboard.press("Escape").catch(() => {});
    await sleep(500);
  }
  return JSON.stringify({ ok: true, remaining });
}
