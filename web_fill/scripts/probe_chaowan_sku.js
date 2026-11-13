async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await hideScenarioWidgets();
  const info = await page.evaluate(() => {
    const visible = (el) => {
      const rect = el.getBoundingClientRect();
      const style = getComputedStyle(el);
      return rect.width > 0 && rect.height > 0 && style.display !== "none" && style.visibility !== "hidden";
    };
    const label = (el) => (el.innerText || "").replace(/\s+/g, " ").trim();
    const buttons = [...document.querySelectorAll("button, a, [role=button]")]
      .filter(visible)
      .map((el) => ({ text: label(el).slice(0, 40), tag: el.tagName, cls: String(el.className || "").slice(0, 60) }))
      .filter((item) => item.text);
    // 找"销售信息"标题及其后 800 字文本
    const bodyText = (document.body.innerText || "").replace(/\s+/g, " ");
    const saleIdx = bodyText.indexOf("销售信息");
    const saleChunk = saleIdx >= 0 ? bodyText.slice(saleIdx, saleIdx + 1200) : "(未找到销售信息)";
    // 表格表头
    const headers = [...document.querySelectorAll("table thead th, table thead td")]
      .map((th) => label(th)).filter(Boolean);
    // SKU 抽屉
    const drawer = document.querySelector(".sku-decouple-drawer");
    const drawerText = drawer ? label(drawer).slice(0, 400) : null;
    // 含"规格"的可见短文本元素（候选入口）
    const specEls = [...document.querySelectorAll("button, a, span, div")]
      .filter(visible)
      .filter((el) => /规格|SKU/.test(label(el)) && label(el).length <= 16)
      .map((el) => ({ text: label(el), tag: el.tagName }))
      .slice(0, 40);
    // 输入规格 输入框
    const specInputs = [...document.querySelectorAll("input")]
      .filter((el) => /规格/.test(el.placeholder || ""))
      .map((el) => ({ placeholder: el.placeholder, value: el.value }));
    // 弹窗
    const dialogs = [...document.querySelectorAll(".next-dialog, [role=dialog]")]
      .filter(visible)
      .map((el) => label(el).slice(0, 200));
    return {
      url: location.href.slice(0, 120),
      buttons: buttons.slice(0, 60),
      saleChunk,
      headers,
      drawerText,
      specEls,
      specInputs,
      dialogs,
      bodyHint: bodyText.slice(0, 300),
    };
  });
  return JSON.stringify(info, null, 1);
}
