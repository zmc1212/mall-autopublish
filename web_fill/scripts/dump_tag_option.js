async page => {
  const PAYLOAD = /*PAYLOAD*/;
  const want = PAYLOAD.value || "日常书写";
  const dump = await page.evaluate((value) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper")].filter((el) => getComputedStyle(el).display !== "none");
    const wrap = [...wraps].reverse().find((el) => (el.innerText || "").includes(value)) || wraps[wraps.length - 1];
    if (!wrap) return { error: "NO_WRAP", n: wraps.length };
    const walker = document.createTreeWalker(wrap, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.textContent.trim() !== value) continue;
      const node = walker.currentNode.parentElement;
      const chain = [];
      let p = node;
      for (let i = 0; i < 8 && p && p !== wrap; i++) {
        chain.push({
          tag: p.tagName,
          cls: String(p.className).slice(0, 100),
          role: p.getAttribute("role"),
          inputs: [...p.querySelectorAll("input")].map((el) => el.type),
          t: (p.innerText || "").replace(/\s+/g, " ").slice(0, 40),
        });
        p = p.parentElement;
      }
      return { chain, wrapCls: String(wrap.className).slice(0, 80) };
    }
    return { error: "NO_TEXT", text: (wrap.innerText || "").replace(/\s+/g, " ").slice(0, 200) };
  }, want);
  return JSON.stringify(dump, null, 2);
}
