async page => {
  /*PAYLOAD*/
  /*HELPERS*/
  return await page.evaluate(() => {
    const visible = (el) => { const r = el.getBoundingClientRect(); const s = getComputedStyle(el); return r.width>0 && r.height>0 && s.display!=="none" && s.visibility!=="hidden"; };
    const label = (el) => (el.innerText || "").replace(/\s+/g, "").trim();
    // 找“款式描述”维度容器：从标题向上找包含排序按钮的块
    const title = [...document.querySelectorAll("span, div")].filter(visible)
      .find((el) => /^款式描述\(\d+\)$/.test(label(el)));
    if (!title) return { found: false };
    // 向上找 3-5 层拿完整区域
    let region = title;
    for (let i = 0; i < 5; i++) {
      if (region.parentElement && (region.parentElement.innerText || "").includes("自定义宝贝规格") === false && region.parentElement !== document.body) {
        region = region.parentElement;
        if ((region.innerText || "").length > 400) break;
      }
    }
    // 用“销售属性”区域：从“销售属性”文本到“一口价”之间
    const all = [...document.querySelectorAll("div")].filter(visible)
      .filter((el) => (el.innerText || "").includes("款式描述(") && (el.innerText || "").includes("添加销售属性") && (el.innerText || "").length < 700);
    const region2 = all.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length)[0];
    const inputs = [...(region2 || region).querySelectorAll("input")].map((el) => ({
      placeholder: el.placeholder || "", value: el.value || "", disabled: el.disabled, cls: String(el.className||"").slice(0,80),
    }));
    const btns = [...(region2 || region).querySelectorAll("button, [role=button], a")].map((el) => ({
      text: label(el).slice(0,20), disabled: el.disabled || false, cls: String(el.className||"").slice(0,80),
    }));
    // 批量导入按钮当前状态
    const importBtn = [...document.querySelectorAll("button")].find((el) => label(el) === "批量导入");
    return {
      found: true,
      regionText: ((region2 || region).innerText || "").replace(/\s+/g, " ").slice(0, 400),
      regionHtml: (region2 || region).outerHTML.slice(0, 3500),
      inputs, btns,
      importBtnDisabled: importBtn ? importBtn.disabled : null,
    };
  });
}
