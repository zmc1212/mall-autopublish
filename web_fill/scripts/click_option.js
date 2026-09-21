async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const value = PAYLOAD.value || "";
  const item = page.locator(".next-overlay-wrapper.opened .options-item").filter({ hasText: value }).first();
  let picked = "NO_ITEM";
  if (await item.count()) {
    await item.click({ force: true, timeout: 5000 });
    picked = "ITEM";
  } else {
    const info = page.locator(".next-overlay-wrapper.opened .info-content").filter({ hasText: value }).first();
    if (await info.count()) {
      await info.click({ force: true, timeout: 5000 });
      picked = "INFO";
    }
  }
  await sleep(400);
  const confirm = page.locator(".next-overlay-wrapper.opened").getByRole("button", { name: /确定|完成/ });
  let confirmed = "NO";
  if (await confirm.count()) {
    await confirm.last().click({ force: true });
    confirmed = "OK";
    await sleep(300);
  }
  const after = await page.evaluate((want) => {
    const tags = [...document.querySelectorAll("button, span, em")].filter((el) => (el.innerText || "").trim() === want).map((el) => ({
      tag: el.tagName,
      cls: String(el.className).slice(0, 60),
    })).slice(0, 6);
    return tags;
  }, value);
  return JSON.stringify({ value, picked, confirmed, after }, null, 2);
}
