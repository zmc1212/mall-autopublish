async page => {
  const PAYLOAD = /*PAYLOAD*/;
  /*HELPERS*/
  if (PAYLOAD.waitForReady) {
    // Navigation completion precedes the asynchronous server form data. This
    // wait is read-only and never sets a default value or clicks a control.
    await page.waitForFunction(() => [...document.querySelectorAll('input, textarea')].some(el =>
      ((el.getAttribute('placeholder') || '').includes('30个汉字')
        || (el.getAttribute('aria-label') || '').includes('30个汉字')) && el.value), null, {timeout:15000});
  }
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
    // Count the same editor content that details.js writes. The enclosing
    // card also contains four legacy preview logos/empty-state illustrations.
    const detailEditor = document.querySelector("#lite-decoration-editor")
      || document.querySelector(".sell-component-lite-decoration-editor");
    const details = detailEditor ? [...detailEditor.querySelectorAll("img")].filter((el) => el.width > 80) : [];
    // 商品视频区已上传视频数：候选 sell-field 视频容器；兜底按“商品视频”
    // 标题向上爬到含“上传视频”按钮的容器。只数 <video> 或空框以外的缩略图，
    // “上传视频”虚线空框不算。两路都定位不到时保持 0。
    let videoRoot = document.querySelector('[id^="sell-field-"][id*="ideo"]');
    if (!videoRoot) {
      const heading = [...document.querySelectorAll("*")].find((el) => (el.childNodes.length <= 5)
        && (el.textContent || "").trim() === "商品视频");
      let node = heading && heading.parentElement;
      for (let i = 0; i < 8 && node; i++) {
        if ([...node.querySelectorAll("button, div, span, a")].some((el) => (el.innerText || "").trim() === "上传视频")) {
          videoRoot = node;
          break;
        }
        node = node.parentElement;
      }
    }
    let videos = 0;
    if (videoRoot) {
      videos = videoRoot.querySelectorAll("video").length;
      if (!videos) {
        const boxRoots = [...videoRoot.querySelectorAll("div, span, button")]
          .filter((el) => (el.innerText || "").trim() === "上传视频");
        videos = [...videoRoot.querySelectorAll("img")].filter((el) => el.width > 40
          && !boxRoots.some((box) => box.contains(el))).length;
      }
    }
    // Only the custom specification cell counts. SKU search-main images live
    // in another cell of the same row and must never satisfy this gate.
    const rowHasImage = tr => !!tr.querySelector('td[id$="-custom_-1"] img.image-item[src]');
    const warehouse = [...document.querySelectorAll('input[type=radio]')].map((el) => ({
      t: [...(el.labels || [])].map(label => label.innerText || '').join(' ').trim()
        || (el.getAttribute('aria-label') || '').trim(),
      checked: el.checked,
    })).filter((x) => /仓库|上架/.test(x.t));
    const cats = [...document.querySelectorAll("table tr")].filter((tr) => (tr.innerText || "").includes("元") && (tr.innerText || "").includes("件") && !(tr.innerText || "").includes("SKU分类"));
    let checkpoint = null;
    try {
      checkpoint = JSON.parse(sessionStorage.getItem('qianniu-fill-checkpoint') || 'null');
      if (checkpoint && checkpoint.href !== location.href) checkpoint = null;
    } catch (_) {}
    return {
      href: location.href,
      itemId: /itemid=/i.test(location.href),
      title: titleBox ? titleBox.value : "",
      attrs,
      mainImgs: main ? [...main.querySelectorAll("img")].filter((el) => el.width > 40).length : 0,
      p34Imgs: p34 ? [...p34.querySelectorAll("img")].filter((el) => el.width > 40).length : 0,
      detailImgs: details.length,
      videos,
      checkpoint,
      specImgs: cats.filter(rowHasImage).length,
      skuNames: cats.map(tr => { const input = tr.querySelector('input, textarea'); return input ? input.value.trim() : ''; }),
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
      captchaVisible: !!document.querySelector('iframe[src*="action=captcha"], .J_MIDDLEWARE_FRAME_WIDGET'),
      captchaClosedCount: Number(sessionStorage.getItem("qianniu-captcha-closed-count") || 0),
    };
  });
  return JSON.stringify(state, null, 2);
}
