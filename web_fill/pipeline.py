"""按已核验剧本填写新建发布页。不覆盖当前得力页，默认不点提交。"""

import importlib
import importlib.util
import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CATEGORY_ENTRY = "https://item.upload.taobao.com/sell/ai/category.htm"


def get_scripts():
    raw = os.environ.get("QIANNIU_SCRIPTS_DIR")
    return Path(raw) if raw else Path(__file__).resolve().parent / "scripts"


def get_output():
    raw = os.environ.get("QIANNIU_OUTPUT_DIR")
    return Path(raw) if raw else ROOT / "output" / "playwright"


def get_helpers():
    return (get_scripts() / "_helpers.inc.js").read_text(encoding="utf-8")


def reload_paths():
    global SCRIPTS, OUTPUT, HELPERS
    SCRIPTS = get_scripts()
    OUTPUT = get_output()
    HELPERS = get_helpers()


SCRIPTS = get_scripts()
OUTPUT = get_output()
HELPERS = get_helpers() if (get_scripts() / "_helpers.inc.js").is_file() else ""


ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]")


def strip_cli_text(text):
    return ANSI_ESCAPE.sub("", str(text or ""))


def _web_candidates():
    paths = []
    root_env = os.environ.get("QIANNIU_ROOT")
    if root_env:
        paths.append(Path(root_env) / "千牛网页执行.py")
    paths.append(ROOT / "千牛网页执行.py")
    exe_dir = Path(sys.executable).resolve().parent
    paths.append(exe_dir / "千牛网页执行.py")
    seen = set()
    unique = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _load_web():
    existing = sys.modules.get("千牛网页执行") or sys.modules.get("qianniu_web")
    if existing is not None:
        return existing
    for path in _web_candidates():
        if path.is_file():
            spec = importlib.util.spec_from_file_location("千牛网页执行", path)
            if spec is None or spec.loader is None:
                continue
            module = importlib.util.module_from_spec(spec)
            sys.modules["千牛网页执行"] = module
            spec.loader.exec_module(module)
            return module
    return importlib.import_module("千牛网页执行")


def _prune_tabs(web=None, **kwargs):
    web = web or _load_web()
    fn = getattr(web, "prune_automation_tabs", None)
    if not callable(fn):
        return None
    try:
        return fn(**kwargs)
    except Exception:
        return None


def _abs(path):
    if path in (None, ""):
        return ""
    return Path(path).resolve().as_posix()


def product_to_payload(product):
    skus = []
    for item in product.get("skus") or []:
        image = item.get("image") or ""
        name = str(item.get("name") or "").strip()
        skus.append({
            "slot": str(item.get("slot") or "").strip(),
            "name": name,
            "image": _abs(image),
            "file": Path(image).name if image else "",
            "price": item.get("price", item.get("价格")),
            "stock": item.get("stock", item.get("库存")),
        })
    mains = [_abs(p) for p in (product.get("main_images") or []) if p]
    portraits = [_abs(p) for p in (product.get("portrait_images") or []) if p]
    details = [_abs(p) for p in (product.get("detail_images") or []) if p]
    category = str(product.get("category") or "")
    leaf = category.replace(">>", ">").split(">")[-1].strip() if category else "中性笔"
    attrs = dict(product.get("attributes") or {})
    if not str(attrs.get("IP联名") or "").strip() and "火影" in str(product.get("title") or ""):
        attrs["IP联名"] = "火影忍者"
    return {
        "title": str(product.get("title") or "").strip(),
        "guide_title": str(product.get("guide_title") or "").strip(),
        "brand": str(product.get("brand") or "").strip(),
        "model": str(product.get("model") or "").strip(),
        "leaf": leaf,
        "attributes": attrs,
        "skus": skus,
        "thickness": str(product.get("thickness") or "0.05mm").strip() or "0.05mm",
        "sku_category": str(product.get("sku_category") or "单品").strip() or "单品",
        "ship_time": str(product.get("ship_time") or "").strip(),
        "ship_from": str(product.get("ship_from") or "").strip(),
        "freight": str(product.get("freight") or "").strip(),
        "stock_deduction": str(product.get("stock_deduction") or "拍下减库存").strip(),
        "main_images": mains,
        "portrait_images": portraits,
        "detail_images": details,
    }


def render_script(name, payload):
    src = (get_scripts() / name).read_text(encoding="utf-8")
    blob = json.dumps(payload, ensure_ascii=False)
    rendered = src.replace("/*PAYLOAD*/", blob, 1).replace("/*HELPERS*/", get_helpers(), 1)
    out = get_output()
    out.mkdir(parents=True, exist_ok=True)
    target = out / f"web_fill_{Path(name).stem}.js"
    target.write_text(rendered, encoding="utf-8")
    return target


class FileChooserNeeded(RuntimeError):
    pass


def extract_result(out):
    marker = "### Result"
    ran = "### Ran Playwright code"
    chunk = out
    if marker in out and ran in out:
        chunk = out.split(marker, 1)[1].split(ran, 1)[0].strip()
    if not chunk:
        return {}
    if chunk.startswith('"') or chunk.startswith("'"):
        chunk = json.loads(chunk)
    if isinstance(chunk, (dict, list)):
        return chunk
    try:
        return json.loads(chunk)
    except json.JSONDecodeError:
        return {"raw": str(chunk)[:4000]}


def _looks_like_filechooser(text):
    return "File chooser" in str(text or "") or "does not handle the modal" in str(text or "")


def _is_user_pause(exc):
    text = str(exc or "")
    if _looks_like_filechooser(text):
        return False
    if re.search(r"(?:^|\n)\s*(?:Error:\s*)?PAUSE:", text):
        return True
    head = text.split("### Ran Playwright code", 1)[0]
    return "REFUSE" in head


def run_script(session, name, payload, timeout=120):
    path = render_script(name, payload)
    try:
        out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=timeout)
    except RuntimeError as exc:
        text = str(exc)
        out = get_output()
        raw_path = out / f"web_fill_{Path(name).stem}.raw.txt"
        out.mkdir(parents=True, exist_ok=True)
        raw_path.write_text(text, encoding="utf-8", errors="replace")
        if _looks_like_filechooser(text):
            raise FileChooserNeeded(strip_cli_text(text)) from exc
        raise RuntimeError(strip_cli_text(text)) from exc
    raw_path = get_output() / f"web_fill_{Path(name).stem}.raw.txt"
    raw_path.write_text(out, encoding="utf-8", errors="replace")
    if _looks_like_filechooser(out):
        raise FileChooserNeeded(strip_cli_text(out))
    if "### Error" in out and "### Result" not in out:
        raise RuntimeError(strip_cli_text(out.split("### Error", 1)[-1].strip())[:800])
    result = extract_result(out)
    (get_output() / f"web_fill_{Path(name).stem}.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if isinstance(result, dict) and result.get("error") and str(result["error"]).startswith("PAUSE"):
        raise RuntimeError(result["error"])
    return result


def parse_tabs(text):
    tabs = []
    for line in str(text or "").splitlines():
        match = re.search(r"(https?://\S+)", line)
        if not match:
            continue
        index_match = re.search(r"(\d+)", line)
        tabs.append((int(index_match.group(1)) if index_match else len(tabs), match.group(1).rstrip("],)")))
    return tabs


def _is_category_url(url):
    return "category.htm" in str(url or "").lower()


def _is_reusable_publish(url, web):
    href = str(url or "")
    if not web.is_publish_page(href):
        return False
    low = href.lower()
    return "itemid=" not in low and "edit.htm" not in low and "item_num_id=" not in low


def _select_reusable_publish(session, web):
    try:
        listed = parse_tabs(session.tab_list())
    except Exception:
        return None
    candidates = [(index, url) for index, url in listed if _is_reusable_publish(url, web)]
    if not candidates:
        return None
    index, url = candidates[-1]
    try:
        session.tab_select(index)
        time.sleep(0.4)
    except Exception:
        return url
    current = (session.href() or url or "").strip()
    if _is_reusable_publish(current, web):
        return current
    return url if _is_reusable_publish(url, web) else None


def ensure_fill_tab(session, web=None, force_new=False):
    """优先接着已打开的新建发布页填，避免每次新开标签从头来。"""
    web = web or _load_web()
    session.attach()
    href = (session.href() or "").strip()
    web.assert_safe_url(href)
    if force_new:
        return ensure_new_category_tab(session, web), "new-category"
    if _is_reusable_publish(href, web):
        return href, "reuse-publish"
    found = _select_reusable_publish(session, web)
    if found:
        return found, "reuse-publish"
    href = (session.href() or "").strip()
    if _is_category_url(href):
        web.assert_logged_in(href)
        return href, "reuse-category"
    try:
        listed = parse_tabs(session.tab_list())
    except Exception:
        listed = []
    for index, url in listed:
        if _is_category_url(url):
            session.tab_select(index)
            time.sleep(0.3)
            current = (session.href() or url or "").strip()
            if _is_category_url(current) or _is_category_url(url):
                web.assert_logged_in(current or url)
                return current or url, "reuse-category"
    return ensure_new_category_tab(session, web), "new-category"


def ensure_new_category_tab(session, web=None):
    web = web or _load_web()
    session.attach()
    href = session.href()
    web.assert_safe_url(href)
    before = []
    try:
        before = parse_tabs(session.tab_list())
    except Exception:
        before = []
    before_indexes = {index for index, _ in before}
    session.tab_new(CATEGORY_ENTRY)
    listed = before
    for _ in range(15):
        time.sleep(0.4)
        try:
            listed = parse_tabs(session.tab_list())
        except Exception:
            listed = before
        new_cats = [(index, url) for index, url in listed if "category.htm" in url.lower() and index not in before_indexes]
        if not new_cats:
            new_cats = [(index, url) for index, url in listed if "category.htm" in url.lower()]
        if not new_cats:
            continue
        index, url = new_cats[-1]
        session.tab_select(index)
        current = (session.href() or url or "").strip()
        if "category.htm" not in current.lower():
            current = url
        if "category.htm" in current.lower():
            web.assert_safe_url(current)
            try:
                web.assert_logged_in(current, session.body_text(800))
            except Exception:
                web.assert_logged_in(current)
            return current
    raise RuntimeError("未能打开新的类目页标签，已停止以免覆盖当前发布页")


def _write_progress(steps):
    out = get_output()
    out.mkdir(parents=True, exist_ok=True)
    (out / "web_fill_progress.json").write_text(
        json.dumps(steps, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def short_fail_notice(text):
    blob = " ".join(str(text or "").split())
    blob = re.sub(r"^(?:Error:\s*)+", "", blob)
    if "规格未写入" in blob or "无法新增规格行" in blob:
        hit = re.search(r"(规格未写入|无法新增规格行)\s*[^\"{]{0,40}", blob)
        return (hit.group(0) if hit else "规格未写入").strip()[:80]
    if "规格图未保存到SKU表格" in blob:
        return "规格图未保存到SKU表格"
    if "规格图未绑定" in blob:
        hit = re.search(r"规格图未绑定到SKU(?:\s+\d+/\d+)?", blob)
        return (hit.group(0) if hit else "规格图未绑定到SKU").strip()[:80]
    if re.search(r"timed out after \d+ seconds", blob, re.I) or "TimeoutExpired" in blob or (
        blob.startswith("Command") and "run-code" in blob
    ):
        if "attributes" in blob:
            return "填写属性超时，请重试"
        if "category" in blob:
            return "选择类目超时，请重试"
        if "warehouse" in blob:
            return "放入仓库超时，请重试"
        return "页面操作超时，请重试"
    blob = re.sub(r"上架时间\s*请根据实际需要[^\s。；;]{0,24}", " ", blob)
    blob = re.sub(r"请根据实际需要，?选择上架时间。?", " ", blob)
    parts = []
    for pattern in (
        r"错误\s*\(\d+\)",
        r"\d+\s*商品属性必填项未填",
        r"必填项未填",
        r"上架时间未选择",
        r"放入仓库未选中",
        r"[^\s；;]{1,40}未填",
        r"不能为空",
        r"PAUSE:[^\n]{1,80}",
    ):
        match = re.search(pattern, blob)
        if not match:
            continue
        piece = match.group(0).strip()
        if piece.startswith("PAUSE:"):
            piece = piece[6:].strip()
        if piece and piece not in parts:
            parts.append(piece)
    if parts:
        return "；".join(parts)[:200]
    if "帮助" in blob or "反馈" in blob:
        blob = re.sub(r"帮助|反馈", " ", blob)
        blob = " ".join(blob.split())
    return blob[:120]


def required_blockers(probe):
    if not isinstance(probe, dict):
        return []
    parts = []
    banners = [str(item) for item in (probe.get("banners") or [])]
    blob = " ".join(banners)
    match = re.search(r"错误\s*\(\d+\)", blob)
    if match:
        parts.append(match.group(0))
    attr = re.search(r"\d+\s*商品属性必填项未填", blob)
    if attr:
        parts.append(attr.group(0))
    elif "必填项未填" in blob:
        parts.append("必填项未填")
    empty = []
    for item in probe.get("empty") or []:
        name = str(item or "").strip()
        if name and name not in empty:
            empty.append(name)
    if empty:
        parts.append("、".join(empty) + "未填")
    if probe.get("warehouseOn") is False:
        parts.append("上架时间未选择")
    return parts


def _warehouse_on(ware, session, web):
    if isinstance(ware, dict) and "warehouseOn" in ware:
        return bool(ware.get("warehouseOn")) and not ware.get("instantOn")
    try:
        return web.warehouse_selected(session.snapshot())
    except Exception:
        return False


def _prepare_submit(session, payload, web, steps):
    ware = run_script(session, "warehouse.js", {}, timeout=40)
    steps.append({"step": "warehouse", "result": ware})
    _write_progress(steps)
    if not _warehouse_on(ware, session, web):
        ware = run_script(session, "warehouse.js", {}, timeout=40)
        steps.append({"step": "warehouse", "result": ware})
        _write_progress(steps)
    if not _warehouse_on(ware, session, web):
        return False, "放入仓库未选中，已停止以免立刻上架"
    probe = {}
    try:
        probe = run_script(session, "probe_errors.js", payload or {}, timeout=40)
    except Exception:
        probe = {}
    blockers = required_blockers(probe)
    if blockers:
        try:
            refill = run_script(session, "attributes.js", payload or {}, timeout=150)
            steps.append({"step": "attributes", "result": {"refill": True, "result": refill}})
            _write_progress(steps)
        except Exception as exc:
            steps.append({"step": "attributes", "result": {"refill": True, "error": str(exc)[:200]}})
        try:
            ware = run_script(session, "warehouse.js", {}, timeout=40)
            steps.append({"step": "warehouse", "result": ware})
        except Exception:
            pass
        try:
            probe = run_script(session, "probe_errors.js", payload or {}, timeout=40)
        except Exception:
            probe = {}
        blockers = required_blockers(probe)
        if blockers:
            return False, "；".join(blockers)[:200]
    if not _warehouse_on(ware, session, web) and probe.get("warehouseOn") is False:
        return False, "放入仓库未选中，已停止以免立刻上架"
    if probe.get("warehouseOn") is False:
        return False, "上架时间未选择"
    return True, ""


def _finish_publish(session, payload, confirm_submit, web, steps):
    snap = session.snapshot()
    ware = None
    if not web.warehouse_selected(snap):
        ware = run_script(session, "warehouse.js", {}, timeout=40)
        steps.append({"step": "warehouse", "result": ware})
        _write_progress(steps)
        snap = session.snapshot()
    if not _warehouse_on(ware, session, web) and not web.warehouse_selected(snap):
        raise RuntimeError("放入仓库未选中，已停止以免立刻上架")
    links = _empty_action_links()
    if confirm_submit:
        ready, reason = _prepare_submit(session, payload, web, steps)
        if not ready:
            return {
                "execution": "提交失败",
                "notice": reason,
                "errors": [reason],
                "steps": steps,
                "url": session.href(),
                **links,
            }
        submitted = run_script(session, "submit.js", payload, timeout=60)
        steps.append({"step": "submit", "result": submitted})
        _write_progress(steps)
        execution, notice, links = _submit_outcome(session, submitted)
    else:
        execution = web.maybe_submit(session, False, snap)
        notice = "已选择放入仓库"
    result = {
        "execution": execution,
        "notice": notice,
        "errors": [],
        "steps": steps,
        "url": session.href(),
    }
    result.update(links)
    return result


def page_looks_in_progress(state, payload):
    if not isinstance(state, dict):
        return False
    title = str(state.get("title") or "")
    want = str((payload or {}).get("title") or "")
    if want and title and (want[:10] in title or title[:10] in want):
        return True
    if int(state.get("skuRows") or 0) > 0:
        return True
    if int(state.get("mainImgs") or 0) > 0:
        return True
    if int(state.get("detailImgs") or 0) > 0:
        return True
    if int(state.get("specImgs") or 0) > 0:
        return True
    return False


def _remember_item(product, item, status=None):
    try:
        import job_session
        job_session.patch_execution(
            item.get("row", product.get("row")),
            item.get("product_id") or product.get("product_id"),
            item.get("execution") or "",
            notice=item.get("notice") or "",
            errors=item.get("errors"),
            status=status,
            extra={
                "taobao_item_id": item.get("taobao_item_id") or "",
                "view_url": item.get("view_url") or "",
                "edit_url": item.get("edit_url") or "",
            },
        )
    except Exception:
        pass


def _empty_action_links():
    return {"taobao_item_id": "", "view_url": "", "edit_url": ""}


def _submit_outcome(session, submitted):
    submitted = submitted or {}
    raw = submitted.get("notice") or submitted.get("text") or ""
    if submitted.get("hasSuccess") or not submitted.get("hasFail"):
        execution = "结果待核实"
        notice = short_fail_notice(raw) if submitted.get("hasFail") else (short_fail_notice(raw) or "已提交")
        item_id = re.search(r"商品ID[:：]\s*(\d{8,})", str(raw))
        if item_id and "商品ID" not in notice:
            notice = ("提交成功 商品ID: " + item_id.group(1) + (" " + notice if notice and notice != "已提交" else "")).strip()
    else:
        execution = "提交失败"
        notice = short_fail_notice(raw) or "提交失败"
    href = str(submitted.get("href") or "")
    try:
        if session:
            href = session.href() or href
    except Exception:
        pass
    links = dict(_empty_action_links())
    try:
        import job_session
        links = job_session.product_action_links(submitted=submitted, notice=notice, href=href)
    except Exception:
        pass
    return execution, notice, links


DONE_EXECUTIONS = frozenset({"已填写未提交", "结果待核实"})
KAYOU_ITEM_ID = "1085558349142"


def _as_state(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def page_conflicts(state, payload):
    """True when the open publish page already holds a different product."""
    if not isinstance(state, dict):
        return False
    title = str(state.get("title") or "").strip()
    want = str((payload or {}).get("title") or "").strip()
    has_content = any(int(state.get(key) or 0) > 0 for key in ("skuRows", "specImgs", "mainImgs", "detailImgs", "p34Imgs"))
    if not title and not has_content:
        return False
    if want and title:
        return title != want
    return bool(want and has_content)


def decide_skips(state, payload):
    """Already-filled sections on the current publish page. Conservative."""
    skips = set()
    if not page_looks_in_progress(state, payload):
        return skips
    want_skus = len((payload or {}).get("skus") or [])
    want_mains = len((payload or {}).get("main_images") or [])
    want_portraits = len((payload or {}).get("portrait_images") or [])
    want_details = len((payload or {}).get("detail_images") or [])
    sku_rows = int(state.get("skuRows") or 0)
    spec_imgs = int(state.get("specImgs") or 0)
    main_imgs = int(state.get("mainImgs") or 0)
    p34_imgs = int(state.get("p34Imgs") or 0)
    detail_imgs = int(state.get("detailImgs") or 0)
    spec_dialog = bool(state.get("specDialog"))
    popup = bool(state.get("popup"))
    spec_incomplete = bool(want_skus) and spec_imgs < want_skus
    if (spec_dialog or popup) and spec_incomplete:
        skips.update({"attributes", "skus"})
        return skips
    if want_skus and sku_rows >= want_skus:
        skips.add("skus")
    if want_skus and spec_imgs >= want_skus:
        skips.add("spec_images")
    if want_mains and main_imgs >= want_mains:
        skips.add("main_images")
    if want_portraits and p34_imgs >= want_portraits:
        skips.add("portraits")
    if want_details and detail_imgs >= want_details:
        skips.add("details")
    return skips


def _probe_fill_state(session, payload):
    try:
        return _as_state(run_script(session, "probe_state.js", payload, timeout=40))
    except Exception:
        return {}


def _maybe_close_overlays(session):
    try:
        run_script(session, "close_overlays.js", {}, timeout=40)
    except Exception:
        pass


def select_kayou_tab(session, allow_item_id=KAYOU_ITEM_ID):
    tabs = session.tab_list()
    ranked = []
    for index, url in parse_tabs(tabs):
        low = url.lower()
        if "deli" in low or "%E5%BE%97%E5%8A%9B" in url or "s11" in low:
            continue
        if allow_item_id and allow_item_id in url:
            if "publish.htm" in low:
                ranked.append((0, index, url))
            elif "success.htm" in low:
                ranked.append((2, index, url))
            else:
                ranked.append((1, index, url))
        elif "publish.htm" in url and "%E5%8D%A1%E6%B8%B8" in url:
            if "itemid=" in low and (not allow_item_id or allow_item_id not in url):
                continue
            ranked.append((3, index, url))
    if not ranked:
        raise RuntimeError("未找到卡游页标签（成功页/编辑页/发布页）")
    ranked.sort()
    _, index, url = ranked[0]
    session.tab_select(index)
    time.sleep(0.5)
    return url


def _dismiss_filechooser(session):
    try:
        session.press("Escape")
        time.sleep(0.3)
    except Exception:
        pass


UPLOAD_RETRY_LIMIT = 2
RETRYABLE_UPLOAD_RE = re.compile(
    r"网络错误|请稍后重试|请尝试禁止浏览器插件|换浏览器或者换电脑重试"
)


def _upload_status(result):
    if not isinstance(result, dict):
        return {}
    status = result.get("status")
    return status if isinstance(status, dict) else result


def _status_text(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    parts = []
    for blob in (data, status):
        if not isinstance(blob, dict):
            continue
        parts.extend(str(x) for x in (blob.get("snippet") or []) if x)
        parts.extend(str(x) for x in (blob.get("failedNames") or []) if x)
        for key in ("error", "after_err", "msg"):
            if blob.get(key):
                parts.append(str(blob[key]))
    return " ".join(parts)


def retryable_upload_failure(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    if any(data.get(key) or status.get(key) for key in ("retryable", "networkError")):
        return True
    return bool(RETRYABLE_UPLOAD_RE.search(_status_text(data)))


def failed_upload_names(result):
    data = result if isinstance(result, dict) else {}
    status = _upload_status(data)
    failed = [str(name) for name in (data.get("failedNames") or status.get("failedNames") or []) if name]
    if failed:
        return failed
    missing = [str(name) for name in (data.get("missing") or []) if name]
    if missing and (retryable_upload_failure(data) or data.get("uploaded") is False or status.get("fail")):
        return missing
    return []


def _files_named(files, names):
    want = {str(name) for name in (names or [])}
    return [path for path in (files or []) if Path(path).name in want]


def _retry_failed_image_uploads(session, script, payload, files, opened, uploaded, attempts=UPLOAD_RETRY_LIMIT):
    current = uploaded
    log = []
    seen_retryable = retryable_upload_failure(opened) or retryable_upload_failure(uploaded)
    for attempt in range(1, max(1, attempts) + 1):
        failed = failed_upload_names(current) or (failed_upload_names(opened) if attempt == 1 else [])
        if not failed:
            break
        if not (retryable_upload_failure(current) or seen_retryable):
            break
        seen_retryable = True
        retry_files = _files_named(files, failed) or list(files or [])
        if not retry_files:
            break
        entry = {"attempt": attempt, "files": [Path(path).name for path in retry_files]}
        time.sleep(1.2 + (attempt - 1))
        try:
            entry["rest"] = _upload_one_by_one(session, retry_files)
        except FileChooserNeeded:
            try:
                session.upload_files(*retry_files[:1], timeout=90)
                entry["via"] = "chooser"
            except Exception as exc:
                entry["err"] = str(exc)[:160]
                log.append(entry)
                break
        except Exception as exc:
            entry["err"] = str(exc)[:160]
            log.append(entry)
            break
        try:
            current = run_script(session, script, {**payload, "phase": "after_upload", "files": retry_files}, timeout=180)
        except FileChooserNeeded:
            _dismiss_filechooser(session)
            entry["after"] = "filechooser"
            log.append(entry)
            break
        except Exception as exc:
            current = {"after_err": str(exc)[:200]}
            entry["after_err"] = str(exc)[:160]
            log.append(entry)
            break
        log.append(entry)
    if log and isinstance(current, dict):
        current = {**current, "cli_retries": log}
    return current, log


def _try_cli_upload(session, files, timeout=90):
    files = [path for path in (files or []) if path]
    if not files:
        return {"via": "skip"}
    try:
        session.upload_files(*files[:1], timeout=timeout)
        time.sleep(0.6)
        return {"via": "cli_modal", "first": Path(files[0]).name}
    except Exception as exc:
        _dismiss_filechooser(session)
        return {"via": "cli_fail", "error": str(exc)[:200]}


def _clear_filechooser(session, files):
    if files:
        session.upload_files(*files, timeout=180)
        time.sleep(1.0)
        return {"via": "cli_modal"}
    _dismiss_filechooser(session)
    return {"via": "escape"}


def _upload_or_set(session, open_result, files, after_script, extra):
    if open_result.get("need_cli_upload") or open_result.get("error") == "NO_INPUT":
        session.upload_files(*files, timeout=180)
        return run_script(session, after_script, {**extra, "phase": "after_upload", "files": files}, timeout=120)
    if open_result.get("uploaded"):
        try:
            closed = run_script(session, after_script, {**extra, "phase": "after_upload", "files": files}, timeout=120)
            return {**open_result, "after": closed}
        except Exception as exc:
            return {**open_result, "after_err": str(exc)[:200]}
    if open_result.get("error"):
        raise RuntimeError(open_result["error"])
    return open_result


def _upload_one_by_one(session, files):
    log = []
    for path in files:
        try:
            run_script(session, "click_upload_btn.js", {}, timeout=20)
        except FileChooserNeeded:
            pass
        except Exception as exc:
            log.append({"click": str(exc)[:120]})
        try:
            session.upload_files(path, timeout=90)
            log.append({"ok": Path(path).name})
            time.sleep(0.8)
        except FileChooserNeeded:
            session.upload_files(path, timeout=90)
            log.append({"ok": Path(path).name})
        except Exception as exc:
            if _looks_like_filechooser(exc):
                session.upload_files(path, timeout=90)
                log.append({"ok": Path(path).name})
            else:
                log.append({"err": Path(path).name, "msg": str(exc)[:160]})
    return log


def pick_from_library(session, script, payload):
    opened = {}
    try:
        opened = run_script(session, script, {**payload, "phase": "open_library"}, timeout=90)
    except FileChooserNeeded:
        files = payload.get("files") or [s.get("image") for s in (payload.get("skus") or []) if s.get("image")]
        if files:
            session.upload_files(files[0], timeout=90)
            time.sleep(0.8)
        opened = {"via": "cli_modal"}
    phase = "bind" if script == "spec_images.js" else "select"
    try:
        picked = run_script(session, script, {**payload, "phase": phase, "files": payload.get("files") or []}, timeout=180)
    except FileChooserNeeded:
        try:
            session.press("Escape")
        except Exception:
            pass
        picked = run_script(session, script, {**payload, "phase": phase}, timeout=180)
    return {"open": opened, "pick": picked}


def spec_images_unbound(step, payload):
    need = len([item for item in (payload or {}).get("skus") or [] if item.get("image")])
    if not need or not isinstance(step, dict):
        return False
    bound = step.get("bind") if isinstance(step.get("bind"), dict) else step
    if not isinstance(bound, dict):
        return False
    # The picker can report every card selected even when the drawer did not persist images.
    # Treat the explicit persistence result as authoritative before falling back to legacy bind logs.
    if bound.get("saved") is False:
        return True
    if bound.get("saved") is True:
        return False
    filled = bound.get("filledCount")
    if filled is not None:
        try:
            return int(filled) < need
        except (TypeError, ValueError):
            return False
    log = bound.get("bindLog")
    if not isinstance(log, list) or not log:
        return False
    ok = 0
    miss = 0
    for item in log:
        pic = item.get("picClick") or item.get("pic") or {}
        click = item.get("skuClick")
        if isinstance(click, dict):
            click = str(click.get("how") or "")
        else:
            click = str(click or "")
        if pic.get("ok") or click == "HAS_IMG":
            ok += 1
        elif click.startswith("NO_") or click in {"NO_DIALOG", "NO_ROW", "NO_EMPTY"}:
            miss += 1
    return ok == 0 and miss == len(log)


GATE_RETRY_LIMIT = 5
HARD_PAUSE_WORDS = ("登录", "验证码", "滑块")


def hard_pause_reason(text):
    blob = str(text or "")
    for word in HARD_PAUSE_WORDS:
        if word in blob:
            return word
    return ""


def gate_error_retryable(exc):
    text = str(exc or "")
    if hard_pause_reason(text):
        return False
    notice = short_fail_notice(text) or text
    blob = text + " " + notice
    needles = (
        "规格未写入",
        "无法新增规格行",
        "规格图未绑定",
        "规格图未保存到SKU表格",
        "未找到编辑规格",
        "规格抽屉",
        "书写粗细",
        "超时",
        "timed out",
        "TimeoutExpired",
        "未进入新建发布页",
        "类目页",
        "放入仓库未选中",
        "NO_FRAME",
        "PAUSE:",
        "File chooser",
    )
    return any(item in blob for item in needles)


def _spec_unbound_error(specs, payload):
    bound = specs.get("bind") if isinstance(specs.get("bind"), dict) else {}
    filled = bound.get("filledCount")
    need = len([item for item in (payload or {}).get("skus") or [] if item.get("image")])
    if bound.get("saved") is False:
        return RuntimeError("规格图未保存到SKU表格")
    extra = (" " + str(filled) + "/" + str(need)) if filled is not None else ""
    return RuntimeError("规格图未绑定到SKU" + extra)


def _spec_frame_error(specs):
    bound = specs.get("bind") if isinstance(specs, dict) and isinstance(specs.get("bind"), dict) else {}
    diagnostics = bound.get("diagnostics") if isinstance(bound.get("diagnostics"), dict) else {}
    parts = []
    if diagnostics.get("url"):
        parts.append("页面=" + str(diagnostics["url"])[:180])
    if diagnostics.get("dialog") is not None:
        parts.append("弹窗=" + str(diagnostics.get("dialog")))
    frame_urls = diagnostics.get("frameUrls")
    if isinstance(frame_urls, list):
        parts.append("iframe=" + (" | ".join(str(url)[:120] for url in frame_urls[-4:]) or "无"))
    return RuntimeError("规格图素材库 iframe 未加载" + ("；" + "；".join(parts) if parts else ""))


def _clear_gate_overlays(session):
    try:
        run_script(session, "close_overlays.js", {}, timeout=20)
    except Exception:
        pass
    try:
        session.press("Escape")
    except Exception:
        pass


def run_gate(session, name, payload, steps, step, timeout=120, attempts=GATE_RETRY_LIMIT):
    last = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            result = run_script(session, name, payload, timeout=timeout)
            steps.append({"step": step, "result": result, "attempt": attempt})
            _write_progress(steps)
            return result
        except Exception as exc:
            last = exc
            steps.append({"step": step, "attempt": attempt, "error": short_fail_notice(str(exc)) or str(exc)[:160]})
            _write_progress(steps)
            if (not gate_error_retryable(exc)) or attempt >= attempts:
                raise
            _clear_gate_overlays(session)
            time.sleep(0.7 + (attempt - 1) * 0.5)
    raise last


def spec_images_gate(session, payload, steps, attempts=GATE_RETRY_LIMIT):
    spec_files = [item["image"] for item in (payload.get("skus") or []) if item.get("image")]
    last = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            specs = _image_step(session, "spec_images.js", payload, spec_files)
            steps.append({"step": "spec_images", "attempt": attempt, **specs})
            _write_progress(steps)
            bound = specs.get("bind") if isinstance(specs, dict) else None
            if isinstance(bound, dict) and bound.get("hadFrame") is False:
                raise _spec_frame_error(specs)
            if spec_images_unbound(specs, payload):
                raise _spec_unbound_error(specs, payload)
            return specs
        except Exception as exc:
            last = exc
            if "spec_images" not in str((steps[-1] or {}).get("step") if steps else ""):
                steps.append({"step": "spec_images", "attempt": attempt, "error": short_fail_notice(str(exc)) or str(exc)[:160]})
                _write_progress(steps)
            if (not gate_error_retryable(exc)) or attempt >= attempts:
                raise
            _clear_gate_overlays(session)
            time.sleep(0.7 + (attempt - 1) * 0.5)
    raise last


def _image_step(session, script, payload, files):
    opened = {"skipped": True}
    pick_phase = "bind" if script == "spec_images.js" else "select"
    library_first = script == "details.js"
    try:
        opened = run_script(session, script, {**payload, "phase": "open"}, timeout=180)
    except FileChooserNeeded:
        opened = {"via": "filechooser"}
        if files:
            result = _try_cli_upload(session, files)
            opened.update(result)
            rest = files[1:] if str(result.get("via") or "").startswith("cli_modal") else files
            if rest:
                opened["rest"] = _upload_one_by_one(session, rest)
            if library_first:
                opened["via"] = "library-after-chooser"
        else:
            _dismiss_filechooser(session)
    else:
        already = bool(
            opened.get("already")
            or opened.get("via") == "library"
            or opened.get("skipUpload")
        )
        if already:
            opened["uploaded"] = True
        elif opened.get("need_cli_upload") and files:
            opened["rest"] = _upload_one_by_one(session, files)
        elif script == "spec_images.js" and (opened.get("hadFrame") is False or opened.get("error")):
            # 规格图必须先进入素材库选择器；这里走系统文件选择器会把每张图拖成 90 秒超时。
            opened["upload_blocked"] = "spec-picker-unavailable"
        elif not opened.get("uploaded") and files and not library_first:
            opened["rest"] = _upload_one_by_one(session, files)
    uploaded = opened
    try:
        uploaded = run_script(session, script, {**payload, "phase": "after_upload", "files": files}, timeout=180)
    except FileChooserNeeded:
        if library_first:
            _dismiss_filechooser(session)
            uploaded = {**opened, "after": "dismissed"}
        else:
            _try_cli_upload(session, files)
            try:
                uploaded = run_script(session, script, {**payload, "phase": "after_upload", "files": files}, timeout=180)
            except Exception as exc:
                uploaded = {"after_err": str(exc)[:200]}
    except Exception as exc:
        uploaded = {"after_err": str(exc)[:200], "open": opened}
    uploaded, retry_log = _retry_failed_image_uploads(session, script, payload, files, opened, uploaded)
    if retry_log and isinstance(opened, dict):
        opened = {**opened, "cli_retries": retry_log}
    bound = {}
    try:
        bound = run_script(session, script, {**payload, "phase": pick_phase, "files": files}, timeout=180)
    except FileChooserNeeded:
        _dismiss_filechooser(session)
        try:
            bound = run_script(session, script, {**payload, "phase": pick_phase, "files": files}, timeout=180)
        except FileChooserNeeded:
            _dismiss_filechooser(session)
            bound = {"error": "filechooser", "picked": []}
        except Exception as exc:
            bound = {"error": str(exc)[:200]}
    return {"open": opened, "upload": uploaded, "bind": bound}


def complete_current_product(session, product, confirm_submit=True, web=None):
    """在已打开的卡游新建页补完并入库，不覆盖得力页。"""
    web = web or _load_web()
    payload = product_to_payload(product)
    steps = []
    execution = "失败"
    notice = ""
    _write_progress([])
    session.attach()
    href = select_kayou_tab(session)
    web.assert_safe_url(href)
    steps.append({"step": "resume-tab", "url": href})
    _write_progress(steps)
    try:
        first_img = (payload.get("skus") or [{}])[0].get("image") or (payload.get("main_images") or [None])[0]
        listed = session.tab_list()
        if _looks_like_filechooser(listed) and first_img:
            session.upload_files(first_img, timeout=90)
            time.sleep(0.8)
        try:
            session.press("Escape")
        except Exception as exc:
            if _looks_like_filechooser(exc) and first_img:
                session.upload_files(first_img, timeout=90)
                time.sleep(0.8)
            else:
                pass

        def _safe_script(name, timeout=120):
            try:
                return run_script(session, name, payload, timeout=timeout)
            except FileChooserNeeded:
                if first_img:
                    session.upload_files(first_img, timeout=90)
                    time.sleep(0.8)
                return run_script(session, name, payload, timeout=timeout)

        attributes = _safe_script("attributes.js", 150)
        steps.append({"step": "attributes", "result": attributes})
        tags = _safe_script("fill_tags.js", 60)
        steps.append({"step": "tags", "result": tags})
        _write_progress(steps)

        if payload["skus"]:
            cats = _safe_script("sku_category.js", 90)
            steps.append({"step": "sku_category", "result": cats})
            thick = _safe_script("thickness.js", 90)
            steps.append({"step": "thickness", "result": thick})
            _write_progress(steps)
            specs = spec_images_gate(session, payload, steps)

        if payload["main_images"]:
            main = _image_step(session, "main_images.js", {
                "files": payload["main_images"],
                "names": [Path(p).name for p in payload["main_images"]],
                "field": "#sell-field-mainImagesGroup",
            }, payload["main_images"])
            steps.append({"step": "main_1_1", **main})
            _write_progress(steps)

        if payload["detail_images"]:
            details = _image_step(session, "details.js", {
                "files": payload["detail_images"],
                "names": [Path(p).name for p in payload["detail_images"]],
            }, payload["detail_images"])
            steps.append({"step": "details", **details})
            _write_progress(steps)

        logistics = run_script(session, "logistics.js", payload, timeout=90)
        steps.append({"step": "logistics", "result": logistics})
        _write_progress(steps)

        result = _finish_publish(session, payload, confirm_submit, web, steps)
        execution = result.get("execution") or execution
        notice = result.get("notice") or notice
        return result
    except Exception as exc:
        execution = "暂停" if hard_pause_reason(str(exc)) else "失败"
        notice = short_fail_notice(str(exc)) or str(exc)[:160]
        try:
            if web.is_publish_page(session.href()):
                run_script(session, "warehouse.js", {}, timeout=40)
        except Exception:
            pass
        return {
            "execution": execution,
            "notice": notice,
            "errors": [notice],
            "steps": steps,
            "url": "",
        }
    finally:
        _write_progress(steps + [{"step": "end", "execution": execution, "notice": notice}])


def fill_new_product(session, product, confirm_submit=False, web=None, force_new=False):
    web = web or _load_web()
    payload = product_to_payload(product)
    steps = []
    execution = "失败"
    notice = ""
    _write_progress([])
    try:
        href, how = ensure_fill_tab(session, web, force_new=force_new)
        steps.append({"step": "tab", "url": href, "how": how})
        _write_progress(steps)

        skips = set()
        if how == "reuse-publish":
            state = _probe_fill_state(session, payload)
            skips = decide_skips(state, payload)
            steps.append({
                "step": "probe",
                "result": {key: state.get(key) for key in (
                    "title", "skuRows", "specImgs", "mainImgs", "p34Imgs", "detailImgs", "popup", "specDialog"
                )},
                "skips": sorted(skips),
            })
            _write_progress(steps)
            if page_conflicts(state, payload):
                href = ensure_new_category_tab(session, web)
                how = "new-category"
                skips = set()
                steps.append({"step": "tab", "url": href, "how": "conflict-new-category"})
                _write_progress(steps)
            else:
                continue_spec = bool(payload.get("skus")) and "spec_images" not in skips
                dialog_open = bool(state.get("specDialog") or state.get("popup"))
                if dialog_open and not continue_spec:
                    _maybe_close_overlays(session)

        if how != "reuse-publish":
            category = run_gate(session, "category.js", payload, steps, "category", timeout=90)
            web.assert_safe_url(session.href())
            if not web.is_publish_page(session.href()):
                raise RuntimeError("未进入新建发布页: " + session.href())
        else:
            steps.append({"step": "category", "result": {"skipped": True, "reason": how, "url": href, "skips": sorted(skips)}})
            _write_progress(steps)

        if "attributes" in skips:
            steps.append({"step": "attributes", "result": {"skipped": True}})
            _write_progress(steps)
        else:
            attributes = run_gate(session, "attributes.js", payload, steps, "attributes", timeout=150)

        if payload["skus"]:
            if "skus" in skips:
                steps.append({"step": "skus", "result": {"skipped": True}})
                _write_progress(steps)
            else:
                skus = run_gate(session, "skus.js", payload, steps, "skus", timeout=300)

            if "spec_images" in skips:
                steps.append({"step": "spec_images", "skipped": True})
                _write_progress(steps)
            else:
                specs = spec_images_gate(session, payload, steps)

        if payload["main_images"]:
            if "main_images" in skips:
                steps.append({"step": "main_1_1", "skipped": True})
                _write_progress(steps)
            else:
                main = _image_step(session, "main_images.js", {
                    "files": payload["main_images"],
                    "names": [Path(p).name for p in payload["main_images"]],
                    "field": "#sell-field-mainImagesGroup",
                }, payload["main_images"])
                steps.append({"step": "main_1_1", **main})
                _write_progress(steps)

        if payload["portrait_images"]:
            if "portraits" in skips:
                steps.append({"step": "main_3_4", "skipped": True})
                _write_progress(steps)
            else:
                portraits = _image_step(session, "main_images.js", {
                    "files": payload["portrait_images"],
                    "names": [Path(p).name for p in payload["portrait_images"]],
                    "field": "#sell-field-threeToFourImages",
                }, payload["portrait_images"])
                steps.append({"step": "main_3_4", **portraits})
                _write_progress(steps)

        if payload["detail_images"]:
            if "details" in skips:
                steps.append({"step": "details", "skipped": True})
                _write_progress(steps)
            else:
                details = _image_step(session, "details.js", {
                    "files": payload["detail_images"],
                    "names": [Path(p).name for p in payload["detail_images"]],
                }, payload["detail_images"])
                steps.append({"step": "details", **details})
                _write_progress(steps)

        logistics = run_script(session, "logistics.js", payload, timeout=90)
        steps.append({"step": "logistics", "result": logistics})
        _write_progress(steps)

        result = _finish_publish(session, payload, confirm_submit, web, steps)
        execution = result.get("execution") or execution
        notice = result.get("notice") or notice
        return result
    except web.SessionLost as exc:
        execution, notice = "暂停", str(exc)
        raise
    except Exception as exc:
        execution = "暂停" if hard_pause_reason(str(exc)) else "失败"
        notice = short_fail_notice(str(exc)) or str(exc)[:160]
        return {
            "execution": execution,
            "notice": notice,
            "errors": [notice],
            "url": session.href() if session else "",
            "steps": steps,
        }
    finally:
        try:
            if session and web.is_publish_page(session.href()):
                run_script(session, "warehouse.js", {}, timeout=40)
        except Exception:
            pass
        _write_progress(steps + [{"step": "end", "execution": execution, "notice": notice}])


def run_batch(products, confirm_submit=False, limit=None, session=None, cancel_event=None, on_item_start=None, on_item_done=None, force_new=False):
    _write_progress([])
    web = _load_web()
    selected = list(products or [])
    if limit:
        selected = selected[:limit]
    if not selected:
        return []
    own_session = session is None
    session = session or web.CliSession()
    session.attach()
    href = session.href()
    web.assert_logged_in(href, session.snapshot())
    try:
        _prune_tabs(web, keep_url=href, keep_fill_pages=True)
    except Exception:
        pass
    updated = []
    need_new_tab = False
    for product in selected:
        if cancel_event is not None and cancel_event.is_set():
            item = dict(product)
            item["execution"] = "已停止"
            item["notice"] = "用户停止任务"
            item["errors"] = []
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            _remember_item(product, item, status="stopped")
            break
        prior = str(product.get("execution") or "")
        if not force_new and prior in DONE_EXECUTIONS:
            item = dict(product)
            item["execution"] = prior
            item["notice"] = item.get("notice") or "已填写，跳过"
            item["errors"] = list(item.get("errors") or [])
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            need_new_tab = True
            continue
        _write_progress([])
        if on_item_start:
            on_item_start(product)
        item = dict(product)
        item_force_new = bool(force_new) or need_new_tab
        try:
            result = fill_new_product(session, product, confirm_submit=confirm_submit, web=web, force_new=item_force_new)
            pause_blob = " ".join([str(result.get("notice") or ""), *(str(e) for e in result.get("errors") or [])])
            if result.get("execution") == "暂停" and hard_pause_reason(pause_blob):
                item.update(result)
                updated.append(item)
                if on_item_done:
                    on_item_done(product, item)
                _remember_item(product, item, status="paused")
                break
            item.update(result)
            if item.get("execution") not in {"失败", "暂停", "提交失败"} and "errors" not in result:
                item["errors"] = []
        except web.SessionLost as exc:
            item["execution"] = "暂停"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
            updated.append(item)
            if on_item_done:
                on_item_done(product, item)
            _remember_item(product, item, status="paused")
            break
        except Exception as exc:
            item["execution"] = "失败"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
        updated.append(item)
        need_new_tab = True
        if on_item_done:
            on_item_done(product, item)
        _remember_item(product, item, status="error" if item.get("execution") in {"失败", "暂停"} else None)
        try:
            _prune_tabs(web, keep_url=session.href())
        except Exception:
            pass
    if own_session:
        try:
            session.detach()
        except Exception:
            pass
    try:
        _prune_tabs(web)
    except Exception:
        pass
    return updated


def resolve_naruto_product():
    import importlib.util
    spec = importlib.util.spec_from_file_location("seller", ROOT / "千牛自动上架.py")
    seller = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(seller)
    pack_dir = seller.naruto_pack_dir()
    pack = seller.scan_image_pack(pack_dir)
    templates = seller.load_templates({"attributes": "中性笔", "logistics": "48小时", "sales": "仓库多规格"})
    row = {
        "商品标识*": "火影-001",
        "商品标题*": "卡游火影忍者中性笔盲盒忍道版",
        "品牌*": "卡游",
        "型号": "忍道版第1弹",
        "价格*": 9.9,
        "库存*": 20,
        "图片包路径*": str(pack_dir),
        "商品属性模板*": "中性笔",
        "物流模板*": "48小时",
        "销售模板*": "仓库多规格",
    }
    product = seller.resolve_product(row, [], pack, templates, pack_dir.parent)
    errors = seller.validate_product(product)
    if errors:
        raise ValueError("火影示例校验失败: " + "; ".join(errors))
    return product
