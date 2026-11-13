async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const log = [];
  await hideScenarioWidgets();
  await dismissKnow();

  // 与 attributes.js 同源：模板属性驱动，无模板属性时回退中性笔默认。
  const pairs = qnAttrPairs(PAYLOAD.attributes, [
    ["笔头类型", "子弹头"],
    ["笔芯颜色", "炭黑"],
    ["闭合方式", "按动式"],
    ["风格", "简约"],
    ["功能", "考试专用"],
    ["适用场景", "日常书写"],
    ["适用人群", "通用"],
    ["包装方式", "单支装"],
    ["IP联名", "火影忍者"],
    ["品牌", PAYLOAD.brand || "卡游"],
    ["型号", PAYLOAD.model || "忍道版第1弹"],
  ]);
  for (const [label, value] of pairs) {
    try {
      if (await attrCommitted(label, String(value))) {
        log.push(label + "=already");
        continue;
      }
      log.push(label + "=" + (await pickComboValue(label, String(value))));
    } catch (err) {
      log.push("FAIL " + label + " " + String(err.message || err).slice(0, 140));
      await page.keyboard.press("Escape").catch(() => {});
    }
  }
  return JSON.stringify({ log }, null, 2);
}
