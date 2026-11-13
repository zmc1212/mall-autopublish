async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const NAME = String(PAYLOAD.name || "单个随机盲盒");
  // 在款式描述维度(#struct-p-1627207)第一个空行输入规格名
  const box = page.locator('#struct-p-1627207 input[placeholder="主色(必选)"]').first();
  if (!(await box.count())) return JSON.stringify({ error: "NO_INPUT" });
  await box.scrollIntoViewIfNeeded();
  await box.click({ force: true, timeout: 3000 }).catch(() => {});
  await box.fill(NAME);
  await sleep(400);
  const afterFill = await page.evaluate((want) => {
    const input = document.querySelector('#struct-p-1627207 input[placeholder="主色(必选)"]');
    const region = document.querySelector("#struct-p-1627207");
    const suggest = [...document.querySelectorAll("ul.color-suggest-wrapper, .color-suggest-wrapper")].filter((el) => el.getBoundingClientRect().width > 0)
      .map((el) => [...el.querySelectorAll("li")].map((li) => (li.innerText || "").trim()).slice(0, 12));
    const importBtn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "批量导入");
    const addBtn = region && region.querySelector("button.add");
    return {
      value: input && input.value,
      match: !!(input && input.value === want),
      suggest,
      addDisabled: addBtn ? addBtn.disabled : null,
      importDisabled: importBtn ? importBtn.disabled : null,
      warning: (region && region.querySelector(".warning-text") && region.querySelector(".warning-text").innerText) || "",
    };
  }, NAME);
  await page.keyboard.press("Enter").catch(() => {});
  await sleep(400);
  await page.keyboard.press("Tab").catch(() => {});
  await sleep(600);
  const afterCommit = await page.evaluate(() => {
    const region = document.querySelector("#struct-p-1627207");
    const input = document.querySelector('#struct-p-1627207 input[placeholder="主色(必选)"]');
    const importBtn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "批量导入");
    const addBtn = region && region.querySelector("button.add");
    const suggest = [...document.querySelectorAll("ul.color-suggest-wrapper, .color-suggest-wrapper")].filter((el) => el.getBoundingClientRect().width > 0)
      .map((el) => [...el.querySelectorAll("li")].map((li) => (li.innerText || "").trim()).slice(0, 12));
    const tableRows = [...document.querySelectorAll("table tr")].map((tr) => (tr.innerText || "").replace(/\s+/g, " ").trim().slice(0, 100)).slice(0, 8);
    return {
      value: input && input.value,
      addDisabled: addBtn ? addBtn.disabled : null,
      importDisabled: importBtn ? importBtn.disabled : null,
      suggest, tableRows,
      warning: (region && region.querySelector(".warning-text") && region.querySelector(".warning-text").innerText) || "",
    };
  });
  return JSON.stringify({ name: NAME, afterFill, afterCommit }, null, 1);
}
