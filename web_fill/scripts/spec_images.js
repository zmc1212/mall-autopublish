async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());

  const phase = PAYLOAD.phase || "upload";
  const specs = PAYLOAD.skus || [];
  const files = (PAYLOAD.files && PAYLOAD.files.length)
    ? PAYLOAD.files
    : specs.map((item) => item.image).filter(Boolean);
  const names = specs.map((item) => item.file || (item.image && String(item.image).split(/[\\/]/).pop())).filter(Boolean);
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
    if (current.open && specs.length && current.filled >= specs.length) {
      return { clicked: "ALREADY_FILLED", frame: null, prefilled: true, current };
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
      if (!dialog && state.open && state.filled >= specs.length) {
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
    await button.scrollIntoViewIfNeeded();
    await button.click({ timeout: 8000 });
    return { result: "CLICKED_VISIBLE", count, meta };
  }

  async function persistedImageState() {
    return page.evaluate((expected) => {
      const rows = [...document.querySelectorAll("table tr")].filter((tr) => {
        const text = tr.innerText || "";
        return text.includes("元") && text.includes("件") && !text.includes("SKU分类");
      });
      const details = rows.map((tr, index) => {
        const images = [...tr.querySelectorAll("img")].filter((img) =>
          (img.width || img.naturalWidth || 0) > 16 && (img.height || img.naturalHeight || 0) > 16
        );
        const backgrounds = [...tr.querySelectorAll("*")].filter((el) => {
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
    const skuClick = await page.evaluate((want) => {
      const dialog = document.querySelector(".batch-fill-sku-image-dialog");
      if (!dialog) return "NO_DIALOG";
      const items = [...dialog.querySelectorAll("li.sku-item, li, [class*='sku-item']")];
      const item = items.find((el) => {
        const text = ((el.querySelector(".sku-text") && el.querySelector(".sku-text").innerText) || el.innerText || "")
          .replace(/\s+/g, " ").trim();
        return text === want.name || (want.slot && text.includes(want.slot)) || (want.name && text.includes(want.name));
      }) || items[want.index];
      if (!item) return "NO_SPEC:" + items.length;
      item.click();
      return "OK:" + ((item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 60));
    }, { ...spec, index: specs.indexOf(spec) });
    await sleep(260);
    if (!frame) return { skuClick, picClick: { ok: false, error: "NO_FRAME" } };
    const query = spec.slot || spec.file || spec.name;
    let searched = await searchSucai(frame, query);
    let picClick = await clickSucaiCard(frame, spec.file || spec.slot || spec.name);
    if (!picClick.ok && spec.file) {
      searched = await searchSucai(frame, spec.file.replace(/\.[^.]+$/, ""));
      picClick = await clickSucaiCard(frame, spec.file);
    }
    await sleep(350);
    await confirmCrop();
    return { skuClick, searched, picClick };
  }

  if (phase === "open" || phase === "open_library") {
    const opened = await openSpecImagePicker();
    const frame = opened.frame;
    if (phase === "open_library") {
      return JSON.stringify({ targetColumn, opened: opened.clicked, pics: frame ? await listSucaiPics(frame) : [], names, dialog: await pickerOpen() });
    }
    if (opened.prefilled) return JSON.stringify({ targetColumn, opened: opened.clicked, prefilled: true, already: true, uploaded: true, filledCount: opened.current.filled, dialog: await pickerOpen() });
    if (!frame) return JSON.stringify({ targetColumn, opened: opened.clicked, uploaded: false, hadFrame: false, error: "规格图素材库 iframe 未加载", diagnostics: opened.diagnostics || await specDiagnostics(), dialog: await pickerOpen() });
    const listed = await listSucaiPics(frame);
    const missing = missingPictureNames(listed, names);
    if (!missing.length) return JSON.stringify({ targetColumn, opened: opened.clicked, already: true, uploaded: true, pics: listed, dialog: await pickerOpen() });
    const finished = await finishLocalUpload(frame, files, names);
    return JSON.stringify({ targetColumn, opened: opened.clicked, ...finished, pics: listed, missing, dialog: await pickerOpen() });
  }

  if (phase === "after_upload") {
    const frame = sucaiFrame();
    if (!frame) {
      const current = await drawerImageState();
      if (current.open && specs.length && current.filled >= specs.length) {
        return JSON.stringify({ targetColumn, uploaded: true, prefilled: true, already: true, filledCount: current.filled, dialog: await pickerOpen() });
      }
      return JSON.stringify({ targetColumn, uploaded: false, hadFrame: false, error: "规格图素材库 iframe 未加载", diagnostics: await specDiagnostics(), dialog: await pickerOpen() });
    }
    const retried = await retryUntilUploaded(frame, files, names);
    return JSON.stringify({ targetColumn, ...retried, hadFrame: true, dialog: await pickerOpen() });
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
  const bindLog = [];
  if (frame) for (const spec of specs) {
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
    bindLog.push({ name: spec.name, slot: spec.slot, ...(await selectSpec(spec, frame)) });
  }

  let confirm = "NO_DIALOG";
  const dialogButtons = page.locator(".batch-fill-sku-image-dialog button:visible").filter({ hasText: /^确定$/ });
  if (await dialogButtons.count()) {
    const dialogItems = page.locator(".batch-fill-sku-image-dialog li.sku-item, .batch-fill-sku-image-dialog li, .batch-fill-sku-image-dialog [class*='sku-item']");
    const filled = await dialogItems.filter({ has: page.locator("img") }).count().catch(() => 0);
    const button = dialogButtons.first();
    await button.scrollIntoViewIfNeeded();
    await button.click({ timeout: 8000 });
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
  for (let i = 0; i < 12 && ((await page.locator(".sku-decouple-drawer").count()) || persisted.filled < specs.length); i++) {
    await sleep(500);
    persisted = await persistedImageState();
  }
  const tableSaved = persisted.rowCount >= specs.length && persisted.filled >= specs.length;
  const state = await drawerImageState();
  const filledCount = persisted.filled;
  const saved = tableSaved;
  const verifiedBy = tableSaved ? "sku-table" : "none";
  return JSON.stringify({ targetColumn, bindLog, confirm, overlaysGone, readyDrawer, drawerConfirm, filledCount, saved, verifiedBy, persisted, drawer: state, wrongTarget: !!state.wrongTarget, error: saved ? "" : "规格图未保存到SKU表格" }, null, 2);
}
