async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  const field = PAYLOAD.field || "#sell-field-mainImagesGroup";
  await dismissKnow();

  if (phase === "open" || phase === "open_library") {
    const clicked = await openMainPicker(field);
    await sleep(1800);
    const frame = await waitFrame(sucaiFrame, 18);
    if (!frame) return JSON.stringify({ clicked, error: "NO_FRAME" });
    if (phase === "open_library") {
      return JSON.stringify({ clicked, pics: await listSucaiPics(frame), names });
    }
    const finished = await finishLocalUpload(frame, files, names);
    return JSON.stringify({ clicked, ...finished, files, names });
  }

  if (phase === "after_upload") {
    const frame = sucaiFrame();
    const retried = await retryUntilUploaded(frame, files, names);
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
    await searchSucai(frame, name.replace(/\.[^.]+$/, ""));
    const pic = await clickSucaiCard(frame, name);
    selected.push({ name, pic });
    await sleep(700);
    await confirmCrop();
  }
  await sleep(600);
  await page.mouse.click(80, 120);
  await sleep(400);
  const slot = await page.evaluate((sel) => {
    const fieldEl = document.querySelector(sel);
    const imgs = fieldEl ? [...fieldEl.querySelectorAll("img")].filter((el) => el.width > 40).length : 0;
    const empty = fieldEl ? fieldEl.querySelectorAll(".image-empty").length : -1;
    return { imgs, empty };
  }, field);
  return JSON.stringify({ selected, slot }, null, 2);
}
