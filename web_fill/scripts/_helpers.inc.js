const sleep = (ms) => page.waitForTimeout(ms);

function unsafeUrl(url) {
  const u = String(url || "");
  // Narrow authorization for a read-only-verified existing-item repair.
  // Never accept another item, another host, or a generic edit route.
  if (typeof PAYLOAD !== "undefined" && /^\d{8,20}$/.test(String(PAYLOAD.repairItemId || ""))) {
    try {
      // CLI's isolated runner does not expose the browser URL constructor.
      const match = u.match(/^https:\/\/item\.upload\.taobao\.com\/sell\/v2\/publish\.htm\?([^#]*)/);
      if (!match) return true;
      const ids = match[1].split('&').map(part => part.split('='))
        .filter(parts => decodeURIComponent(parts[0]) === 'itemId')
        .map(parts => decodeURIComponent(parts[1] || ''));
      return ids.length !== 1 || ids[0] !== String(PAYLOAD.repairItemId);
    } catch (_) { return true; }
  }
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
    return cards.map(el => [el.innerText, el.getAttribute('title'),
      ...[...el.querySelectorAll('[title], [data-file-name]')].map(node => node.getAttribute('title') || node.getAttribute('data-file-name'))]
      .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()).filter(Boolean).slice(0, 40);
  });
}

async function clickSucaiCard(frame, file, preferInner, single) {
  const exact = String(file || "").split(/[\\/]/).pop();
  return frame.evaluate(([fileName, inner, onlyOne]) => {
    // The material library stores '+' in uploaded filenames as a space.
    const normalize = value => String(value || "").replace(/\+/g, " ").replace(/\s+/g, " ").trim();
    const want = normalize(fileName);
    const identity = fileName.match(/^qn_[a-f0-9]{24}(?=[_.])/i)?.[0];
    const raw = [...document.querySelectorAll(".PicList_PicturesShow_main-show__QVvZn, [class*='PicturesShow_main-show'], .item.pic")].filter((el) => el.querySelector("img"));
    const seen = new Set();
    const cards = [];
    for (const el of raw) {
      const t = [el.innerText, el.getAttribute('title'), ...[...el.querySelectorAll('[title]')].map(node => node.getAttribute('title'))]
        .filter(Boolean).join(' ').replace(/\s+/g, " ").trim();
      if (!t || seen.has(t)) continue;
      seen.add(t);
      cards.push(el);
    }
    const labels = el => [el.innerText, el.getAttribute('title'), el.getAttribute('data-file-name'),
      ...[...el.querySelectorAll('[title], [data-file-name]')].map(node => node.getAttribute('title') || node.getAttribute('data-file-name'))]
      .filter(Boolean).map(normalize);
    const hits = cards.filter(el => labels(el).some(label => identity
      ? new RegExp('(?:^|\\s)' + identity + '(?=[_.\\s]|$)', 'i').test(label)
      : label.includes(want)));
    hits.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const card = hits.find((el) => (el.innerText || "").trim().startsWith(want)) || hits[0];
    if (!card) return { ok: false, n: cards.length, names: cards.slice(0, 8).map((el) => (el.innerText || "").replace(/\s+/g, " ").slice(0, 40)) };
    const checkbox = card.querySelector("input[type='checkbox']");
    const src = card.querySelector('img')?.getAttribute('src') || '';
    if (onlyOne) {
      if (checkbox && checkbox.disabled) return {ok: false, reason: 'NO_SELECTABLE_CHECKBOX'};
      // A reused picker can retain the previous row's selection. A ready
      // confirm button alone is not proof that the new image is selected.
      for (const old of document.querySelectorAll("input[type='checkbox']:checked")) {
        if (old !== checkbox) old.click();
      }
      if ([...document.querySelectorAll("input[type='checkbox']:checked")].some(el => el !== checkbox)) {
        return {ok: false, reason: 'STALE_SELECTION'};
      }
    }
    // Upload completion can preselect the last image. Selecting it again must
    // not toggle it off; the picker action is idempotent, not a blind click.
    if (checkbox && checkbox.checked) return {ok: true, alreadySelected: true, n: hits.length, src};
    if (checkbox && checkbox.disabled) return {ok: false, reason: "disabled", n: hits.length};
    const target = checkbox || (inner
      ? (card.querySelector(".select-icon, .cover, [class*='select-icon'], [class*='cover'], img") || card)
      : card);
    target.click();
    if (onlyOne && checkbox && (!checkbox.checked || [...document.querySelectorAll("input[type='checkbox']:checked")].some(el => el !== checkbox))) {
      return {ok: false, reason: 'SELECTION_NOT_EXCLUSIVE'};
    }
    return { ok: true, src, t: (card.innerText || "").replace(/\s+/g, " ").slice(0, 80), n: hits.length,
      target: target === card ? "card" : String(target.className || target.tagName || "inner").slice(0, 80) };
  }, [exact, !!preferInner, !!single]);
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

async function searchSucai(frame, query, maxPolls, reloadOnStale, queryPolicy) {
  if (!frame || !query) return "NO";
  query = String(query).replace(/\+/g, " ").replace(/\s+/g, " ").trim();
  const typed = await frame.evaluate((q) => {
    const input = document.querySelector("input[placeholder*='搜索'], input[type=search], input[placeholder*='图片']");
    if (!input) return "NO_BOX";
    input.focus();
    const proto = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value");
    if (proto && proto.set) proto.set.call(input, q);
    else input.value = q;
    input.dispatchEvent(new Event("input", { bubbles: true }));
    input.dispatchEvent(new Event("change", { bubbles: true }));
    return "OK";
  }, query).catch(() => "NO");
  if (typed !== "OK") return typed || "NO";
  // The picker uses controlled input state. A click in the same evaluate turn
  // can submit the previous query before the input event has been processed.
  await sleep(150);
  for (let attempt = 0; attempt < 2; attempt++) {
    await assertNoSecurityChallenge();
    if (attempt && frame.locator) {
      const input = frame.locator("input[placeholder*='搜索'], input[type=search], input[placeholder*='图片']").first();
      // A controlled input can show the new DOM value while React still holds
      // the previous query. Clear it first so fill always emits a fresh event.
      await input.fill("", { timeout: 3000 }).catch(() => {});
      await input.fill(query, { timeout: 3000 }).catch(() => {});
      await sleep(200);
    }
    await paceSucaiSearch(queryPolicy);
    if (attempt && frame.locator) {
      const input = frame.locator("input[placeholder*='搜索'], input[type=search], input[placeholder*='图片']").first();
      await input.press("Enter", { timeout: 3000 }).catch(() => {});
    } else await frame.evaluate(() => {
      const input = document.querySelector("input[placeholder*='搜索'], input[type=search], input[placeholder*='图片']");
      const btn = [...document.querySelectorAll("button, [role='button']")].find((el) =>
        (el.innerText || "").trim() === "搜索"
        || el.getAttribute("aria-label") === "搜索"
        || el.getAttribute("title") === "搜索");
      if (btn) btn.click();
      else if (input) input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", keyCode: 13, which: 13, bubbles: true }));
    }).catch(() => {});
    for (let i = 0; i < (maxPolls || 12); i++) {
      await sleep(400);
      const names = await listSucaiPics(frame);
      if (names.some((n) => n.includes(query))) return "OK";
    }
    await sleep(250);
  }
  if (reloadOnStale && frame.goto && frame.url) {
    try {
      await frame.goto(frame.url(), { waitUntil: "domcontentloaded", timeout: 20000 });
      await sleep(350);
      return await searchSucai(frame, query, maxPolls, false, queryPolicy);
    } catch (error) {
      // Keep the stale result below so the caller can report the failed SKU.
    }
  }
  const leftover = await listSucaiPics(frame);
  return "STALE:" + query + ":" + leftover.slice(0, 3).join("|");
}

async function paceSucaiSearch(policy) {
  if (typeof page.evaluate !== "function") return 0;
  let delay = 0;
  try {
    delay = await page.evaluate((options) => {
      const last = Number(sessionStorage.getItem("qianniu-last-sucai-query") || 0);
      const count = Number(sessionStorage.getItem("qianniu-sucai-query-count") || 0);
      const minMs = Math.max(5000, Number(options?.minMs) || 5000);
      const maxMs = Math.max(minMs, Number(options?.maxMs) || 10000);
      const cooldownEvery = Number(options?.cooldownEvery) || 0;
      const cooldownMs = Math.max(0, Number(options?.cooldownMs) || 0);
      const interval = minMs + Math.floor(Math.random() * (maxMs - minMs + 1))
        + (cooldownEvery && count && count % cooldownEvery === 0 ? cooldownMs : 0);
      return last ? Math.max(0, last + interval - Date.now()) : 0;
    }, policy || {});
  } catch (e) { return 0; }
  if (delay > 0) await sleep(delay);
  try { await page.evaluate(() => {
    sessionStorage.setItem("qianniu-last-sucai-query", String(Date.now()));
    const count = Number(sessionStorage.getItem("qianniu-sucai-query-count") || 0);
    sessionStorage.setItem("qianniu-sucai-query-count", String(count + 1));
  }); }
  catch (e) {}
  return delay;
}

async function missingSucaiNames(frame, names, maxPolls) {
  if (!frame) return [...new Set(names || [])];
  const listed = await listSucaiPics(frame);
  const candidates = missingPictureNames(listed, [...new Set(names || [])]);
  const missing = [];
  for (const name of candidates) {
    await searchSucai(frame, pictureIdentityQuery(name), maxPolls || 5);
    if (missingPictureNames(await listSucaiPics(frame), [name]).length) missing.push(name);
  }
  return missing;
}

function pictureIdentityQuery(name) {
  return String(name).match(/^qn_[a-f0-9]{24}(?=[_.])/i)?.[0]
    || String(name).replace(/\.[^.]+$/, "");
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
    return cards.map(el => [el.innerText, el.getAttribute('title'), el.getAttribute('data-file-name'),
      ...[...el.querySelectorAll('[title], [data-file-name]')].map(node => node.getAttribute('title') || node.getAttribute('data-file-name'))]
      .filter(Boolean).join(' ').replace(/\s+/g, ' ').trim()).filter(Boolean);
  });
}

function missingPictureNames(listed, want) {
  const normalize = value => String(value || "").replace(/\+/g, " ").replace(/\s+/g, " ").trim();
  const have = (listed || []).map(normalize);
  return (want || []).filter((name) => {
    // The library may re-encode PNG as JPG and reuse identical main/detail files.
    // Only our content-addressed names may ignore the original name/extension.
    const identity = String(name).match(/^qn_[a-f0-9]{24}(?=[_.])/i)?.[0];
    const pattern = identity && new RegExp('(?:^|\\s)' + identity + '(?=[_.\\s]|$)', 'i');
    return !have.some(t => pattern ? pattern.test(t) : t.includes(normalize(name)));
  });
}

async function clearPictureSpaceSelection(frame) {
  // Upload completion may preselect a card in completion order. Keep this
  // reset specific to ordered detail binding; other callers need idempotence.
  for (let attempt = 0; attempt < 50; attempt++) {
    const state = await frame.evaluate(() => {
      const selected = [...new Set([...document.querySelectorAll(".item.pic, [class*='PicturesShow']")]
        .flatMap(card => [...card.querySelectorAll("input[type='checkbox']:checked")]))];
      if (!selected.length) return "EMPTY";
      if (selected[0].disabled) return "DISABLED";
      selected[0].click();
      return "CLICKED";
    });
    if (state === "EMPTY") return;
    if (state === "DISABLED") break;
    await sleep(100);
  }
  throw new Error("PAUSE:详情图素材预选状态无法清除，未确认写入");
}

async function pickPictureSpaceCards(frame, names) {
  if (!frame) return [];
  const inspect = ({name, action, target}) => {
      // Preview/selection icons are also img elements. Identify a card by its
      // own selection control, not by the number of images inside it.
      const visible = el => {
        for (let node = el; node; node = node.parentElement) {
          const style = getComputedStyle(node);
          if (style.display === 'none' || style.visibility === 'hidden') return false;
        }
        return true;
      };
      const raw = [...document.querySelectorAll(".item.pic, [class*='PicturesShow']")]
        .filter(el => visible(el) && el.querySelector('img'));
      const normalize = value => String(value || '').replace(/\+/g, ' ').replace(/\s+/g, ' ').trim();
      const identity = String(name).match(/^qn_[a-f0-9]{24}(?=[_.])/i)?.[0];
      const pattern = identity && new RegExp('(?:^|\\s)' + identity + '(?=[_.\\s]|$)', 'i');
      const labels = el => [el.innerText, el.getAttribute('title'), el.getAttribute('data-file-name'),
        ...[...el.querySelectorAll('[title], [data-file-name]')].map(node => node.getAttribute('title') || node.getAttribute('data-file-name'))]
        .filter(Boolean).map(normalize);
      const want = normalize(name);
      const matches = el => labels(el).some(label => pattern ? pattern.test(label) : label.includes(want));
      const matched = raw.filter(matches);
      // Multiple-card wrappers must never lend another image's checkbox to a
      // matching label. Nested wrappers for the SAME checkbox collapse to the
      // innermost matching card so each material has exactly one candidate.
      const cards = raw.filter(el => el.querySelectorAll("input[type='checkbox']").length === 1);
      const hits = cards.filter(matches).filter(el => !cards.some(child => child !== el
        && el.contains(child) && matches(child)
        && child.querySelector("input[type='checkbox']") === el.querySelector("input[type='checkbox']")));
      const exact = el => labels(el).some(label => label === want || label.startsWith(want + ' '));
      const checked = el => {
        const box = el.querySelector("input[type='checkbox']");
        return !!(box && box.checked);
      };
      hits.sort((a, b) => {
        const exactDelta = Number(exact(b)) - Number(exact(a));
        if (exactDelta) return exactDelta;
        const checkedDelta = Number(checked(a)) - Number(checked(b));
        if (checkedDelta) return checkedDelta;
        return (a.innerText || "").length - (b.innerText || "").length;
      });
      const key = el => {
        const value = el.querySelector("input[type='checkbox']")?.getAttribute('value');
        // The real selector exposes a stable material ID here. Thumbnail URLs
        // and labels can change while lazy loading or adding a reference icon.
        return value && value !== 'on' ? 'material:' + value
          : JSON.stringify(labels(el));
      };
      const card = target ? hits.find(el => key(el) === target)
        : hits.find(el => exact(el) && !checked(el)) || hits.find(el => !checked(el)) || hits[0];
      if (!card) {
        return {name, ok: false, reason: target ? 'selection-lost' : matched.length ? 'unsupported-card' : 'not-found',
          n: cards.length, candidates: matched.slice(0, 3).map(el => ({
            cls: String(el.className || '').slice(0, 120),
            images: el.querySelectorAll('img').length,
            checkboxes: el.querySelectorAll("input[type='checkbox']").length,
          }))};
      }
      const checkbox = card.querySelector("input[type='checkbox']");
      const evidence = {name, target: key(card), n: hits.length,
        src: card.querySelector('img')?.getAttribute('src') || '',
        cls: String(card.className || '').slice(0, 120)};
      if (action === 'read') return {...evidence, ok: checkbox.checked,
        reason: checkbox.checked ? 'selected' : 'selection-unconfirmed'};
      if (checkbox && checkbox.checked) {
        return {...evidence, ok: true, alreadySelected: true};
      }
      if (checkbox && checkbox.disabled) {
        return {...evidence, ok: false, reason: 'disabled'};
      }
      checkbox.click();
      return {...evidence, ok: false, reason: 'selection-pending'};
  };
  const out = [];
  for (const name of names || []) {
    let one = await frame.evaluate(inspect, {name, action: 'select'});
    if (one.reason === 'selection-pending') {
      const target = one.target;
      let consecutive = 0;
      // Read fresh DOM after the framework processes the click. Never click a
      // second time on timeout: it could toggle a delayed selection back off.
      for (let attempt = 0; attempt < 12; attempt++) {
        await frame.evaluate(() => new Promise(resolve => window.setTimeout(resolve, 100)));
        one = await frame.evaluate(inspect, {name, action: 'read', target});
        consecutive = one.ok ? consecutive + 1 : 0;
        if (consecutive === 2) break;
      }
      if (consecutive < 2) one = {...one, ok: false, reason: 'selection-unconfirmed'};
    }
    out.push(one);
    if (!one.ok) break;
  }
  return out;
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
      const buttons = [...footer.querySelectorAll("button")].filter((el) => visible(el) && /^(确认|确定)(?:\s*[（(]\s*\d+\s*[）)])?$/.test((el.innerText || "").trim()));
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
      const btn = [...document.querySelectorAll("button, .btn, a")]
        .find((el) => /^(确认|确定)(?:\s*[（(]\s*\d+\s*[）)])?$/.test((el.innerText || "").trim()))
        || document.querySelector(".btn.btn-blue");
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
    await assertNoSecurityChallenge();
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
  for (const f of (typeof page.frames === "function" ? page.frames() : [])) {
    if (f !== frame && f !== page) list.push(f);
  }
  return [...new Set(list)].filter(ctx => ctx === page
    || typeof page.mainFrame !== "function" || ctx !== page.mainFrame());
}

async function uploadContextVisible(ctx) {
  // A hidden picker can retain an old failure receipt after it has closed.
  // Check every ancestor iframe, not only visibility inside its document.
  if (ctx === page || typeof ctx.parentFrame !== "function") return true;
  try {
    for (let current = ctx; current.parentFrame(); current = current.parentFrame()) {
      const element = await current.frameElement();
      try {
        if (!(await element.evaluate(el => {
          const rect = el.getBoundingClientRect();
          if (rect.width <= 4 || rect.height <= 4) return false;
          for (let node = el; node; node = node.parentElement) {
            const style = getComputedStyle(node);
            if (style.display === "none" || style.visibility === "hidden"
                || Number(style.opacity) === 0) return false;
          }
          return true;
        }))) return false;
      } finally {
        await element.dispose();
      }
    }
    return true;
  } catch (error) {
    return false; // Detached/closed iframe, not the active upload surface.
  }
}

async function securityChallengeReason() {
  const frame = typeof page.frames === "function" ? (pictureSpaceFrame() || sucaiFrame()) : null;
  for (const ctx of uploadContexts(frame)) {
    try {
      if (!(await uploadContextVisible(ctx))) continue;
      // The stream-upload challenge can use a baxia wrapper rather than the
      // older middleware class. A visible punish/captcha frame is sufficient.
      if (typeof ctx.url === "function" && /(?:\/punish(?:[/?#]|$)|[?&]action=captcha(?:&|$))/.test(ctx.url())) {
        return "滑块验证";
      }
      const visible = await ctx.evaluate(() => [...document.querySelectorAll(".J_MIDDLEWARE_FRAME_WIDGET")]
        .some((el) => {
          const rect = el.getBoundingClientRect();
          const style = getComputedStyle(el);
          return rect.width > 4 && rect.height > 4 && style.display !== "none"
            && style.visibility !== "hidden" && Number(style.opacity) !== 0
            && !!el.querySelector("iframe[src*='action=captcha'], iframe[src*='/punish']");
        }));
      if (visible) return "滑块验证";
    } catch (e) {}
  }
  return "";
}

async function assertNoSecurityChallenge() {
  const reason = await securityChallengeReason();
  if (reason) {
    await recordUploadPacingResult(false, undefined, "platform-verification");
    // Keep the challenge visible for the user. Dismissing it is not proof
    // that the platform has authorized further uploads.
    throw new Error("PAUSE:淘宝触发“" + reason + "”，请在浏览器手动完成验证后继续；已保留现场，未自动重试");
  }
}

function fileBase(path) {
  return String(path || "").split(/[\\/]/).pop();
}

function filesForNames(files, names) {
  const want = new Set((names || []).map((n) => String(n)));
  return (files || []).filter((p) => want.has(fileBase(p)));
}

async function readUploadStatus(ctx, names) {
  if (!(await uploadContextVisible(ctx))) return {};
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
    const dialogs = [...document.querySelectorAll(".batch-fill-sku-image-dialog, .next-dialog, [role='dialog'], .next-overlay-wrapper.opened, [class*='Upload'], [class*='upload'], [class*='dialog']")]
      .filter((el) => visible(el) && /上传结果/.test(el.innerText || "")
        && [...el.querySelectorAll("button")].some(b => (b.innerText || "").trim() === "完成"));
    dialogs.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const root = dialogs.length ? dialogs[0] : document.body;
    const text = (root && root.innerText) || body;
    const countMatch = dialogs.length ? text.match(/(\d+)\s*个文件\s*上传成功/) : null;
    const successCount = countMatch ? Number(countMatch[1]) : null;
    const batchComplete = !!(dialogs.length && hasComplete && successCount === (want || []).length
      && !/有\s*\d+\s*个上传失败|网络错误|请稍后重试/.test(text));
    const found = (want || []).filter((n) => n && text.includes(n));
    const items = [];
    const nodeTexts = dialogs.length && !batchComplete
      ? [...root.querySelectorAll("*")].map((el) => el.innerText || "").filter(Boolean) : [];
    for (const name of dialogs.length && !batchComplete ? (want || []) : []) {
      if (!name) continue;
      const others = (want || []).filter((n) => n && n !== name);
      const nodes = nodeTexts.filter((value) => value.includes(name));
      let best = "";
      let bestLen = Infinity;
      for (const t of nodes) {
        if (t.length >= bestLen) continue;
        if (others.some((n) => t.includes(n))) continue;
        best = t;
        bestLen = t.length;
      }
      const failed = /网络错误|请尝试禁止浏览器插件|换浏览器或者换电脑重试|操作过于频繁|请滑动验证码/.test(best)
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
    const securityLimit = /操作过于频繁|请滑动验证码/.test(text);
    return {
      uploading: /上传中/.test(text) || /上传中/.test(body),
      success: /上传成功|上传完成|\d+\s*个文件上传成功|成功上传\s*\d+\s*个文件/.test(text) || /上传成功/.test(body),
      fail: failedNames.length > 0 || /没有权限|无图片空间|有\s*\d+\s*个上传失败/.test(text),
      found,
      hasComplete,
      snippet: (text.match(/([^\n]*(?:上传|网络错误|操作过于频繁|验证码)[^\n]*)/g) || []).slice(0, 8),
      okNames,
      failedNames,
      networkError,
      retryable,
      securityLimit,
      securityEvidence: securityLimit ? [{
        source: dialogs.length ? "upload-result" : "visible-document",
        context: typeof location === "object" ? location.origin + location.pathname : "",
        text: (text.match(/[^\n]*(?:操作过于频繁|验证码)[^\n]*/g) || [])
          .slice(0, 3).map(line => line.trim().slice(0, 200)),
      }] : [],
      successCount,
      batchComplete,
      items,
    };
  }, names || []);
}

async function clickLocalUpload(frame) {
  const button = frame.getByRole("button", { name: "本地上传", exact: true }).first();
  if (!(await button.count())) return "NO";
  await button.click({ force: true, timeout: 8000 });
  await sleep(900);
  return "OK";
}

async function fileInputs(frame) {
  if (!frame) return [];
  return frame.evaluate(() => [...document.querySelectorAll("input[type=file]")].map((el) => ({
    id: el.id || "",
    multiple: !!el.multiple,
  })));
}

function uploadPacingPolicy(policy) {
  const options = policy || (typeof PAYLOAD === "object" && PAYLOAD ? PAYLOAD : {});
  const custom = options.uploadPacingOptions || {};
  const number = (key, fallback, min, max) => Math.max(min,
    Math.min(max, Number.isFinite(Number(custom[key])) ? Number(custom[key]) : fallback));
  const minGapMs = number("minGapMs", 12000, 0, 120000);
  const backoffBaseMs = number("backoffBaseMs", 120000, 1000, 900000);
  return {
    enabled: options.uploadPacing === true,
    initialDelayMs: number("initialDelayMs", 12000, 0, 120000),
    minGapMs, maxGapMs: Math.max(minGapMs, number("maxGapMs", 18000, 0, 120000)),
    windowMs: number("windowMs", 60000, 1000, 300000),
    maxFilesPerWindow: Math.floor(number("maxFilesPerWindow", 3, 1, 10)),
    backoffBaseMs,
    backoffMaxMs: Math.max(backoffBaseMs, number("backoffMaxMs", 900000, 1000, 3600000)),
  };
}

function effectiveUploadPacingPolicy(options, state) {
  // A cooldown expiring is not evidence that the old throughput is safe.
  // Keep a slower rate until distinct, verified receipts reduce the penalty.
  const penalty = Math.max(0, Math.min(8, Math.floor(Number(state.penalty) || 0)));
  const multiplier = Math.pow(2, Math.min(3, penalty));
  return {...options, recoveryMultiplier: multiplier,
    minGapMs: Math.min(120000, options.minGapMs * multiplier),
    maxGapMs: Math.min(120000, options.maxGapMs * multiplier),
    maxFilesPerWindow: Math.max(1, Math.floor(options.maxFilesPerWindow / multiplier))};
}

async function readUploadPacingState() {
  try {
    const state = await page.evaluate(() => {
      try { return JSON.parse(localStorage.getItem('qianniu-upload-pacing-v1') || '{}'); }
      catch (_) { return {}; }
    });
    if (state && state.version === 1) return state;
  } catch (_) {}
  return page.__qianniuUploadPacing || {};
}

async function writeUploadPacingState(state) {
  const saved = {...state, version: 1};
  page.__qianniuUploadPacing = saved;
  try {
    await page.evaluate(data => {
      localStorage.setItem('qianniu-upload-pacing-v1', JSON.stringify(data));
    }, saved);
  } catch (_) {} // Storage unavailable: retain same-page pacing at minimum.
  return saved;
}

function uploadReadyAt(state, policy, count, now) {
  let ready = Math.max(now, Number(state.nextAllowedAt) || 0);
  const recent = (state.recent || []).filter(entry => entry.at > now - policy.windowMs)
    .sort((a, b) => a.at - b.at);
  const capacity = Math.max(count, policy.maxFilesPerWindow);
  let total = recent.reduce((sum, entry) => sum + entry.count, 0);
  for (const entry of recent) {
    if (total + count <= capacity) break;
    ready = Math.max(ready, entry.at + policy.windowMs);
    total -= entry.count;
  }
  return ready;
}

async function waitForUploadTurn(frame, names, policy) {
  const options = uploadPacingPolicy(policy);
  if (!options.enabled) return null;
  if (!Array.isArray(names) || names.length !== 1) {
    throw new Error("图片上传失败：限流模式只允许逐张提交，已阻止批量突发");
  }
  let state = await readUploadPacingState();
  const started = Date.now();
  if (!state.lastDispatchAt && !state.nextAllowedAt) {
    state = await writeUploadPacingState({...state, nextAllowedAt: started + options.initialDelayMs});
  }
  let waitMs = 0;
  while (true) {
    await assertNoSecurityChallenge();
    const status = await collectUploadStatus(frame, names);
    if (status.securityLimit) await pauseForUploadSecurityLimit(status, names, "before-dispatch");
    state = await readUploadPacingState();
    const effective = effectiveUploadPacingPolicy(options, state);
    waitMs = uploadReadyAt(state, effective, names.length, Date.now()) - Date.now();
    if (waitMs <= 0) break;
    // These are local waits, not repeated upload/probe requests to Taobao.
    await sleep(Math.min(waitMs, 1000));
  }
  const now = Date.now();
  const effective = effectiveUploadPacingPolicy(options, state);
  const gapMs = effective.minGapMs + Math.floor(Math.random() * (effective.maxGapMs - effective.minGapMs + 1));
  // Reserve immediately before dispatch. A timeout/uncertain result still
  // consumes its slot, so switching phases cannot create a fresh burst.
  await writeUploadPacingState({...state, lastDispatchAt: now, gapMs,
    nextAllowedAt: now + gapMs,
    recent: [...(state.recent || []).filter(entry => entry.at > now - options.windowMs),
      {at: now, count: names.length}].slice(-100)});
  return {waitedMs: now - started, gapMs, windowMs: effective.windowMs,
    maxFilesPerWindow: effective.maxFilesPerWindow, recoveryMultiplier: effective.recoveryMultiplier};
}

async function recordUploadPacingResult(success, policy, reason) {
  const options = uploadPacingPolicy(policy);
  if (!options.enabled) return;
  const state = await readUploadPacingState();
  const now = Date.now();
  if (success) {
    if (!state.lastDispatchAt || state.finalizedDispatchAt === state.lastDispatchAt) return;
    const streak = (Number(state.successStreak) || 0) + 1;
    await writeUploadPacingState({...state, lastCompletedAt: now, finalizedDispatchAt: state.lastDispatchAt,
      nextAllowedAt: Math.max(Number(state.nextAllowedAt) || 0, now + (state.gapMs || options.minGapMs)),
      successStreak: streak >= 5 ? 0 : streak,
      penalty: streak >= 5 ? Math.max(0, (state.penalty || 0) - 1) : state.penalty || 0});
    return;
  }
  const failure = reason || 'unconfirmed';
  if (state.lastFailureDispatchAt === (state.lastDispatchAt || 0) && state.lastFailure === failure) return;
  const penalty = Math.min(8, (Number(state.penalty) || 0) + 1);
  const base = Math.min(options.backoffMaxMs, options.backoffBaseMs * Math.pow(2, penalty - 1));
  const backoffMs = Math.min(options.backoffMaxMs, base + Math.floor(Math.random() * Math.max(1, base / 4)));
  await writeUploadPacingState({...state, penalty, successStreak: 0, lastFailure: failure,
    lastFailureDispatchAt: state.lastDispatchAt || 0,
    lastFailureAt: now, nextAllowedAt: Math.max(Number(state.nextAllowedAt) || 0, now + backoffMs)});
}

async function pacedSetInputFiles(frame, files, policy) {
  await waitForUploadTurn(frame, files.map(fileBase), policy);
  return trySetInputFiles(frame, files);
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

async function guardLocalFileChooser(frame, enabled) {
  // 本地上传 initializes the widget, then clicks its file input. CLI returns
  // as soon as that native chooser opens, while this script can keep running
  // and call setInputFiles. Prevent the chooser's default action so only the
  // explicit setInputFiles below submits files; keep the widget's handlers.
  await frame.evaluate((active) => {
    const key = "__qianniuLocalFileChooserGuard";
    if (active && !document[key]) {
      const listener = (event) => {
        const input = event.target;
        if (input && input.tagName === "INPUT" && input.type === "file") event.preventDefault();
      };
      document[key] = listener;
      document.addEventListener("click", listener, true);
    } else if (!active && document[key]) {
      document.removeEventListener("click", document[key], true);
      delete document[key];
    }
  }, enabled);
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
  await waitForUploadTurn(null, files.map(fileBase));
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
    securityLimit: false,
    securityEvidence: [],
    successCount: null,
    batchComplete: false,
    items: [],
  };
  for (const cur of parts || []) {
    acc.uploading = acc.uploading || !!cur.uploading;
    acc.success = acc.success || !!cur.success;
    acc.hasComplete = acc.hasComplete || !!cur.hasComplete;
    acc.networkError = acc.networkError || !!cur.networkError;
    acc.retryable = acc.retryable || !!cur.retryable;
    acc.securityLimit = acc.securityLimit || !!cur.securityLimit;
    acc.securityEvidence.push(...(cur.securityEvidence || []));
    acc.batchComplete = acc.batchComplete || !!cur.batchComplete;
    if (cur.successCount != null) acc.successCount = cur.successCount;
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

async function collectUploadStatus(frame, names) {
  const parts = [];
  for (const ctx of uploadContexts(frame)) {
    try { parts.push(await readUploadStatus(ctx, names)); } catch (e) {}
  }
  return mergeUploadStatus(parts);
}

async function waitUploadStatus(frame, names) {
  let status = mergeUploadStatus([]);
  const limit = Math.min(160, Math.max(45, (names || []).length * 5));
  for (let i = 0; i < limit; i++) {
    await assertNoSecurityChallenge();
    status = await collectUploadStatus(frame, names);
    if (status.securityLimit) break;
    const want = (names || []).filter(Boolean).length;
    const resolved = status.batchComplete || !want || (status.okNames.length + status.failedNames.length) >= want;
    const hasUi = status.uploading || status.hasComplete || status.success || status.fail
      || status.okNames.length || status.failedNames.length || status.networkError;
    if (!hasUi && i >= 5) break;
    if (status.batchComplete || (!status.uploading && (resolved || status.fail
      || (status.hasComplete && status.successCount != null)))) break;
    await sleep(1000);
  }
  return status;
}

async function pauseForUploadSecurityLimit(status, names, phase) {
  // Backoff is persisted for future authorized runs; this function still
  // stops immediately. It never attempts to solve or dismiss a challenge.
  await recordUploadPacingResult(false, undefined, "platform-verification");
  const diagnostic = {
    at: new Date().toISOString(), phase: phase || "receipt-check", names: names || [],
    securityEvidence: status.securityEvidence || [],
    okNames: status.okNames || [], failedNames: status.failedNames || [],
    successCount: status.successCount, snippet: status.snippet || [],
  };
  // Preserve the evidence and do not claim that an uncertain upload failed.
  const message = phase === "before-dispatch"
    ? 'PAUSE:淘宝当前仍提示操作过于频繁；本次未提交图片，已保留现场。请解除限制后再继续'
    : 'PAUSE:淘宝提示操作过于频繁；上传结果尚未确认，已停止自动重试并保留现场。请解除限制后核验素材';
  throw new Error(message + '\nUPLOAD_SECURITY_DIAGNOSTIC:' + JSON.stringify(diagnostic));
}

async function retryUntilUploaded(frame, files, names, maxTries) {
  await assertNoSecurityChallenge();
  const retries = [];
  let status = await waitUploadStatus(frame, names);
  if (status.securityLimit) await pauseForUploadSecurityLimit(status, names);
  const retryLimit = maxTries == null ? 3 : Math.max(0, maxTries);
  for (let attempt = 0; attempt < retryLimit; attempt++) {
    const failed = (status.failedNames || []).filter(Boolean);
    if (!failed.length) break;
    if (!status.retryable && !status.networkError) break;
    const retryFiles = filesForNames(files, failed);
    if (!retryFiles.length) break;
    await assertNoSecurityChallenge();
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
    if (status.securityLimit) await pauseForUploadSecurityLimit(status, names);
  }
  const failedNames = status.failedNames || [];
  const allNamed = (names || []).length === 0 || [...new Set(names)].every(name =>
    (status.okNames || []).includes(name));
  const countMatches = status.batchComplete || status.successCount == null
    || status.successCount === (names || []).length;
  let uploaded = !status.fail && !failedNames.length
    && countMatches && (status.batchComplete || (!status.uploading && allNamed));
  let complete = uploaded ? await waitUploadResultClosed() : "UNCONFIRMED";
  let verifiedBy = uploaded ? "upload-result" : "";
  let missing = [];
  // Taobao sometimes includes an earlier queued file in the result count.
  // Confirm the actual target filenames in the material library before
  // accepting an oversized batch count.
  if (!uploaded && frame && status.hasComplete && !status.uploading && !status.fail
      && !failedNames.length && status.successCount >= (names || []).length
      && (status.found || []).length) {
    complete = await waitUploadResultClosed();
    if (complete === "CLOSED") {
      missing = await missingSucaiNames(frame, names, 5);
      uploaded = missing.length === 0;
      if (uploaded) verifiedBy = "library-search";
    }
  }
  // The result dialog can settle without a usable success count even though
  // every requested file is already listed in it, and can also disappear
  // before CLI reads a number at all. In both cases treat a closed popup plus
  // a library search that names every target file as proof of success,
  // instead of reporting a slow receipt as a failed upload.
  if (!uploaded && frame && !status.uploading && !status.fail && !failedNames.length) {
    const wanted = (names || []).filter(Boolean);
    const namedAll = wanted.length && wanted.every(name => (status.found || []).includes(name));
    // 成功回执缺失的兜底：弹窗已出"完成"且点名覆盖全部目标文件，
    // 或弹窗已消失（页面读不到任何回执）时，关闭弹窗后到素材库点名复核，
    // 全命中即判成功，避免把"回执慢/弹窗提前关闭"误报为失败。
    const silent = !status.hasComplete && !status.success && !status.fail
      && !(status.okNames || []).length && !(status.found || []).length;
    // 弹窗消失（!hasComplete）且素材库可用时，一律兜底复核，不管是否有残留状态。
    // 但上传中（uploading=true）或素材库 iframe 丢失时，不做复核，避免误判。
    const popupGone = !status.hasComplete && !status.uploading && !status.fail && !failedNames.length;
    // An empty current receipt cannot tell whether an earlier upload started.
    // Verify names without submitting the files again.
    if ((status.hasComplete && namedAll) || silent || popupGone) {
      const closed = status.hasComplete ? await waitUploadResultClosed() : "CLOSED";
      complete = closed === "OPEN" ? complete : "CLOSED";
      missing = await missingSucaiNames(frame, names, 5);
      uploaded = missing.length === 0;
      if (uploaded) verifiedBy = "library-search";
    }
  }
  return {
    status,
    retries,
    complete,
    verifiedBy,
    missing,
    failedNames,
    retryable: !!(status.retryable || status.networkError),
    networkError: !!status.networkError,
    uploaded: uploaded && complete === "CLOSED",
    error: uploaded && complete !== "CLOSED" ? "图片上传结果弹窗未关闭" : "",
  };
}

async function finishLocalUploadBatch(frame, files, names, policy) {
  await assertNoSecurityChallenge();
  // Do not open a main-image picker or target a different file input here.
  if (!frame) frame = await waitFrame(pictureSpaceFrame, 8);
  if (!frame) throw new Error("图片上传失败：素材库未打开，已停止提交文件");
  const before = await collectUploadStatus(frame, names);
  if (before.securityLimit) await pauseForUploadSecurityLimit(before, names, "before-dispatch");
  if (before.uploading || before.hasComplete) {
    // A previous run may still own the input/result. Verify it, never race it.
    const verified = await retryUntilUploaded(frame, files, names, 0);
    return {local: "SKIP", via: "pending-receipt", ...verified,
      dispatched: false, dispatchUncertain: true, need_cli_upload: false};
  }
  let setFiles = (await fileInputs(frame)).length ? await pacedSetInputFiles(frame, files, policy) : "NO_INPUT";
  if (setFiles === "OK" || setFiles === "TIMEOUT") {
    // A timeout may occur after the browser has accepted the file. Verify only.
    const retried = await retryUntilUploaded(frame, files, names, 0);
    await recordUploadPacingResult(retried.uploaded === true, policy);
    return { local: "SKIP", setFiles, via: "hidden-input", ...retried,
      dispatched: true, dispatchUncertain: setFiles !== "OK", need_cli_upload: false };
  }
  const inputs = frame ? await fileInputs(frame) : [];
  if (setFiles !== "OK") {
    const status = await waitUploadStatus(frame, names);
    if (status.securityLimit) await pauseForUploadSecurityLimit(status, names, "before-dispatch");
    const already = !!(status && !status.uploading && !status.fail && names.length
      && (status.batchComplete || names.every(name => (status.okNames || []).includes(name))));
    if (!already) {
      // The material picker creates its input asynchronously after 本地上传.
      // Scope the input to this picker, never the page's SKU import control.
      if (!frame) throw new Error("图片上传失败：素材库未打开，重新打开后仍无法访问");
      let ready = false;
      let reloaded = false;
      try {
        for (let attempt = 0; attempt < 2; attempt++) {
          if (attempt) {
            await frame.goto(frame.url(), { waitUntil: "domcontentloaded", timeout: 20000 });
            reloaded = true;
          }
          await guardLocalFileChooser(frame, true);
          const localButton = frame.getByRole("button", { name: "本地上传", exact: true }).first();
          await localButton.waitFor({ state: "attached", timeout: 10000 });
          await localButton.evaluate(el => el.click());
          try {
            await frame.locator("input[type=file]").first().waitFor({ state: "attached", timeout: 8000 });
            ready = true;
            break;
          } catch (error) {
            if (attempt) throw new Error("图片上传失败：素材库上传控件初始化失败，刷新重试后仍无文件输入框");
          }
        }
        if (!ready) throw new Error("图片上传失败：素材库上传控件未就绪");
        await assertNoSecurityChallenge();
        const initialized = await collectUploadStatus(frame, names);
        if (initialized.securityLimit) await pauseForUploadSecurityLimit(initialized, names, "before-dispatch");
        setFiles = await pacedSetInputFiles(frame, files, policy);
        const retried = await retryUntilUploaded(frame, files, names, 0);
        await recordUploadPacingResult(retried.uploaded === true, policy);
        return { local: "OK", inputs, setFiles, via: "picker-input-batch", reloaded, ...retried,
          dispatched: true, dispatchUncertain: setFiles !== "OK", need_cli_upload: false };
      } finally {
        await guardLocalFileChooser(frame, false).catch(() => {});
      }
    }
  }
  const retried = await retryUntilUploaded(frame, files, names, 0);
  return { local: "SKIP", inputs, setFiles, dispatched: setFiles === "OK", ...retried };
}

async function finishLocalUpload(frame, files, names, policy) {
  const options = policy || (typeof PAYLOAD === "object" && PAYLOAD ? PAYLOAD : {});
  const requested = Number(options.uploadBatchSize) || 0;
  const batchSize = uploadPacingPolicy(options).enabled ? 1
    : requested > 0 ? Math.max(1, Math.min(6, requested)) : files.length;
  const legacyDelay = Number(options.uploadBatchDelayMs) || 0;
  const delayMinMs = Math.max(1500, Number(options.uploadBatchDelayMinMs) || legacyDelay || 5000);
  const delayMaxMs = Math.max(delayMinMs, Number(options.uploadBatchDelayMaxMs) || (legacyDelay ? legacyDelay + 700 : 10000));
  const uploadPolicy = { batchSize, delayMinMs, delayMaxMs, pacing: uploadPacingPolicy(options) };
  if (!files.length || files.length <= batchSize) {
    const result = await finishLocalUploadBatch(frame, files, names, options);
    return { ...result, uploadPolicy, batches: [{ index: 1, names, waitBeforeMs: 0,
      uploaded: result.uploaded === true }] };
  }
  const batches = [];
  let dispatchedAny = false;
  for (let offset = 0; offset < files.length; offset += batchSize) {
    await assertNoSecurityChallenge();
    let waitBeforeMs = 0;
    if (offset) {
      waitBeforeMs = delayMinMs + Math.floor(Math.random() * (delayMaxMs - delayMinMs + 1));
      await sleep(waitBeforeMs);
      await assertNoSecurityChallenge();
    }
    const partFiles = files.slice(offset, offset + batchSize);
    const partNames = partFiles.map(fileBase);
    const result = await finishLocalUploadBatch(frame, partFiles, partNames, options);
    if (result.dispatched) dispatchedAny = true;
    batches.push({
      index: batches.length + 1,
      names: partNames,
      waitBeforeMs,
      uploaded: result.uploaded === true,
      verifiedBy: result.verifiedBy || "",
      error: result.error || "",
    });
    if (result.uploaded !== true) {
      return { ...result, via: "throttled-batches", uploadPolicy, batches, uploaded: false, dispatched: dispatchedAny || result.dispatched === true };
    }
  }
  return {
    local: "OK",
    setFiles: "OK",
    via: "throttled-batches",
    uploaded: true,
    complete: "CLOSED",
    verifiedBy: "throttled-batches",
    uploadPolicy,
    status: {
      uploading: false,
      success: true,
      fail: false,
      batchComplete: true,
      successCount: names.length,
      okNames: names,
      failedNames: [],
    },
    batches,
    dispatched: dispatchedAny,
  };
}

async function clickComplete(frame) {
  const clickIn = (ctx) => ctx.evaluate(() => {
    const visible = (el) => {
      if (!el) return false;
      const r = el.getBoundingClientRect();
      const s = getComputedStyle(el);
      return r.width > 4 && r.height > 4 && s.display !== "none" && s.visibility !== "hidden" && Number(s.opacity) !== 0;
    };
    const dialogs = [...document.querySelectorAll(".batch-fill-sku-image-dialog, .next-dialog, [role='dialog'], .next-overlay-wrapper.opened, [class*='UploadPanel'], [class*='media-popup'], [class*='upload']")]
      .filter((el) => visible(el) && /上传结果/.test(el.innerText || "")
        && [...el.querySelectorAll("button")].some(b => (b.innerText || "").trim() === "完成" && visible(b)));
    dialogs.sort((a, b) => (a.innerText || "").length - (b.innerText || "").length);
    const scopes = dialogs.length ? [dialogs[0]] : [document];
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
      if (!(await uploadContextVisible(ctx))) continue;
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
    try {
      if (await uploadContextVisible(ctx) && await ctx.evaluate(check)) return true;
    } catch (e) {}
  }
  return false;
}

async function waitUploadResultClosed(tries) {
  const frame = pictureSpaceFrame() || sucaiFrame();
  for (let i = 0; i < (tries || 12); i++) {
    await assertNoSecurityChallenge();
    const status = await collectUploadStatus(frame, []);
    if (status.securityLimit) await pauseForUploadSecurityLimit(status, []);
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
