"""上次导入的清单和执行进度。关闭软件后仍可接着做。"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

SESSION_NAME = "job_session.json"
_ITEM_ID_RE = re.compile(r"(?:商品ID[:：]\s*|primaryId=|itemId=)(\d{8,})", re.I)
_CAT_ID_RE = re.compile(r"catId=(\d+)", re.I)
ACTION_LINK_KEYS = ("taobao_item_id", "view_url", "edit_url")
# 这些状态下 notice/url 里的 itemId 属于"被拒绝进入的页面"或"中断时所在页面"，
# 可能是别的商品；只信显式传入的 ID，不再从文本刮取。
FAIL_EXECUTIONS = frozenset({"失败", "暂停", "提交失败", "已停止"})
FLOW_KEYS = (
    "flow_version",
    "sku_image_strategy",
    "seller_account",
    "flow_stage",
    "spec_image_stage",
    "run_status",
    "sku_material_manifest",
    "material_result",
    "material_preview",
    "material_folder",
    "last_error",
    "updated_at",
)
ALL_EXTENDED_KEYS = tuple(dict.fromkeys(ACTION_LINK_KEYS + FLOW_KEYS))
HISTORY_LIMIT = 500


def _clip(text, limit=240):
    cleaned = " ".join(str(text or "").split())
    return cleaned[:limit]


def _http_url(url):
    text = str(url or "").strip()
    lowered = text.lower()
    if not text:
        return ""
    if lowered.startswith(("javascript:", "data:", "file:")):
        return ""
    if not lowered.startswith(("http://", "https://")):
        return ""
    return text


def product_action_links(submitted=None, notice="", href="", item=None, execution=""):
    """从提交成功页或说明文字里取出查看/编辑商品链接。"""
    submitted = dict(submitted or {})
    item = dict(item or {})
    state = str(execution or item.get("execution") or "").strip()
    item_id = str(
        submitted.get("itemId")
        or submitted.get("item_id")
        or item.get("taobao_item_id")
        or item.get("itemId")
        or ""
    ).strip()
    cat_id = str(submitted.get("catId") or submitted.get("cat_id") or item.get("cat_id") or "").strip()
    view_url = _http_url(submitted.get("viewUrl") or submitted.get("view_url") or item.get("view_url") or "")
    edit_url = _http_url(submitted.get("editUrl") or submitted.get("edit_url") or item.get("edit_url") or "")
    blob = " ".join(
        str(part)
        for part in (
            href,
            notice,
            item.get("notice") or "",
            item.get("url") or "",
            submitted.get("href") or "",
            submitted.get("text") or "",
        )
        if part
    )
    if state not in FAIL_EXECUTIONS:
        if not item_id:
            match = _ITEM_ID_RE.search(blob)
            if match:
                item_id = match.group(1)
        if not cat_id:
            match = _CAT_ID_RE.search(blob)
            if match:
                cat_id = match.group(1)
    if item_id:
        if not view_url:
            view_url = f"https://item.taobao.com/item.htm?id={item_id}"
        if not edit_url:
            edit_url = f"https://item.upload.taobao.com/sell/v2/publish.htm?itemId={item_id}"
            if cat_id:
                edit_url += f"&catId={cat_id}"
    return {
        "taobao_item_id": item_id,
        "view_url": view_url,
        "edit_url": edit_url,
    }


def apply_action_links(target, submitted=None, notice="", href="", execution=""):
    data = dict(target or {})
    links = product_action_links(
        submitted=submitted if submitted is not None else data,
        notice=notice or data.get("notice") or "",
        href=href or data.get("url") or "",
        item=data,
        execution=execution or data.get("execution") or "",
    )
    for key, value in links.items():
        data[key] = value or _http_url(data.get(key)) or ""
    return data


def extend_flow_fields(target, source=None):
    """把扩展流程字段复制进记录，且不覆盖目标里已有的非空值。"""
    data = dict(target or {})
    source = dict(source or {})
    for key in FLOW_KEYS:
        if data.get(key) not in (None, ""):
            continue
        if source.get(key) not in (None, ""):
            data[key] = source[key]
    return data


def _appdata_dir():
    raw = os.environ.get("QIANNIU_APPDATA")
    if raw:
        return Path(raw)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "千牛自动上架"


def session_path():
    raw = os.environ.get("QIANNIU_APPDATA")
    if not raw:
        return None
    path = Path(raw)
    path.mkdir(parents=True, exist_ok=True)
    return path / SESSION_NAME


def _norm_path(path):
    text = str(path or "").strip()
    if not text:
        return ""
    try:
        return str(Path(text).expanduser().resolve())
    except OSError:
        return text


def latest_result_session():
    """用最近一次入库结果找回清单路径和执行进度。"""
    results_dir = os.environ.get("QIANNIU_RESULTS_DIR") or ""
    if not results_dir:
        results_dir = str(_appdata_dir() / "results")
    folder = Path(results_dir) if results_dir else None
    if not folder or not folder.is_dir():
        return {}
    files = sorted(folder.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
    for path in files[:12]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(data, dict):
            continue
        source = str(data.get("source") or data.get("workbook_path") or "").strip()
        rows = data.get("results") or data.get("rows") or []
        if not source or not Path(source).is_file():
            continue
        if not isinstance(rows, list) or not rows:
            continue
        return {
            "workbook_path": _norm_path(source),
            "workspace_path": str(data.get("workspace_path") or ""),
            "rows": rows,
            "products": [],
            "result_json": str(path),
            "status": "idle",
        }
    return {}


def load_session():
    path = session_path()
    data = {}
    if path and path.is_file():
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    source = str(data.get("workbook_path") or "").strip()
    workspace = str(data.get("workspace_path") or "").strip()
    if workspace and Path(workspace).is_dir():
        return data
    if source and Path(source).is_file():
        return data
    fallback = latest_result_session()
    if fallback:
        return fallback
    return data


def save_session(data):
    path = session_path()
    if not path:
        return None
    payload = dict(data or {})
    payload["saved_at"] = datetime.now().isoformat(timespec="seconds")
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    tmp.replace(path)
    return path


def _fingerprint_allows(old_fingerprint, current_fingerprint):
    """内容指纹守卫：两边指纹都存在且不一致时阻断回贴，防止同一文件夹被换成
    新商品后误跳过上架。任一侧指纹缺失（旧会话数据或图片夹暂不可读）视为
    无法判断，保持原有回贴行为。"""
    old = str(old_fingerprint or "")
    current = str(current_fingerprint or "")
    if not old or not current:
        return True
    return old == current


def _has_execution_state(row):
    if str(row.get("execution") or "").strip() not in ("", "未执行"):
        return True
    if any(row.get(key) for key in ACTION_LINK_KEYS):
        return True
    return bool(str(row.get("flow_stage") or "").strip())


def _history_record(row):
    record = {
        "product_id": str(row.get("product_id") or ""),
        "title": str(row.get("title") or ""),
        "execution": str(row.get("execution") or ""),
        "notice": _clip(row.get("notice") or ""),
        "pack_fingerprint": str(row.get("pack_fingerprint") or ""),
        "updated_at": datetime.now().isoformat(timespec="seconds"),
    }
    for key in ACTION_LINK_KEYS:
        record[key] = row.get(key) or ""
    for key in FLOW_KEYS:
        if row.get(key) not in (None, ""):
            record[key] = row.get(key)
    return record


def _prune_history(history):
    if len(history) <= HISTORY_LIMIT:
        return history
    ranked = sorted(history.items(), key=lambda kv: str((kv[1] or {}).get("updated_at") or ""))
    return dict(ranked[-HISTORY_LIMIT:])


def _sync_history_from_rows(data, row=None, product_id=""):
    """把当前行最新执行状态归档进 execution_history（行被移除后仍可回贴）。"""
    history = dict(data.get("execution_history") or {})
    pid = str(product_id or "")
    changed = False
    for item in data.get("rows") or []:
        if row is not None and item.get("row") != row:
            continue
        item_pid = str(item.get("product_id") or "")
        if not item_pid or (pid and item_pid != pid):
            continue
        if not _has_execution_state(item):
            continue
        history[item_pid] = _history_record(item)
        changed = True
    if changed:
        data["execution_history"] = _prune_history(history)
    return changed


def forget_execution(row=None, product_id=""):
    """清空某商品的执行状态并删除其历史归档（手动清除入口），
    否则下次校验会被 merge_execution 按会话行或历史再次回贴。"""
    data = load_session()
    if not data:
        return None
    pid = str(product_id or "")
    targets = set()
    cleared_keys = ("taobao_item_id", "view_url", "edit_url", *FLOW_KEYS)
    changed = False
    for item in data.get("rows") or []:
        if row is not None and item.get("row") != row:
            continue
        item_pid = str(item.get("product_id") or "")
        if pid and item_pid and item_pid != pid:
            continue
        if item_pid:
            targets.add(item_pid)
        item["execution"] = "未执行"
        item["notice"] = ""
        item["errors"] = []
        for key in cleared_keys:
            item[key] = ""
        changed = True
    for bundle in data.get("products") or []:
        meta = bundle.get("meta") or {}
        if row is not None and meta.get("row") != row:
            continue
        item_pid = str(meta.get("product_id") or "")
        if pid and item_pid and item_pid != pid:
            continue
        if item_pid:
            targets.add(item_pid)
        meta["execution"] = "未执行"
        meta["notice"] = ""
        for key in cleared_keys:
            meta[key] = ""
        bundle["meta"] = meta
        changed = True
    if not targets and not changed:
        return None
    history = dict(data.get("execution_history") or {})
    for key in targets:
        history.pop(key, None)
    data["execution_history"] = history
    return save_session(data)


def merge_execution(results, workbook_path):
    """把上次同一份清单的执行状态填回重新校验后的结果。

    匹配顺序：清单行 (row, product_id) 精确匹配 → 执行历史按 product_id 回贴
    （覆盖文件夹删除后重新出现的场景）。内容指纹不一致或当前指纹缺失时跳过。
    """
    session = load_session()
    if not session:
        return results
    current = _norm_path(workbook_path)
    saved = _norm_path(session.get("workbook_path") or "")
    if saved and current and saved != current:
        return results
    previous_by_key = {}
    for row in session.get("rows") or []:
        previous_by_key[(row.get("row"), str(row.get("product_id") or ""))] = row
    for bundle in session.get("products") or []:
        meta = bundle.get("meta") or {}
        previous_by_key[(meta.get("row"), str(meta.get("product_id") or ""))] = meta
    history_by_id = dict(session.get("execution_history") or {})
    for item in results or []:
        pid = str(item.get("product_id") or "")
        old = previous_by_key.get((item.get("row"), pid)) or history_by_id.get(pid)
        if not old:
            continue
        if not _fingerprint_allows(old.get("pack_fingerprint"), item.get("pack_fingerprint")):
            continue
        execution = old.get("execution") or "未执行"
        if execution and execution != "未执行":
            item["execution"] = execution
            item["notice"] = _clip(old.get("notice") or item.get("notice") or "")
            for key in ACTION_LINK_KEYS:
                if old.get(key):
                    item[key] = old.get(key)
            for key in FLOW_KEYS:
                if old.get(key) not in (None, ""):
                    item[key] = old[key]
            item.update(apply_action_links(item))
    return results


def remember_workbook(workbook_path, results):
    source = _norm_path(workbook_path)
    products = []
    rows = []
    for item in results or []:
        product = dict(item.get("product") or {})
        product["row"] = item.get("row")
        product["product_id"] = item.get("product_id") or product.get("product_id")
        products.append({"meta": dict(item), "product": product})
        links = apply_action_links(item)
        rows.append({
            "row": item.get("row"),
            "product_id": item.get("product_id") or "",
            "title": product.get("title") or "",
            "category": product.get("category") or "",
            "brand": product.get("brand") or "",
            "validation": item.get("validation") or "",
            "execution": item.get("execution") or "未执行",
            "notice": _clip(item.get("notice") or ""),
            "errors": [_clip(err) for err in (item.get("errors") or [])][:5],
            "taobao_item_id": links.get("taobao_item_id") or "",
            "view_url": links.get("view_url") or "",
            "edit_url": links.get("edit_url") or "",
            "pack_fingerprint": str(item.get("pack_fingerprint") or ""),
            **{key: item.get(key) or "" for key in FLOW_KEYS},
        })
    mtime = None
    try:
        if source and Path(source).is_file():
            mtime = Path(source).stat().st_mtime
    except OSError:
        mtime = None
    existing = load_session()
    existing.update({
        "workbook_path": source,
        "workbook_mtime": mtime,
        "products": products,
        "rows": rows,
        "count": len(rows),
    })
    existing.setdefault("status", "idle")
    history = dict(existing.get("execution_history") or {})
    for row in rows:
        row_pid = str(row.get("product_id") or "")
        if not row_pid or not _has_execution_state(row):
            continue
        history[row_pid] = _history_record(row)
    existing["execution_history"] = _prune_history(history)
    return save_session(existing)


def patch_execution(row, product_id, execution, notice="", errors=None, status=None, phase=None, blocker=None, extra=None):
    data = load_session()
    if not data:
        return None
    pid = str(product_id or "")
    extra = extra or {}
    links = apply_action_links({"notice": notice, **extra}, execution=execution)
    flow_patch = {key: extra.get(key) for key in FLOW_KEYS if extra.get(key) not in (None, "")}
    if flow_patch.get("flow_stage") == "complete":
        flow_patch.update(run_status="completed", last_error="")
    for bundle in data.get("products") or []:
        meta = bundle.get("meta") or {}
        if meta.get("row") != row:
            continue
        if pid and str(meta.get("product_id") or "") not in {"", pid}:
            continue
        meta["execution"] = execution
        meta["notice"] = notice
        meta.update(flow_patch)
        meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
        if errors is not None:
            meta["errors"] = list(errors)
        for key in ACTION_LINK_KEYS:
            if links.get(key):
                meta[key] = links[key]
        bundle["meta"] = meta
        product = bundle.get("product") or {}
        product["execution"] = execution
        bundle["product"] = product
    for item in data.get("rows") or []:
        if item.get("row") != row:
            continue
        item["execution"] = execution
        item["notice"] = notice
        item.update(flow_patch)
        item["updated_at"] = datetime.now().isoformat(timespec="seconds")
        for key in ACTION_LINK_KEYS:
            if links.get(key):
                item[key] = links[key]
    _sync_history_from_rows(data, row=row, product_id=pid)
    if status:
        data["status"] = status
    if phase is not None:
        data["phase"] = phase
    if blocker is not None:
        data["blocker"] = blocker
    return save_session(data)


def patch_flow_state(row, product_id, fields=None):
    """商品 ID 与最新阶段即时落盘；不改变 execution 展示字段。"""
    data = load_session()
    if not data:
        return None
    pid = str(product_id or "")
    patch = {key: value for key, value in (fields or {}).items() if key in FLOW_KEYS}
    links = apply_action_links(patch)
    patch.update({key: links[key] for key in ACTION_LINK_KEYS if links.get(key)})
    patch["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if not patch:
        return None
    for bundle in data.get("products") or []:
        meta = bundle.get("meta") or {}
        if meta.get("row") != row:
            continue
        if pid and str(meta.get("product_id") or "") not in {"", pid}:
            continue
        meta.update(patch)
        bundle["meta"] = meta
        bundle["product"] = extend_flow_fields(bundle.get("product") or {}, meta)
    for item in data.get("rows") or []:
        if item.get("row") != row:
            continue
        item.update(patch)
    _sync_history_from_rows(data, row=row, product_id=pid)
    return save_session(data)


_RESTORE_TRIED = False


def restore_desktop_manager():
    """把上次清单直接填回正在运行的任务对象。打包版 exe 也能用。"""
    global _RESTORE_TRIED
    if _RESTORE_TRIED:
        return False
    _RESTORE_TRIED = True
    if not os.environ.get("QIANNIU_APPDATA"):
        return False
    try:
        from desktop.jobs import MANAGER, serialize_row
    except Exception:
        return False
    if str(getattr(MANAGER, "workbook_path", "") or "").strip():
        return False
    if getattr(MANAGER, "products", None):
        return False
    session = load_session() or {}
    workspace_path = str(session.get("workspace_path") or "").strip()
    source = str(session.get("workbook_path") or "").strip()
    if workspace_path and Path(workspace_path).is_dir():
        try:
            import workspace as ws
            synced = ws.sync_workbook(workspace_path)
            source = synced.get("path") or source
            if hasattr(MANAGER, "workspace_scan"):
                MANAGER.workspace_scan = synced.get("scan")
            if hasattr(MANAGER, "workspace_defaults"):
                MANAGER.workspace_defaults = synced.get("defaults")
        except Exception:
            pass
    if not source or not Path(source).is_file():
        return False
    try:
        from desktop.modules import load_seller
        seller = load_seller()
        results = seller.validate_workbook(source)
        rows = [serialize_row(item) for item in results]
        for row in rows:
            row["notice"] = _clip(row.get("notice") or "")
            row["errors"] = [_clip(err) for err in (row.get("errors") or [])][:5]
        products = []
        for item in results:
            product = dict(item.get("product") or {})
            product["row"] = item.get("row")
            product["product_id"] = item.get("product_id") or product.get("product_id")
            products.append({"meta": item, "product": product})
        MANAGER.workbook_path = source
        if workspace_path and Path(workspace_path).is_dir():
            MANAGER.workspace_path = workspace_path
        MANAGER.rows = rows
        MANAGER.products = products
        if getattr(MANAGER, "status", "") not in {"running", "stopping"}:
            saved = session.get("status") or ""
            MANAGER.status = saved if saved in {"paused", "error", "stopped"} else "idle"
        if hasattr(MANAGER, "restored"):
            MANAGER.restored = True
        if hasattr(MANAGER, "_restored"):
            MANAGER._restored = True
        MANAGER.phase = "已恢复上次清单"
        if session.get("result_xlsx"):
            MANAGER.result_xlsx = session.get("result_xlsx") or ""
        if session.get("result_json"):
            MANAGER.result_json = session.get("result_json") or ""
        if hasattr(MANAGER, "log"):
            MANAGER.log(
                f"已恢复上次{'工作空间' if workspace_path else '清单'} {Path(workspace_path or source).name}，可直接继续入库"
            )
        remember_workbook(source, results)
        return True
    except Exception as exc:
        try:
            if hasattr(MANAGER, "log"):
                MANAGER.log(f"恢复上次清单失败: {exc}", "warn")
        except Exception:
            pass
        return False
