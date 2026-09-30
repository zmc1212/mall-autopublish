async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());

  const phase = PAYLOAD.phase || "upload";
  const specs = PAYLOAD.skus || [];
  const bindStart = Math.max(0, Number(PAYLOAD.bindStart) || 0);
  const bindEnd = Math.min(specs.length, PAYLOAD.bindEnd == null
    ? specs.length : Math.max(bindStart, Number(PAYLOAD.bindEnd) || 0));
  // 分批补图：onlyRows 为 0 基行号，绑定与保存校验只针对这些行；
  // 其余行属于后续批次，不参与本次确认。
  const onlyRows = Array.isArray(PAYLOAD.onlyRows)
    ? [...new Set(PAYLOAD.onlyRows.map((value) => Number(value)))]
        .filter((value) => Number.isInteger(value) && value >= 0 && value < specs.length)
        .sort((a, b) => a - b)
    : null;
  // 抽屉里会显示之前批次已绑定的行，稳定性判断用“本批结束时应至少已填多少行”。
  const minFilled = Number(PAYLOAD.minFilledCount) > 0 ? Number(PAYLOAD.minFilledCount) : specs.length;
  // Several SKU rows can use the same image. Upload each file once, then bind it to every row.
  const files = [...new Set(((PAYLOAD.files && PAYLOAD.files.length)
    ? PAYLOAD.files
    : specs.map((item) => item.image)).filter(Boolean))];
  const names = [...new Set(files.map(fileBase))];
  const uploadNames = [...new Set(PAYLOAD.uploadNames && PAYLOAD.uploadNames.length ? PAYLOAD.uploadNames : names)];
  const targetColumn = "商品规格";

  await dismissKnow({ escape: false });

  async function specDiagnostics() {
    const dom = await page.evaluate(() => {
      const visible = (el) => {
        if (!el) return false;
        const rect = el.getBoundingClientRect();
        const style = getComputedStyle(el);
        return rect.width > 4 && rect.height > 4 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
      };
      const textOf = (el) => (el.innerText || el.textContent || "").replace(/\s+/g, " ").trim().slice(0, 220);
      const dialogs = [...document.querySelectorAll(".batch-fill-sku-image-dialog, .next-dialog, .sell-component-image-v2-media-popup, .next-overlay-wrapper.opened")]
        .filter(visible)
        .map((el) => ({ className: String(el.className || "").slice(0, 160), text: textOf(el) }))
        .slice(-8);
      const frames = [...document.querySelectorAll("iframe")].map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          src: el.getAttribute("src") || el.src || "",
          title: el.getAttribute("title") || "",
          visible: rect.width > 4 && rect.height > 4,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      });
      const drawer = document.querySelector(".sku-decouple-drawer");
      const imageControls = drawer ? [...drawer.querySelectorAll(
        ".sell-color-option-image-empty, .sell-color-option-image-upload, .sell-color-option-image, [class*='sku-image'], [class*='color-option-image']"
      )].slice(0, 12).map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          className: String(el.className || "").slice(0, 180),
          text: textOf(el),
          visible: rect.width > 4 && rect.height > 4,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          html: String(el.outerHTML || "").replace(/\s+/g, " ").slice(0, 500),
        };
      }) : [];
      const body = (document.body && document.body.innerText || "").replace(/\s+/g, " ");
      return {
        drawer: !!drawer,
        picker: !!document.querySelector(".batch-fill-sku-image-dialog"),
        dialogs,
        iframeElements: frames,
        imageControls,
        bodyHint: body.slice(0, 320),
      };
    }).catch((error) => ({ domError: String(error && error.message || error) }));
    return {
      url: page.url(),
      title: await page.title().catch(() => ""),
      frameUrls: page.frames().map((frame) => frame.url()).filter(Boolean),
      ...dom,
    };
  }

  async function ensureSpecDrawer() {
    if (await page.locator(".sku-decouple-drawer").count()) return "already";
    const opened = await page.evaluate(() => {
      const button = [...document.querySelectorAll("button")].find((el) => {
        const text = (el.innerText || "").trim();
        return text === "编辑规格" || text.includes("创建规格");
      });
      if (!button) return "NO_EDIT";
      button.scrollIntoView({ block: "center" });
      button.click();
      return "OPEN";
    });
    await sleep(900);
    if (!(await page.locator(".sku-decouple-drawer").count())) {
      throw new Error("PAUSE:规格抽屉未打开");
    }
    return opened;
  }

  async function openSpecImagePicker() {
    await ensureSpecDrawer();
    const current = await drawerImageState();
    if (current.open && specs.length && current.filled >= minFilled) {
      return { clicked: "ALREADY_FILLED", frame: null, prefilled: true, current };
    }
    if (await pickerOpen()) {
      const frame = sucaiFrame() || await waitFrame(sucaiFrame, 18);
      if (frame) return { clicked: "REUSE_PICKER", frame };
    }
    const clicked = await page.evaluate(() => {
      const drawer = document.querySelector(".sku-decouple-drawer");
      if (!drawer) return "NO_DRAWER";
      const box = drawer.querySelector(".sell-color-option-image-empty")
        || drawer.querySelector(".sell-color-option-image-upload");
      if (!box) return "NO_SPEC_IMAGE";
      box.scrollIntoView({ block: "center" });
      return "READY_SPEC_IMAGE";
    });
    if (clicked === "NO_SPEC_IMAGE") throw new Error("规格图未找到商品规格图片控件");
    if (clicked === "READY_SPEC_IMAGE") {
      const empty = page.locator(".sku-decouple-drawer .sell-color-option-image-empty");
      const target = (await empty.count())
        ? empty.first()
        : page.locator(".sku-decouple-drawer .sell-color-option-image-upload").first();
      await target.scrollIntoViewIfNeeded().catch(() => {});
      await target.click({ force: true, timeout: 8000 });
    }
    await sleep(1400);
    const frame = sucaiFrame() || await waitFrame(sucaiFrame, 18);
    return { clicked, frame, diagnostics: frame ? null : await specDiagnostics() };
  }

  async function pickerOpen() {
    return page.evaluate(() => [...document.querySelectorAll(".batch-fill-sku-image-dialog, .next-dialog")]
      .some((el) => {
        if (getComputedStyle(el).display === "none") return false;
        const text = (el.innerText || "").replace(/\s+/g, "");
        return text.includes("规格主图") || text.includes("选择规格图") || text.includes("选择SKU图");
      }));
  }

  async function waitSpecUploadOverlay(frame) {
    if (!frame) return "NO_FRAME";
    for (let i = 0; i < 90; i++) {
      const uploading = await frame.evaluate(() => /\d+\s*个文件\s*上传中|文件上传中\.\.\./.test(
        (document.body && document.body.innerText) || ""
      )).catch(() => false);
      if (!uploading) {
        if (await hasUploadResult() && (await waitUploadResultClosed(20)) !== "CLOSED") {
          throw new Error("图片上传结果弹窗未关闭");
        }
        return "READY";
      }
      await sleep(1000);
    }
    throw new Error("图片空间仍在上传，已暂停规格绑定");
  }

  async function specRowImageState(index) {
    return page.evaluate((i) => {
      const dialog = document.querySelector(".batch-fill-sku-image-dialog");
      const items = dialog ? [...dialog.querySelectorAll("li.sku-item")] : [];
      const item = items[i];
      if (!item) return { found: false, count: items.length, hasImage: false };
      const images = [...item.querySelectorAll("img")].filter((img) =>
        (img.width || img.naturalWidth || 0) > 12 && (img.height || img.naturalHeight || 0) > 12);
      const backgrounds = [...item.querySelectorAll("*")].filter((el) =>
        /url\(/i.test(getComputedStyle(el).backgroundImage || ""));
      return {
        found: true,
        hasImage: images.length + backgrounds.length > 0,
        imageCount: images.length + backgrounds.length,
        name: (item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 70),
        html: String(item.outerHTML || "").replace(/\s+/g, " ").slice(0, 600),
      };
    }, index);
  }

  async function drawerImageState() {
    return page.evaluate(() => {
      const drawer = document.querySelector(".sku-decouple-drawer");
      if (!drawer) return { open: false, filled: 0, wrongTarget: false };
      const body = (drawer.innerText || "").replace(/\s+/g, " ");
      const boxes = [...drawer.querySelectorAll(
        ".sell-color-option-image-upload img, .sell-color-option-image img"
      )];
      return {
        open: true,
        filled: boxes.filter((img) => (img.width || 0) > 12).length,
        wrongTarget: body.includes("SKU搜索主图") && !body.includes("商品规格"),
      };
    });
  }

  async function waitDrawerImagesStable() {
    let stable = 0;
    let state = await drawerImageState();
    for (let i = 0; i < 24; i++) {
      const dialog = await pickerOpen();
      state = await drawerImageState();
      if (!dialog && state.open && state.filled >= minFilled) {
        stable += 1;
        if (stable >= 3) return state;
      } else {
        stable = 0;
      }
      await sleep(400);
    }
    return state;
  }

  async function waitPickerOverlaysGone() {
    for (let i = 0; i < 30; i++) {
      const blocking = await page.evaluate(() => {
        const visible = (el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 4 && rect.height > 4 && style.display !== "none" && style.visibility !== "hidden" && style.opacity !== "0";
        };
        return [...document.querySelectorAll(".batch-fill-sku-image-dialog, .sell-component-image-v2-media-popup, iframe[src*='sucai-selector']")]
          .some(visible);
      });
      if (!blocking) return true;
      await sleep(300);
    }
    return false;
  }

  async function clickVisibleDrawerConfirm() {
    const buttons = page.locator('.sku-decouple-drawer button:visible').filter({ hasText: /^确认创建$/ });
    const count = await buttons.count();
    if (!count) return { result: "NO_VISIBLE_BUTTON", count };
    const button = buttons.first();
    const meta = await button.evaluate((el) => {
      const rect = el.getBoundingClientRect();
      return {
        text: (el.innerText || "").trim(),
        className: String(el.className || "").slice(0, 180),
        disabled: !!el.disabled,
        rect: { x: Math.round(rect.x), y: Math.round(rect.y), width: Math.round(rect.width), height: Math.round(rect.height) },
      };
    });
    if (meta.disabled) return { result: "DISABLED", count, meta };
    await button.evaluate((el) => { el.scrollIntoView({ block: "center" }); el.click(); });
    return { result: "CLICKED_VISIBLE", count, meta };
  }

  async function persistedImageState() {
    return page.evaluate((expected) => {
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const text = tr.innerText || "";
        return text.includes("元") && text.includes("件") && !text.includes("SKU分类");
      });
      const details = rows.map((tr, index) => {
        const cell = tr.querySelector('td[id$="-custom_-1"]');
        const images = [...(cell ? cell.querySelectorAll("img.image-item") : [])].filter((img) =>
          (img.width || img.naturalWidth || 0) > 16 && (img.height || img.naturalHeight || 0) > 16
        );
        const backgrounds = [...(cell ? cell.querySelectorAll(".image-item") : [])].filter((el) => {
          const value = getComputedStyle(el).backgroundImage || "";
          return value !== "none" && /url\(/i.test(value);
        });
        const input = tr.querySelector("input, textarea");
        return {
          index,
          name: input ? input.value : (tr.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80),
          imageCount: images.length + backgrounds.length,
          hasImage: images.length + backgrounds.length > 0,
          src: images[0] ? String(images[0].src || "").split("/").pop() : (backgrounds[0] ? "background-image" : ""),
        };
      });
      return {
        expected,
        rowCount: details.length,
        filled: details.filter((row) => row.hasImage).length,
        missing: details.filter((row) => !row.hasImage).map((row) => row.index),
        rows: details.slice(0, Math.max(expected, 20)),
      };
    }, specs.length);
  }

  async function selectSpec(spec, frame) {
    await assertNoSecurityChallenge();
    const index = specs.indexOf(spec);
    const skuClick = await page.evaluate((want) => {
      const dialog = document.querySelector(".batch-fill-sku-image-dialog");
      if (!dialog) return "NO_DIALOG";
      const specific = [...dialog.querySelectorAll("li.sku-item")];
      const items = specific.length ? specific : [...dialog.querySelectorAll("li, [class*='sku-item']")];
      const textOf = (el) => ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "")
        .replace(/\s+/g, " ").trim();
      const matches = items.filter((el) => {
        const text = textOf(el);
        return text === want.name || (want.slot && text.includes(want.slot)) || (want.name && text.includes(want.name));
      });
      const indexed = items[want.index];
      const item = (indexed && matches.includes(indexed) ? indexed : null)
        || matches[want.occurrence] || indexed || matches[0];
      if (!item) return "NO_SPEC:" + items.length;
      item.click();
      return "OK:" + items.indexOf(item) + ":" + ((item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60));
    }, {
      ...spec,
      index,
      occurrence: specs.slice(0, index).filter((item) => item.name === spec.name).length,
    });
    await sleep(260);
    if (!frame) return { skuClick, picClick: { ok: false, error: "NO_FRAME" } };
    // Newly uploaded cards are usually all in the current material list.
    // Avoid a remote search for every SKU: repeated searches can leave the
    // picker showing the previous SKU's results when one request stalls.
    let searched = "CURRENT_LIST";
    // The picker listens on the image inside the material card. Clicking the
    // outer card reports success but does not assign anything to the SKU row.
    let picClick = await clickSucaiCard(frame, spec.file || spec.slot || spec.name, true);
    if (!picClick.ok) {
      searched = await searchSucai(frame, spec.slot || spec.file || spec.name, undefined, true);
      picClick = await clickSucaiCard(frame, spec.file || spec.slot || spec.name, true);
      if (!picClick.ok && spec.file) {
        searched = await searchSucai(frame, spec.file.replace(/\.[^.]+$/, ""), undefined, true);
        picClick = await clickSucaiCard(frame, spec.file, true);
      }
    }
    await sleep(350);
    await confirmCrop();
    let row = await specRowImageState(index);
    for (let i = 0; i < 6 && row.found && !row.hasImage; i++) {
      await sleep(300);
      row = await specRowImageState(index);
    }
    let innerClick = null;
    if (picClick.ok && row.found && !row.hasImage) {
      innerClick = await clickSucaiCard(frame, spec.file || spec.slot || spec.name);
      for (let i = 0; i < 6 && !row.hasImage; i++) {
        await sleep(300);
        row = await specRowImageState(index);
      }
    }
    return { skuClick, searched, picClick, innerClick, row };
  }

  if (phase === "open" || phase === "open_library") {
    if (await hasUploadResult() && (await waitUploadResultClosed(20)) !== "CLOSED") {
      throw new Error("图片上传结果弹窗未关闭");
    }
    const opened = await openSpecImagePicker();
    const frame = opened.frame;
    if (phase === "open_library") {
      return JSON.stringify({ targetColumn, opened: opened.clicked, pics: frame ? await listSucaiPics(frame) : [], names, dialog: await pickerOpen() });
    }
    if (opened.prefilled) return JSON.stringify({ targetColumn, opened: opened.clicked, prefilled: true, already: true, uploaded: true, filledCount: opened.current.filled, dialog: await pickerOpen() });
    if (!frame) return JSON.stringify({ targetColumn, opened: opened.clicked, uploaded: false, hadFrame: false, error: "规格图素材库 iframe 未加载", diagnostics: opened.diagnostics || await specDiagnostics(), dialog: await pickerOpen() });
    await waitSpecUploadOverlay(frame);
    const listed = await listSucaiPics(frame);
    // The initial library view already contains recent uploads. Searching
    // every filename here sends many file.query requests before upload starts.
    const missing = missingPictureNames(listed, names);
    if (!missing.length) return JSON.stringify({ targetColumn, opened: opened.clicked, already: true, uploaded: true, pics: listed, dialog: await pickerOpen() });
    const pending = filesForNames(files, missing);
    const finished = await finishLocalUpload(frame, pending, missing);
    return JSON.stringify({ targetColumn, opened: opened.clicked, ...finished, pics: listed, missing, dialog: await pickerOpen() });
  }

  if (phase === "after_upload") {
    const frame = sucaiFrame();
    if (!frame) {
      const current = await drawerImageState();
      if (current.open && specs.length && current.filled >= minFilled) {
        return JSON.stringify({ targetColumn, uploaded: true, prefilled: true, already: true, filledCount: current.filled, dialog: await pickerOpen() });
      }
      return JSON.stringify({ targetColumn, uploaded: false, hadFrame: false, error: "规格图素材库 iframe 未加载", diagnostics: await specDiagnostics(), dialog: await pickerOpen() });
    }
    if (!(await hasUploadResult())) {
      const missing = await missingSucaiNames(frame, uploadNames, 5);
      return JSON.stringify({ targetColumn, uploaded: !missing.length, verifiedBy: "library-search", missing, hadFrame: true, dialog: await pickerOpen() });
    }
    const retried = await retryUntilUploaded(frame, files, uploadNames);
    return JSON.stringify({ targetColumn, ...retried, hadFrame: true, dialog: await pickerOpen() });
  }

  if (await hasUploadResult() && (await waitUploadResultClosed(20)) !== "CLOSED") {
    throw new Error("图片上传结果弹窗未关闭");
  }
  let frame = sucaiFrame();
  const opened = frame ? { clicked: "REUSE_PICKER", frame } : await openSpecImagePicker();
  frame = opened.frame || sucaiFrame();
  const prefilled = !!opened.prefilled;
  if (!frame && !prefilled) {
    return JSON.stringify({
      targetColumn,
      error: "规格图素材库 iframe 未加载",
      hadFrame: false,
      filledCount: 0,
      bindLog: [],
      diagnostics: opened.diagnostics || await specDiagnostics(),
      dialog: await pickerOpen(),
    });
  }
  if (frame) await waitSpecUploadOverlay(frame);
  const bindLog = [];
  const bindTargets = onlyRows ? onlyRows.map((index) => specs[index]) : specs.slice(bindStart, bindEnd);
  if (frame) for (const spec of bindTargets) {
    await assertNoSecurityChallenge();
    if (!(await pickerOpen())) {
      const reopened = await openSpecImagePicker();
      frame = reopened.frame || sucaiFrame();
      if (!frame) {
        return JSON.stringify({
          targetColumn,
          error: "规格图素材库 iframe 未加载",
          hadFrame: false,
          filledCount: bindLog.filter((item) => item.picClick && item.picClick.ok).length,
          bindLog,
          diagnostics: reopened.diagnostics || await specDiagnostics(),
          dialog: await pickerOpen(),
        });
      }
    }
    const selected = await selectSpec(spec, frame);
    bindLog.push({ name: spec.name, slot: spec.slot, ...selected });
    if (!selected.row || !selected.row.hasImage) {
      return JSON.stringify({ targetColumn, error: "素材卡片点击后规格行仍为空", hadFrame: true,
        bindStart, bindEnd, bindLog, dialog: await pickerOpen() });
    }
  }

  if (!onlyRows && bindEnd < specs.length && !prefilled) {
    return JSON.stringify({ targetColumn, hadFrame: true, bindStart, bindEnd, bindLog, partial: true, dialog: await pickerOpen() });
  }

  let confirm = "NO_DIALOG";
  const dialogButtons = page.locator(".batch-fill-sku-image-dialog button:visible").filter({ hasText: /^确定$/ });
  if (await dialogButtons.count()) {
    const dialogItems = page.locator(".batch-fill-sku-image-dialog li.sku-item, .batch-fill-sku-image-dialog li, .batch-fill-sku-image-dialog [class*='sku-item']");
    const filled = await dialogItems.filter({ has: page.locator("img") }).count().catch(() => 0);
    const button = dialogButtons.first();
    await button.evaluate((el) => { el.scrollIntoView({ block: "center" }); el.click(); });
    confirm = "OK:" + filled;
  }
  const overlaysGone = await waitPickerOverlaysGone();
  const readyDrawer = await waitDrawerImagesStable();
  await sleep(2200);
  let drawerConfirm = await clickVisibleDrawerConfirm();
  for (let i = 0; i < 4 && await page.locator(".sku-decouple-drawer").count(); i++) {
    await sleep(500);
  }
  if (await page.locator(".sku-decouple-drawer").count()) {
    drawerConfirm.retry = await clickVisibleDrawerConfirm();
  }
  let persisted = await persistedImageState();
  for (let i = 0; i < 12 && ((await page.locator(".sku-decouple-drawer").count()) || persisted.filled < minFilled); i++) {
    await sleep(500);
    persisted = await persistedImageState();
  }
  // 分批时只要求本批行已写入；其余行属于后续批次，不能据此判失败。
  const scopeSaved = onlyRows
    ? onlyRows.every((index) => !persisted.missing.includes(index))
    : persisted.filled >= specs.length;
  const tableSaved = persisted.rowCount >= specs.length && scopeSaved;
  const state = await drawerImageState();
  const filledCount = persisted.filled;
  const saved = tableSaved;
  const verifiedBy = tableSaved ? "sku-table" : "none";
  return JSON.stringify({ targetColumn, bindLog, confirm, overlaysGone, readyDrawer, drawerConfirm, filledCount, saved, verifiedBy, persisted, drawer: state, wrongTarget: !!state.wrongTarget, error: saved ? "" : "规格图未保存到SKU表格" }, null, 2);
}
