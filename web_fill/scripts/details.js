async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  // Keep the material picker alive across the separately executed phases.
  await dismissKnow({ escape: false });

  async function pictureSpaceVisible() {
    return page.evaluate(() => [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened")]
      .some(el => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 80 && r.height > 80 && s.display !== "none"
          && s.visibility !== "hidden" && /图片空间/.test(el.innerText || "");
      }));
  }

  async function openPictureSpace() {
    let frame = pictureSpaceFrame();
    if (frame && await uploadContextVisible(frame).catch(() => false)) return frame;
    if (!(await pictureSpaceVisible())) {
      await page.evaluate(() => {
        const el = [...document.querySelectorAll(".m-editor-content-footer-add, .add_item-NH_hk3, button, div, span")].find((n) => {
          const t = (n.innerText || "").trim();
          return t === "图片" && n.offsetWidth > 0;
        });
        if (!el) return false;
        el.scrollIntoView({ block: "center" });
        el.click();
        return true;
      });
      await sleep(1800);
    }
    for (let attempt = 0; attempt < 18; attempt++) {
      await assertNoSecurityChallenge();
      frame = pictureSpaceFrame();
      if (frame && await uploadContextVisible(frame).catch(() => false)) return frame;
      await sleep(400);
    }
    if (await pictureSpaceVisible()) return page;
    return null;
  }

  async function editorAfter() {
    return page.evaluate(() => {
      const editor = document.querySelector("#lite-decoration-editor")
        || document.querySelector(".sell-component-lite-decoration-editor");
      const imgs = editor ? [...editor.querySelectorAll("img")].filter((el) => el.width > 80).length : 0;
      const iframeOpen = [...document.querySelectorAll("iframe")].some((el) => {
        const src = el.src || "";
        const r = el.getBoundingClientRect();
        return r.width > 80 && r.height > 80 && /sucai\.wangpu|select\.htm|sucai-selector|picturestudio/i.test(src);
      });
      const dialogOpen = [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened")].some((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 80 && r.height > 80 && /图片空间/.test(el.innerText || "");
      });
      return { imgs, dialog: iframeOpen || dialogOpen };
    });
  }

  async function clearExistingDetails() {
    const before = await editorAfter();
    if (!before.imgs) return { before: 0, after: 0, cleared: true };
    // The current selector renders its close icon inside the iframe, not in
    // the host .next-dialog. Never click editor controls through that overlay.
    const existingPicker = pictureSpaceFrame();
    if (existingPicker && existingPicker !== page && await uploadContextVisible(existingPicker)) {
      await assertNoSecurityChallenge();
      const pending = await collectUploadStatus(existingPicker, []);
      if (pending.securityLimit) await pauseForUploadSecurityLimit(pending, [], "before-clear-details");
      if (pending.uploading || pending.hasComplete) {
        throw new Error("PAUSE:素材库仍有上传或待核验回执，未清空详情图");
      }
      const close = existingPicker.locator(".qn_close_blod").first();
      if (!(await close.count())) throw new Error("详情图清空前素材选择框未关闭，已保留原内容");
      await close.click({timeout: 3000});
      for (let i = 0; i < 10 && await uploadContextVisible(existingPicker); i++) await sleep(100);
      if (await uploadContextVisible(existingPicker)) {
        throw new Error("详情图清空前素材选择框仍未关闭，已保留原内容");
      }
    }
    const clearControl = await page.evaluate(() => {
      const scope = document.querySelector("#lite-decoration-editor")
        || document.querySelector(".sell-component-lite-decoration-editor") || document;
      const visible = (el) => {
        const r = el.getBoundingClientRect();
        const s = getComputedStyle(el);
        return r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden";
      };
      const controls = [...scope.querySelectorAll("button, [role='button'], a, span, div")];
      const btn = controls.find((el) =>
        /^清空(?:全部|内容|图片)?$/.test((el.innerText || "").trim()) && visible(el));
      if (!btn) return {
        clicked: false,
        scope: scope === document ? "document" : String(scope.className || scope.id),
        controls: controls.filter(visible).map((el) => ({
          tag: el.tagName, text: (el.innerText || "").trim().slice(0, 50),
          cls: String(el.className || "").slice(0, 100),
        })).filter((el) => /清|删除|图片|编辑|更多/.test(el.text)).slice(-25),
        imageParent: String((scope.querySelector("img") || {}).parentElement?.outerHTML || "").slice(0, 600),
      };
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return { clicked: true, tag: btn.tagName, text: (btn.innerText || "").trim() };
    });
    if (!clearControl.clicked) throw new Error(`详情图已有 ${before.imgs} 张，但未找到编辑器的清空控件：${JSON.stringify(clearControl)}`);
    await sleep(350);
    const confirm = page.getByRole("button", { name: "确定", exact: true })
      .or(page.getByRole("button", { name: "确认", exact: true }));
    if (await confirm.count()) await confirm.last().click({ force: true }).catch(() => {});
    let after = await editorAfter();
    for (let i = 0; i < 12 && after.imgs; i++) {
      await sleep(300);
      after = await editorAfter();
    }
    if (after.imgs) throw new Error(`详情图清空后仍有 ${after.imgs} 张，无法安全重建`);
    return { before: before.imgs, after: after.imgs, cleared: true };
  }

  if (phase === "open" || phase === "open_library") {
    const cleared = phase === "open" ? await clearExistingDetails() : null;
    const frame = await openPictureSpace();
    if (!frame) return JSON.stringify({ error: "NO_FRAME", need_cli_upload: false });
    const listed = await listPictureSpaceNames(frame);
    const missing = await missingSucaiNames(frame, names, 5);
    if (phase === "open_library") {
      return JSON.stringify({ pics: listed.slice(0, 40), names, missing, dialog: true });
    }
    if (!missing.length) {
      return JSON.stringify({ uploaded: true, already: listed.slice(0, 20), missing, files, names, via: "library", cleared });
    }
    if (PAYLOAD.libraryOnly) return JSON.stringify({uploaded: false,
      error: "MISSING_LIBRARY_IMAGES", missing, files, names, cleared});
    const toUpload = filesForNames(files, missing);
    const target = toUpload.length ? toUpload : files;
    const targetNames = target.map(fileBase);
    const finished = await finishLocalUpload(frame, target, targetNames, PAYLOAD);
    if (finished.uploaded) {
      return JSON.stringify({ ...finished, via: finished.via || "hidden-input", files, names, missing, cleared });
    }
    return JSON.stringify({
      uploaded: false,
      dispatched: finished.dispatched === true,
      need_cli_upload: finished.need_cli_upload === true && !finished.dispatched,
      missing,
      listed: listed.slice(0, 20),
      files,
      names,
      cleared,
      uploadStatus: finished,
    });
  }

  if (phase === "after_upload") {
    const frame = pictureSpaceFrame() || ((await pictureSpaceVisible()) ? page : null);
    let retried = { status: {}, complete: "SKIP", uploaded: true };
    if (await hasUploadResult()) {
      retried = await retryUntilUploaded(frame, files, names, 0);
    } else {
      const status = frame ? await waitUploadStatus(frame, names) : {};
      if (status.securityLimit) await pauseForUploadSecurityLimit(status, names);
      if ((status.failedNames || []).length && (status.retryable || status.networkError)) {
        retried = await retryUntilUploaded(frame, files, names, 0);
      } else {
        retried = {
          status,
          complete: await waitUploadResultClosed(),
          failedNames: status.failedNames || [],
          retryable: !!(status.retryable || status.networkError),
          uploaded: !((status.failedNames || []).length),
        };
      }
    }
    const listed = frame ? await listPictureSpaceNames(frame) : [];
    // Uploading new files can push a previously reused asset off the current
    // page. Search by content identity before declaring it missing.
    const stillMissing = await missingSucaiNames(frame, names, 5);
    return JSON.stringify({
      ...retried,
      uploaded: !!frame && retried.uploaded === true && !stillMissing.length
        && retried.complete === "CLOSED",
      listed: listed.slice(0, 20),
      missing: stillMissing,
      failedNames: retried.failedNames || stillMissing,
      hadFrame: !!frame,
    });
  }

  await waitUploadResultClosed();
  let frame = await openPictureSpace();
  if (!frame) return JSON.stringify({ error: "NO_FRAME", selected: [] });
  await assertNoSecurityChallenge();
  await clearPictureSpaceSelection(frame);
  const picked = [];
  let confirm = "NO";
  let after = { imgs: 0, dialog: true };

  async function commitSelection(currentFrame) {
    let currentConfirm = "NO";
    let currentAfter = { imgs: 0, dialog: true };
    for (let i = 0; i < 4; i++) {
      await assertNoSecurityChallenge();
      currentConfirm = await confirmPictureSpace(currentFrame);
      await sleep(900);
      currentAfter = await editorAfter();
      if (!currentAfter.dialog) break;
    }
    if (!currentAfter.dialog) {
      for (let i = 0; i < 20 && currentAfter.imgs < picked.length; i++) {
        await sleep(500);
        currentAfter = await editorAfter();
      }
    }
    confirm = currentConfirm;
    after = currentAfter;
    if (currentConfirm === "NO" || currentAfter.dialog || currentAfter.imgs !== picked.length) {
      throw new Error(`PAUSE:详情图分段写入未确认（期望 ${picked.length} 张，页面 ${currentAfter.imgs} 张），已保留现场，未继续插入`);
    }
    return currentAfter;
  }

  for (const name of names) {
    let one = (await pickPictureSpaceCards(frame, [name]))[0] || { name, ok: false };
    let search = "NOT_NEEDED";
    if (!one.ok && (!one.reason || one.reason === "not-found")) {
      search = await searchSucai(frame, pictureIdentityQuery(name));
    }
    if (!one.ok && search === "OK") {
      one = (await pickPictureSpaceCards(frame, [name]))[0] || one;
    }
    // The library may deduplicate identical files and expose only one card
    // for two detail positions. Commit the current ordered batch, reopen the
    // picker, and select that same card again so the duplicate is inserted at
    // the correct position instead of being reported as a stale selection.
    const identity = pictureIdentityQuery(name);
    const repeatedContent = /^qn_[a-f0-9]{24}$/i.test(identity)
      && picked.some(item => pictureIdentityQuery(item.name) === identity);
    if (one.alreadySelected && repeatedContent) {
      await commitSelection(frame);
      frame = await openPictureSpace();
      if (!frame) throw new Error("PAUSE:详情图重复素材窗口未能重新打开，已保留当前内容");
      await assertNoSecurityChallenge();
      await clearPictureSpaceSelection(frame);
      one = (await pickPictureSpaceCards(frame, [name]))[0] || { name, ok: false };
      search = "NOT_NEEDED";
      if (!one.ok && (!one.reason || one.reason === "not-found")) {
        search = await searchSucai(frame, pictureIdentityQuery(name));
      }
      if (!one.ok && search === "OK") {
        one = (await pickPictureSpaceCards(frame, [name]))[0] || one;
      }
    }
    // A selection retained outside the current search page has an unknown
    // position in the picker queue. Never confirm it as correctly ordered.
    if (!one.ok || one.alreadySelected) {
      const reason = one.alreadySelected ? "存在顺序未确认的预选" : ({
        "not-found": "当前素材列表未找到目标",
        "unsupported-card": "素材卡片选择控件无法识别",
        "disabled": "素材选择控件被禁用",
        "selection-unconfirmed": "点击后未确认选中，未重复点击",
        "selection-lost": "目标素材在选中确认时消失",
      }[one.reason] || "选择状态未确认");
      throw new Error(`PAUSE:详情图未能按顺序选择 ${name}（${reason}），已保留素材窗口供复核；诊断：${JSON.stringify({selection: one, search, picked: picked.map(item => item.name)})}`);
    }
    picked.push(one);
    await sleep(220);
  }
  await commitSelection(frame);
  if (!after.dialog) {
    for (let i = 0; i < 20 && after.imgs < names.length; i++) {
      await sleep(500);
      after = await editorAfter();
    }
  }
  const confirmationControls = confirm === "NO" ? await frame.evaluate(() => {
    const visible = (el) => {
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 6 && r.height > 6 && s.display !== "none" && s.visibility !== "hidden";
    };
    return [...document.querySelectorAll("button, [role='button'], [class*='footer'], [class*='Footer']")]
      .filter(visible).slice(-18).map((el) => ({
        tag: el.tagName,
        text: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 100),
        className: String(el.className || "").slice(0, 120),
        html: String(el.outerHTML || "").replace(/\s+/g, " ").slice(0, 260),
      }));
  }).catch(() => []) : [];
  return JSON.stringify({ picked, confirm, after, confirmationControls }, null, 2);
}
