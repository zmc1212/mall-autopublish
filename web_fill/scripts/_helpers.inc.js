const sleep = (ms) => page.waitForTimeout(ms);

function unsafeUrl(url) {
  const u = String(url || "");
  if (/1085558349142/.test(u)) return false;
  return /itemid=|item_num_id=|\/edit\.htm|\/subitem\/publish\.htm/i.test(u);
}

async function hideScenarioWidgets() {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".scenario-widget, [class*='PendantWrapper'], [class*='pendant-wrapper']")];
    for (const el of nodes) {
      el.style.setProperty("pointer-events", "none", "important");
      el.style.setProperty("visibility", "hidden", "important");
    }
    return nodes.length;
  }).catch(() => 0);
}

async function dismissBlockingDialogs() {
  await page.evaluate(() => {
    const roots = [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened .next-dialog, .next-feedback, .next-overlay-wrapper.opened")];
    for (const root of roots) {
      const t = (root.innerText || "").replace(/\s+/g, " ");
      if (!/草稿|我知道了|最大保存|属性值反馈|申请理由|举证材料|未找到合适的值/.test(t)) continue;
      const close = root.querySelector(".next-dialog-close, [aria-label='关闭'], .next-icon-close, .next-dialog-close-icon");
      if (close) {
        try { close.click(); continue; } catch (e) {}
      }
      const buttons = [...root.querySelectorAll("button")];
      const cancel = buttons.find((el) => /取消|关闭|我知道了/.test((el.innerText || "").trim()));
      if (cancel) {
        try { cancel.click(); continue; } catch (e) {}
      }
      if (/草稿|最大保存|属性值反馈|申请理由|举证材料/.test(t)) continue;
      const ok = buttons.find((el) => /确定/.test((el.innerText || "").trim()));
      if (ok) {
        try { ok.click(); } catch (e) {}
      }
    }
  }).catch(() => {});
}

async function hideDraftOverlays() {
  return page.evaluate(() => {
    const nodes = [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened")];
    let n = 0;
    for (const el of nodes) {
      const t = (el.innerText || "").replace(/\s+/g, " ").trim();
      if (!/草稿箱最大保存|最大保存\s*\d+\s*条草稿/.test(t)) continue;
      if (t.length > 400) continue;
      if (/笔头类型|提交宝贝信息|确认，下一步|商品标题/.test(t)) continue;
      el.style.setProperty("pointer-events", "none", "important");
      el.style.setProperty("display", "none", "important");
      n += 1;
    }
    return n;
  }).catch(() => 0);
}

async function dismissKnow(opts) {
  await hideScenarioWidgets();
  await dismissBlockingDialogs();
  const know = page.getByText("我知道了", { exact: true });
  if (await know.count()) {
    try { await know.last().click({ timeout: 800, force: true }); } catch (e) {}
  }
  if (opts && opts.escape === false) return;
  await page.keyboard.press("Escape").catch(() => {});
}

async function installAttrDom() {
  await page.evaluate(() => {
    window.__qnHit = function (lab) {
      return [...document.querySelectorAll(".sell-component-info-wrapper-label")].find((el) => (el.textContent || "").trim() === lab)
        || [...document.querySelectorAll(".next-form-item-label")].find((el) => (el.textContent || "").trim() === lab)
        || null;
    };
    window.__qnItem = function (lab) {
      const hit = window.__qnHit(lab);
      if (!hit) return null;
      return hit.closest(".sell-component-item-prop-item")
        || hit.closest(".sell-horizon-layout-info-wrapper")
        || hit.closest(".next-form-item");
    };
    window.__qnCombo = function (lab) {
      const item = window.__qnItem(lab);
      if (item) {
        const combo = [...item.querySelectorAll("input[role='combobox'], [role='combobox']")].find((el) => !el.closest(".next-overlay-wrapper"));
        if (!combo) return null;
        return combo.tagName === "INPUT" ? combo : (combo.querySelector("input") || combo);
      }
      const hit = window.__qnHit(lab);
      if (!hit) return null;
      let root = hit;
      for (let i = 0; i < 8 && root; i++) {
        const combos = [...root.querySelectorAll("input[role='combobox'], [role='combobox']")].filter((el) => !el.closest(".next-overlay-wrapper"));
        const t = (root.innerText || "").replace(/\s+/g, " ").trim();
        if (combos.length === 1 && t.includes(lab) && t.length < 220) {
          const el = combos[0];
          return el.tagName === "INPUT" ? el : (el.querySelector("input") || el);
        }
        root = root.parentElement;
      }
      return null;
    };
    window.__qnOptionOn = function (scope, name) {
      if (!scope || !name) return false;
      const want = String(name).replace(/\s+/g, "");
      return [...scope.querySelectorAll("label, .next-radio-wrapper, [role='radio'], .next-radio")].some((el) => {
        const t = (el.innerText || "").replace(/\s+/g, "");
        if (t !== want && !(t.includes(want) && t.length <= want.length + 6)) return false;
        const wrap = el.closest(".next-radio-wrapper, [role='radio'], label") || el;
        const input = wrap.querySelector("input[type='radio']")
          || (el.parentElement && el.parentElement.querySelector("input[type='radio']"));
        return !!(input && input.checked)
          || /checked/.test(wrap.className || "")
          || wrap.getAttribute("aria-checked") === "true";
      });
    };
    window.__qnAttr = function (lab) {
      const hit = window.__qnHit(lab);
      if (!hit) return { found: false };
      const combo = window.__qnCombo(lab);
      const item = window.__qnItem(lab);
      const box = combo && (combo.closest(".next-select, .next-form-item-control") || combo.parentElement) || item;
      const input = combo && combo.tagName === "INPUT" ? combo : (combo && combo.querySelector("input"));
      const text = ((box && box.innerText) || "").replace(/\s+/g, " ").trim();
      const tags = [...(box ? box.querySelectorAll(".next-tag, .next-select-values, .next-select-inner, em") : [])].map((el) => (el.innerText || "").trim()).filter(Boolean);
      const cls = String((item && item.className) || "");
      return {
        found: true,
        wrap: ((hit.textContent || "").trim()).slice(0, 80),
        text: text.slice(0, 200),
        val: input ? String(input.value || "").trim() : "",
        tags,
        hasCombo: !!combo,
        kind: /checkbox/.test(cls) ? "checkbox" : /horizon-layout|label-horizontal/.test(cls) ? "radio" : /select/.test(cls) ? "select" : "combo",
        ph: input ? String(input.getAttribute("placeholder") || "") : "",
      };
    };
    window.__qnCommitted = function (lab, want) {
      const info = window.__qnAttr(lab);
      if (!info.found || !want) return false;
      if (/不能为空|必填项未填/.test(info.text || "")) return false;
      const item = window.__qnItem(lab);
      if (info.kind === "radio" || (item && /horizon-layout|label-horizontal/.test(item.className || "") && !info.hasCombo)) {
        return !!(window.__qnOptionOn && window.__qnOptionOn(item, want));
      }
      if (info.val && info.val.includes(want) && info.val !== "模板") return true;
      if ((info.tags || []).some((x) => x && x.includes(want))) return true;
      const cleaned = String(info.text || "").replace(/平台推荐值[:：]\s*\S+/g, " ").replace(/请选择|请输入|重要|\*/g, " ");
      const wrapClean = String(info.wrap || "").replace(/平台推荐值[:：]\s*\S+/g, " ").replace(/请选择|请输入|重要|\*/g, " ");
      if (cleaned.trim() === wrapClean.trim()) return false;
      return cleaned.includes(want);
    };
  });
}

async function findAttrCombo(label) {
  await installAttrDom();
  return page.evaluateHandle((lab) => (window.__qnCombo && window.__qnCombo(lab)) || null, label);
}

async function clickUnblocked(locator, timeout) {
  const ms = timeout || 8000;
  await dismissKnow();
  try {
    await locator.click({ timeout: Math.min(ms, 2500) });
    return "click";
  } catch (e) {}
  await hideScenarioWidgets();
  try {
    await locator.click({ force: true, timeout: Math.min(ms, 5000) });
    return "force";
  } catch (e) {}
  const ok = await locator.evaluate((el) => {
    if (!el) return false;
    el.click();
    return true;
  }).catch(() => false);
  if (ok) return "dom";
  throw new Error("页面悬浮层挡住了按钮，已尝试强制点击仍失败");
}

async function openMainPicker(field) {
  const sel = field || "#sell-field-mainImagesGroup";
  return page.evaluate((target) => {
    const empty = document.querySelector(target + " .image-empty");
    if (empty) {
      empty.scrollIntoView({ block: "center" });
      empty.click();
      return "empty";
    }
    const title = target.indexOf("threeToFour") >= 0 ? "3:4主图" : "1:1主图";
    const headings = [...document.querySelectorAll("*")].filter((el) => (el.childNodes.length <= 5) && (el.textContent || "").trim() === title);
    let root = headings[0];
    for (let i = 0; i < 8 && root; i++) {
      const btn = [...root.querySelectorAll("button, div, span, a")].find((el) => (el.innerText || "").trim() === "上传图片");
      if (btn) {
        btn.scrollIntoView({ block: "center" });
        btn.click();
        return "upload-btn";
      }
      root = root.parentElement;
    }
    return "NO";
  }, sel);
}

async function listSucaiPics(frame) {
  if (!frame) return [];
  return frame.evaluate(() => {
    const exact = [...document.querySelectorAll(".PicList_PicturesShow_main-show__QVvZn")];
    const cards = exact.length ? exact : [...document.querySelectorAll("[class*='PicturesShow'], .item.pic")].filter((el) => el.querySelector("img") && (el.innerText || "").trim().length < 180);
    return cards.map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).filter(Boolean).slice(0, 40);
  });
}

async function clickSucaiCard(frame, file) {
  const exact = String(file || "").split(/[\\/]/).pop();
  return frame.evaluate((want) => {
    const raw = [...document.querySelectorAll(".PicList_PicturesShow_main-show__QVvZn, [class*='PicturesShow'], .item.pic")].filter((el) => el.querySelector("img"));
    const seen = new Set();
    const cards = [];
    for (const el of raw) {
      const t = (el.innerText || "").replace(/\s+/g, " ").trim();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      cards.push(el);
    }
    const hits = cards.filter((el) => (el.innerText || "").includes(want));
    hits.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const card = hits.find((el) => (el.innerText || "").trim().startsWith(want)) || hits[0];
    if (!card) return { ok: false, n: cards.length, names: cards.slice(0, 8).map((el) => (el.innerText || "").replace(/\s+/g, " ").slice(0, 40)) };
    (card.querySelector("img") || card).click();
    card.click();
    return { ok: true, t: (card.innerText || "").replace(/\s+/g, " ").slice(0, 80), n: hits.length };
  }, exact);
}

async function confirmCrop() {
  const crop = page.locator(".next-dialog").filter({ hasText: "裁剪" }).locator("button", { hasText: "确定" });
  if (await crop.count()) {
    await crop.last().click({ force: true });
    await sleep(700);
    return "OK";
  }
  return "NO";
}

async function searchSucai(frame, query) {
  if (!frame || !query) return "NO";
  const typed = await frame.evaluate((q) => {
    const input = document.querySelector("input[placeholder*='搜索'], input[type=search], input[placeholder*='图片']");
    if (!input) return "NO_BOX";
    input.focus();
    const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    const setVal = (v) => {
      if (proto && proto.set) proto.set.call(input, v);
      else input.value = v;
      input.dispatchEvent(new Event("input", { bubbles: true }));
      input.dispatchEvent(new Event("change", { bubbles: true }));
    };
    setVal("");
    const clear = document.querySelector(".next-icon-delete-filling, .next-input-clear-icon, [class*='clear-icon'], [class*='InputClear']");
    if (clear) clear.click();
    setVal(q);
    const btn = [...document.querySelectorAll("button")].find((el) => (el.innerText || "").trim() === "搜索");
    if (btn) btn.click();
    else input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, which: 13, bubbles: true }));
    return "OK";
  }, query).catch(() => "NO");
  if (typed !== "OK") return typed || "NO";
  for (let i = 0; i < 25; i++) {
    await sleep(400);
    const names = await listSucaiPics(frame);
    if (names.some((n) => n.includes(query))) return "OK";
  }
  const leftover = await listSucaiPics(frame);
  return "STALE:" + query + ":" + leftover.slice(0, 3).join("|");
}

async function clickOverlayText(want) {
  return page.evaluate((value) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened, .next-overlay-wrapper")].filter((el) => {
      if (getComputedStyle(el).display === "none") return false;
      const t = el.innerText || "";
      if (/图文描述|草稿箱|最大保存|属性值反馈|申请理由|举证材料|点击申请/.test(t)) return false;
      return true;
    });
    const wrap = [...wraps].reverse().find((el) => (el.innerText || "").includes(value));
    if (!wrap) {
      const seen = wraps.map((el) => (el.innerText || "").replace(/\s+/g, " ").trim().slice(0, 40)).filter(Boolean).slice(0, 4);
      return "NO_WRAP:" + (seen.join("|") || "none");
    }
    const walker = document.createTreeWalker(wrap, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      if (walker.currentNode.textContent.trim() === value) {
        const node = walker.currentNode.parentElement;
        const box = node.querySelector("input[type=checkbox]") || (node.parentElement && node.parentElement.querySelector("input[type=checkbox]"));
        if (box) {
          box.click();
          return "BOX:" + value;
        }
        node.click();
        return "CLICKED:" + value;
      }
    }
    const nodes = [...wrap.querySelectorAll("li, .next-menu-item, .options-item, .info-content, .next-checkbox-wrapper, label, span, div")];
    const hit = nodes.find((el) => (el.innerText || "").trim() === value)
      || nodes.find((el) => {
        const t = (el.innerText || "").trim();
        return t.includes(value) && t.length < 40;
      });
    if (hit) {
      const box = hit.querySelector("input[type=checkbox]");
      if (box) {
        box.click();
        return "BOX:" + value;
      }
      hit.click();
      return "CLICKED:" + value;
    }
    return "NO_TEXT:" + (wrap.innerText || "").replace(/\s+/g, " ").slice(0, 160);
  }, want);
}

async function attrCommitted(label, value) {
  await installAttrDom();
  return page.evaluate(([lab, val]) => !!(window.__qnCommitted && window.__qnCommitted(lab, val)), [label, value]);
}

async function pickInsideItem(label, value) {
  await installAttrDom();
  return page.evaluate(([lab, val]) => {
    const item = window.__qnItem && window.__qnItem(lab);
    if (!item) return "NO_ITEM";
    item.scrollIntoView({ block: "center", inline: "nearest" });
    const norm = (s) => String(s || "").replace(/\s+/g, " ").trim();
    const radios = [...item.querySelectorAll("label, .next-radio-wrapper, [role='radio']")];
    const hit = radios.find((el) => norm(el.innerText) === val);
    if (!hit) return "NO_OPT";
    const input = hit.querySelector("input[type=radio]")
      || (hit.parentElement && hit.parentElement.querySelector("input[type=radio]"));
    if (input) input.click();
    hit.click();
    return "RADIO";
  }, [label, value]);
}

async function overlayHasValue(value) {
  return page.evaluate((want) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened")].filter((el) => getComputedStyle(el).display !== "none");
    return wraps.some((wrap) => [...wrap.querySelectorAll(".options-item, .next-menu-item, li, .next-checkbox-wrapper, label")].some((el) => {
      const t = (el.getAttribute("title") || el.innerText || "").replace(/\s+/g, " ").trim();
      return t === want || (t.includes(want) && t.length < 40 && !/申请|未找到/.test(t));
    }));
  }, value);
}

async function typeOverlaySearch(value) {
  const box = page.locator(".next-overlay-wrapper.opened .options-search input, .next-overlay-wrapper.opened input:not([readonly]):not([type=checkbox]):not([type=radio])").first();
  if (!(await box.count())) return "NO_INPUT";
  await box.click({ force: true, timeout: 1500 }).catch(() => {});
  await box.fill(String(value)).catch(() => {});
  await sleep(400);
  return "SEARCH";
}

async function confirmAttrOverlay() {
  const confirm = page.locator(".next-overlay-wrapper.opened").filter({ hasNotText: /草稿|最大保存|图文描述/ }).locator("button").filter({ hasText: /^(确定|完成|确认)$/ });
  if (await confirm.count()) {
    await confirm.last().click({ force: true, timeout: 1500 }).catch(() => {});
    await sleep(250);
    return "OK";
  }
  return "";
}

async function pickFromOpenedOverlay(value) {
  const picked = await page.evaluate((want) => {
    const wraps = [...document.querySelectorAll(".next-overlay-wrapper.opened")].filter((el) => getComputedStyle(el).display !== "none");
    const wrap = wraps.reverse().find((el) => !/属性值反馈|申请理由|举证材料|草稿箱/.test(el.innerText || "")) || wraps[wraps.length - 1];
    if (!wrap) return "NO_WRAP:none";
    if (/属性值反馈|申请理由|举证材料/.test(wrap.innerText || "")) return "APPLY_DIALOG";
    const items = [...wrap.querySelectorAll(".options-item, .next-menu-item, .next-checkbox-wrapper, label")];
    const hit = items.find((el) => (el.getAttribute("title") || "").trim() === want)
      || items.find((el) => (el.innerText || "").replace(/\s+/g, " ").trim() === want);
    if (!hit) return "NO_OPT";
    const box = hit.querySelector("input[type=checkbox]");
    if (box) {
      box.click();
      return "CHECK:" + want;
    }
    hit.click();
    return "ITEM:" + want;
  }, value);
  await sleep(220);
  const ok = await confirmAttrOverlay();
  return String(picked) + (ok ? ":OK" : "");
}

async function pickComboValue(label, value) {
  if (await attrCommitted(label, value)) return "already";
  await hideScenarioWidgets();
  await dismissBlockingDialogs();
  await installAttrDom();
  const inside = await pickInsideItem(label, value);
  await sleep(220);
  if (await attrCommitted(label, value)) return inside + ":stuck";

  const opened = await page.evaluate((lab) => {
    const el = window.__qnCombo && window.__qnCombo(lab);
    if (!el) return "NO_COMBO";
    const item = window.__qnItem && window.__qnItem(lab);
    if (item) item.scrollIntoView({ block: "center", inline: "nearest" });
    const wrap = el.closest(".next-select") || el;
    wrap.click();
    el.click();
    if (el.focus) el.focus();
    return "OPEN:" + String(el.getAttribute("placeholder") || "") + (el.readOnly ? ":ro" : "");
  }, label);
  if (opened === "NO_COMBO") {
    return inside + ":NO_COMBO:" + ((await attrCommitted(label, value)) ? "stuck" : "lost");
  }
  await sleep(500);
  for (let i = 0; i < 8; i++) {
    if (await page.locator(".next-overlay-wrapper.opened").count()) break;
    await sleep(120);
  }
  if (!(await overlayHasValue(value))) {
    const typed = await typeOverlaySearch(value);
    if (typed !== "SEARCH" && /请输入/.test(String(opened))) {
      await page.keyboard.type(String(value), { delay: 16 }).catch(() => {});
    }
    await sleep(450);
  }
  let picked = await pickFromOpenedOverlay(value);
  let ok = await attrCommitted(label, value);
  if (!ok && !/NO_OPT|APPLY_DIALOG/.test(String(picked))) {
    await page.evaluate((lab) => {
      const el = window.__qnCombo && window.__qnCombo(lab);
      const wrap = el && (el.closest(".next-select") || el);
      if (wrap) wrap.click();
    }, label).catch(() => {});
    await sleep(400);
    if (!(await overlayHasValue(value))) {
      await typeOverlaySearch(value);
      await sleep(400);
    }
    picked += "+" + (await pickFromOpenedOverlay(value));
    ok = await attrCommitted(label, value);
  }
  if (!ok) await dismissBlockingDialogs();
  return picked + (ok ? ":stuck" : /NO_OPT|APPLY_DIALOG/.test(String(picked)) ? ":skip" : ":lost");
}

function sucaiFrame() {
  return page.frames().find((f) => /sucai-selector|sucai-tu|material-center|picturestudio|material|picture-space|picture_space|tupian|素材|图片空间/i.test(f.url()));
}

function wangpuFrame() {
  return page.frames().find((f) => /sucai\.wangpu|select\.htm/.test(f.url()));
}

function pictureSpaceFrame() {
  return wangpuFrame() || sucaiFrame();
}

async function listPictureSpaceNames(frame) {
  if (!frame) return [];
  return frame.evaluate(() => {
    const cards = [...document.querySelectorAll(".item.pic, [class*='PicturesShow']")].filter((el) => el.querySelector("img"));
    return cards.map((el) => (el.innerText || "").replace(/\s+/g, " ").trim()).filter(Boolean);
  });
}

function missingPictureNames(listed, want) {
  const have = listed || [];
  return (want || []).filter((name) => !have.some((t) => t.includes(name)));
}

async function pickPictureSpaceCards(frame, names) {
  if (!frame) return [];
  return frame.evaluate((want) => {
    const cards = [...document.querySelectorAll(".item.pic, [class*='PicturesShow']")].filter((el) => el.querySelector("img"));
    const out = [];
    for (const name of want || []) {
      const hits = cards.filter((el) => (el.innerText || "").includes(name));
      hits.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
      const card = hits[0];
      if (!card) {
        out.push({ name, ok: false, n: cards.length });
        continue;
      }
      const icon = card.querySelector(".select-icon") || card.querySelector(".cover") || card.querySelector("img") || card;
      icon.click();
      if (!/\bactive\b/.test(card.className || "")) card.click();
      out.push({ name, ok: true, cls: String(card.className || "").slice(0, 80) });
    }
    return out;
  }, names || []);
}

async function confirmPictureSpace(frame) {
  const pageOk = await page.evaluate(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 8 && r.height > 8 && s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0;
    };
    const dialogs = [...document.querySelectorAll(".next-dialog")].filter((el) => visible(el) && /图片空间/.test(el.innerText || ""));
    const wrap = dialogs[dialogs.length - 1];
    if (wrap) {
      const footer = wrap.querySelector(".next-dialog-footer") || wrap;
      const buttons = [...footer.querySelectorAll("button")].filter((el) => visible(el) && /^(确认|确定)$/.test((el.innerText || "").trim()));
      const btn = buttons.find((el) => /primary/.test(el.className || "")) || buttons[buttons.length - 1];
      if (btn) {
        btn.click();
        return "PAGE";
      }
    }
    return "NO";
  });
  if (pageOk === "PAGE") return pageOk;
  if (frame) {
    const ok = await frame.evaluate(() => {
      const btn = document.querySelector(".btn.btn-blue")
        || [...document.querySelectorAll("button, .btn, a")].find((el) => /^(确认|确定)$/.test((el.innerText || "").trim()));
      if (!btn) return "NO";
      btn.click();
      return "OK";
    }).catch(() => "NO");
    if (ok === "OK") return ok;
  }
  return "NO";
}

async function waitFrame(find, tries) {
  for (let i = 0; i < (tries || 20); i++) {
    const blob = await page.evaluate(() => (document.body && document.body.innerText) || "").catch(() => "");
    if (/请拖动下方滑块|请按住滑块|通过验证以确保正常访问/.test(blob)) {
      throw new Error("PAUSE:页面出现滑块验证，请手动完成后重试");
    }
    const frame = find();
    if (frame) return frame;
    await sleep(400);
  }
  return null;
}

function uploadContexts(frame) {
  const list = [];
  if (frame) list.push(frame);
  list.push(page);
  for (const f of page.frames()) {
    if (f !== frame && f !== page) list.push(f);
  }
  return list;
}

function fileBase(path) {
  return String(path || "").split(/[\\/]/).pop();
}

function filesForNames(files, names) {
  const want = new Set((names || []).map((n) => String(n)));
  return (files || []).filter((p) => want.has(fileBase(p)));
}

async function readUploadStatus(ctx, names) {
  return ctx.evaluate((want) => {
    const body = (document.body && document.body.innerText) || "";
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 4 && r.height > 4 && s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0;
    };
    const hasComplete = [...document.querySelectorAll("button")].some((el) => {
      if ((el.innerText || "").trim() !== "完成") return false;
      return visible(el);
    });
    const dialogs = [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened, [class*='Upload'], [class*='upload'], [class*='dialog']")]
      .filter((el) => visible(el) && /上传结果/.test(el.innerText || ""));
    const root = dialogs.length ? dialogs[dialogs.length - 1] : document.body;
    const text = (root && root.innerText) || body;
    const found = (want || []).filter((n) => n && text.includes(n));
    const items = [];
    for (const name of want || []) {
      if (!name) continue;
      const others = (want || []).filter((n) => n && n !== name);
      const nodes = [...root.querySelectorAll("*")].filter((el) => (el.innerText || "").includes(name));
      let best = "";
      let bestLen = Infinity;
      for (const el of nodes) {
        const t = el.innerText || "";
        if (t.length >= bestLen) continue;
        if (others.some((n) => t.includes(n))) continue;
        best = t;
        bestLen = t.length;
      }
      const failed = /网络错误|请尝试禁止浏览器插件|换浏览器或者换电脑重试/.test(best)
        || (/上传失败/.test(best) && !/\d+(\.\d+)?\s*[KMGT]B?/i.test(best));
      const ok = !failed && /\d+(\.\d+)?\s*[KMGT]B?/i.test(best);
      items.push({
        name,
        failed,
        ok,
        text: best.replace(/\s+/g, " ").trim().slice(0, 160),
      });
    }
    const failedNames = items.filter((it) => it.failed && !it.ok).map((it) => it.name);
    const okNames = items.filter((it) => it.ok).map((it) => it.name);
    const networkError = items.some((it) => /网络错误|禁止浏览器插件/.test(it.text)) || /网络错误/.test(text);
    const retryable = networkError || /请稍后重试/.test(text);
    return {
      uploading: /上传中/.test(text) || /上传中/.test(body),
      success: /上传成功|上传完成|\d+\s*个文件上传成功|成功上传\s*\d+\s*个文件/.test(text) || /上传成功/.test(body),
      fail: failedNames.length > 0 || /没有权限|无图片空间/.test(text),
      found,
      hasComplete,
      snippet: (text.match(/([^\n]*(?:上传|网络错误)[^\n]*)/g) || []).slice(0, 8),
      okNames,
      failedNames,
      networkError,
      retryable,
      items,
    };
  }, names || []);
}

async function clickLocalUpload(frame) {
  const clicked = await frame.evaluate(() => {
    const primary = [...document.querySelectorAll("button.next-btn-primary")].find((el) => (el.innerText || "").includes("本地上传"));
    const any = primary || [...document.querySelectorAll("button")].reverse().find((el) => (el.innerText || "").trim() === "本地上传");
    if (!any) return "NO";
    any.click();
    return "OK";
  });
  await sleep(900);
  return clicked;
}

async function fileInputs(frame) {
  if (!frame) return [];
  return frame.evaluate(() => [...document.querySelectorAll("input[type=file]")].map((el) => ({
    id: el.id || "",
    multiple: !!el.multiple,
  })));
}

async function trySetInputFiles(frame, files) {
  if (!frame || !files || !files.length) return "NO_FILES";
  try {
    await frame.locator("input[type=file]").first().setInputFiles(files, { timeout: 8000 });
    return "OK";
  } catch (e) {
    return "TIMEOUT";
  }
}

async function fileInputLocator() {
  const selectors = [
    ".batch-fill-sku-image-dialog input[type=file]",
    ".next-overlay-wrapper.opened input[type=file]",
    ".next-upload input[type=file]",
    "input[type=file][multiple]",
    "input[type=file]",
  ];
  for (const sel of selectors) {
    const loc = page.locator(sel).first();
    if (await loc.count()) return loc;
  }
  for (const frame of page.frames()) {
    const loc = frame.locator("input[type=file]").first();
    if (await loc.count()) return loc;
  }
  return null;
}

async function setFilesAnywhere(files) {
  if (!files || !files.length) return "NO_FILES";
  const loc = await fileInputLocator();
  if (!loc) return "NO_INPUT";
  try {
    await loc.setInputFiles(files, { timeout: 8000 });
    return "OK";
  } catch (e) {
    return "FAIL";
  }
}

function mergeUploadStatus(parts) {
  const ok = new Set();
  const failed = new Set();
  const acc = {
    uploading: false,
    success: false,
    fail: false,
    found: [],
    hasComplete: false,
    snippet: [],
    okNames: [],
    failedNames: [],
    networkError: false,
    retryable: false,
    items: [],
  };
  for (const cur of parts || []) {
    acc.uploading = acc.uploading || !!cur.uploading;
    acc.success = acc.success || !!cur.success;
    acc.hasComplete = acc.hasComplete || !!cur.hasComplete;
    acc.networkError = acc.networkError || !!cur.networkError;
    acc.retryable = acc.retryable || !!cur.retryable;
    acc.found = [...new Set([...acc.found, ...(cur.found || [])])];
    acc.snippet = [...acc.snippet, ...(cur.snippet || [])].slice(0, 8);
    acc.items = [...acc.items, ...(cur.items || [])].slice(0, 40);
    for (const name of cur.okNames || []) ok.add(name);
    for (const name of cur.failedNames || []) failed.add(name);
  }
  acc.okNames = [...ok];
  acc.failedNames = [...failed].filter((name) => !ok.has(name));
  acc.fail = acc.failedNames.length > 0 || (parts || []).some((cur) => cur.fail && !(cur.okNames || []).length && !(cur.failedNames || []).length);
  return acc;
}

async function waitUploadStatus(frame, names) {
  let status = mergeUploadStatus([]);
  for (let i = 0; i < 30; i++) {
    const parts = [];
    for (const ctx of uploadContexts(frame)) {
      try { parts.push(await readUploadStatus(ctx, names)); } catch (e) {}
    }
    status = mergeUploadStatus(parts);
    const want = (names || []).filter(Boolean).length;
    const resolved = !want || (status.okNames.length + status.failedNames.length) >= want;
    const hasUi = status.uploading || status.hasComplete || status.success || status.fail
      || status.okNames.length || status.failedNames.length || status.networkError;
    if (!hasUi && i >= 2) break;
    if (!status.uploading && (status.hasComplete || resolved || (status.success && !status.failedNames.length))) break;
    await sleep(1000);
  }
  return status;
}

async function retryUntilUploaded(frame, files, names, maxTries) {
  const retries = [];
  let status = await waitUploadStatus(frame, names);
  for (let attempt = 0; attempt < (maxTries || 3); attempt++) {
    const failed = (status.failedNames || []).filter(Boolean);
    if (!failed.length) break;
    if (!status.retryable && !status.networkError) break;
    const retryFiles = filesForNames(files, failed);
    if (!retryFiles.length) break;
    await sleep(1500 + attempt * 1200);
    const setFiles = await setFilesAnywhere(retryFiles);
    retries.push({
      attempt: attempt + 1,
      failed,
      setFiles,
      names: retryFiles.map(fileBase),
    });
    if (setFiles !== "OK") {
      return {
        status,
        retries,
        need_cli_upload: true,
        retryFiles,
        failedNames: failed,
        retryable: true,
        uploaded: false,
        complete: "SKIP",
      };
    }
    status = await waitUploadStatus(frame, names);
  }
  const complete = await waitUploadResultClosed();
  const failedNames = status.failedNames || [];
  return {
    status,
    retries,
    complete,
    failedNames,
    retryable: !!(status.retryable || status.networkError),
    networkError: !!status.networkError,
    uploaded: !failedNames.length,
  };
}

async function finishLocalUpload(frame, files, names) {
  let setFiles = await setFilesAnywhere(files);
  if (setFiles === "OK") {
    const retried = await retryUntilUploaded(frame, files, names);
    return { local: "SKIP", setFiles, via: "hidden-input", ...retried };
  }
  const inputs = frame ? await fileInputs(frame) : [];
  if (frame && inputs.length) setFiles = await trySetInputFiles(frame, files);
  if (setFiles !== "OK") {
    const status = await waitUploadStatus(frame, names);
    const already = !!(status && (status.success || status.hasComplete || (status.okNames || []).length || (status.found || []).length));
    if (!already) {
      return { local: "SKIP", inputs, setFiles, status, need_cli_upload: true, uploaded: false };
    }
  }
  const retried = await retryUntilUploaded(frame, files, names);
  return { local: "SKIP", inputs, setFiles, ...retried };
}

async function clickComplete(frame) {
  const clickIn = (ctx) => ctx.evaluate(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 4 && r.height > 4 && s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0;
    };
    const dialogs = [...document.querySelectorAll(".next-dialog, [class*='UploadPanel'], [class*='media-popup'], [class*='upload']")]
      .filter((el) => visible(el) && /上传结果|个文件上传/.test(el.innerText || ""));
    const scopes = dialogs.length ? [dialogs[dialogs.length - 1]] : [document];
    for (const scope of scopes) {
      const buttons = [...scope.querySelectorAll("button")].filter((el) => (el.innerText || "").trim() === "完成" && visible(el));
      const btn = buttons.find((el) => /primary/.test(el.className || "")) || buttons[buttons.length - 1];
      if (btn) {
        btn.click();
        return "OK";
      }
    }
    return "NO";
  });
  for (const ctx of uploadContexts(frame)) {
    try {
      if ((await clickIn(ctx)) === "OK") {
        await sleep(1000);
        return "OK";
      }
    } catch (e) {}
  }
  await sleep(300);
  return "NO";
}

async function hasUploadResult() {
  const check = () => {
    const t = (document.body && document.body.innerText) || "";
    if (!/上传结果/.test(t)) return false;
    if (!/个文件上传成功|上传成功|成功上传\s*\d+\s*个文件|有\d+个上传失败|请稍后重试|网络错误/.test(t)) return false;
    return [...document.querySelectorAll("button")].some((el) => {
      if ((el.innerText || "").trim() !== "完成") return false;
      const r = el.getBoundingClientRect();
      return r.width > 8 && r.height > 8;
    });
  };
  for (const ctx of uploadContexts(pictureSpaceFrame() || sucaiFrame())) {
    try { if (await ctx.evaluate(check)) return true; } catch (e) {}
  }
  return false;
}

async function waitUploadResultClosed(tries) {
  const frame = pictureSpaceFrame() || sucaiFrame();
  for (let i = 0; i < (tries || 12); i++) {
    if (!(await hasUploadResult())) return "CLOSED";
    await clickComplete(frame);
    await sleep(500);
  }
  return (await hasUploadResult()) ? "OPEN" : "CLOSED";
}

async function closeDialogsOnly() {
  return page.evaluate(() => {
    const btn = [...document.querySelectorAll(".sku-decouple-drawer button")].find((el) => /确认创建|完成/.test(el.innerText || ""));
    if (btn) btn.click();
    const roots = [...document.querySelectorAll(".next-dialog, .next-overlay-wrapper.opened .next-dialog, .batch-fill-sku-image-dialog")];
    let n = 0;
    for (const root of roots) {
      const close = root.querySelector(".next-dialog-close, [aria-label='关闭']");
      if (close) {
        try { close.click(); n += 1; } catch (e) {}
      }
    }
    return n;
  });
}

async function warehouseState() {
  const dom = await page.evaluate(() => {
    const group = [...document.querySelectorAll(".next-form-item, .sell-component-info-wrapper, [class*='form-item']")].find((el) => {
      const t = (el.innerText || "").replace(/\s+/g, "");
      return t.includes("上架时间") && t.includes("放入仓库") && t.includes("立刻上架") && t.length < 600;
    });
    const optionOn = (scope, name) => {
      const nodes = [...(scope || document).querySelectorAll("label, .next-radio-wrapper, [role='radio'], span, div")];
      const hit = nodes.find((el) => (el.innerText || "").replace(/\s+/g, "") === name);
      if (!hit) return false;
      const wrap = hit.closest(".next-radio-wrapper, [role='radio'], label") || hit;
      const input = wrap.querySelector("input[type='radio']")
        || (hit.parentElement && hit.parentElement.querySelector("input[type='radio']"));
      return !!(input && input.checked)
        || /checked/.test(wrap.className || "")
        || wrap.getAttribute("aria-checked") === "true";
    };
    return {
      found: !!group,
      warehouseOn: optionOn(group, "放入仓库"),
      instantOn: optionOn(group, "立刻上架"),
    };
  }).catch(() => ({ found: false, warehouseOn: false, instantOn: false }));
  if (dom && dom.found) {
    return { warehouseOn: !!dom.warehouseOn, instantOn: !!dom.instantOn, href: page.url(), via: "dom" };
  }
  const warehouseOn = await page.getByRole("radio", { name: "放入仓库" }).isChecked().catch(() => false);
  const instantOn = await page.getByRole("radio", { name: "立刻上架" }).isChecked().catch(() => false);
  return { warehouseOn: !!warehouseOn, instantOn: !!instantOn, href: page.url(), via: "role" };
}

async function selectWarehouseRadio() {
  await hideScenarioWidgets();
  await page.evaluate(() => {
    const hit = [...document.querySelectorAll("*")].find((el) => (el.childNodes.length <= 5) && (el.textContent || "").trim() === "上架时间");
    const root = hit && (hit.closest(".next-form-item, .sell-component-info-wrapper") || hit.parentElement);
    if (root) root.scrollIntoView({ block: "center" });
  }).catch(() => {});
  await sleep(200);
  let state = await warehouseState();
  if (state.warehouseOn && !state.instantOn) return state;
  const group = page.locator(".next-form-item, .sell-component-info-wrapper, [class*='form-item']").filter({ hasText: "上架时间" }).filter({ hasText: "放入仓库" }).first();
  if (await group.count()) {
    await group.getByText("放入仓库", { exact: true }).first().click({ timeout: 4000 }).catch(() => {});
    await sleep(300);
    state = await warehouseState();
    if (state.warehouseOn && !state.instantOn) return state;
  }
  await page.getByRole("radio", { name: "放入仓库" }).click({ timeout: 4000 }).catch(() => {});
  await sleep(300);
  state = await warehouseState();
  if (state.warehouseOn && !state.instantOn) return state;
  await page.evaluate(() => {
    const group = [...document.querySelectorAll(".next-form-item, .sell-component-info-wrapper, [class*='form-item']")].find((el) => {
      const t = (el.innerText || "").replace(/\s+/g, "");
      return t.includes("上架时间") && t.includes("放入仓库") && t.includes("立刻上架") && t.length < 600;
    });
    const scope = group || document;
    const hit = [...scope.querySelectorAll("label, .next-radio-wrapper, [role='radio'], span, div")].find((el) => (el.innerText || "").replace(/\s+/g, "") === "放入仓库");
    if (!hit) return "NO";
    const wrap = hit.closest(".next-radio-wrapper, [role='radio'], label") || hit;
    const inner = wrap.querySelector(".next-radio-inner, .next-radio, input[type='radio']") || wrap;
    inner.click();
    if (inner !== hit) hit.click();
    return "CLICK";
  }).catch(() => "ERR");
  await sleep(400);
  return warehouseState();
}
