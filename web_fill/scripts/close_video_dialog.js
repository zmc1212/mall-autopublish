async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  // 关闭“选择视频”对话框（.wdeDialog）。不能按 Escape：上传弹层异步脱离会
  // 留下假 frame（见 main_video.js 注释）。视频对话框开着时，videoSelector
  // iframe 会劫持图片空间定位（wangpuFrame 同域匹配），详情图会被当成视频投递。
  const videoFrameGone = () => !page.frames().some((f) => /videoSelector/i.test(f.url() || ""));
  if (videoFrameGone()) return JSON.stringify({ open: false, clicked: false, frameGone: true });
  const clicked = await page.evaluate(() => {
    const close = document.querySelector(".wdeDialog .next-dialog-close");
    if (!close) return false;
    close.click();
    return true;
  });
  for (let i = 0; i < 5 && !videoFrameGone(); i++) await sleep(600);
  return JSON.stringify({ open: true, clicked, frameGone: videoFrameGone() });
}
