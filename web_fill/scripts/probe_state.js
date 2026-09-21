async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  const state = await page.evaluate(() => {
    const text = document.body.innerText || "";
    const attrLabels = ["笔头类型", "笔芯颜色", "闭合方式", "风格", "功能", "品牌", "型号", "适用场景", "适用人群", "包装方式", "采购地"];
    const attrs = {};
    for (const lab of attrLabels) {
      const node = [...document.querySelectorAll("*")].find((el) => (el.childNodes.length <= 5) && (el.textContent || "").trim() === lab);
      let root = node && node.parentElement;
      let snippet = "";
      for (let i = 0; i < 6 && root; i++) {
        const t = (root.innerText || "").replace(/\s+/g, " ").trim();
        if (t.length > lab.length && t.length < 180) {
          snippet = t;
          break;
        }
        root = root.parentElement;
      }
      attrs[lab] = snippet;
    }
    const title = (document.querySelector("textarea, input") && "") || "";
    const titleBox = [...document.querySelectorAll("input, textarea")].find((el) => (el.getAttribute("placeholder") || "").includes("30个汉字") || (el.getAttribute("aria-label") || "").includes("30个汉字"));
    const main = document.querySelector("#sell-field-mainImagesGroup");
    const p34 = document.querySelector("#sell-field-threeToFourImages");
    const details = [...document.querySelectorAll("#newDesc-card img, #sell-field-descRepublicOfSell img")].filter((el) => el.width > 80);
    const skuImgs = [...document.querySelectorAll(".sell-component-sku-images img, table img")].filter((el) => el.width > 16);
    const warehouse = [...document.querySelectorAll(".next-radio-wrapper")].map((el) => ({
      t: (el.innerText || "").trim(),
      checked: el.className.includes("checked"),
    })).filter((x) => /仓库|上架/.test(x.t));
    const cats = [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件") && !(tr.innerText || "").includes("SKU分类"));
    return {
      href: location.href,
      itemId: /itemid=/i.test(location.href),
      title: titleBox ? titleBox.value : "",
      attrs,
      mainImgs: main ? [...main.querySelectorAll("img")].filter((el) => el.width > 40).length : 0,
      p34Imgs: p34 ? [...p34.querySelectorAll("img")].filter((el) => el.width > 40).length : 0,
      detailImgs: details.length,
      specImgs: skuImgs.length,
      skuRows: cats.length,
      skuDanpin: cats.filter((tr) => /单品/.test(tr.innerText || "")).length,
      thick: cats.map((tr) => {
        const el = [...tr.querySelectorAll("input")].find((n) => n.placeholder === "请选择" || /mm/i.test(n.value || ""));
        return el ? el.value : "";
      }),
      warehouse,
      hasSubmit: [...document.querySelectorAll("button")].some((el) => (el.innerText || "").trim() === "提交宝贝信息"),
      freight: /文具用品 包邮/.test(text),
      ship48: /48小时内发货/.test(text),
      popup: !!document.querySelector(".batch-fill-sku-image-dialog, .sell-component-image-v2-media-popup, .sku-decouple-drawer"),
      specDialog: !!document.querySelector(".batch-fill-sku-image-dialog"),
      sucai: [...document.querySelectorAll("iframe")].some((el) => /sucai/.test(el.src || "")),
    };
  });
  return JSON.stringify(state, null, 2);
}
