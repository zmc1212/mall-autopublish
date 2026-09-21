"""后台任务：校验清单、入库填写、进度日志。"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from . import paths
from .modules import load_seller, load_web

DONE_EXECUTIONS = frozenset({"已填写未提交", "结果待核实"})
RESUME_EXECUTIONS = frozenset({"失败", "暂停", "已停止", "提交失败"})

STEP_LABELS = {
    "tab": "定位填写页",
    "probe": "检查已填内容",
    "category": "选择类目",
    "attributes": "填写属性",
    "skus": "填写规格",
    "spec_images": "规格图",
    "main_1_1": "1:1主图",
    "main_3_4": "3:4主图",
    "details": "详情图",
    "logistics": "物流",
    "warehouse": "放入仓库",
    "submit": "提交",
    "end": "本条结束",
    "resume-tab": "定位标签",
}

MAX_LOGS = 400
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]")


def _now():
    return datetime.now().strftime("%H:%M:%S")


def _plain(message):
    return ANSI_ESCAPE.sub("", str(message or ""))


def _paths_to_str(value):
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _paths_to_str(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_paths_to_str(item) for item in value]
    return value


def _action_links(item):
    module = _job_session()
    if module is not None and hasattr(module, "apply_action_links"):
        return module.apply_action_links(item)
    data = dict(item or {})
    data.setdefault("taobao_item_id", data.get("taobao_item_id") or "")
    data.setdefault("view_url", data.get("view_url") or "")
    data.setdefault("edit_url", data.get("edit_url") or "")
    return data


def serialize_row(item):
    product = item.get("product") or {}
    mains = product.get("main_images") or []
    portraits = product.get("portrait_images") or []
    details = product.get("detail_images") or []
    skus = product.get("skus") or []
    pack = ""
    if product.get("pack_dir"):
        pack = str(product.get("pack_dir"))
    links = _action_links(item)
    return {
        "row": item.get("row"),
        "product_id": item.get("product_id") or product.get("product_id") or "",
        "title": product.get("title") or "",
        "category": product.get("category") or "",
        "brand": product.get("brand") or "",
        "validation": item.get("validation") or "",
        "execution": item.get("execution") or "未执行",
        "notice": item.get("notice") or "",
        "errors": list(item.get("errors") or []),
        "main_count": len(mains),
        "portrait_count": len(portraits),
        "detail_count": len(details),
        "sku_count": len(skus),
        "pack": pack,
        "pack_found": bool(pack and Path(pack).is_dir()),
        "taobao_item_id": links.get("taobao_item_id") or "",
        "view_url": links.get("view_url") or "",
        "edit_url": links.get("edit_url") or "",
    }


def read_fill_progress():
    path = paths.playwright_output_dir() / "web_fill_progress.json"
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _job_session():
    existing = sys.modules.get("job_session")
    if existing is not None:
        return existing
    try:
        import job_session
        return job_session
    except ImportError:
        pass
    for root in (paths.install_dir(), paths.project_root()):
        path = Path(root) / "job_session.py"
        if not path.is_file():
            continue
        spec = importlib.util.spec_from_file_location("job_session", path)
        if spec is None or spec.loader is None:
            continue
        module = importlib.util.module_from_spec(spec)
        sys.modules["job_session"] = module
        spec.loader.exec_module(module)
        return module
    return None


def current_step_label(steps=None):
    steps = steps if steps is not None else read_fill_progress()
    if not steps:
        return ""
    last = steps[-1] if isinstance(steps[-1], dict) else {}
    key = str(last.get("step") or "")
    return STEP_LABELS.get(key, key)


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.workbook_path = ""
        self.workspace_path = ""
        self.workspace_scan = None
        self.workspace_defaults = None
        self.rows = []
        self.products = []
        self.logs = []
        self.status = "idle"
        self.phase = ""
        self.blocker = ""
        self.message = ""
        self.current_row = None
        self.current_id = ""
        self.done = 0
        self.total = 0
        self.result_xlsx = ""
        self.result_json = ""
        self.seen_steps = set()
        self._hide_chrome_after_login = False
        self._restored = False
        self.restored = False

    def snapshot(self):
        self._ensure_restored()
        with self.lock:
            valid = sum(1 for row in self.rows if row.get("validation") == "通过")
            failed = sum(1 for row in self.rows if row.get("validation") != "通过")
            pending = sum(
                1 for row in self.rows
                if row.get("validation") == "通过" and (row.get("execution") or "未执行") not in DONE_EXECUTIONS
            )
            can_resume = self.status in {"paused", "error", "stopped"} or any(
                row.get("validation") == "通过" and (row.get("execution") or "") in RESUME_EXECUTIONS
                for row in self.rows
            )
            retryable = sum(
                1 for row in self.rows
                if row.get("validation") == "通过" and (row.get("execution") or "") in RESUME_EXECUTIONS
            )
            return {
                "status": self.status,
                "phase": self.phase or current_step_label(),
                "blocker": self.blocker,
                "message": self.message,
                "current_row": self.current_row,
                "current_id": self.current_id,
                "done": self.done,
                "total": self.total,
                "workbook_path": self.workbook_path,
                "workspace_path": self.workspace_path,
                "result_xlsx": self.result_xlsx,
                "result_json": self.result_json,
                "valid": valid,
                "failed": failed,
                "pending": pending,
                "retryable": retryable,
                "can_resume": can_resume,
                "restored": self.restored,
                "count": len(self.rows),
                "rows": [_action_links(row) for row in self.rows],
                "logs": list(self.logs[-200:]),
            }

    def log(self, message, level="info"):
        text = _plain(message)
        entry = {"time": _now(), "level": level, "message": text}
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > MAX_LOGS:
                self.logs = self.logs[-MAX_LOGS:]
            self.message = text
        log_file = paths.logs_dir() / "desktop.log"
        try:
            with log_file.open("a", encoding="utf-8") as stream:
                stream.write(f"{entry['time']} [{level}] {text}\n")
        except OSError:
            pass

    def _session_payload(self):
        return {
            "workbook_path": self.workbook_path,
            "workspace_path": self.workspace_path,
            "status": self.status,
            "phase": self.phase,
            "blocker": self.blocker,
            "message": self.message,
            "current_row": self.current_row,
            "current_id": self.current_id,
            "done": self.done,
            "total": self.total,
            "result_xlsx": self.result_xlsx,
            "result_json": self.result_json,
            "products": _paths_to_str(self.products),
            "rows": list(self.rows),
            "logs": list(self.logs[-80:]),
        }

    def _save_session(self):
        module = _job_session()
        if module is None:
            return
        try:
            with self.lock:
                payload = self._session_payload()
            module.save_session(payload)
        except Exception:
            pass

    def _ensure_restored(self):
        if self._restored:
            return
        self._restored = True
        if self.workbook_path or self.products or self.status in {"running", "stopping"}:
            return
        module = _job_session()
        if module is None:
            return
        try:
            session = module.load_session() or {}
        except Exception:
            return
        workspace = str(session.get("workspace_path") or "").strip()
        source = str(session.get("workbook_path") or "").strip()
        try:
            if workspace and Path(workspace).is_dir():
                self.open_workspace(workspace, restoring=True)
            elif source and Path(source).is_file():
                self.import_workbook(source, restoring=True)
            else:
                return
        except Exception as exc:
            self.log(f"恢复上次清单失败: {exc}", "warn")
            return
        if workspace and Path(workspace).is_dir():
            source = self.workbook_path or source
        with self.lock:
            self.restored = True
            saved_status = session.get("status") or ""
            if saved_status in {"paused", "error", "stopped"}:
                self.status = saved_status
                self.blocker = session.get("blocker") or self.blocker
                self.phase = session.get("phase") or "已恢复上次清单"
            elif not self.phase:
                self.phase = "已恢复上次清单"
            self.result_xlsx = session.get("result_xlsx") or self.result_xlsx
            self.result_json = session.get("result_json") or self.result_json
            if session.get("logs") and not self.logs:
                self.logs = list(session.get("logs") or [])[-80:]
        label = workspace if workspace and Path(workspace).is_dir() else source
        self.log(f"已恢复上次{'工作空间' if workspace and Path(workspace).is_dir() else '清单'} {Path(label).name}，可直接继续入库")
        self._save_session()

    def import_workbook(self, path, restoring=False, workspace_path=None):
        self._restored = True
        source = Path(path).expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(f"找不到清单文件: {source}")
        seller = load_seller()
        results = seller.validate_workbook(str(source))
        rows = [serialize_row(item) for item in results]
        products = []
        for item in results:
            product = dict(item.get("product") or {})
            product["row"] = item.get("row")
            product["product_id"] = item.get("product_id") or product.get("product_id")
            products.append({"meta": item, "product": product})
        with self.lock:
            self.workbook_path = str(source)
            if workspace_path is not None:
                self.workspace_path = str(workspace_path or "")
                if not self.workspace_path:
                    self.workspace_scan = None
                    self.workspace_defaults = None
            elif not restoring:
                listed = ""
                if self.workspace_path:
                    listed = str((Path(self.workspace_path) / "商品清单.xlsx").resolve())
                if str(source) != listed:
                    self.workspace_path = ""
                    self.workspace_scan = None
                    self.workspace_defaults = None
            self.rows = rows
            self.products = products
            if not restoring:
                self.result_xlsx = ""
                self.result_json = ""
                self.restored = False
            if self.status not in {"running", "stopping"}:
                self.status = "idle"
                self.blocker = ""
                self.phase = "已恢复上次清单" if restoring else ""
                self.done = 0
                self.total = 0
                self.current_row = None
                self.current_id = ""
        valid = sum(1 for row in rows if row["validation"] == "通过")
        pending = sum(
            1 for row in rows
            if row["validation"] == "通过" and (row.get("execution") or "未执行") not in DONE_EXECUTIONS
        )
        if restoring:
            self.log(f"已恢复 {source.name}：{len(rows)} 条，通过 {valid} 条，待入库 {pending} 条")
        else:
            self.log(f"已导入 {source.name}：{len(rows)} 条，通过 {valid} 条")
        self._save_session()
        return self.snapshot()

    def workspace_info(self, scan=None, defaults=None):
        import workspace as ws
        with self.lock:
            root = self.workspace_path
            if scan is not None:
                self.workspace_scan = scan
            if defaults is not None:
                self.workspace_defaults = defaults
            cached_scan = self.workspace_scan
            cached_defaults = self.workspace_defaults
        payload = {
            "path": root or "",
            "workbook_path": self.workbook_path,
            "defaults": ws.defaults_for_api(
                defaults if defaults is not None else (cached_defaults if cached_defaults is not None else (ws.load_defaults(root) if root else None))
            ),
            "registry": ws.template_registry(),
            "scan": scan if scan is not None else cached_scan,
        }
        return payload

    def open_workspace(self, path, restoring=False):
        import workspace as ws
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"工作空间不存在或不是目录: {root}")
        synced = ws.sync_workbook(root)
        snap = self.import_workbook(synced["path"], restoring=restoring, workspace_path=str(root))
        errors = (synced.get("scan") or {}).get("errors") or []
        added = synced.get("added") or []
        missing = synced.get("missing") or []
        extra = []
        if added:
            extra.append(f"新增 {len(added)} 款")
        if missing:
            extra.append(f"资料缺失 {len(missing)} 款")
        if errors:
            extra.append(f"扫描问题 {len(errors)} 个")
        self.log(
            f"{'已恢复工作空间' if restoring else '已打开工作空间'} {root.name}："
            + f"{synced.get('count') or 0} 条"
            + (("，" + "，".join(extra)) if extra else "")
        )
        snap = self.snapshot()
        snap["workspace"] = self.workspace_info(scan=synced.get("scan"), defaults=synced.get("defaults"))
        snap["sync"] = {"added": added, "missing": missing, "created": synced.get("created")}
        return snap

    def rescan_workspace(self):
        with self.lock:
            root = self.workspace_path
        if not root:
            raise RuntimeError("请先选择工作空间")
        return self.open_workspace(root)

    def load_workspace_defaults(self):
        import workspace as ws
        with self.lock:
            root = self.workspace_path
        if not root:
            return {"defaults": ws.defaults_for_api(), "registry": ws.template_registry(), "path": ""}
        return {
            "defaults": ws.defaults_for_api(ws.load_defaults(root)),
            "registry": ws.template_registry(),
            "path": root,
        }

    def save_workspace_defaults(self, data):
        import workspace as ws
        with self.lock:
            root = self.workspace_path
        if not root:
            raise RuntimeError("请先选择工作空间")
        saved = ws.save_defaults(root, data)
        with self.lock:
            self.workspace_defaults = saved
        self.log("已保存批次默认")
        return {"defaults": ws.defaults_for_api(saved), "registry": ws.template_registry(), "path": root}

    def create_template(self, path):
        target = Path(path).expanduser().resolve()
        seller = load_seller()
        seller.create_template(str(target))
        self.log(f"已生成空白模板: {target}")
        return str(target)

    def chrome_status(self):
        settings = paths.load_settings()
        web = load_web()
        web.reload_paths()
        chrome = Path(settings.chrome_path) if settings.chrome_path else web.detect_chrome()
        found = bool(chrome and Path(chrome).is_file())
        cdp = False
        browser = ""
        login = {"logged_in": False, "blocker": "未连接调试 Chrome", "url": ""}
        try:
            cdp = web.cdp_available()
            if cdp:
                version = web.cdp_version()
                browser = version.get("Browser") or ""
                login = web.login_status_from_tabs()
                if getattr(self, "_hide_chrome_after_login", False) and login.get("logged_in"):
                    try:
                        web.hide_automation_chrome()
                    except Exception:
                        pass
                    self._hide_chrome_after_login = False
        except Exception as exc:
            login = {"logged_in": False, "blocker": str(exc), "url": ""}
        return {
            "chrome_path": str(chrome or ""),
            "chrome_found": found,
            "profile": settings.chrome_profile,
            "cdp_port": settings.cdp_port,
            "debug_browser": bool(getattr(settings, "debug_browser", False)),
            "cdp": cdp,
            "browser": browser,
            "logged_in": bool(login.get("logged_in")),
            "blocker": login.get("blocker") or "",
            "url": login.get("url") or "",
            "cli_js": str(paths.cli_js_path()),
            "cli_js_found": paths.cli_js_path().is_file(),
            "node": str(paths.node_exe_path() or ""),
            "node_found": bool(paths.node_exe_path() and paths.node_exe_path().is_file()),
        }

    def apply_debug_browser(self, enabled):
        """Apply the visibility preference to an already connected automation browser."""
        enabled = bool(enabled)
        self._hide_chrome_after_login = not enabled
        try:
            web = load_web()
            if not web.cdp_available():
                return False
            if enabled:
                return bool(web.reveal_automation_chrome())
            login = web.login_status_from_tabs() or {}
            if login.get("logged_in"):
                return bool(web.hide_automation_chrome())
        except Exception:
            return False
        return False

    def _hide_chrome_for_fill(self):
        if paths.load_settings().debug_browser:
            self._hide_chrome_after_login = False
            try:
                load_web().reveal_automation_chrome()
            except Exception:
                pass
            return
        try:
            web = load_web()
            if web.cdp_available() and (web.login_status_from_tabs() or {}).get("logged_in"):
                web.hide_automation_chrome()
                self._hide_chrome_after_login = False
        except Exception:
            pass

    def _reveal_chrome_for_login(self):
        self._hide_chrome_after_login = True
        try:
            web = load_web()
            web.reveal_seller_chrome()
        except Exception:
            try:
                load_web().reveal_automation_chrome()
            except Exception:
                pass

    def open_chrome(self):
        settings = paths.configure_environ()
        web = load_web()
        web.reload_paths()
        if not Path(settings.chrome_path).is_file():
            raise RuntimeError("未找到 Google Chrome，请在设置里指定 chrome.exe")
        debug_browser = bool(getattr(settings, "debug_browser", False))
        action = web.start_persistent_chrome(
            focus=True,
            hide_if_logged_in=not debug_browser,
        )
        status = self.chrome_status()
        if status.get("logged_in"):
            if debug_browser:
                try:
                    web.reveal_automation_chrome()
                except Exception:
                    pass
                self._hide_chrome_after_login = False
            else:
                try:
                    web.hide_automation_chrome()
                except Exception:
                    pass
                self._hide_chrome_after_login = False
            try:
                web.prune_automation_tabs(keep_fill_pages=True)
            except Exception:
                pass
            notice = (
                "调试模式已开启，自动化浏览器保持显示"
                if debug_browser
                else "卖家中心已登录，浏览器已收起。填表过程请看执行页进度"
            )
        else:
            self._hide_chrome_after_login = True
            notice = "请在弹出窗口登录一次。登录后窗口会自动收起"
        self.log(notice)
        status["opened"] = action or "focused"
        status["notice"] = notice
        return status

    def open_item(self, row, product_id, action):
        kind = str(action or "").strip()
        if kind not in {"view", "edit"}:
            raise RuntimeError("未知操作")
        pid = str(product_id or "")
        found = None
        with self.lock:
            for item in self.rows:
                if item.get("row") != row:
                    continue
                if pid and str(item.get("product_id") or "") not in {"", pid}:
                    continue
                found = dict(item)
                break
        if not found:
            raise RuntimeError("找不到该商品")
        links = _action_links(found)
        url = links.get("view_url") if kind == "view" else links.get("edit_url")
        if not url:
            raise RuntimeError("还没有商品链接，请先入库提交")
        self._hide_chrome_after_login = False
        web = load_web()
        result = web.open_item_url(url)
        self.log(f"已打开{'查看' if kind == 'view' else '编辑'}商品 {found.get('product_id') or ''}")
        return result

    def _pending_products(self, force_new=False, retry_failed=False):
        pending = []
        for bundle in self.products:
            meta = bundle.get("meta") or {}
            if meta.get("validation") != "通过":
                continue
            execution = meta.get("execution") or "未执行"
            if retry_failed:
                if execution not in RESUME_EXECUTIONS:
                    continue
            elif not force_new and execution in DONE_EXECUTIONS:
                continue
            product = dict(bundle.get("product") or {})
            product["execution"] = execution
            product["notice"] = meta.get("notice") or product.get("notice") or ""
            product["errors"] = list(meta.get("errors") or [])
            product["taobao_item_id"] = meta.get("taobao_item_id") or product.get("taobao_item_id") or ""
            product["view_url"] = meta.get("view_url") or product.get("view_url") or ""
            product["edit_url"] = meta.get("edit_url") or product.get("edit_url") or ""
            pending.append(product)
        return pending

    def start_job(self, confirm_submit=False, limit=0, force_new=False, retry_failed=False):
        with self.lock:
            if self.status in {"running", "stopping"}:
                raise RuntimeError("已有入库任务在运行")
            if not self.workbook_path:
                raise RuntimeError("请先导入商品清单或选择工作空间")
            executable = self._pending_products(force_new=force_new, retry_failed=retry_failed)
            if not executable:
                if retry_failed:
                    raise RuntimeError("没有失败、暂停或已停止的商品")
                if force_new:
                    raise RuntimeError("没有通过校验的商品，无法入库")
                raise RuntimeError("待入库商品都已填过。如需重填，请勾选「从头新建」")
            self.cancel.clear()
            self.status = "running"
            self.blocker = ""
            self.phase = "准备"
            self.done = 0
            self.total = len(executable) if not limit else min(len(executable), int(limit))
            self.seen_steps = set()
            self.result_xlsx = ""
            self.result_json = ""
        self._hide_chrome_for_fill()
        if retry_failed:
            mode = "只重试失败项"
        elif force_new:
            mode = "从头新建"
        else:
            mode = "继续上次"
        extra_tab = ""
        if force_new:
            extra_tab = "，新开类目页"
        elif self.total > 1:
            extra_tab = "，第一条可续跑当前页，其后新开类目页"
        else:
            extra_tab = "，接着当前发布页未完成的步骤"
        self.log(
            f"{mode}：{self.total} 条，放入仓库"
            + ("，确认提交到仓库" if confirm_submit else "，不点击提交")
            + extra_tab
        )
        self.thread = threading.Thread(
            target=self._run_job,
            kwargs={
                "confirm_submit": bool(confirm_submit),
                "limit": int(limit or 0),
                "force_new": bool(force_new),
                "retry_failed": bool(retry_failed),
            },
            daemon=True,
            name="qianniu-job",
        )
        self.thread.start()
        return self.snapshot()

    def stop_job(self):
        with self.lock:
            if self.status != "running":
                return self.snapshot()
            self.status = "stopping"
        self.cancel.set()
        self.log("将在当前商品结束后停止", "warn")
        return self.snapshot()

    def _consume_fill_progress(self, steps, watch_state):
        with self.lock:
            current_id = self.current_id
        if current_id != watch_state.get("last_id"):
            watch_state["last_id"] = current_id
            watch_state["last_label"] = ""
            with self.lock:
                self.seen_steps = set()
            return
        label = current_step_label(steps)
        last_label = watch_state.get("last_label") or ""
        if label and label != last_label:
            watch_state["last_label"] = label
            with self.lock:
                self.phase = label
            key = ""
            if steps and isinstance(steps[-1], dict):
                key = str(steps[-1].get("step") or "")
            token = (current_id, key)
            if token not in self.seen_steps and key:
                self.seen_steps.add(token)
                extra = ""
                if key == "end" and isinstance(steps[-1], dict):
                    extra = " ".join(
                        str(steps[-1].get(field) or "") for field in ("execution", "notice")
                    ).strip()
                    extra = extra[:240]
                self.log(
                    f"{current_id or '当前商品'} · {label}"
                    + (f" {extra}" if extra else ""),
                    "error" if key == "end" and "失败" in extra else "info",
                )

    def _watch_progress(self, stop):
        watch_state = {"last_label": "", "last_id": None}
        while not stop.wait(0.4):
            self._consume_fill_progress(read_fill_progress(), watch_state)

    def _run_job(self, confirm_submit=False, limit=0, force_new=False, retry_failed=False):
        stop = threading.Event()
        paths.configure_environ()
        try:
            (paths.playwright_output_dir() / "web_fill_progress.json").write_text("[]", encoding="utf-8")
        except OSError:
            pass
        watcher = threading.Thread(target=self._watch_progress, args=(stop,), daemon=True)
        watcher.start()
        seller = load_seller()
        settings = paths.configure_environ()
        paths.apply_to_loaded_modules()
        self._hide_chrome_for_fill()
        try:
            load_web().prune_automation_tabs(keep_fill_pages=True)
        except Exception:
            pass
        try:
            with self.lock:
                selected = self._pending_products(force_new=force_new, retry_failed=retry_failed)
                source = self.workbook_path
            cap = int(limit or 0)
            selected = selected[:cap] if cap else selected
            web_fill = seller.load_web_fill()
            finished = {"count": 0}

            def on_start(product):
                with self.lock:
                    self.current_row = product.get("row")
                    self.current_id = str(product.get("product_id") or "")
                    self.phase = "开始填写"
                    self.done = finished["count"]
                    self.seen_steps = set()
                self.log(f"正在填写第 {product.get('row')} 行 {product.get('product_id') or ''}")

            def on_done(product, item):
                finished["count"] += 1
                execution = item.get("execution") or ""
                notice = str(item.get("notice") or "").strip()
                serialized = serialize_row({**product, **item})
                reveal_login = execution == "暂停" and any(
                    word in notice for word in ("登录", "验证码", "滑块")
                )
                with self.lock:
                    self.done = finished["count"]
                    if execution == "暂停":
                        self.blocker = notice
                    for row in self.rows:
                        if row.get("row") != product.get("row"):
                            continue
                        row["execution"] = serialized.get("execution") or row.get("execution")
                        row["notice"] = serialized.get("notice") or ""
                        row["taobao_item_id"] = serialized.get("taobao_item_id") or row.get("taobao_item_id") or ""
                        row["view_url"] = serialized.get("view_url") or row.get("view_url") or ""
                        row["edit_url"] = serialized.get("edit_url") or row.get("edit_url") or ""
                        break
                    for bundle in self.products:
                        meta = bundle.get("meta") or {}
                        if meta.get("row") != product.get("row"):
                            continue
                        meta["execution"] = serialized.get("execution") or meta.get("execution")
                        meta["notice"] = serialized.get("notice") or ""
                        meta["errors"] = list(item.get("errors") or [])
                        meta["taobao_item_id"] = serialized.get("taobao_item_id") or meta.get("taobao_item_id") or ""
                        meta["view_url"] = serialized.get("view_url") or meta.get("view_url") or ""
                        meta["edit_url"] = serialized.get("edit_url") or meta.get("edit_url") or ""
                        bundle["meta"] = meta
                        break
                pid = product.get("product_id") or ""
                if execution in ("失败", "暂停", "提交失败"):
                    self.log(f"{pid} {execution}: {notice[:400]}", "error")
                else:
                    self.log(f"{pid} {execution}")
                if reveal_login:
                    self._reveal_chrome_for_login()

            executed = web_fill.run_batch(
                selected,
                confirm_submit=confirm_submit,
                cancel_event=self.cancel,
                on_item_start=on_start,
                on_item_done=on_done,
                force_new=force_new,
            )
            by_row = {item.get("row"): item for item in executed or []}
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            results_dir = Path(settings.results_dir)
            results_dir.mkdir(parents=True, exist_ok=True)
            source_path = Path(source)
            output = results_dir / f"{source_path.stem}.结果-{stamp}.xlsx"
            journal = results_dir / f"{source_path.stem}.结果-{stamp}.json"
            updated_rows = []
            report_rows = []
            paused = False
            with self.lock:
                for index, bundle in enumerate(self.products):
                    item = dict(bundle["meta"])
                    web_item = by_row.get(item.get("row"))
                    if web_item:
                        item["execution"] = web_item.get("execution", item.get("execution"))
                        item["notice"] = web_item.get("notice") or ""
                        item["errors"] = list(web_item.get("errors") or [])
                        for key in ("taobao_item_id", "view_url", "edit_url", "url"):
                            if web_item.get(key):
                                item[key] = web_item.get(key)
                        if item["execution"] == "暂停":
                            paused = True
                            self.blocker = item["notice"]
                    serialized = serialize_row(item)
                    updated_rows.append(serialized)
                    report_rows.append(item)
                    bundle["meta"] = item
                self.rows = updated_rows
                self.done = len(executed or [])
                self.total = len(selected)
            entries = [[
                stamp,
                r.get("row"),
                r.get("product_id"),
                ("校验" + r.get("validation", "")) if r.get("execution") == "未执行" else r.get("execution"),
                "; ".join(str(e).split(":", 1)[0] for e in (r.get("errors") or [])),
                r.get("notice") or "",
                "; ".join(r.get("errors") or []) or (r.get("notice") or ""),
                _action_links(r).get("taobao_item_id") or "",
            ] for r in report_rows]
            try:
                seller.write_log(source, entries, str(output))
            except Exception as log_exc:
                self.log(f"结果表写入失败: {log_exc}", "error")
            payload = {
                "source": source,
                "workspace_path": self.workspace_path,
                "confirm_submit": bool(confirm_submit),
                "force_new": bool(force_new),
                "results": [serialize_row(r) for r in report_rows],
            }
            journal.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            reveal_login = False
            with self.lock:
                self.result_xlsx = str(output)
                self.result_json = str(journal)
                if self.cancel.is_set():
                    self.status = "stopped"
                    self.phase = "已停止"
                elif paused:
                    self.status = "paused"
                    self.phase = "需人工处理"
                    notice = self.blocker or ""
                    reveal_login = any(word in notice for word in ("登录", "验证码", "滑块"))
                else:
                    self.status = "done"
                    self.phase = "完成"
            if reveal_login:
                self._reveal_chrome_for_login()
            self.log(f"任务结束，结果已保存: {output.name}")
            self._save_session()
        except Exception as exc:
            text = _plain(exc)
            login_needed = "登录" in text or "验证码" in text or "滑块" in text
            with self.lock:
                if login_needed:
                    self.status = "paused"
                    self.blocker = text
                    self.phase = "需人工处理"
                else:
                    self.status = "error"
                    self.phase = "失败"
                self.message = text
            if login_needed:
                self._reveal_chrome_for_login()
            self.log(text, "error")
            self.log(traceback.format_exc(), "error")
            self._save_session()
        finally:
            stop.set()
            watcher.join(timeout=1.5)
            try:
                load_web().prune_automation_tabs()
            except Exception:
                pass
            self._hide_chrome_for_fill()
            self._save_session()


MANAGER = JobManager()
