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

  const attrs = PAYLOAD.attributes || {};
  const pairs = [
    ["笔头类型", attrs["笔头类型"] || "子弹头"],
    ["笔芯颜色", attrs["笔芯颜色"] || "炭黑"],
    ["闭合方式", attrs["闭合方式"] || "按动式"],
    ["风格", attrs["风格"] || "简约"],
    ["功能", attrs["功能"] || "考试专用"],
    ["适用场景", attrs["适用场景"] || "日常书写"],
    ["适用人群", attrs["适用人群"] || "通用"],
    ["包装方式", attrs["包装方式"] || "单支装"],
    ["采购地", attrs["采购地"] || "中国内地（大陆）"],
    ["IP联名", attrs["IP联名"] || ""],
  ];
  const log = [];
  const missing = [];
  for (const [label, value] of pairs) {
    if (!value) continue;
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
