async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  const stem = String(names[0] || "").replace(/\.[^.]+$/, "");
  // 与主图选择器一致：上传弹层在回执后异步脱离，Escape 会留下假 frame。
  await dismissKnow({ escape: false });

  // 实测页面结构（2026-09-30 真实发布页核验）：
  // - 商品视频字段 #sell-field-auctionVideos；空框 .sell-component-single-video.emptyVideo，
  //   点整个空框打开“选择视频”对话框（点内层文字 span 反而会弹原生文件选择器）。
  // - 对话框内嵌 iframe sucai.wangpu.taobao.com/videoSelector.htm（sucaiFrame 正则
  //   匹配不到，必须单独找）。
  // - iframe 内：上传子面板（上传至/上传列表/上传文件 input）→ 条目“生成封面图中/
  //   上传中”→“封面图生成完成”→“发布成功/已上传”；点“完成”关子面板。
  // - 可选视频列表 VideoList--list 由服务端索引后才出现（实测新发布视频延迟数分钟），
  //   勾选后“确认上传 (N)”把视频绑定回发布页。
  function videoSelectorFrame() {
    return page.frames().find((f) => /videoSelector/i.test(f.url() || ""));
  }

  async function videoSection(mode) {
    return page.evaluate((action) => {
      let root = document.querySelector('[id^="sell-field-"][id*="ideo"]');
      if (!root) {
        const heading = [...document.querySelectorAll("*")].find((el) => (el.childNodes.length <= 5)
          && (el.textContent || "").trim() === "商品视频");
        let node = heading && heading.parentElement;
        for (let i = 0; i < 8 && node; i++) {
          if ([...node.querySelectorAll("button, div, span, a")].some((el) => (el.innerText || "").trim() === "上传视频")) {
            root = node;
            break;
          }
          node = node.parentElement;
        }
      }
      if (!root) return { found: false, videos: 0 };
      let videos = root.querySelectorAll("video").length;
      if (!videos) {
        // 没有 <video> 元素时统计“上传视频”空框以外的缩略图；空框本身
        // 可能是 img 占位，必须排除，避免把上传入口当成已上传视频。
        const boxRoots = [...root.querySelectorAll("div, span, button")]
          .filter((el) => (el.innerText || "").trim() === "上传视频");
        videos = [...root.querySelectorAll("img")].filter((el) => el.width > 40
          && !boxRoots.some((box) => box.contains(el))).length;
      }
      if (action === "click") {
        const box = root.querySelector(".sell-component-single-video.emptyVideo, .emptyVideo .placeholder");
        if (!box) return { found: true, videos, clicked: false };
        box.scrollIntoView({ block: "center" });
        box.click();
        return { found: true, videos, clicked: "empty-box" };
      }
      return { found: true, videos };
    }, mode || "probe");
  }

  // 视频绑定回发布页是最后一步；5 秒一轮轮询视频区。
  async function waitVideoUploaded(polls) {
    let state = { found: false, videos: 0 };
    for (let i = 0; i < (polls || 12); i++) {
      state = await videoSection("probe");
      if (state.videos > 0) return state;
      await sleep(5000);
    }
    return videoSection("probe");
  }

  async function readSelectorState() {
    const frame = videoSelectorFrame();
    if (!frame) return { noFrame: true };
    return await frame.evaluate((want) => {
      const text = (document.body.innerText || "");
      const lists = [...document.querySelectorAll('[class*=VideoList--list]')]
        .filter((el) => !/listView/.test(el.className));
      const list = lists[0];
      const items = list ? list.children.length : 0;
      const itemTexts = list ? [...list.children].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80)) : [];
      return {
        hasUploadItem: text.includes(want),
        processing: /生成封面图中|转码中|上传中/.test(text) && !/已上传/.test(text),
        published: /发布成功|已上传/.test(text),
        failed: /上传失败/.test(text),
        items,
        itemTexts,
        confirmCount: Number((text.match(/确认上传\s*\(\s*(\d+)\s*\)/) || [])[1] || 0),
        snippet: text.replace(/\s+/g, " ").slice(0, 260),
      };
    }, names[0]);
  }

  async function refreshLibraryTab() {
    const frame = videoSelectorFrame();
    if (!frame) return;
    await frame.evaluate(() => {
      const tabs = [...document.querySelectorAll("*")].filter((e) => (e.children.length === 0)
        && (e.innerText || "").trim() === "全部" && e.getBoundingClientRect().width < 120
        && e.getBoundingClientRect().height < 50);
      if (tabs.length) tabs[tabs.length - 1].click();
    });
  }

  if (phase === "verify") {
    // CLI 代投文件后的复核：只看视频区是否实际写入。
    const slot = await waitVideoUploaded(10);
    return JSON.stringify({
      uploaded: slot.videos > 0,
      verifiedBy: slot.videos > 0 ? "slot" : "",
      slot,
      names,
    }, null, 2);
  }

  const state = await videoSection("probe");
  if (state.videos > 0) return JSON.stringify({ already: true, videos: state.videos });
  if (!state.found) return JSON.stringify({ error: "未找到商品视频区", videos: 0 });

  let clicked = null;
  let frame = videoSelectorFrame();
  if (!frame) {
    clicked = await videoSection("click");
    await sleep(2000);
    frame = await waitFrame(videoSelectorFrame, 24);
  }
  if (!frame) {
    return JSON.stringify({ clicked: clicked && clicked.clicked, error: "选择视频对话框未打开" });
  }

  let sel = await readSelectorState();
  // 断点续接：上次可能已把视频传到平台但尚未出现在可选列表。列表已有内容
  // 时不重复投递，避免同一视频传两份。
  if (!sel.hasUploadItem && !sel.items) {
    for (let i = 0; i < 3; i++) {
      await refreshLibraryTab();
      await sleep(8000);
      sel = await readSelectorState();
      if (sel.hasUploadItem || sel.items) break;
    }
  }
  if (!sel.hasUploadItem && !sel.items) {
    const setFiles = await setFilesAnywhere(files);
    if (setFiles !== "OK") {
      return JSON.stringify({ clicked: clicked && clicked.clicked, need_cli_upload: true, error: "未找到上传入口", setFiles });
    }
    await sleep(2500);
    sel = await readSelectorState();
  }

  // 等平台处理（生成封面/转码）完成。真实视频实测数秒完成；伪视频会永远
  // 卡在“生成封面图中”，112 秒足以区分。
  for (let i = 0; i < 14 && sel.processing; i++) {
    await sleep(8000);
    sel = await readSelectorState();
    if (sel.failed) return JSON.stringify({ error: "视频上传失败", detail: sel.snippet });
  }
  if (sel.processing) return JSON.stringify({ error: "视频处理超时", detail: sel.snippet });

  // 关闭上传子面板（若开着），等视频进入可选列表；索引有平台侧延迟（实测
  // 可超过 25 分钟），等待后仍未入列则暂停，点继续自动接续且不会重复上传。
  await frame.evaluate(() => {
    const btn = [...document.querySelectorAll("button")].find((b) => (b.innerText || "").trim() === "完成");
    if (btn) btn.click();
  });
  await sleep(1500);
  for (let i = 0; i < 12 && !sel.items; i++) {
    await refreshLibraryTab();
    await sleep(15000);
    sel = await readSelectorState();
  }
  if (!sel.items) {
    return JSON.stringify({
      error: "视频已发布但选择列表未就绪",
      detail: "平台索引有延迟，稍后点继续会自动接续勾选，不会重复上传",
      detailState: sel,
    });
  }

  // 勾选：优先按文件名匹配条目；仅一条时直接选。点条目计数不变再点其 checkbox。
  const pick = await frame.evaluate((want) => {
    const lists = [...document.querySelectorAll('[class*=VideoList--list]')].filter((el) => !/listView/.test(el.className));
    const list = lists[0];
    if (!list || !list.children.length) return "NO_ITEM";
    const named = [...list.children].filter((el) => (el.innerText || "").includes(want));
    if (named.length > 1) return "AMBIGUOUS";
    const item = named[0] || (list.children.length === 1 ? list.children[0] : null);
    if (!item) return "NOT_MATCHED";
    item.click();
    return "clicked-item";
  }, stem);
  await sleep(1500);
  let count = (await readSelectorState()).confirmCount;
  if (!count) {
    await frame.evaluate(() => {
      const lists = [...document.querySelectorAll('[class*=VideoList--list]')].filter((el) => !/listView/.test(el.className));
      const item = lists[0] && lists[0].children[0];
      const input = item && item.querySelector("input[type=checkbox]");
      if (input) input.click();
    });
    await sleep(1500);
    count = (await readSelectorState()).confirmCount;
  }
  if (!count) {
    return JSON.stringify({ error: "未能勾选视频", pick, detailState: sel });
  }

  const confirmed = await frame.evaluate(() => {
    const btn = [...document.querySelectorAll("button")]
      .filter((b) => /确认上传/.test((b.innerText || "").replace(/\s+/g, "")))
      .find((b) => b.getBoundingClientRect().width > 4);
    if (!btn) return "NO_BTN";
    btn.click();
    return "ok";
  });
  // 成功以视频区实际写入为准：只有回执不算上传完成。
  const slot = await waitVideoUploaded(12);
  return JSON.stringify({
    clicked: clicked && clicked.clicked,
    pick,
    confirmed,
    countBefore: count,
    slot,
    uploaded: slot.videos > 0,
    verifiedBy: slot.videos > 0 ? "slot" : "",
    names,
  }, null, 2);
}
