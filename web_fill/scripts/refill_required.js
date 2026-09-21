async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (unsafeUrl(page.url())) throw new Error("UNSAFE:" + page.url());
  const log = [];
  await hideScenarioWidgets();
  await dismissKnow();

  const pairs = [
    ["笔头类型", (PAYLOAD.attributes && PAYLOAD.attributes["笔头类型"]) || "子弹头"],
    ["笔芯颜色", (PAYLOAD.attributes && PAYLOAD.attributes["笔芯颜色"]) || "炭黑"],
    ["闭合方式", (PAYLOAD.attributes && PAYLOAD.attributes["闭合方式"]) || "按动式"],
    ["风格", (PAYLOAD.attributes && PAYLOAD.attributes["风格"]) || "简约"],
    ["功能", (PAYLOAD.attributes && PAYLOAD.attributes["功能"]) || "考试专用"],
    ["适用场景", (PAYLOAD.attributes && PAYLOAD.attributes["适用场景"]) || "日常书写"],
    ["适用人群", (PAYLOAD.attributes && PAYLOAD.attributes["适用人群"]) || "通用"],
    ["包装方式", (PAYLOAD.attributes && PAYLOAD.attributes["包装方式"]) || "单支装"],
    ["IP联名", (PAYLOAD.attributes && PAYLOAD.attributes["IP联名"]) || "火影忍者"],
    ["品牌", (PAYLOAD.attributes && PAYLOAD.attributes["品牌"]) || PAYLOAD.brand || "卡游"],
    ["型号", (PAYLOAD.attributes && PAYLOAD.attributes["型号"]) || PAYLOAD.model || "忍道版第1弹"],
  ];
  for (const [label, value] of pairs) {
    try {
      log.push(label + "=" + (await pickComboValue(label, value)));
    } catch (err) {
      log.push("FAIL " + label + " " + String(err.message || err).slice(0, 140));
      await page.keyboard.press("Escape").catch(() => {});
    }
  }
  return JSON.stringify({ log }, null, 2);
}
