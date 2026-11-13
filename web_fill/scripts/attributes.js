async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  try { page.setDefaultTimeout(2500); } catch (e) {}
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  if (!/\/sell\/v2\/publish\.htm/i.test(page.url())) throw new Error("PAUSE:当前不在新建发布页: " + page.url());
  await dismissKnow();
  await installAttrDom();
  for (let i = 0; i < 20; i++) {
    const n = await page.evaluate(() => document.querySelectorAll(".sell-component-info-wrapper-label, .next-form-item-label").length);
    if (n >= 6) break;
    await sleep(400);
  }

  const title = PAYLOAD.title || "";
  if (title) {
    const titleBox = page.getByRole("textbox", { name: "最多允许输入30个汉字（60字符）" });
    if (await titleBox.count()) {
      await titleBox.click({ force: true, timeout: 2000 }).catch(() => {});
      await titleBox.fill(title).catch(() => {});
    }
  }
  if (PAYLOAD.guide_title) {
    const guide = page.getByRole("textbox", { name: "最多输入30字符（15个汉字）" });
    if (await guide.count()) await guide.fill(PAYLOAD.guide_title).catch(() => {});
  }

  // 属性由分类模板驱动（templates/attributes/*.json）：模板定义什么就填什么，
  // 数组值=多选属性逐值勾选。无模板属性时回退中性笔默认，兼容老清单。
  const pairs = qnAttrPairs(PAYLOAD.attributes, [
    ["笔头类型", "子弹头"],
    ["笔芯颜色", "炭黑"],
    ["闭合方式", "按动式"],
    ["风格", "简约"],
    ["功能", "考试专用"],
    ["适用场景", "日常书写"],
    ["适用人群", "通用"],
    ["包装方式", "单支装"],
    ["采购地", "中国内地（大陆）"],
    ["IP联名", ""],
  ]);
  const log = [];
  const missing = [];
  // 浏览器侧共用：属性条目内第一个可见、非下拉的文本输入框。evaluate 无法
  // 带闭包，过滤条件以源码内联进两段浏览器代码，改动时需同步。
  const FIND_INPUT_SRC = `const item = window.__qnItem && window.__qnItem(lab);
      if (!item) return null;
      return [...item.querySelectorAll("input, textarea")].find((el) => {
        const type = String(el.type || "").toLowerCase();
        if (["checkbox", "radio", "hidden", "file"].includes(type)) return false;
        if (el.getAttribute("role") === "combobox") return false;
        if (el.closest(".next-overlay-wrapper")) return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }) || null;`;
  async function plainInputValue(label) {
    return page.evaluate(([lab, findSrc]) => {
      const find = new Function("lab", findSrc);
      const input = find(lab);
      return input ? String(input.value || "").trim() : "";
    }, [label, FIND_INPUT_SRC]);
  }
  async function fillPlainInput(label, value) {
    return page.evaluate(([lab, val, findSrc]) => {
      const input = new Function("lab", findSrc)(lab);
      if (!input) return input === null ? "NO_INPUT" : "NO_ITEM";
      input.focus();
      const proto = input.tagName === "TEXTAREA" ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
      const desc = Object.getOwnPropertyDescriptor(proto, "value");
      if (desc && desc.set) desc.set.call(input, val);
      else input.value = val;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
      return "FILLED";
    }, [label, value, FIND_INPUT_SRC]);
  }
  for (const [label, value] of pairs) {
    if (!value) continue;
    const info = await page.evaluate((lab) => (window.__qnAttr ? window.__qnAttr(lab) : { found: false }), label);
    // 没有下拉/搜索输入的纯文本属性（如尺寸、概率描述）：直接写输入框，
    // pickComboValue 找不到 combobox 会直接放弃。
    if (info && info.found && !info.hasCombo
        && await fillPlainInput(label, String(value)) === "FILLED") {
      let committed = await plainInputValue(label);
      if (committed !== String(value)) {
        await fillPlainInput(label, String(value));
        committed = await plainInputValue(label);
      }
      log.push(label + "=text:" + (committed === String(value) ? "stuck" : "lost"));
      if (committed !== String(value)) missing.push(label + "=" + value);
      continue;
    }
    if (await attrCommitted(label, String(value))) { log.push(label + "=already"); continue; }
    let how = await pickComboValue(label, String(value));
    if (/:lost|NO_COMBO|NO_WRAP/.test(String(how)) && !/:skip/.test(String(how)) && !(await attrCommitted(label, String(value)))) {
      how = await pickComboValue(label, String(value));
    }
    log.push(label + "=" + how);
    if (!(await attrCommitted(label, String(value)))) missing.push(label + "=" + value);
  }
  await dismissBlockingDialogs();
  await page.keyboard.press("Escape").catch(() => {});
  await sleep(250);
  return JSON.stringify({ title, log, missing, href: page.url() });
}
