async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const phase = PAYLOAD.phase || "open";
  const files = PAYLOAD.files || [];
  const names = PAYLOAD.names || files.map((p) => String(p).split(/[\\/]/).pop());
  await dismissKnow();

  async function pictureSpaceVisible() {
    return page.evaluate(() => /图片空间/.test((document.body && document.body.innerText) || ""));
  }

  async function openPictureSpace() {
    let frame = pictureSpaceFrame();
    if (frame) return frame;
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
    frame = pictureSpaceFrame() || await waitFrame(pictureSpaceFrame, 18);
    if (frame) return frame;
    if (await pictureSpaceVisible()) return page;
    return null;
  }

  async function editorAfter() {
    return page.evaluate(() => {
      const imgs = [...document.querySelectorAll("#newDesc-card img, #sell-field-descRepublicOfSell img, .sell-component-lite-decoration-editor img")].filter((el) => el.width > 80).length;
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

  if (phase === "open" || phase === "open_library") {
    const frame = await openPictureSpace();
    if (!frame) return JSON.stringify({ error: "NO_FRAME", need_cli_upload: false });
    const listed = await listPictureSpaceNames(frame);
    const missing = missingPictureNames(listed, names);
    if (phase === "open_library") {
      return JSON.stringify({ pics: listed.slice(0, 40), names, missing, dialog: true });
    }
    if (!missing.length) {
      return JSON.stringify({ uploaded: true, already: listed.slice(0, 20), missing, files, names, via: "library" });
    }
    const toUpload = filesForNames(files, missing);
    const setFiles = await setFilesAnywhere(toUpload.length ? toUpload : files);
    if (setFiles === "OK") {
      const retried = await retryUntilUploaded(frame, toUpload.length ? toUpload : files, missing);
      return JSON.stringify({ setFiles, via: "hidden-input", files, names, missing, ...retried });
    }
    return JSON.stringify({
      uploaded: false,
      need_cli_upload: true,
      setFiles,
      missing,
      listed: listed.slice(0, 20),
      files,
      names,
    });
  }

  if (phase === "after_upload") {
    const frame = pictureSpaceFrame() || ((await pictureSpaceVisible()) ? page : null);
    let retried = { status: {}, complete: "SKIP", uploaded: true };
    if (await hasUploadResult()) {
      retried = await retryUntilUploaded(frame, files, names);
    } else {
      const status = frame ? await waitUploadStatus(frame, names) : {};
      if ((status.failedNames || []).length && (status.retryable || status.networkError)) {
        retried = await retryUntilUploaded(frame, files, names);
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
    const stillMissing = missingPictureNames(listed, names);
    return JSON.stringify({
      ...retried,
      listed: listed.slice(0, 20),
      missing: stillMissing,
      failedNames: retried.failedNames || stillMissing,
      hadFrame: !!frame,
    });
  }

  await waitUploadResultClosed();
  const frame = await openPictureSpace();
  if (!frame) return JSON.stringify({ error: "NO_FRAME", selected: [] });
  const picked = [];
  for (const name of names) {
    const one = (await pickPictureSpaceCards(frame, [name]))[0] || { name, ok: false };
    picked.push(one);
    await sleep(220);
  }
  let confirm = "NO";
  let after = { imgs: 0, dialog: true };
  for (let i = 0; i < 4; i++) {
    confirm = await confirmPictureSpace(frame);
    await sleep(900);
    after = await editorAfter();
    if (!after.dialog) break;
  }
  return JSON.stringify({ picked, confirm, after }, null, 2);
}
