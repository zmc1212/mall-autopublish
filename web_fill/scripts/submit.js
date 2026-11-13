async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const warehouse = page.getByRole("radio", { name: "放入仓库", includeHidden: true });
  const instant = page.getByRole("radio", { name: "立刻上架", includeHidden: true });
  if (!(await warehouse.isChecked())) throw new Error("PAUSE:提交前放入仓库未选中");
  if (await instant.isChecked()) throw new Error("PAUSE:提交前仍是立刻上架");
  // 提交前最后一道数值闸：物流/仓库步骤的表单重渲染可能重置价格或库存
  // 单元格（库存 0 不是必填错误，probe_errors 拦不住），回读不符则重填，
  // 仍不符则暂停，避免提交出库存为 0 的商品。
  const valueMismatch = await verifySkuTableValues(page, PAYLOAD.skus || []);
  if (valueMismatch.length) {
    throw new Error("PAUSE:提交前规格表价格或库存与输入不一致（"
      + valueMismatch.map((item) => item.name + ": " + (item.got || "空") + "≠" + item.want).join("；")
      + "）");
  }
  const attributeUpdates = [];
  const attributePolicy = {preserveExisting: !!PAYLOAD.repairItemId};
  const pendingUpdate = await confirmProductAttributeUpdate(attributePolicy);
  if (pendingUpdate) attributeUpdates.push(pendingUpdate);
  else {
    await closeDialogsOnly();
    await hideScenarioWidgets();
    await dismissKnow();
    await page.mouse.click(40, 80);
    await sleep(400);
    const btn = page.locator("#button-submit, button[name='button-submit']");
    if (await btn.count() !== 1) throw new Error("PAUSE:未找到唯一提交宝贝信息按钮");
    try {
      await btn.click({ timeout: 8000 });
    } catch (e) {
      // The click may have reached the server even if Playwright timed out.
      // Keep the persisted submit checkpoint instead of dispatching again.
      throw new Error("PAUSE:提交结果待核实，未重复点击：" + String(e).slice(0, 200));
    }
  }
  // An existing confirmation is already part of an in-flight submission.
  // Confirm it without clicking the outer submit button a second time.
  if (pendingUpdate) await sleep(8000);
  else for (let poll = 0; poll < 20; poll++) {
    await sleep(400);
    const update = await confirmProductAttributeUpdate(attributePolicy);
    if (update) {
      attributeUpdates.push(update);
      await sleep(8000);
      break;
    }
  }
  const readOutcome = () => page.evaluate(() => {
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
    const pendingAttributeUpdate = [...document.querySelectorAll('.next-dialog, [role="dialog"], [role="alertdialog"]')]
      .some(el => el.getBoundingClientRect().height > 0 && getComputedStyle(el).visibility !== 'hidden'
        && (el.innerText || '').includes('商品属性信息更新确定'));
    if (pendingAttributeUpdate) snippets.push('商品属性更新弹窗仍未完成，保存结果待核实');
    const notice = snippets.join("；").slice(0, 240);
    const hasSuccess = /发布成功|提交成功|已经提交到仓库|已放入仓库|入库成功/.test(body) || /\/sell\/(?:v2\/)?success\.htm/i.test(location.href);
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
      pendingAttributeUpdate,
    };
  });
  // Confirmation closes before a slow save redirects. Observe the outcome;
  // never dispatch the outer submit or a second attribute confirmation here.
  const observeOutcome = async () => {
    try { return await readOutcome(); }
    catch (error) {
      if (!/Execution context was destroyed|Cannot find context|because of a navigation/i.test(String(error))) throw error;
      return {href: page.url(), hasSuccess: false, hasFail: false};
    }
  };
  let after = await observeOutcome();
  for (let poll = 0; poll < 30 && !after.hasSuccess && !after.hasFail && !after.pendingAttributeUpdate; poll++) {
    await sleep(400);
    after = await observeOutcome();
  }
  return JSON.stringify({ ...after, attributeUpdates }, null, 2);
}
