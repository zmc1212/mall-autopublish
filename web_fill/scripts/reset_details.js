async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const names = PAYLOAD.names || [];
  const phase = PAYLOAD.phase || "clear";
  await dismissKnow();

  if (phase === "clear") {
    const cleared = await page.evaluate(() => {
      const lite = document.querySelector("#lite-decoration-editor") || document.querySelector(".sell-component-lite-decoration-editor");
      const scope = lite || document;
      const btn = [...scope.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "清空");
      if (!btn) return "NO_CLEAR";
      btn.scrollIntoView({ block: "center" });
      btn.click();
      return "CLICK";
    });
    await sleep(500);
    const ok = page.getByRole("button", { name: "确定" }).or(page.getByRole("button", { name: "确认" }));
    if (await ok.count()) await ok.last().click({ force: true }).catch(() => {});
    await sleep(600);
    return JSON.stringify({ cleared });
  }

  const clicked = await page.evaluate(() => {
    const lite = document.querySelector("#lite-decoration-editor") || document;
    const el = [...lite.querySelectorAll(".m-editor-content-footer-add, .add_item-NH_hk3, button, div")].find((n) => (n.innerText || "").trim() === "图片" && n.offsetWidth > 0);
    if (!el) return false;
    el.scrollIntoView({ block: "center" });
    el.click();
    return true;
  });
  await sleep(1800);
  const frame = await waitFrame(wangpuFrame, 18);
  if (!frame) {
    const sucai = sucaiFrame() || await waitFrame(sucaiFrame, 8);
    if (sucai) {
      const picked = [];
      for (const name of names) {
        const searched = await searchSucai(sucai, name.replace(/\.[^.]+$/, ""));
        const pic = String(searched).startsWith("STALE") ? { ok: false } : await clickSucaiCard(sucai, name);
        picked.push({ name, searched, pic });
        await sleep(250);
      }
      const confirm = await sucai.evaluate(() => {
        const btn = [...document.querySelectorAll("button")].find((el) => /确认|确定/.test(el.innerText || ""));
        if (!btn) return "NO";
        btn.click();
        return "OK";
      });
      return JSON.stringify({ clicked, via: "sucai", picked, confirm }, null, 2);
    }
    return JSON.stringify({ clicked, error: "NO_FRAME" });
  }
  const picked = [];
  for (const name of names) {
    const one = await frame.evaluate((file) => {
      const card = [...document.querySelectorAll(".item.pic")].find((n) => (n.innerText || "").includes(file));
      if (!card) return { name: file, ok: false };
      const icon = card.querySelector(".select-icon") || card.querySelector(".cover") || card;
      icon.click();
      return { name: file, ok: true, cls: String(card.className) };
    }, name);
    picked.push(one);
    await sleep(220);
  }
  const confirm = await frame.evaluate(() => {
    const btn = document.querySelector(".btn.btn-blue") || [...document.querySelectorAll(".btn, button")].find((el) => (el.innerText || "").trim() === "确认");
    if (!btn) return "NO";
    btn.click();
    return "OK";
  });
  await sleep(1600);
  return JSON.stringify({ clicked, via: "wangpu", picked, confirm }, null, 2);
}
