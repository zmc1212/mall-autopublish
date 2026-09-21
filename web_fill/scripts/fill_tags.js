async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  await dismissKnow();
  const pairs = PAYLOAD.tags || [
    ["适用场景", PAYLOAD.scene || "日常书写"],
    ["适用人群", PAYLOAD.crowd || "通用"],
  ];
  const log = [];

  async function pick(label, value) {
    await page.keyboard.press("Escape");
    await sleep(150);
    const already = await page.evaluate(([lab, val]) => {
      const nodes = [...document.querySelectorAll("*")].filter((el) => (el.childNodes.length <= 5) && (el.textContent || "").trim() === lab);
      for (const node of nodes) {
        let root = node.parentElement;
        for (let i = 0; i < 6 && root; i++) {
          const t = (root.innerText || "").replace(/\s+/g, " ");
          if (/不能为空|必填项/.test(t)) return false;
          if (t.includes(val) && t.length < 240) return true;
          root = root.parentElement;
        }
      }
      return false;
    }, [label, value]);
    if (already) return "already";
    const combo = page.getByText(label, { exact: true }).locator("xpath=following::input[@role='combobox'][1]");
    if (await combo.count()) {
      await combo.first().click({ force: true, timeout: 8000 });
      await sleep(500);
    } else {
      await page.evaluate((lab) => {
        const el = [...document.querySelectorAll("*")].find((n) => (n.childNodes.length <= 5) && (n.textContent || "").trim() === lab);
        if (el) {
          const box = el.parentElement && el.parentElement.querySelector("input, .next-select");
          if (box) box.click();
          else el.click();
        }
      }, label);
      await sleep(400);
    }
    let picked = await page.evaluate((want) => {
      const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened, .next-overlay-wrapper")].filter((el) => getComputedStyle(el).display !== "none");
      const wrap = [...wraps].reverse().find((el) => (el.innerText || "").includes(want) && !(el.innerText || "").includes("图文描述")) || wraps[wraps.length - 1];
      if (!wrap) return "NO_WRAP";
      const walker = document.createTreeWalker(wrap, NodeFilter.SHOW_TEXT);
      while (walker.nextNode()) {
        if (walker.currentNode.textContent.trim() === want) {
          const node = walker.currentNode.parentElement;
          const box = node.querySelector("input[type=checkbox]") || node;
          box.click();
          node.click();
          return "CLICKED:" + want;
        }
      }
      return "NO_TEXT:" + (wrap.innerText || "").replace(/\s+/g, " ").slice(0, 160);
    }, value);
    if (String(picked).indexOf("CLICKED") < 0) {
      const visible = page.getByText(value, { exact: true });
      if (await visible.count()) {
        await visible.last().click({ force: true });
        picked = "TEXT:" + value;
      }
    }
    await page.keyboard.press("Escape");
    await sleep(200);
    return picked;
  }

  for (const [label, value] of pairs) {
    try {
      log.push(label + "=" + (await pick(label, value)));
    } catch (err) {
      log.push("FAIL " + label + " " + String(err.message || err).slice(0, 120));
    }
  }
  return JSON.stringify({ log }, null, 2);
}
