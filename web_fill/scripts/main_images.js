async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  if (phase === "slot_count") {
    // 只读复核：与 bind 阶段完全相同的口径重读主图位。页面异步插入缩略图
    // 时 bind 阶段的读数可能偏少，这里给渲染留出额外的追赶窗口。
    let slot = { imgs: 0, empty: -1 };
    for (let i = 0; i < 24; i++) {
      slot = await page.evaluate((sel) => {
        const fieldEl = document.querySelector(sel);
        const imgs = fieldEl ? [...fieldEl.querySelectorAll("img")].filter((el) => el.width > 40).length : 0;
        const empty = fieldEl ? fieldEl.querySelectorAll(".image-empty").length : -1;
        return { imgs, empty };
      }, field);
      if (slot.imgs >= names.length) break;
      await sleep(500);
    }
    return JSON.stringify({ slot, names });
  }
  // The same picker survives upload -> receipt -> binding. Escape closes it
  // asynchronously, leaving a soon-to-detach Frame in page.frames().
  await dismissKnow({ escape: false });

  if (phase === "open" || phase === "open_library") {
    const clicked = await openMainPicker(field);
    await sleep(1800);
    const frame = await waitFrame(sucaiFrame, 18);
    if (!frame) return JSON.stringify({ clicked, error: "NO_FRAME" });
    if (phase === "open_library") {
      return JSON.stringify({ clicked, pics: await listSucaiPics(frame), names });
    }
    // Only content-addressed names are safe to reuse across products. Generic
    // names such as 宝贝主图01.jpg can refer to a completely different item.
    const reusable = PAYLOAD.contentAddressedMedia === true
      && names.every(name => /^qn_[0-9a-f]{24}_/.test(name));
    const missing = reusable ? missingPictureNames(await listSucaiPics(frame), names) : names;
    if (!missing.length) return JSON.stringify({clicked, uploaded: true, via: "library",
      missing, files, names});
    if (PAYLOAD.libraryOnly) return JSON.stringify({uploaded: false,
      error: "MISSING_LIBRARY_IMAGES", missing, files, names});
    const targetFiles = reusable ? filesForNames(files, missing) : files;
    const finished = await finishLocalUpload(frame, targetFiles, missing, PAYLOAD);
    return JSON.stringify({ clicked, ...finished, files, names });
  }

  if (phase === "after_upload") {
    const frame = sucaiFrame();
    if (frame && !(await hasUploadResult())) {
      const missing = await missingSucaiNames(frame, names, 5);
      if (!missing.length) {
        return JSON.stringify({ uploaded: true, verifiedBy: "library-search", complete: "CLOSED",
          missing, hadFrame: true });
      }
    }
    const retried = await retryUntilUploaded(frame, files, names, 0);
    return JSON.stringify({ ...retried, hadFrame: !!frame });
  }

  await waitUploadResultClosed();
  let frame = sucaiFrame();
  if (!frame) {
    await openMainPicker(field);
    await sleep(1600);
    frame = await waitFrame(sucaiFrame, 18);
  }
  if (!frame) return JSON.stringify({ error: "NO_FRAME", selected: [] });
  const done = await waitUploadResultClosed();
  await sleep(400);
  const selected = [];
  for (const name of names) {
    let pic = await clickSucaiCard(frame, name, true);
    if (!pic.ok) {
      await searchSucai(frame, name.replace(/\.[^.]+$/, ""));
      pic = await clickSucaiCard(frame, name, true);
    }
    selected.push({ name, pic });
    await sleep(700);
    await confirmCrop();
  }
  await sleep(600);
  await page.mouse.click(80, 120);
  // 缩略图是异步插入/加载的，width 从 0 到正常有延迟；数量仍在增长时必须
  // 继续等，否则会把已写入的图误报成缺图（2026-10-02 客户机真实复现：
  // 图片包 5 张页面读到 4 张，数秒后 probe 却读到 5 张）。
  let slot = { imgs: 0, empty: -1 };
  let previous = -1;
  let stale = 0;
  for (let i = 0; i < 60; i++) {
    slot = await page.evaluate((sel) => {
      const fieldEl = document.querySelector(sel);
      const imgs = fieldEl ? [...fieldEl.querySelectorAll("img")].filter((el) => el.width > 40).length : 0;
      const empty = fieldEl ? fieldEl.querySelectorAll(".image-empty").length : -1;
      return { imgs, empty };
    }, field);
    if (slot.imgs >= names.length) break;
    stale = slot.imgs === previous ? stale + 1 : 0;
    previous = slot.imgs;
    if (stale >= 16) break; // 连续 8 秒数量无增长：判定为真实缺失，不再空等
    await sleep(500);
  }
  return JSON.stringify({ selected, slot }, null, 2);
}
