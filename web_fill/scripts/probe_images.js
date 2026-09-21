async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const state = await page.evaluate(() => {
    const main = document.querySelector("#sell-field-mainImagesGroup");
    const mains = main ? [...main.querySelectorAll(".drag-item img")].map((el) => (el.src || "").split("/").pop()) : [];
    const lite = document.querySelector("#lite-decoration-editor, .sell-component-lite-decoration-editor");
    const detailImgs = lite ? [...lite.querySelectorAll("img")].filter((el) => el.width > 60 && !/tps-12-12|tfs\//.test(el.src || "")) : [];
    const rows = [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件"));
    const skus = rows.map((tr) => {
      const nameEl = tr.querySelector("input, textarea");
      const first = tr.querySelector("td");
      const img = first && first.querySelector("img");
      return {
        name: nameEl ? nameEl.value : (tr.innerText || "").slice(0, 40),
        hasImg: !!(img && img.width > 16),
        src: img ? (img.src || "").split("/").pop() : "",
      };
    });
    return {
      href: location.href,
      title: (([...document.querySelectorAll("input, textarea")].find((el) => (el.getAttribute("placeholder") || "").includes("30个汉字")) || {}).value) || "",
      mainCount: mains.length,
      mains,
      detailCount: detailImgs.length,
      details: detailImgs.map((el) => ({ w: el.width, h: el.height, src: (el.src || "").split("/").pop() })),
      skuCount: skus.length,
      skusMissing: skus.filter((s) => !s.hasImg),
      skus,
      warehouse: [...document.querySelectorAll(".next-radio-wrapper")].map((el) => ({
        t: (el.innerText || "").trim(),
        checked: el.className.includes("checked"),
      })).filter((x) => /仓库|上架/.test(x.t)),
      hasSubmit: [...document.querySelectorAll("button")].some((el) => (el.innerText || "").trim() === "提交宝贝信息"),
      popup: !!document.querySelector(".batch-fill-sku-image-dialog, .sell-component-image-v2-media-popup, .sku-decouple-drawer, .next-dialog"),
    };
  });
  return JSON.stringify(state, null, 2);
}
