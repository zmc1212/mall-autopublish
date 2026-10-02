async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 关闭“选择视频”对话框（.wdeDialog）。不能按 Escape：上传弹层异步脱离会
  // 留下假 frame（见 main_video.js 注释）。视频对话框开着时，videoSelector
  // iframe 会劫持图片空间定位（wangpuFrame 同域匹配），详情图会被当成视频投递。
  // 关闭失败绝不能静默：残留对话框会把后续详情图吸进视频上传框，形成
  // “重试→再传视频→再残留”的死循环（2026-10-01 真实页面复现）。
  const videoFrameGone = () => !page.frames().some((f) => /videoSelector/i.test(f.url() || ""));
  if (videoFrameGone()) return JSON.stringify({ open: false, clicked: false, frameGone: true });
  const clicked = await page.evaluate(() => {
    const dlg = document.querySelector(".wdeDialog");
    if (!dlg) return "NO_DIALOG";
    const close = dlg.querySelector(".next-dialog-close")
      || [...dlg.querySelectorAll("[class*='close'], [aria-label*='关闭'], [aria-label*='Close']")]
        .find((el) => el.getBoundingClientRect().width > 4);
    if (close) { close.click(); return "close-icon"; }
    // 兜底：对话框右上角的 X 图标按钮（不同版本类名不同），取对话框头部
    // 最后一个可见的小按钮。
    const head = [...dlg.querySelectorAll("button, [role='button']")]
      .filter((el) => el.getBoundingClientRect().width > 4);
    const xBtn = head.find((el) => {
      const t = (el.innerText || "").trim();
      return !t && /×|✕|x/i.test(el.textContent || "");
    });
    if (xBtn) { xBtn.click(); return "x-icon"; }
    return "NO_BTN";
  }).catch(() => "EVAL_FAIL");
  for (let i = 0; i < 5 && !videoFrameGone(); i++) await sleep(600);
  const frameGone = videoFrameGone();
  return JSON.stringify({ open: !frameGone, clicked, frameGone });
}
