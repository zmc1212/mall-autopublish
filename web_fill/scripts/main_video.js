async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  const stem = String(names[0] || "").replace(/\.[^.]+$/, "");
  // trace：关键决策点的状态快照，随返回值交 Python 落 logs/web_fill.log。
  // 勾选绑错视频曾无痕迹可查（2026-10-01），列表里有什么、勾了什么必须留档。
  const trace = [];
  const clip = (t) => String(t || "").slice(0, 60);
  const note = (event) => { trace.push(event); };
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
      const itemTextsFull = list ? [...list.children].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()) : [];
      const itemTexts = itemTextsFull.map((t) => t.slice(0, 80));
      return {
        hasUploadItem: text.includes(want),
        // 可选列表里是否已有本文件条目。素材库是账号级共享的，列表里会有
        // 其他商品刚上传的视频；只能认本文件的内容寻址名，认不得就等。
        listHasFile: itemTextsFull.some((t) => t.includes(want)),
        // “发布成功”后底部汇总条仍会显示“N 个文件上传中”，不能据此判成
        // 还在处理；本条目已发布就放行，其他条目状态与绑定无关。
        processing: /生成封面图中|转码中|上传中/.test(text) && !/已上传|发布成功/.test(text),
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

  async function closeVideoDialogShell() {
    // 只关对话框外壳（X 按钮）；上传子面板的“完成”不在这里点，避免把
    // 接续所需的回执视图收走。
    await page.evaluate(() => {
      const dlg = document.querySelector(".wdeDialog");
      const btn = dlg && dlg.querySelector(".next-dialog-close");
      if (btn) btn.click();
    }).catch(() => {});
    for (let i = 0; i < 6 && videoSelectorFrame(); i++) await sleep(600);
  }

  if (phase === "verify") {
    // CLI 代投文件后的复核：只看视频区是否实际写入。
    const slot = await waitVideoUploaded(10);
    note(`verify videos=${slot.videos}`);
    return JSON.stringify({
      uploaded: slot.videos > 0,
      verifiedBy: slot.videos > 0 ? "slot" : "",
      slot,
      names,
      trace,
    }, null, 2);
  }

  const state = await videoSection("probe");
  note(`probe videos=${state.videos} found=${state.found}`);
  if (state.videos > 0) return JSON.stringify({ already: true, videos: state.videos, trace });
  if (!state.found) return JSON.stringify({ error: "未找到商品视频区", videos: 0, trace });

  let clicked = null;
  let frame = videoSelectorFrame();
  if (frame) {
    // 残留对话框可能停在上一商品/上一次尝试的状态。视频区未写入且对话框里
    // 既没有本文件回执也没有已发布回执时，先关掉重开，避免拿脏状态做判断。
    const stale = await readSelectorState();
    note(`staleDialog keep=${stale.noFrame ? "no-frame" : !(stale.hasUploadItem || stale.items || stale.published) ? "reopen" : "keep"} items=${stale.items}`);
    if (!stale.noFrame && !stale.hasUploadItem && !stale.items && !stale.published) {
      await closeVideoDialogShell();
      frame = videoSelectorFrame();
    }
  }
  if (!frame) {
    clicked = await videoSection("click");
    await sleep(2000);
    frame = await waitFrame(videoSelectorFrame, 24);
  }
  if (!frame) {
    return JSON.stringify({ clicked: clicked && clicked.clicked, error: "选择视频对话框未打开", trace });
  }

  let sel = await readSelectorState();
  note(`dialogOpen hasUploadItem=${sel.hasUploadItem} listHasFile=${sel.listHasFile} items=${sel.items} itemTexts=${JSON.stringify(sel.itemTexts.slice(0, 5).map(clip))}`);
  // 断点续接：上次可能已把视频传到平台但尚未出现在可选列表。本文件回执或
  // 本文件条目任一在列即不重复投递，避免同一视频传两份（平台索引有延迟，
  // 重试时先等索引，而不是再传一遍）。文件名是内容寻址名（qn_<hash>_），
  // 跨商品、跨重试都不会撞名；列表里有其他商品的条目不算本文件已上传，
  // 不能因此跳过投递。
  if (!sel.hasUploadItem && !sel.published) {
    for (let i = 0; i < 8; i++) {
      await refreshLibraryTab();
      await sleep(8000);
      sel = await readSelectorState();
      note(`resumeWait i=${i} hasUploadItem=${sel.hasUploadItem} published=${sel.published} items=${sel.items}`);
      if (sel.hasUploadItem || sel.published) break;
    }
  }
  if (!sel.hasUploadItem && !sel.published) {
    // 定向投递到视频对话框自己的 input。全局 fileInput 查找现在会排除视频
    // 选择器 context（防图片误投），视频必须显式指回这里；定向失败交还
    // CLI 代投，不再全局乱找。
    let setFiles = "NO_INPUT";
    const target = videoSelectorFrame();
    const input = target && target.locator("input[type=file]").first();
    if (input && await input.count().catch(() => 0)) {
      try {
        await input.setInputFiles(files, { timeout: 8000 });
        setFiles = "OK";
      } catch (e) {
        setFiles = "FAIL";
      }
    }
    note(`setFiles=${setFiles} file=${clip(names[0])}`);
    if (setFiles !== "OK") {
      return JSON.stringify({ clicked: clicked && clicked.clicked, need_cli_upload: true, error: "未找到上传入口", setFiles, trace });
    }
    await sleep(2500);
    sel = await readSelectorState();
  }

  // 等平台处理（生成封面/转码）完成。真实视频实测数秒完成；伪视频会永远
  // 卡在“生成封面图中”，112 秒足以区分。
  for (let i = 0; i < 14 && sel.processing; i++) {
    await sleep(8000);
    sel = await readSelectorState();
    if (sel.failed) {
      note(`uploadFailed i=${i} snippet=${clip(sel.snippet)}`);
      return JSON.stringify({ error: "视频上传失败", detail: sel.snippet, trace });
    }
  }
  note(`processingDone processing=${sel.processing} published=${sel.published} snippet=${clip(sel.snippet)}`);
  if (sel.processing) return JSON.stringify({ error: "视频处理超时", detail: sel.snippet, trace });

  // 收起上传子面板。“完成”按钮可能渲染在 videoSelector iframe 内，也可能在
  // 主页面 .wdeDialog 壳上（不同环境 DOM 不同），两处都试；点了哪个都行。
  await frame.evaluate(() => {
    const btn = [...document.querySelectorAll("button")].find((b) => (b.innerText || "").trim() === "完成");
    if (btn) btn.click();
  }).catch(() => {});
  await page.evaluate(() => {
    const dlg = document.querySelector(".wdeDialog");
    const btn = dlg && [...dlg.querySelectorAll("button")].find((b) => (b.innerText || "").trim() === "完成");
    if (btn) btn.click();
  }).catch(() => {});
  await sleep(1500);
  // 等的是“本文件条目出现在可选列表”，不是“列表非空”：素材库是账号级
  // 共享的，别的商品刚上传的视频可能先出现，据此进入勾选会绑错视频。
  for (let i = 0; i < 12 && !sel.listHasFile; i++) {
    await refreshLibraryTab();
    await sleep(15000);
    sel = await readSelectorState();
    note(`listWait i=${i} listHasFile=${sel.listHasFile} items=${sel.items} itemTexts=${JSON.stringify(sel.itemTexts.slice(0, 5).map(clip))}`);
  }
  if (!sel.listHasFile) {
    return JSON.stringify({
      error: "视频已上传成功但本商品条目未出现在选择列表",
      detail: "平台索引有延迟，稍后点继续会按同名回执接续勾选，不会重复上传",
      detailState: { published: sel.published, hasUploadItem: sel.hasUploadItem, items: sel.items, itemTexts: sel.itemTexts, snippet: sel.snippet },
      trace,
    });
  }

  // 勾选：只认按文件名（内容寻址名 qn_<hash>_）匹配到的本商品条目。
  // 内容寻址名同名即同内容，多条目时取第一条也安全；普通名撞多条目仍视为
  // 歧义，交人工复核。named 为空时绝不能退而选“列表唯一一条”——素材库
  // 列表里那一条很可能是其他商品刚上传的视频（2026-10-01 两个商品被绑上
  // 同一第三方视频的根因），宁可选不了报错跳过，也不绑错。
  const picked = await frame.evaluate((want) => {
    const lists = [...document.querySelectorAll('[class*=VideoList--list]')].filter((el) => !/listView/.test(el.className));
    const list = lists[0];
    const itemTexts = list ? [...list.children].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80)) : [];
    if (!list || !list.children.length) return { decision: "NO_ITEM", items: 0, itemTexts };
    const named = [...list.children].filter((el) => (el.innerText || "").includes(want));
    const contentAddressed = /^qn_[0-9a-f]{16,}/i.test(want);
    if (named.length > 1 && !contentAddressed) return { decision: "AMBIGUOUS", items: list.children.length, itemTexts };
    const item = named[0];
    if (!item) return { decision: "NOT_MATCHED", items: list.children.length, itemTexts };
    item.click();
    return {
      decision: named.length > 1 ? "clicked-first-of-same-content" : "clicked-item",
      items: list.children.length,
      itemTexts,
    };
  }, stem);
  const pick = picked.decision;
  note(`pick=${pick} items=${picked.items} itemTexts=${JSON.stringify(picked.itemTexts.slice(0, 5))}`);
  await sleep(1500);
  let count = (await readSelectorState()).confirmCount;
  // 仅当 pick 已确认点击过本商品条目时才做 checkbox 重试；AMBIGUOUS /
  // NOT_MATCHED / NO_ITEM 一律不重试，避免任何“退而选其他条目”的路径。
  if (!count && (pick === "clicked-item" || pick === "clicked-first-of-same-content")) {
    // 条目点击未触发勾选时，对同一“按名匹配到的条目”直接点它的 checkbox
    // 重试；绝不点列表第一条兜底——那会把其他商品的视频勾上。
    await frame.evaluate((want) => {
      const lists = [...document.querySelectorAll('[class*=VideoList--list]')].filter((el) => !/listView/.test(el.className));
      const list = lists[0];
      const named = list ? [...list.children].filter((el) => (el.innerText || "").includes(want)) : [];
      const input = named[0] && named[0].querySelector("input[type=checkbox]");
      if (input) input.click();
    }, stem);
    await sleep(1500);
    count = (await readSelectorState()).confirmCount;
    note(`checkboxRetry count=${count}`);
  }
  if (!count) {
    return JSON.stringify({ error: "未能勾选视频", pick, detailState: sel, trace });
  }
  if (pick !== "clicked-item" && pick !== "clicked-first-of-same-content") {
    // 有勾选计数但本次没有点击过任何条目：勾选状态来自残留对话框（上次
    // 勾了别的视频未确认），来源不可信，拒绝绑定。
    return JSON.stringify({
      error: "勾选状态非本次操作产生（可能为残留对话框勾选），拒绝绑定",
      pick,
      detailState: { items: sel.items, itemTexts: sel.itemTexts },
      trace,
    });
  }

  // 绑定前最后一道校验：读取当前已勾选条目的文本，必须能对上本商品的内容
  // 寻址名。读不到勾选状态（checkedText 为空）时以 pick 的按名匹配结果为准
  // 放行；一旦读得到且不匹配，立即拒绝绑定，视频按可选项告警跳过。
  const checkedText = await frame.evaluate((want) => {
    const lists = [...document.querySelectorAll('[class*=VideoList--list]')].filter((el) => !/listView/.test(el.className));
    const list = lists[0];
    if (!list) return "";
    return [...list.children]
      .filter((el) => {
        const input = el.querySelector("input[type=checkbox]");
        return input && input.checked;
      })
      .map((el) => (el.innerText || "").replace(/\s+/g, " ").trim())
      .join(" | ");
  }, stem);
  note(`checkedVerify count=${count} checkedText=${clip(checkedText) || "<unreadable>"}`);
  if (checkedText && !checkedText.includes(stem)) {
    return JSON.stringify({
      error: "勾选校验失败：已勾选条目不是本商品视频，拒绝绑定",
      pick, checkedText,
      detailState: { items: sel.items, itemTexts: sel.itemTexts },
      trace,
    });
  }

  const confirmed = await frame.evaluate(() => {
    const btn = [...document.querySelectorAll("button")]
      .filter((b) => /确认上传/.test((b.innerText || "").replace(/\s+/g, "")))
      .find((b) => b.getBoundingClientRect().width > 4);
    if (!btn) return "NO_BTN";
    btn.click();
    return "ok";
  });
  // 成功以视频区实际写入为准：只有回执不算上传完成。checkedText 留档，
  // 便于事后核对绑定的确实是本商品的视频。
  const slot = await waitVideoUploaded(12);
  note(`confirmed=${confirmed} slotVideos=${slot.videos}`);
  return JSON.stringify({
    clicked: clicked && clicked.clicked,
    pick,
    confirmed,
    countBefore: count,
    checkedText,
    slot,
    uploaded: slot.videos > 0,
    verifiedBy: slot.videos > 0 ? (checkedText ? "slot+checked" : "slot") : "",
    names,
    trace,
  }, null, 2);
}
