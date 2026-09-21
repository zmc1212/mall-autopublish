async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  await closeDialogsOnly();
  await hideScenarioWidgets();
  await dismissKnow();
  await page.mouse.click(40, 80);
  await sleep(400);
  const warehouse = page.getByRole("radio", { name: "放入仓库" });
  const instant = page.getByRole("radio", { name: "立刻上架" });
  if (!(await warehouse.isChecked())) throw new Error("PAUSE:提交前放入仓库未选中");
  if (await instant.isChecked()) throw new Error("PAUSE:提交前仍是立刻上架");
  const btn = page.locator("#button-submit, button[name='button-submit']").first();
  let clicked = "NO";
  try {
    await btn.click({ force: true, timeout: 8000 });
    clicked = "LOCATOR";
  } catch (e) {
    clicked = await page.evaluate(() => {
      const el = document.querySelector("#button-submit") || document.querySelector("button[name='button-submit']");
      if (!el) return "NO";
      el.dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true, view: window }));
      return "DISPATCH";
    });
  }
  if (clicked === "NO") throw new Error("PAUSE:未找到提交宝贝信息");
  await sleep(8000);
  const after = await page.evaluate(() => {
    const body = (document.body && document.body.innerText) || "";
    const errTab = (body.match(/错误\s*\((\d+)\)/) || [])[1];
    const abs = (href) => {
      try { return new URL(href, location.href).href; } catch (e) { return ""; }
    };
    const labeledHref = (name) => {
      const nodes = [...document.querySelectorAll("a, button, [role='link']")];
      const el = nodes.find((n) => ((n.innerText || "").replace(/\s+/g, "")).includes(name.replace(/\s+/g, "")));
      if (!el) return "";
      const href = el.href || el.getAttribute("href") || el.getAttribute("data-href") || el.getAttribute("data-url") || "";
      const url = abs(href);
      if (!url || /^(javascript:|data:|file:)/i.test(url)) return "";
      return url;
    };
    const params = new URLSearchParams(location.search);
    const fromText = (body.match(/商品ID[:：]\s*(\d{8,})/) || [])[1] || "";
    let viewUrl = labeledHref("查看商品");
    let editUrl = labeledHref("编辑商品");
    if (!viewUrl) {
      const hit = [...document.querySelectorAll("a[href]")].find((a) => /item\.taobao\.com\/item\.htm|item\.tmall\.com|detail\.tmall\.com/i.test(a.href));
      if (hit) viewUrl = hit.href;
    }
    if (!editUrl) {
      const hit = [...document.querySelectorAll("a[href]")].find((a) => /itemid=/i.test(a.href) && /publish\.htm|edit\.htm/i.test(a.href));
      if (hit) editUrl = hit.href;
    }
    const timeError = [...document.querySelectorAll(".next-form-item, .sell-component-info-wrapper")].some((el) => {
      const t = (el.innerText || "").replace(/\s+/g, "");
      if (!(t.includes("上架时间") && t.includes("放入仓库") && t.length < 600)) return false;
      const on = [...el.querySelectorAll("label, .next-radio-wrapper, [role='radio']")].some((node) => {
        if ((node.innerText || "").replace(/\s+/g, "") !== "放入仓库") return false;
        const wrap = node.closest(".next-radio-wrapper, [role='radio'], label") || node;
        const input = wrap.querySelector("input[type='radio']");
        return (input && input.checked) || /checked/.test(wrap.className || "") || wrap.getAttribute("aria-checked") === "true";
      });
      return !on;
    });
    const snippets = [];
    const err = (body.match(/错误\s*\(\d+\)/) || [])[0];
    if (err) snippets.push(err.replace(/\s+/g, ""));
    const required = (body.match(/\d+\s*商品属性必填项未填/) || body.match(/必填项未填/) || [])[0];
    if (required) snippets.push(required.replace(/\s+/g, " ").trim());
    if (timeError) snippets.push("上架时间未选择");
    const successHit = (body.match(/商品提交成功[^。]{0,40}/) || body.match(/商品ID[:：]\s*\d{8,}/) || [])[0];
    if (successHit) snippets.push(successHit.replace(/\s+/g, " ").trim());
    const notice = snippets.join("；").slice(0, 240);
    const hasSuccess = /发布成功|提交成功|已经提交到仓库|已放入仓库|入库成功|success\.htm/.test(body) || /itemid=/i.test(location.href) || /sell\/success/i.test(location.href);
    const hasFail = /必填项未填|不能为空/.test(body) || (errTab && errTab !== "0") || timeError;
    return {
      href: location.href,
      notice,
      text: notice || (hasFail ? "提交失败" : body.replace(/\s+/g, " ").slice(0, 120)),
      errTab: errTab || "",
      itemId: params.get("primaryId") || params.get("itemId") || fromText || "",
      catId: params.get("catId") || "",
      viewUrl,
      editUrl,
      hasSuccess,
      hasFail,
    };
  });
  return JSON.stringify(after, null, 2);
}
