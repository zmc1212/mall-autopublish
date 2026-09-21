async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const names = PAYLOAD.names || [];
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  await dismissKnow();

  async function ensureFrame() {
    let frame = sucaiFrame();
    if (frame) return frame;
    await openMainPicker(field);
    await sleep(1600);
    frame = await waitFrame(sucaiFrame, 18);
    await waitUploadResultClosed();
    if (frame && !(await frame.locator("input[placeholder*='搜索'], input[type=search]").count())) {
      await waitUploadResultClosed();
      await sleep(400);
      frame = sucaiFrame() || frame;
    }
    return frame;
  }

  let frame = await ensureFrame();
  if (!frame) return JSON.stringify({ error: "NO_FRAME" });

  const existing = await page.evaluate((sel) => {
    const fieldEl = document.querySelector(sel);
    return fieldEl ? [...fieldEl.querySelectorAll("img")].map((el) => (el.alt || el.src || "")).join(" ") : "";
  }, field);

  const selected = [];
  for (const name of names) {
    const stem = name.replace(/\.[^.]+$/, "");
    if (existing.includes(name) || existing.includes(stem)) {
      selected.push({ name, skipped: "already" });
      continue;
    }
    frame = await ensureFrame();
    if (!frame) {
      selected.push({ name, error: "NO_FRAME" });
      break;
    }
    let searched = await searchSucai(frame, stem);
    if (String(searched).startsWith("STALE")) {
      await sleep(800);
      searched = await searchSucai(frame, stem);
    }
    if (String(searched).startsWith("STALE")) {
      selected.push({ name, searched, pic: { ok: false } });
      continue;
    }
    const pic = await clickSucaiCard(frame, name);
    selected.push({ name, searched, pic });
    await sleep(700);
    await confirmCrop();
    await sleep(400);
  }
  await sleep(400);
  await page.mouse.click(40, 80);
  await sleep(300);
  const slot = await page.evaluate((sel) => {
    const fieldEl = document.querySelector(sel);
    const imgs = fieldEl ? [...fieldEl.querySelectorAll("img")].filter((el) => el.width > 40).length : 0;
    const empty = fieldEl ? fieldEl.querySelectorAll(".image-empty").length : -1;
    const alts = fieldEl ? [...fieldEl.querySelectorAll("img")].filter((el) => el.width > 40).map((el) => el.alt || "") : [];
    return { imgs, empty, alts };
  }, field);
  return JSON.stringify({ selected, slot }, null, 2);
}
