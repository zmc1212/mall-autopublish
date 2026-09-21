async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const id = PAYLOAD.allow_item_id || "1085558349142";
  const href = page.url();
  if (href.includes(id) && /publish\.htm/i.test(href)) {
    return JSON.stringify({ already: true, href });
  }
  if (/success\.htm/i.test(href) && href.includes(id)) {
    const edit = page.getByRole("link", { name: "编辑商品" }).or(page.getByRole("button", { name: "编辑商品" }));
    if (await edit.count()) {
      await edit.first().click({ force: true, timeout: 8000 });
    } else {
      await page.evaluate(() => {
        const el = [...document.querySelectorAll("a, button")].find((n) => (n.innerText || "").trim() === "编辑商品");
        if (el) el.click();
      });
    }
    for (let i = 0; i < 25; i++) {
      await sleep(400);
      if (page.url().includes(id) && /publish\.htm/i.test(page.url())) break;
    }
    return JSON.stringify({ opened: true, href: page.url() });
  }
  throw new Error("PAUSE:当前不是卡游成功页或编辑页: " + href);
}
