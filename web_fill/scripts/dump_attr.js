async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const labels = PAYLOAD.labels || ["适用场景", "适用人群", "包装方式", "采购地", "IP联名"];
  const dump = await page.evaluate((labs) => {
    function chain(el) {
      const out = [];
      let n = el;
      for (let i = 0; i < 10 && n && n !== document.body; i++) {
        const combos = n.querySelectorAll ? n.querySelectorAll("input[role='combobox'], [role='combobox']").length : 0;
        out.push({
          tag: n.tagName,
          cls: String(n.className || "").slice(0, 120),
          text: (n.innerText || "").replace(/\s+/g, " ").trim().slice(0, 80),
          combos,
          children: n.children ? n.children.length : 0,
        });
        n = n.parentElement;
      }
      return out;
    }
    return labs.map((lab) => {
      const hit = [...document.querySelectorAll(".sell-component-info-wrapper-label")].find((el) => (el.textContent || "").trim() === lab)
        || [...document.querySelectorAll(".next-form-item-label")].find((el) => (el.textContent || "").trim() === lab)
        || [...document.querySelectorAll("*")].find((el) => (el.childNodes.length <= 6) && (el.textContent || "").trim() === lab);
      if (!hit) return { lab, found: false };
      const wrap = hit.closest(".sell-component-info-wrapper, .next-form-item") || hit.parentElement;
      const item = hit.closest(".sell-component-item-prop-item") || hit.closest(".sell-horizon-layout-info-wrapper");
      const combo = item && [...item.querySelectorAll("input[role='combobox'], [role='combobox']")].find((el) => !el.closest(".next-overlay-wrapper"));
      const input = combo && (combo.tagName === "INPUT" ? combo : combo.querySelector("input"));
      const radios = item ? [...item.querySelectorAll("label, .next-radio-wrapper, [role='radio']")].map((el) => ({
        t: (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40),
        cls: String(el.className || "").slice(0, 80),
        checked: /checked/.test(el.className || "") || el.getAttribute("aria-checked") === "true",
      })).filter((x) => x.t).slice(0, 8) : [];
      const html = (item || wrap) ? (item || wrap).outerHTML.replace(/\s+/g, " ").slice(0, 900) : "";
      return {
        lab,
        found: true,
        hitCls: String(hit.className || "").slice(0, 80),
        itemCls: item ? String(item.className || "").slice(0, 160) : "",
        itemText: item ? (item.innerText || "").replace(/\s+/g, " ").trim().slice(0, 160) : "",
        comboPh: input ? (input.getAttribute("placeholder") || input.value || "") : "",
        radios,
        wrapCls: wrap ? String(wrap.className || "").slice(0, 120) : "",
        wrapText: wrap ? (wrap.innerText || "").replace(/\s+/g, " ").trim().slice(0, 120) : "",
        chain: chain(hit),
        html,
      };
    });
  }, labels);
  return JSON.stringify({ href: page.url(), dump }, null, 2);
}
