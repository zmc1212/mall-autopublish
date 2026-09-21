async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await hideScenarioWidgets();
  await installAttrDom();
  const dump = await page.evaluate((extra) => {
    const labels = ["笔头类型", "笔芯颜色", "闭合方式", "风格", "功能", "品牌", "型号", "适用场景", "适用人群", "包装方式", "采购地", "IP联名"];
    const empty = [];
    const items = [];
    const want = extra.want || {};
    const brand = extra.brand || "";
    const model = extra.model || "";
    for (const lab of labels) {
      const info = (window.__qnAttr && window.__qnAttr(lab)) || { found: false };
      if (!info.found) continue;
      items.push((info.wrap || "") + " | " + (info.val || info.tags.join(",") || info.text || "").slice(0, 120));
      const item = window.__qnItem && window.__qnItem(lab);
      const required = !!(item && item.querySelector(".sell-component-info-wrapper-required"));
      if (lab === "品牌" && (info.val || (brand && (info.text || "").includes(brand)) || /keyProps=/.test(location.href))) continue;
      if (lab === "型号" && (info.val || (model && (info.text || "").includes(model)) || /keyProps=/.test(location.href))) continue;
      const target = want[lab] || "";
      const filled = target ? !!(window.__qnCommitted && window.__qnCommitted(lab, target)) : !!(info.val || (info.tags || []).length);
      if (!filled && required) empty.push(lab);
    }
    const group = [...document.querySelectorAll(".next-form-item, .sell-component-info-wrapper, [class*='form-item']")].find((el) => {
      const t = (el.innerText || "").replace(/\s+/g, "");
      return t.includes("上架时间") && t.includes("放入仓库") && t.includes("立刻上架") && t.length < 600;
    });
    const optionOn = (scope, name) => {
      const hit = [...(scope || document).querySelectorAll("label, .next-radio-wrapper, [role='radio'], span, div")].find((el) => (el.innerText || "").replace(/\s+/g, "") === name);
      if (!hit) return false;
      const wrap = hit.closest(".next-radio-wrapper, [role='radio'], label") || hit;
      const input = wrap.querySelector("input[type='radio']")
        || (hit.parentElement && hit.parentElement.querySelector("input[type='radio']"));
      return !!(input && input.checked)
        || /checked/.test(wrap.className || "")
        || wrap.getAttribute("aria-checked") === "true";
    };
    return {
      items,
      banners: [...document.querySelectorAll("span, a, div, li")].map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).filter((t) => t && t.length < 40 && /错误\s*\(\d+\)|必填项未填|不能为空/.test(t) && !t.includes("上架时间")).slice(0, 20),
      empty,
      warehouseOn: optionOn(group, "放入仓库"),
      instantOn: optionOn(group, "立刻上架"),
      pct: ((document.body.innerText || "").match(/已填写\s*\d+%/) || [""])[0],
    };
  }, { brand: PAYLOAD.brand || "", model: PAYLOAD.model || "", want: PAYLOAD.attributes || {} });
  return JSON.stringify(dump, null, 2);
}
