"""后台任务：校验清单、入库填写、进度日志。"""

from __future__ import annotations

import importlib.util
import copy
import json
import os
import re
import sys
import threading
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path

from . import code_watch, detail_browser, paths
from .image_preview import is_supported_pack_path, preview_cache_token, preview_metadata
from .modules import load_seller, load_web

DONE_EXECUTIONS = frozenset({"已填写未提交", "结果待核实"})
RESUME_EXECUTIONS = frozenset({"失败", "暂停", "已停止", "提交失败"})
ATTENTION_EXECUTIONS = frozenset({
    "失败", "暂停", "提交失败", "提交待核实", "结果待核实", "已停止",
})
FLOW_COMPLETE_STAGE = "complete"
FLOW_FIELDS = (
    "execution_reset_id",
    "resume_checkpoint",
    "last_browser_write",
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
    "video_warning",
    "video_status",
    "updated_at",
)

# 清除执行记录时需要重置的字段（clear_row_state / clear_rows_state 共用）。
CLEAR_EXECUTION_KEYS = (
    "execution", "notice", "errors", "taobao_item_id", "view_url", "edit_url", "url",
    "resume_checkpoint", "legacy_checkpoint", "last_browser_write",
    "flow_version", "sku_image_strategy", "seller_account", "flow_stage", "spec_image_stage",
    "run_status", "sku_material_manifest", "material_result", "material_preview", "last_error",
    "updated_at", "material_folder", "duration_seconds", "video_warning", "video_status",
)


def _reset_execution_fields(item, reset_id):
    """把一条执行状态记录重置回「未执行」。"""
    for key in CLEAR_EXECUTION_KEYS:
        if key == "execution":
            item[key] = "未执行"
        elif key == "errors":
            item[key] = []
        elif key == "duration_seconds":
            item[key] = None
        else:
            item[key] = ""
    item["execution_reset_id"] = reset_id


FLOW_STAGE_LABELS = {
    "pending": "待入库",
    "filling": "正在填写",
    "filled": "已填写，待提交",
    "submit_pending": "提交结果待核实",
    "created": "已入库，待补图",
    "material_prepared": "已生成素材",
    "material_upload_pending": "上传结果待核实",
    "material_recognizing": "正在识别素材",
    "material_reviewed": "素材已核对",
    "material_adopt_pending": "采纳结果待核实",
    "material_verifying": "正在核验图片",
    "complete": "已入库，图片已核验",
}

RUN_STATUS_LABELS = {
    "paused": "补图暂停",
    "error": "补图失败",
    "stopped": "已停止",
}

STEP_LABELS = {
    "tab": "定位填写页",
    "probe": "检查已填内容",
    "category": "选择类目",
    "attributes": "填写属性",
    "skus": "填写规格",
    "sku_import": "导入 SKU 模板",
    "sku_seed": "建立规格表",
    "sku_category": "设置 SKU 分类",
    "thickness": "设置书写粗细",
    "spec_images": "规格图",
    "spec_images_resume": "规格图核验续传",
    "main_1_1": "1:1主图",
    "main_3_4": "3:4主图",
    "main_images": "主图",
    "details": "详情图",
    "probe_state": "检查已填内容",
    "sku_audit": "核对规格",
    "tags": "填写标签",
    "video": "主视频",
    "video_dialog_close": "关闭视频弹窗",
    "logistics": "物流",
    "warehouse": "放入仓库",
    "submit": "提交",
    "end": "本条结束",
    "resume-tab": "定位标签",
    "material_baseline": "读取后台 SKU",
    "material_prepare": "生成素材",
    "material_upload": "上传素材",
    "material_recognize": "等待识别",
    "material_review": "核对确认页",
    "material_adopt": "采纳素材",
    "material_verify": "核验图片",
}

MAX_LOGS = 400
MAX_LOG_FILE_BYTES = 5 * 1024 * 1024
# 任务无任何进展的看门狗阈值：超过后标记 stalled 并弹出浏览器，但不强杀
# 流水线（保持协作式停止，遵守“结果不明确不自动重复执行”）。
DEFAULT_STALL_SECONDS = 20 * 60
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[@-Z\\-_]")


def _now():
    return datetime.now().strftime("%H:%M:%S")


def format_duration(seconds):
    """把秒数格式化为可读时长；无有效耗时时返回空串（供结果表「耗时」列）。"""
    try:
        total = int(round(float(seconds or 0)))
    except (TypeError, ValueError):
        return ""
    if total <= 0:
        return ""
    if total < 60:
        return f"{total}秒"
    if total < 3600:
        return f"{total // 60}分{total % 60:02d}秒"
    return f"{total // 3600}小时{(total % 3600) // 60:02d}分"


def _plain(message):
    return ANSI_ESCAPE.sub("", str(message or ""))


def stall_seconds():
    try:
        return max(60, int(os.environ.get("QIANNIU_STALL_SECONDS") or DEFAULT_STALL_SECONDS))
    except (TypeError, ValueError):
        return DEFAULT_STALL_SECONDS


def pause_reason_code(text):
    """安全验证类硬暂停原因码（login/captcha/slider），非硬暂停返回空串。

    分类逻辑集中在 web_fill.pipeline.pause_reason_code；load_web_fill 返回
    的是 web_fill 包，分类器在其 pipeline 子模块上。加载失败时退回关键词
    兜底，保证暂停分流不失效。
    """
    blob = str(text or "")
    classifier = None
    try:
        module = load_seller().load_web_fill()
        classifier = getattr(module, "pause_reason_code", None)
        if classifier is None:
            classifier = getattr(getattr(module, "pipeline", None), "pause_reason_code", None)
    except Exception:
        classifier = None
    if callable(classifier):
        try:
            return classifier(blob) or ""
        except Exception:
            pass
    for word, code in (("滑块", "slider"), ("验证码", "captcha"), ("登录", "login")):
        if word in blob:
            return code
    return ""


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


def _flow_of(item):
    meta = dict(item or {})
    product = dict(item.get("product") or {})
    return {key: meta.get(key, product.get(key)) or "" for key in FLOW_FIELDS}


def flow_stage_label(item):
    stage = (dict(item or {}).get("flow_stage") or "").strip()
    if not stage:
        return ""
    base = FLOW_STAGE_LABELS.get(stage, stage)
    run_status = (dict(item or {}).get("run_status") or "").strip()
    if run_status in RUN_STATUS_LABELS and stage not in {"complete"}:
        return f"{base}（{RUN_STATUS_LABELS[run_status]}）"
    return base


def serialize_row(item):
    product = item.get("product") or {}
    mains = product.get("main_images") or []
    portraits = product.get("portrait_images") or []
    details = product.get("detail_images") or []
    skus = product.get("skus") or []
    video_display = product.get("video_display") or {}
    pack = ""
    if product.get("pack_dir"):
        pack = str(product.get("pack_dir"))
    preview = preview_metadata(product, item.get("pack_fingerprint"))
    product_id = item.get("product_id") or product.get("product_id") or ""
    preview_url = ""
    row_number = item.get("row")
    if preview.get("available") and row_number is not None:
        from urllib.parse import quote

        version = preview.get("cache_token") or preview_cache_token(product, item.get("pack_fingerprint"))
        query = f"row={quote(str(row_number), safe='')}&product_id={quote(str(product_id), safe='')}"
        if version:
            query += f"&v={quote(version, safe='')}"
        preview_url = f"/api/item/preview?{query}"
    links = _action_links(item)
    return {
        "row": item.get("row"),
        "product_id": product_id,
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
        "video_name": str(video_display.get("name") or ""),
        "video_ok": bool(video_display.get("playable")),
        "pack": pack,
        "pack_found": bool(pack and is_supported_pack_path(pack)),
        "pack_fingerprint": str(item.get("pack_fingerprint") or ""),
        "preview_url": preview_url,
        "preview_available": bool(preview.get("available")),
        "preview_name": str(preview.get("name") or ""),
        "preview_media_type": str(preview.get("media_type") or ""),
        "taobao_item_id": links.get("taobao_item_id") or "",
        "view_url": links.get("view_url") or "",
        "edit_url": links.get("edit_url") or "",
        "duration_seconds": float(item["duration_seconds"]) if item.get("duration_seconds") else None,
        **_flow_of(item),
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


def _parse_history_file(path):
    """把一个结果 JSON 解析成历史统计条目；解析失败返回 None 跳过该文件。"""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    results = data.get("results") or []
    rows = [r for r in results if isinstance(r, dict)]

    def _num(value):
        try:
            value = float(value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    # 旧版本结果文件没有时间字段，从文件名 stamp（任务结束时刻）兜底。
    stamp = re.search(r"结果-(\d{8})-(\d{6})-\d+\.json$", path.name)
    finished_fallback = None
    if stamp:
        try:
            finished_fallback = datetime.strptime(
                stamp.group(1) + stamp.group(2), "%Y%m%d%H%M%S"
            ).timestamp()
        except ValueError:
            finished_fallback = None

    durations = [_num(r.get("duration_seconds")) for r in rows]
    durations = [v for v in durations if v is not None]
    return {
        "file": path.name,
        "source": Path(str(data.get("source") or "")).name,
        "started_at": _num(data.get("started_at")),
        "finished_at": _num(data.get("finished_at")) or finished_fallback,
        "duration_seconds": _num(data.get("duration_seconds")),
        "total": len(rows),
        "succeeded": sum(1 for r in rows if str(r.get("taobao_item_id") or "").strip()),
        "failed": sum(1 for r in rows if r.get("execution") == "失败"),
        "avg_seconds": round(sum(durations) / len(durations), 1) if durations else None,
    }


def current_step_label(steps=None):
    steps = steps if steps is not None else read_fill_progress()
    if not steps:
        return ""
    last = steps[-1] if isinstance(steps[-1], dict) else {}
    key = str(last.get("step") or "")
    if key == "spec_images" and last.get("progress"):
        return f"规格图 {last['progress']}"
    return STEP_LABELS.get(key, key)


def _has_cjk(text):
    return any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))


def worker_phase_label(phase="", steps=None):
    """Return a human phase for worker events.

    WorkerRuntime reports the raw script stem as ``phase`` while the steps
    list contains the richer pipeline state.  Prefer that list and keep raw
    unknown stems out of the UI; already-human Chinese phases remain intact.
    """
    if isinstance(steps, list) and steps:
        label = current_step_label(steps)
        if label and (_has_cjk(label) or label in STEP_LABELS.values()):
            return label
    raw = str(phase or "").strip()
    if raw in STEP_LABELS:
        return STEP_LABELS[raw]
    if _has_cjk(raw):
        return raw
    return "执行中"


class JobManager:
    def __init__(self):
        self.lock = threading.RLock()
        self.cancel = threading.Event()
        self.thread = None
        self.update_pending = False
        # The pipeline owns the actual worker pool.  JobManager keeps the
        # batch-level immutable settings snapshot and a compact view of worker
        # activity so the API remains useful while items finish out of order.
        self.batch_settings = None
        self.concurrency = 2
        self.worker_events = {}
        self.active_worker_events = {}
        self._completed_rows = set()
        self._attention_rows = set()
        self.attention_count = 0
        self.global_blocker = ""
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
        self.activity_at = time.time()
        self.started_at = 0.0
        self.finished_at = 0.0
        self.item_durations = []
        self.stalled = False
        self._hide_chrome_after_login = False
        self._login_candidate_url = ""
        self._login_candidate_since = 0.0
        self._login_confirmed = False
        # 启动时的后台登录态自动检测：profile 里有登录记录时直接显示「已登录」，
        # 用户不再需要手动点击「登录卖家中心」。idle → running → done，每进程一次。
        self._auto_check_state = "idle"
        self._auto_check_lock = threading.Lock()
        self._login_check_timeout = 12.0
        self._login_check_settle = 2.0
        self._login_check_grace = 2.0
        self._auto_check_wait = 8.0
        # 最近一次成功的 CDP 探测结果：任务运行期间 Chrome 忙碌可能让
        # 单次探测超时，轮询短暂复用该结果，避免顶部徽标闪回「未连接」。
        self._last_good_probe = None
        self._last_good_probe_at = 0.0
        self._probe_stale_seconds = 15.0
        self._restored = False
        self.restored = False

    @staticmethod
    def _setting(settings, key, default=None):
        if isinstance(settings, dict):
            return settings.get(key, default)
        return getattr(settings, key, default)

    @staticmethod
    def _saved_debug_browser():
        """Read the live visibility preference without changing browser paths."""
        try:
            return bool(getattr(paths.load_settings(), "debug_browser", False))
        except Exception:
            return False

    def _batch_context_retained(self):
        """Whether the current batch still owns the browser context.

        A completed batch can still retain pages for rows requiring manual
        review.  Those pages belong to the batch snapshot until the review is
        resolved, so status/open/reveal endpoints must not switch to a newly
        saved profile or CDP port merely because the status is ``done``.
        """
        with self.lock:
            if self.batch_settings is None:
                return False
            if self.status != "done":
                return True
            return any(
                row.get("execution") in {"暂停", "失败", "结果待核实", "提交失败", "提交待核实"}
                for row in self.rows
            )

    @classmethod
    def _settings_snapshot(cls, settings):
        """Copy settings once so a later PUT cannot mutate this batch."""
        try:
            snapshot = copy.deepcopy(settings)
        except Exception:
            snapshot = dict(getattr(settings, "__dict__", {}) or {})
        try:
            concurrency = int(cls._setting(snapshot, "concurrency", 2) or 2)
        except (TypeError, ValueError):
            concurrency = 2
        concurrency = max(1, min(8, concurrency))
        if isinstance(snapshot, dict):
            snapshot["concurrency"] = concurrency
        else:
            try:
                snapshot.concurrency = concurrency
            except Exception:
                snapshot = dict(getattr(snapshot, "__dict__", {}) or {})
                snapshot["concurrency"] = concurrency
        return snapshot

    @classmethod
    def _settings_dict(cls, settings):
        if settings is None:
            return {}
        if isinstance(settings, dict):
            return dict(settings)
        return dict(getattr(settings, "__dict__", {}) or {})

    def _worker_step_log_entry(self, worker_id, row, product_id, steps, label):
        """把 worker 进度事件的步骤标签还原成日志行；同一标签只记一次。

        并行化后进度写入 worker 独立目录，共享 web_fill_progress.json 恒空，
        旧 _consume_fill_progress 的逐步日志随之失效；实时步骤面板改由
        worker 事件驱动，格式与其保持一致。
        """
        if not isinstance(steps, list) or not steps or not label:
            return None
        last_step = steps[-1] if isinstance(steps[-1], dict) else {}
        key = str(last_step.get("step") or "")
        if not key or key == "end":
            return None
        token = (worker_id, row, key, label if key == "spec_images" else "")
        if token in self.seen_steps:
            return None
        self.seen_steps.add(token)
        extra = ""
        if last_step.get("skipped") or (isinstance(last_step.get("result"), dict) and last_step["result"].get("skipped")):
            extra = "已完成，跳过"
        prefix = f"[槽 {worker_id}] " if int(self.concurrency or 1) > 1 else ""
        who = str(product_id or "").strip()
        if not who:
            who = f"第 {row} 行" if row is not None else "当前商品"
        return f"{prefix}{who} · {label}" + (f" {extra}" if extra else "")

    def _on_worker_event(self, event):
        """Consume pipeline worker events without assuming completion order."""
        if not isinstance(event, dict):
            return
        kind = str(event.get("event") or "").strip().lower()
        if kind not in {"start", "progress", "done", "global_blocker"}:
            return
        try:
            worker_id = int(event.get("worker_id") or 0)
        except (TypeError, ValueError):
            worker_id = 0
        row = event.get("row")
        product_id = str(event.get("product_id") or "")
        output_dir = str(event.get("output_dir") or "")
        phase = str(event.get("phase") or "").strip()
        steps = event.get("steps")
        phase = worker_phase_label(phase, steps)
        status = str(event.get("status") or "").strip()
        if not status:
            item = event.get("item")
            if isinstance(item, dict):
                status = str(item.get("execution") or item.get("run_status") or "").strip()
        item = event.get("item")
        item_execution = str(item.get("execution") or "").strip() if isinstance(item, dict) else ""
        now = time.time()
        normalized = dict(event)
        normalized.update({
            "event": kind,
            "worker_id": worker_id,
            "row": row,
            "product_id": product_id,
            "status": status,
            "phase": phase,
            "output_dir": output_dir,
        })
        log_entry = None
        with self.lock:
            if event.get("video_status"):
                video_fields = {"video_status": event["video_status"]}
                if "video_warning" in event:
                    video_fields["video_warning"] = event["video_warning"]
                for current in self.rows:
                    if current.get("row") == row and current.get("product_id") == product_id:
                        current.update(video_fields)
                for bundle in self.products:
                    meta = bundle.get("meta") or {}
                    if meta.get("row") == row and meta.get("product_id") == product_id:
                        meta.update(video_fields)
                        bundle["meta"] = meta
            previous = self.active_worker_events.get(worker_id) or {}
            normalized["started_at"] = previous.get("started_at") or event.get("started_at") or now
            normalized["activity_at"] = now
            normalized["stalled"] = bool(event.get("stalled", False))
            if isinstance(steps, list):
                normalized["steps"] = list(steps)
            self.worker_events[worker_id] = normalized
            if kind in {"start", "progress"}:
                self.active_worker_events[worker_id] = normalized
                self.current_row = row
                self.current_id = product_id
                if phase and not self.global_blocker:
                    self.phase = phase
                if kind == "progress":
                    log_entry = self._worker_step_log_entry(worker_id, row, product_id, steps, phase)
            elif kind == "done":
                self.active_worker_events.pop(worker_id, None)
                if phase and not self.global_blocker:
                    self.phase = phase
            elif kind == "global_blocker":
                blocker = str(
                    event.get("blocker")
                    or event.get("notice")
                    or event.get("message")
                    or phase
                    or "全局任务阻断"
                ).strip()
                self.global_blocker = blocker
                self.blocker = blocker
                self.phase = "需人工处理"
                if self.status == "running":
                    self.status = "stopping"
                log_entry = blocker
            self.activity_at = now
            self.stalled = False
            attention_status = item_execution or status
            if kind == "done" and attention_status in ATTENTION_EXECUTIONS:
                key = row if row is not None else product_id
                self._attention_rows.add(key)
                self.attention_count = len(self._attention_rows)
        if log_entry:
            # “全局阻断：”只属于 global_blocker 分支；progress 步骤日志共用
            # log_entry 变量，加同样前缀会把普通进度伪装成全局故障（2026-10-06
            # 用户把步骤进度误读为任务失败）。
            if kind == "global_blocker":
                self.log(f"全局阻断：{log_entry}", "error")
            else:
                self.log(log_entry, "info")

    def preview_product(self, row, product_id=""):
        """按当前内存清单定位商品，供只读主图预览接口使用。"""
        self._ensure_restored()
        try:
            row_number = int(row)
        except (TypeError, ValueError):
            return None
        wanted = str(product_id or "").strip()
        with self.lock:
            for bundle in self.products:
                if not isinstance(bundle, dict):
                    continue
                meta = dict(bundle.get("meta") or {})
                product = dict(bundle.get("product") or {})
                current_row = meta.get("row", product.get("row"))
                if current_row != row_number:
                    continue
                current_id = str(meta.get("product_id") or product.get("product_id") or "").strip()
                if wanted and wanted != current_id:
                    continue
                # 让预览接口使用与当前清单行相同的版本标记，旧 URL 不会
                # 因为 row/product_id 恰好重用而指向新工作空间的图片。
                if meta.get("pack_fingerprint") and "pack_fingerprint" not in product:
                    product["pack_fingerprint"] = meta.get("pack_fingerprint")
                return copy.deepcopy(product)
        return None

    def snapshot(self):
        self._ensure_restored()
        with self.lock:
            valid = sum(1 for row in self.rows if row.get("validation") == "通过")
            failed = sum(1 for row in self.rows if row.get("validation") != "通过")
            pending = sum(
                1 for row in self.rows
                if row.get("validation") == "通过" and not self._row_flow_done(row)
            )
            can_resume = self.status in {"paused", "error", "stopped"} or any(
                row.get("validation") == "通过" and self._row_flow_resumable(row)
                for row in self.rows
            )
            retryable = sum(
                1 for row in self.rows
                if row.get("validation") == "通过" and self._row_flow_resumable(row)
            )
            running = self.status in {"running", "stopping"}
            if running and self.started_at:
                elapsed = time.time() - self.started_at
            elif self.finished_at and self.started_at:
                elapsed = max(0.0, self.finished_at - self.started_at)
            else:
                elapsed = None
            durations = [value for value in self.item_durations if value > 0]
            active_workers = []
            for worker_id, event in sorted(self.active_worker_events.items(), key=lambda pair: pair[0]):
                active_workers.append({
                    "worker_id": str(worker_id),
                    "row": event.get("row"),
                    "product_id": str(event.get("product_id") or ""),
                    "status": str(event.get("status") or ""),
                    "phase": str(event.get("phase") or ""),
                    "started_at": event.get("started_at"),
                    "activity_at": event.get("activity_at"),
                    "stalled": bool(event.get("stalled", False)),
                })
            return {
                "status": self.status,
                "phase": self.phase or current_step_label(),
                "blocker": self.blocker,
                "message": self.message,
                "current_row": self.current_row,
                "current_id": self.current_id,
                "done": self.done,
                "total": self.total,
                "concurrency": self.concurrency,
                "sku_image_strategy": self._setting(self.batch_settings if running and self.batch_settings is not None else paths.load_settings(), "sku_image_strategy", "slim_material"),
                "active_workers": active_workers,
                "active_count": len(active_workers),
                "attention_count": self.attention_count,
                "global_blocker": self.global_blocker,
                "started_at": self.started_at or None,
                "finished_at": self.finished_at or None,
                "elapsed_seconds": round(elapsed, 1) if elapsed is not None else None,
                "avg_item_seconds": (
                    round(sum(durations) / len(durations), 1) if durations else None
                ),
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
                "stalled": self.stalled,
                "count": len(self.rows),
                "rows": [_action_links(row) for row in self.rows],
                "logs": list(self.logs[-200:]),
            }

    def _row_flow_done(self, row):
        # 商品 ID 是已经入库的事实。即使旧记录没有 flow_stage，或执行文案
        # 仍是“已填写未提交/结果待核实”，也不能把它当成可跳过的未入库记录；
        # 这类记录必须保留在续跑队列，由补图流程打开编辑页继续核验。
        has_item_id = bool(str(row.get("taobao_item_id") or "").strip())
        stage = (row.get("flow_stage") or "").strip()
        if stage:
            if stage != FLOW_COMPLETE_STAGE:
                return False
            # A running batch owns an immutable settings snapshot.  The user
            # may save a new image strategy while it is running, but that
            # value must only affect the next start/continue action.  Once a
            # batch is paused/stopped, the next resume intentionally reads the
            # saved settings again through ``paths.load_settings``.
            with self.lock:
                batch_settings = (
                    self.batch_settings
                    if self.status in {"running", "stopping"} and self.batch_settings is not None
                    else None
                )
            selected = self._setting(
                batch_settings if batch_settings is not None else paths.load_settings(),
                "sku_image_strategy",
                "slim_material",
            )
            completed = row.get("sku_image_strategy") or ""
            if selected in {"publish_page", "both"} and row.get("flow_version") in {"spec-column-v1", "both-images-v1"}:
                return False  # These versions counted SKU搜索主图 as specification photos.
            targets = {"slim_material": {"slim_material"},
                       "publish_page": {"publish_page"},
                       "both": {"slim_material", "publish_page"}}
            return targets.get(selected, set()) <= targets.get(completed, set())
        if row.get("flow_version"):
            return False
        if has_item_id:
            return False
        # A filled form or an unverified response without an item ID is not
        # a completed warehouse product. Continue must examine it again.
        return False

    def _row_flow_resumable(self, row):
        # 有商品 ID 的商品永远按已有商品续跑；策略和阶段只决定补哪类图，
        # 不再因为旧 execution 文案把它过滤掉。
        if str(row.get("taobao_item_id") or "").strip():
            return not self._row_flow_done(row)
        stage = (row.get("flow_stage") or "").strip()
        legacy = not (row.get("flow_version") or stage)
        if legacy:
            return (row.get("execution") or "") in RESUME_EXECUTIONS | {
                "已填写未提交", "提交待核实", "结果待核实",
            }
        if stage in {"", "pending", "filling", FLOW_COMPLETE_STAGE}:
            return (row.get("execution") or "") in RESUME_EXECUTIONS
        return True

    def log(self, message, level="info"):
        text = _plain(message)
        runtime = None
        # Import lazily: desktop jobs also runs in installs where web_fill is
        # not imported until the first task, and log() is called during boot.
        try:
            from web_fill.runtime import current_runtime
            runtime = current_runtime()
        except Exception:
            runtime = None
        context = {}
        if runtime is not None:
            for field in ("worker_id", "row", "product_id"):
                value = getattr(runtime, field, None)
                if value not in (None, ""):
                    context[field] = str(value) if field == "worker_id" else value
        entry = {"time": _now(), "level": level, "message": text, **context}
        with self.lock:
            self.logs.append(entry)
            if len(self.logs) > MAX_LOGS:
                self.logs = self.logs[-MAX_LOGS:]
            self.message = text
        log_file = paths.logs_dir() / "desktop.log"
        try:
            if log_file.exists() and log_file.stat().st_size > MAX_LOG_FILE_BYTES:
                rotated = log_file.with_name("desktop.log.1")
                try:
                    if rotated.exists():
                        rotated.unlink()
                except OSError:
                    pass
                try:
                    log_file.rename(rotated)
                except OSError:
                    pass
            with log_file.open("a", encoding="utf-8") as stream:
                prefix = " ".join(f"{field}={value}" for field, value in context.items())
                if prefix:
                    prefix = f"[{prefix}] "
                stream.write(f"{entry['time']} [{level}] {prefix}{text}\n")
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
            "concurrency": self.concurrency,
            "attention_count": self.attention_count,
            "global_blocker": self.global_blocker,
            "batch_settings": self._settings_dict(self.batch_settings),
            "result_xlsx": self.result_xlsx,
            "result_json": self.result_json,
            "started_at": self.started_at or None,
            "finished_at": self.finished_at or None,
            "item_durations": list(self.item_durations[-500:]),
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
                # ``rows`` contains mutable dicts.  Copy it while holding the
                # manager lock; otherwise a worker can mutate the same dict
                # after this method releases the lock and before the session
                # transaction commits.
                payload = copy.deepcopy(self._session_payload())
            update = getattr(module, "update_session", None)
            if update is not None:
                def merge(existing):
                    # 执行历史档案独立于当前行，整体覆盖会话时必须保留。
                    if existing.get("execution_history"):
                        payload["execution_history"] = existing.get("execution_history")

                    # A flow checkpoint may commit between the manager
                    # snapshot above and this transaction.  The checkpoint
                    # carries ``updated_at`` on both rows and product metas;
                    # preserve that newer state instead of replacing it with
                    # the stale manager snapshot.  If the manager snapshot is
                    # newer, its values remain authoritative.
                    def key(item):
                        if not isinstance(item, dict):
                            return None
                        row = item.get("row")
                        pid = str(item.get("product_id") or "")
                        return (row, pid)

                    def merge_state(saved, incoming):
                        if not isinstance(saved, dict) or not isinstance(incoming, dict):
                            return
                        saved_at = str(saved.get("updated_at") or "")
                        incoming_at = str(incoming.get("updated_at") or "")
                        if not saved_at or (incoming_at and incoming_at > saved_at):
                            return
                        for field in (
                            "execution", "notice", "errors", "taobao_item_id",
                            "view_url", "edit_url", "duration_seconds", *FLOW_FIELDS,
                        ):
                            if field in saved:
                                incoming[field] = copy.deepcopy(saved[field])

                    def merge_rows(saved_rows, incoming_rows):
                        saved_by_key = {key(item): item for item in saved_rows or []}
                        for incoming in incoming_rows or []:
                            merge_state(saved_by_key.get(key(incoming)), incoming)

                    merge_rows(existing.get("rows"), payload.get("rows"))
                    saved_products = {
                        key((bundle or {}).get("meta") or {}): (bundle or {}).get("meta")
                        for bundle in existing.get("products") or []
                        if isinstance(bundle, dict)
                    }
                    for bundle in payload.get("products") or []:
                        if not isinstance(bundle, dict):
                            continue
                        merge_state(saved_products.get(key(bundle.get("meta") or {})), bundle.get("meta"))
                    existing.update(payload)

                update(merge)
            else:
                raise RuntimeError("会话模块不支持事务写入")
        except Exception as exc:
            # 会话保存失败意味着断点续跑状态可能丢失，必须可见而不是静默
            self.log(f"会话保存失败，断点续跑状态可能不完整: {exc}", "warn")

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
            try:
                self.concurrency = max(1, min(8, int(session.get("concurrency") or self.concurrency)))
            except (TypeError, ValueError):
                pass
            self.global_blocker = str(session.get("global_blocker") or self.global_blocker)
            try:
                self.attention_count = max(0, int(session.get("attention_count") or self.attention_count))
            except (TypeError, ValueError):
                pass
            self.started_at = float(session.get("started_at") or 0.0)
            self.finished_at = float(session.get("finished_at") or 0.0)
            durations = session.get("item_durations")
            if isinstance(durations, list):
                self.item_durations = [float(v) for v in durations if isinstance(v, (int, float))]
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
                self.started_at = 0.0
                self.finished_at = 0.0
                self.item_durations = []
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
            if row["validation"] == "通过" and not self._row_flow_done(row)
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

    def open_workspace(self, path, restoring=False, selected_categories=None):
        import workspace as ws
        root = Path(path).expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"工作空间不存在或不是目录: {root}")
        synced = ws.sync_workbook(root, selected_categories=selected_categories)
        snap = self.import_workbook(synced["path"], restoring=restoring, workspace_path=str(root))
        errors = (synced.get("scan") or {}).get("errors") or []
        added = synced.get("added") or []
        removed = synced.get("removed") or []
        extra = []
        if added:
            extra.append(f"新增 {len(added)} 款")
        if removed:
            extra.append(f"移除 {len(removed)} 款")
        if errors:
            extra.append(f"扫描问题 {len(errors)} 个")
        self.log(
            f"{'已恢复工作空间' if restoring else '已打开工作空间'} {root.name}："
            + f"{synced.get('count') or 0} 条"
            + (("，" + "，".join(extra)) if extra else "")
        )
        snap = self.snapshot()
        snap["workspace"] = self.workspace_info(scan=synced.get("scan"), defaults=synced.get("defaults"))
        snap["sync"] = {"added": added, "removed": removed, "created": synced.get("created")}
        return snap

    def rescan_workspace(self, selected_categories=None):
        with self.lock:
            root = self.workspace_path
        if not root:
            raise RuntimeError("请先选择工作空间")
        return self.open_workspace(root, selected_categories=selected_categories)

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

    def _stable_login_status(self, login, settle_seconds=3.0):
        """Confirm a seller URL once, then keep login until a real logout signal."""
        login = dict(login or {})
        with self.lock:
            if not login.get("logged_in"):
                # 登录页、卖家标签消失或 CDP 断开是真实登出信号：解除滞回
                # 确认，下次出现卖家域名时重新走稳定窗口。
                self._login_candidate_url = ""
                self._login_candidate_since = 0.0
                self._login_confirmed = False
                return login
            if self._login_confirmed:
                # 已确认登录后，任务运行期间的标签跳转只改变 URL，不再
                # 翻转登录状态，避免顶部徽标反复跳回“正在确认登录状态”。
                return login
            url = str(login.get("url") or "")
            now = time.monotonic()
            if self._login_candidate_url != url or not self._login_candidate_since:
                self._login_candidate_url = url
                self._login_candidate_since = now
            if now - self._login_candidate_since >= max(0.0, float(settle_seconds)):
                self._login_confirmed = True
                return login
        return {"logged_in": False, "blocker": "正在确认登录状态", "url": str(login.get("url") or "")}

    def begin_login_check(self, force=False):
        """启动一次后台登录态检测；已在检测或检测过时忽略，返回是否真的启动。"""
        with self.lock:
            if not force and self._auto_check_state != "idle":
                return False
            self._auto_check_state = "running"
        threading.Thread(
            target=self._run_login_check,
            daemon=True,
            name="qianniu-login-check",
        ).start()
        return True

    def _run_login_check(self):
        """后台检测一次卖家中心登录态：后台启动托管浏览器并恢复上次会话。

        浏览器 profile 保存过登录记录时，恢复的卖家页会让 cookie 直接生效，
        状态轮询随即显示「已登录」；未登录时保持现状，由用户点击
        「登录卖家中心」后弹出窗口登录。任何失败都不能影响手动流程。
        """
        try:
            with self.lock:
                busy = self.status in {"running", "stopping"}
            if busy:
                return
            settings = paths.configure_environ()
            web = load_web()
            web.reload_paths()
            browser = paths.browser_exe_path(settings.chrome_path)
            if not browser or not Path(browser).is_file():
                self.log("自动检测登录状态跳过：未找到可用浏览器", "warn")
                return
            with self._auto_check_lock:
                # Existing browsers also need their runtime startup preference
                # verified; the previous version may have only changed JSON.
                web.start_persistent_chrome(
                    focus=False,
                    # 调试模式尊重“保持显示”偏好；默认模式保持收起不弹窗。
                    hide_if_logged_in=not bool(getattr(settings, "debug_browser", False)),
                )
                if not web.cdp_available():
                    raise RuntimeError("已尝试后台启动浏览器，但调试端口未就绪")
                login = self._wait_login_settled(web)
            if login.get("logged_in"):
                url = str(login.get("url") or "")
                with self.lock:
                    # URL 已在稳定窗内确认过，直接置为已确认，让下一次状态
                    # 轮询立即显示「已登录」，不再等 chrome_status 的 3 秒稳定期。
                    self._login_candidate_url = url
                    self._login_candidate_since = time.monotonic()
                    self._login_confirmed = True
                self.log("已自动连接浏览器：卖家中心登录状态有效，无需再次登录")
            else:
                blocker = _plain(login.get("blocker") or "未检测到登录状态")
                self.log(f"自动检测登录状态：{blocker}；需要登录时点击「登录卖家中心」")
        except Exception as exc:
            self.log(f"自动检测登录状态失败：{_plain(exc)}", "warn")
        finally:
            with self.lock:
                self._auto_check_state = "done"

    def _wait_login_settled(self, web, timeout=None, settle=None):
        """轮询 CDP 标签登录态：等卖家 URL 稳定，或确认跳到了登录页。

        恢复的会话里可能没有卖家标签（例如首次使用、只有空白新标签页），
        此时打开一次卖家中心首页，让 cookie 状态决定落在卖家页还是登录页。
        """
        timeout = self._login_check_timeout if timeout is None else float(timeout)
        settle = self._login_check_settle if settle is None else float(settle)
        deadline = time.time() + max(2.0, timeout)
        # 会话恢复的标签可能晚于 CDP 就绪出现，先给一小段宽限再补开首页。
        grace_until = time.time() + max(0.0, self._login_check_grace)
        opened_home = False
        last_url = ""
        stable_since = 0.0
        last = {"logged_in": False, "blocker": "未打开卖家中心", "url": ""}
        while time.time() < deadline:
            with self.lock:
                busy = self.status in {"running", "stopping"}
            if busy:
                break
            try:
                tabs = web.cdp_tabs()
                last = web.login_status_from_tabs(tabs)
            except Exception:
                time.sleep(0.3)
                continue
            url = str(last.get("url") or "")
            if last.get("logged_in"):
                if url and url == last_url and time.time() - stable_since >= max(0.0, settle):
                    return last
                if url != last_url:
                    last_url = url
                    stable_since = time.time()
                time.sleep(0.3)
                continue
            if web.is_login_url(url):
                return last
            has_seller = any(web.is_seller_url(str(tab.get("url") or "")) for tab in tabs)
            if not has_seller and not opened_home and time.time() >= grace_until:
                opened_home = True
                try:
                    web.activate_seller_tab(tabs)
                except Exception:
                    pass
                time.sleep(0.5)
                continue
            if not has_seller and opened_home:
                return last
            time.sleep(0.3)
        return last

    def _wait_for_login_check(self, timeout=None):
        """等待后台登录检测收尾（最多 timeout 秒），避免手动打开时双开浏览器。"""
        seconds = self._auto_check_wait if timeout is None else float(timeout)
        if self._auto_check_lock.acquire(timeout=max(0.0, seconds)):
            self._auto_check_lock.release()

    def _stale_probe(self, active):
        """任务运行期探测失败时返回最近一次成功的 CDP 探测结果。

        批处理上下文保留期间浏览器由任务自己管理；Chrome 忙碌时的单次
        探测超时不代表断开。空闲或超过 ``_probe_stale_seconds`` 时返回
        None，如实上报当前状态。
        """
        if not active:
            return None
        with self.lock:
            probe = self._last_good_probe
            if not probe or not probe.get("cdp"):
                return None
            if time.time() - self._last_good_probe_at > self._probe_stale_seconds:
                return None
            return {"browser": probe.get("browser") or "", "login": dict(probe.get("login") or {})}

    def chrome_status(self):
        # A running batch owns its immutable settings snapshot.  The settings
        # page may have been edited meanwhile, but status polling must not
        # reload those paths into the live worker runtime or report the new
        # profile/port as if it belonged to the active batch.
        active = self._batch_context_retained()
        with self.lock:
            batch_settings = copy.deepcopy(self.batch_settings) if active else None
        if active:
            settings = batch_settings
        else:
            settings = paths.load_settings()
            # save_settings intentionally leaves the current process
            # environment untouched while a batch is active. Once the old
            # browser context is no longer retained, sync the saved profile,
            # port and output paths before reloading the web module. A mocked
            # or malformed settings object must not make status polling fail.
            try:
                settings = paths.configure_environ(settings) or settings
            except Exception:
                pass
        web = load_web()
        if not active:
            web.reload_paths()
        chrome_path = self._setting(settings, "chrome_path", "")
        chrome = paths.browser_exe_path(chrome_path)
        found = bool(chrome and Path(chrome).is_file())
        cdp = False
        browser = ""
        login = {"logged_in": False, "blocker": "未连接调试 Chrome", "url": ""}
        try:
            cdp = web.cdp_available()
            if cdp:
                version = web.cdp_version()
                browser = version.get("Browser") or ""
                login = self._stable_login_status(web.login_status_from_tabs())
                if getattr(self, "_hide_chrome_after_login", False) and login.get("logged_in"):
                    try:
                        web.hide_automation_chrome()
                    except Exception:
                        pass
                    self._hide_chrome_after_login = False
                with self.lock:
                    self._last_good_probe = {"cdp": True, "browser": browser, "login": dict(login)}
                    # 用 wall clock 而不是 monotonic：这里只是 15 秒级的
                    # 陈旧度判断，且 chrome_status 的既有测试按调用次数
                    # mock monotonic，不能再消耗它的序列。
                    self._last_good_probe_at = time.time()
            else:
                fallback = self._stale_probe(active)
                if fallback is None:
                    self._stable_login_status(login)
                else:
                    cdp, browser, login = True, fallback["browser"], fallback["login"]
        except Exception as exc:
            fallback = self._stale_probe(active)
            if fallback is None:
                login = {"logged_in": False, "blocker": str(exc) or "未连接调试 Chrome", "url": ""}
                self._stable_login_status(login)
            else:
                cdp, browser, login = True, fallback["browser"], fallback["login"]
        return {
            "chrome_path": str(chrome or ""),
            "chrome_found": found,
            "browser_source": paths.browser_source(chrome_path),
            "profile": self._setting(settings, "chrome_profile", ""),
            "cdp_port": self._setting(settings, "cdp_port", 0),
            # Window visibility is an immediate preference and is therefore
            # read from disk even while the browser path/port stay frozen to
            # the batch context above.
            "debug_browser": self._saved_debug_browser() if active else bool(self._setting(settings, "debug_browser", False)),
            "cdp": cdp,
            "browser": browser,
            "logged_in": bool(login.get("logged_in")),
            "blocker": login.get("blocker") or "",
            "url": login.get("url") or "",
            # 后台正在自动检测登录态时，前端据此显示“正在检测”而不是未连接。
            "checking": self._auto_check_state == "running",
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
            # 取消勾选后立即收起已有窗口；登录状态不应决定任务栏是否显示。
            return bool(web.hide_automation_chrome())
        except Exception:
            return False
        return False

    def reveal_chrome(self):
        """Show the managed automation browser without changing the saved visibility preference."""
        active = self._batch_context_retained()
        with self.lock:
            batch_settings = copy.deepcopy(self.batch_settings) if active else None
        settings = batch_settings if active else paths.configure_environ()
        web = load_web()
        if not active:
            web.reload_paths()
        chrome_path = self._setting(settings, "chrome_path", "")
        browser = paths.browser_exe_path(chrome_path)
        if not browser or not browser.is_file():
            raise RuntimeError("未找到可用浏览器")

        self._hide_chrome_after_login = False
        self._wait_for_login_check()
        action = web.start_persistent_chrome(focus=True, hide_if_logged_in=False)

        status = self.chrome_status()
        status["opened"] = action
        status["notice"] = "自动化浏览器已显示"
        self.log("已显示自动化浏览器")
        return status

    def _hide_chrome_for_fill(self):
        with self.lock:
            batch_settings = self.batch_settings if self.status in {"running", "stopping"} else None
        debug_browser = bool(self._setting(batch_settings, "debug_browser", False)) if batch_settings is not None else paths.load_settings().debug_browser
        if debug_browser:
            self._hide_chrome_after_login = False
            try:
                load_web().reveal_automation_chrome()
            except Exception:
                pass
            return
        try:
            web = load_web()
            # Starting/resuming a task applies the preference immediately.
            # The login settling delay belongs only to the manual login flow.
            if web.cdp_available():
                web.hide_automation_chrome()
                self._hide_chrome_after_login = False
        except Exception:
            pass

    def _apply_chrome_pref_for_fill(self):
        """填单/入库运行期间的窗口可见性跟随「显示自动化浏览器」开关。

        隐藏实现（hide_automation_chrome）是"移出屏幕 + 移除任务栏按钮但保持
        IsWindowVisible"，配合防节流启动参数 Chrome 渲染不冻结，自动化点击
        不会超时，因此运行期间无需再为可靠性强制显示窗口；勾选开关可实时
        查看现场。结束/暂停后的可见性由 _finish_browser 按开关恢复。
        """
        self._hide_chrome_after_login = False
        if not self._saved_debug_browser():
            try:
                load_web().hide_automation_chrome()
            except Exception:
                pass
            return
        try:
            load_web().reveal_automation_chrome()
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

    def _reveal_chrome_for_attention(self):
        """非登录的人工介入场景（验证码/滑块/停滞/需人工检查）的窗口策略。

        跟随「显示自动化浏览器」开关：勾选时显示现场，未勾选时保持隐藏；
        只有登录场景才无条件弹出窗口。
        """
        try:
            web = load_web()
        except Exception:
            return
        # This preference is deliberately live: saving the display switch
        # must affect a running/paused batch without changing its profile or
        # CDP endpoint.
        debug_browser = self._saved_debug_browser()
        if not debug_browser:
            try:
                web.hide_automation_chrome()
            except Exception:
                pass
            return
        self._hide_chrome_after_login = False
        try:
            web.reveal_automation_chrome()
        except Exception:
            pass

    def open_chrome(self):
        active = self._batch_context_retained()
        with self.lock:
            batch_settings = copy.deepcopy(self.batch_settings) if active else None
        settings = batch_settings if active else paths.configure_environ()
        web = load_web()
        if not active:
            web.reload_paths()
        chrome_path = self._setting(settings, "chrome_path", "")
        browser = paths.browser_exe_path(chrome_path)
        if not browser or not browser.is_file():
            raise RuntimeError("未找到可用浏览器：安装包缺少内置 Chromium，且未检测到自定义或系统 Chrome")
        # 后台登录检测可能正在启动同一个浏览器；最多等它收尾，避免双开。
        self._wait_for_login_check()
        debug_browser = self._saved_debug_browser()
        action = web.start_persistent_chrome(
            focus=True,
            # 点击按钮后先确保浏览器真实显示且可交互。是否已登录由带稳定期
            # 的 chrome_status 再确认，避免首次登录重定向时提前收起窗口。
            hide_if_logged_in=False,
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
            # An active batch owns its pages through the worker pool.  Do not
            # run a process-wide cleanup from the manual browser entrypoint.
            if not active:
                try:
                    web.reconcile_browser_tabs(keep_fill_pages=True)
                except Exception:
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
        web = load_web()
        # 商品查看和编辑都在独立的内置 Chromium 中打开。这个入口不复用
        # 入库浏览器的 profile/CDP 端口，也不调用会清理入库页签的旧入口。
        opener = getattr(web, "open_item_url_in_builtin_browser", None)
        if not callable(opener):
            raise RuntimeError("当前运行时缺少独立商品详情浏览器")
        result = opener(url)
        self.log(f"已打开{'查看' if kind == 'view' else '编辑'}商品 {found.get('product_id') or ''}")
        return result

    def clear_row_state(self, row, product_id=""):
        """清除某条商品的执行状态/商品 ID，让它回到「未执行」可重新入库。

        商品数据本身保留，仅清空 rows 与 products[].meta 上的执行字段。
        用于本地残留了已被千牛后台删除的商品 ID，导致永远走续跑补图的情况。
        """
        pid = str(product_id or "")
        reset_id = uuid.uuid4().hex
        cleared = None
        with self.lock:
            if self.status in {"running", "stopping"}:
                raise RuntimeError("任务正在运行，请先停止后再清除")
            for item in self.rows:
                if item.get("row") != row:
                    continue
                if pid and str(item.get("product_id") or "") not in {"", pid}:
                    continue
                _reset_execution_fields(item, reset_id)
                cleared = dict(item)
                break
            for bundle in self.products:
                meta = bundle.get("meta") or {}
                if meta.get("row") != row:
                    continue
                if pid and str(meta.get("product_id") or "") not in {"", pid}:
                    continue
                _reset_execution_fields(meta, reset_id)
                _reset_execution_fields(bundle.setdefault("product", {}), reset_id)
                bundle["meta"] = meta
                if cleared is None:
                    cleared = dict(meta)
                break
        if cleared is None:
            raise RuntimeError("找不到该商品")
        module = _job_session()
        if module is not None:
            try:
                module.forget_execution(row=row, product_id=pid, reset_id=reset_id)
            except Exception as exc:
                self.log(f"执行历史清除失败（{pid or row}）: {exc}", "warn")
        self._save_session()
        label = cleared.get("product_id") or f"第{row}行"
        self.log(f"{label} 已清除执行状态，下次会重新入库", "warn")
        return {"ok": True, "row": row, "product_id": cleared.get("product_id") or ""}

    def clear_rows_state(self, rows):
        """批量清除多行商品的执行状态（执行明细一键清除入口）。

        语义与 clear_row_state 一致：仅清空 rows 与 products[].meta 的执行
        字段，商品数据保留。行号不在当前清单里的会被忽略；全部未知时才报错。
        """
        wanted = {int(r) for r in rows or []}
        if not wanted:
            raise RuntimeError("请先选择要清除的记录")
        cleared_rows = set()
        reset_ids = {row: uuid.uuid4().hex for row in wanted}
        with self.lock:
            if self.status in {"running", "stopping"}:
                raise RuntimeError("任务正在运行，请先停止后再清除")
            for item in self.rows:
                if item.get("row") not in wanted:
                    continue
                _reset_execution_fields(item, reset_ids[item.get("row")])
                cleared_rows.add(item.get("row"))
            for bundle in self.products:
                meta = bundle.get("meta") or {}
                if meta.get("row") not in wanted:
                    continue
                _reset_execution_fields(meta, reset_ids[meta.get("row")])
                _reset_execution_fields(bundle.setdefault("product", {}), reset_ids[meta.get("row")])
                bundle["meta"] = meta
                cleared_rows.add(meta.get("row"))
        if not cleared_rows:
            raise RuntimeError("找不到该商品")
        module = _job_session()
        if module is not None:
            try:
                module.forget_executions(rows=cleared_rows, reset_ids=reset_ids)
            except Exception as exc:
                self.log(f"执行历史批量清除失败（{len(cleared_rows)} 行）: {exc}", "warn")
        self._save_session()
        self.log(f"已批量清除 {len(cleared_rows)} 条执行记录，对应商品下次会重新入库", "warn")
        return {"ok": True, "cleared": len(cleared_rows)}

    def _pending_products(self, force_new=False, retry_failed=False, selected_rows=None):
        selection = None if selected_rows is None else {
            (item["row"], item["product_id"]) for item in selected_rows
        }
        pending = []
        for bundle in self.products:
            meta = dict(bundle.get("meta") or {})
            if selection is not None and (meta.get("row"), str(meta.get("product_id") or (bundle.get("product") or {}).get("product_id") or "")) not in selection:
                continue
            # rows 是执行明细的即时镜像。某些中断时序下 on_item_done
            # 先刷新了 rows、随后才写入 products[].meta；续跑不能因此丢掉
            # 已显示的商品 ID，否则会把已有商品误送回新建发布页。
            row_state = next(
                (
                    row for row in self.rows
                    if row.get("row") == meta.get("row")
                ),
                None,
            )
            if row_state:
                for key in (
                    "execution", "notice", "errors", "taobao_item_id", "view_url", "edit_url",
                    "duration_seconds",
                    *FLOW_FIELDS,
                ):
                    value = row_state.get(key)
                    if key == "errors":
                        if value is not None:
                            meta[key] = list(value or [])
                    elif value not in (None, "") or (key == "video_warning" and key in row_state):
                        meta[key] = value
            if meta.get("validation") != "通过":
                continue
            execution = meta.get("execution") or "未执行"
            if (retry_failed or not force_new) and self._row_flow_done(meta):
                continue
            product = dict(bundle.get("product") or {})
            product["execution"] = execution
            product["execution_reset_id"] = meta.get("execution_reset_id") or product.get("execution_reset_id") or ""
            for key in ("resume_checkpoint", "last_browser_write"):
                if meta.get(key):
                    product[key] = copy.deepcopy(meta[key])
            product["notice"] = meta.get("notice") or product.get("notice") or ""
            product["errors"] = list(meta.get("errors") or [])
            product["flow_version"] = meta.get("flow_version") or product.get("flow_version") or ""
            product["sku_image_strategy"] = meta.get("sku_image_strategy") or product.get("sku_image_strategy") or ""
            product["flow_stage"] = meta.get("flow_stage") or product.get("flow_stage") or ""
            product["spec_image_stage"] = meta.get("spec_image_stage") or product.get("spec_image_stage") or ""
            product["run_status"] = meta.get("run_status") or product.get("run_status") or ""
            product["sku_material_manifest"] = meta.get("sku_material_manifest") or product.get("sku_material_manifest") or ""
            product["material_result"] = meta.get("material_result") or product.get("material_result") or ""
            product["material_preview"] = meta.get("material_preview") or product.get("material_preview") or []
            product["material_folder"] = meta.get("material_folder") or product.get("material_folder") or ""
            product["last_error"] = meta.get("last_error") or product.get("last_error") or ""
            product["video_warning"] = meta.get("video_warning", product.get("video_warning")) or ""
            product["video_status"] = meta.get("video_status") or product.get("video_status") or ""
            product["taobao_item_id"] = meta.get("taobao_item_id") or product.get("taobao_item_id") or ""
            product["view_url"] = meta.get("view_url") or product.get("view_url") or ""
            product["edit_url"] = meta.get("edit_url") or product.get("edit_url") or ""
            pending.append(product)
        return pending

    def start_job(self, confirm_submit=True, limit=0, concurrency=None, force_new=False, retry_failed=False, selected_rows=None, workbook_path=None):
        with self.lock:
            if self.update_pending:
                raise RuntimeError("已安排任务结束后重启更新，请先取消自动重启再开始新任务")
            if self.status in {"running", "stopping"}:
                raise RuntimeError("已有入库任务在运行")
            stale = code_watch.stale_code_files()
            if stale:
                raise RuntimeError(code_watch.stale_code_notice(stale))
            if not self.workbook_path:
                raise RuntimeError("请先导入商品清单或选择工作空间")
            if workbook_path is not None and Path(workbook_path).resolve() != Path(self.workbook_path).resolve():
                raise RuntimeError("当前清单已变化，请刷新后重新选择商品")
            if selected_rows is not None:
                selected_rows = copy.deepcopy(selected_rows)
                selected_keys = {(item["row"], item["product_id"]) for item in selected_rows}
                available = {(row.get("row"), str(row.get("product_id") or "")) for row in self.rows}
                if not selected_keys or len(selected_keys) != len(selected_rows) or not selected_keys.issubset(available):
                    raise RuntimeError("所选商品已变化或包含重复项，请重新选择后执行")
                fingerprints = {(row.get("row"), str(row.get("product_id") or "")): str(row.get("pack_fingerprint") or "") for row in self.rows}
                if any(item.get("pack_fingerprint") is not None and item["pack_fingerprint"] != fingerprints[(item["row"], item["product_id"])] for item in selected_rows):
                    raise RuntimeError("所选商品素材已变化，请重新扫描并选择后执行")
            executable = self._pending_products(force_new=force_new, retry_failed=retry_failed, selected_rows=selected_rows)
            if not executable:
                if selected_rows is not None:
                    raise RuntimeError("所选商品没有通过校验的未完成项，已完成商品会自动跳过")
                if retry_failed:
                    raise RuntimeError("没有通过校验的未完成商品")
                if force_new:
                    raise RuntimeError("没有通过校验的商品，无法入库")
                raise RuntimeError("没有待处理商品。如需重新建品，请在执行明细中清除对应商品的记录后重试")
            self.batch_settings = self._settings_snapshot(paths.load_settings())
            if concurrency is not None:
                try:
                    requested_concurrency = max(1, min(8, int(concurrency)))
                except (TypeError, ValueError) as exc:
                    raise RuntimeError("并发数必须是 1 到 8 之间的整数") from exc
                if isinstance(self.batch_settings, dict):
                    self.batch_settings["concurrency"] = requested_concurrency
                else:
                    self.batch_settings.concurrency = requested_concurrency
            try:
                self.concurrency = max(1, min(8, int(self._setting(self.batch_settings, "concurrency", 2) or 2)))
            except (TypeError, ValueError):
                self.concurrency = 2
            self.cancel.clear()
            self.status = "running"
            self.blocker = ""
            self.global_blocker = ""
            self.phase = "准备"
            self.done = 0
            self.total = len(executable) if not limit else min(len(executable), int(limit))
            self.seen_steps = set()
            self.worker_events = {}
            self.active_worker_events = {}
            self._completed_rows = set()
            self._attention_rows = set()
            self.attention_count = 0
            self.activity_at = time.time()
            self.started_at = time.time()
            self.finished_at = 0.0
            self.item_durations = []
            self.stalled = False
            self.result_xlsx = ""
            self.result_json = ""
        self._hide_chrome_for_fill()
        if retry_failed:
            mode = "重试未完成项"
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
            f"{mode}：{self.total} 条，放入仓库，确认提交到仓库；并发 {self.concurrency}"
            + (f"；仅处理所选 {len(selected_rows)} 件商品" if selected_rows is not None else "；全部未完成项")
            + extra_tab
        )
        self.thread = threading.Thread(
            target=self._run_job,
            kwargs={
                "confirm_submit": bool(confirm_submit),
                "limit": int(limit or 0),
                "force_new": bool(force_new),
                "retry_failed": bool(retry_failed),
                "selected_rows": selected_rows,
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
        self.log("已请求暂停，正在中断当前页面操作并保留现场；之后可继续", "warn")
        return self.snapshot()

    def job_history(self, limit=30):
        """扫描 results 目录最近的结果 JSON，汇总每次入库任务的耗时统计。

        旧版本结果文件没有时间字段，对应项返回 None，前端显示为 —。
        """
        results_dir = Path(paths.load_settings().results_dir)
        entries = []
        if results_dir.is_dir():
            try:
                files = sorted(
                    (p for p in results_dir.glob("*.json") if ".结果-" in p.name),
                    key=lambda p: p.stat().st_mtime,
                    reverse=True,
                )
            except OSError:
                files = []
            for path in files[: max(1, int(limit))]:
                entry = _parse_history_file(path)
                if entry:
                    entries.append(entry)
        return entries

    def _touch_activity(self, note=""):
        """记录任务活动时间；从看门狗的停滞态恢复时给出提示。"""
        with self.lock:
            self.activity_at = time.time()
            stalled = self.stalled
            self.stalled = False
        if stalled:
            self.log("任务已恢复进展，继续执行", "info")

    def _consume_fill_progress(self, steps, watch_state):
        with self.lock:
            current_id = self.current_id
        if current_id != watch_state.get("last_id"):
            watch_state["last_id"] = current_id
            watch_state["last_label"] = ""
            with self.lock:
                self.seen_steps = set()
            return
        signature = (len(steps), str(steps[-1].get("step") or "") if steps and isinstance(steps[-1], dict) else "")
        if signature != watch_state.get("steps_signature"):
            watch_state["steps_signature"] = signature
            self._touch_activity()
        label = current_step_label(steps)
        last_label = watch_state.get("last_label") or ""
        if label and label != last_label:
            watch_state["last_label"] = label
            with self.lock:
                self.phase = label
            key = ""
            if steps and isinstance(steps[-1], dict):
                key = str(steps[-1].get("step") or "")
            token = (current_id, key, label if key == "spec_images" else "")
            if token not in self.seen_steps and key:
                self.seen_steps.add(token)
                extra = ""
                last_step = steps[-1] if steps and isinstance(steps[-1], dict) else {}
                if last_step.get("skipped") or (isinstance(last_step.get("result"), dict) and last_step["result"].get("skipped")):
                    extra = "已完成，跳过"
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
            # Concurrent workers write progress to their isolated output
            # directories and report it through ``on_worker_event``.  Read
            # the legacy shared progress file only for the serial path; the
            # watchdog itself is shared and checks each active worker event.
            with self.lock:
                serial = self.concurrency <= 1
            if serial:
                self._consume_fill_progress(read_fill_progress(), watch_state)
            self._check_stalled()

    def _check_stalled(self):
        """看门狗：running 且长时间无任何进展时显式报警并弹出浏览器。

        不强杀流水线：浏览器现场必须保留给人工判断，任务可继续或协作停止。
        """
        with self.lock:
            if self.status != "running" or self.stalled:
                # A batch-level stall has already been reported.  Worker
                # slots can still recover independently, so continue below
                # only when the batch itself is not marked stalled.
                batch_stalled = self.stalled
            else:
                batch_stalled = False
            idle = time.time() - self.activity_at
        threshold = stall_seconds()
        worker_messages = []
        with self.lock:
            if self.status != "running":
                return
            now = time.time()
            for worker_id, state in self.active_worker_events.items():
                last = float(state.get("activity_at") or now)
                if now - last <= threshold:
                    continue
                if state.get("stalled"):
                    continue
                state["stalled"] = True
                worker_messages.append(
                    f"执行槽 {worker_id}（第{state.get('row')}行 {state.get('product_id') or ''}）"
                )
            if idle > threshold and not batch_stalled:
                self.stalled = True
                self.blocker = (
                    f"任务已超过 {max(1, threshold // 60)} 分钟无任何进展，"
                    "可能被页面弹窗或验证阻塞"
                )
            elif worker_messages:
                self.stalled = True
                self.blocker = "；".join(worker_messages) + "超过停滞阈值，可能被页面弹窗或验证阻塞"
            elif batch_stalled:
                return
            elif not self.stalled:
                return
        # 停滞意味着可能被弹窗/验证阻塞；窗口可见性跟随开关——隐藏窗口
        # 渲染正常，不会因隐藏而卡死，未勾选时保持隐藏并提示如何查看现场。
        self._apply_chrome_pref_for_fill()
        if self._saved_debug_browser():
            self.log(f"{self.blocker}；已显示自动化浏览器，请检查现场后选择暂停或继续等待", "error")
        else:
            self.log(f"{self.blocker}；浏览器保持隐藏，勾选「显示自动化浏览器」可查看现场后选择暂停或继续等待", "error")

    def _run_job(self, confirm_submit=True, limit=0, force_new=False, retry_failed=False, selected_rows=None):
        stop = threading.Event()
        with self.lock:
            settings = copy.deepcopy(self.batch_settings)
            concurrency = self.concurrency
        if settings is None:
            settings = self._settings_snapshot(paths.load_settings())
        # Configure the loaded runtime once from the immutable batch snapshot.
        # Settings writes during this run are handled by the server/UI layer
        # without reloading the active runtime.
        paths.configure_environ(settings)
        watcher = None
        if concurrency <= 1:
            try:
                (paths.playwright_output_dir() / "web_fill_progress.json").write_text("[]", encoding="utf-8")
            except OSError:
                pass
        # The concurrent path has no single shared progress file, but its
        # worker events still need periodic stall checks.
        watcher = threading.Thread(target=self._watch_progress, args=(stop,), daemon=True)
        watcher.start()
        seller = load_seller()
        paths.apply_to_loaded_modules()
        self._apply_chrome_pref_for_fill()
        try:
            with self.lock:
                selected = self._pending_products(force_new=force_new, retry_failed=retry_failed, selected_rows=selected_rows)
                source = self.workbook_path
            cap = int(limit or 0)
            selected = selected[:cap] if cap else selected
            web_fill = seller.load_web_fill()
            runtime_settings = copy.deepcopy(settings)
            if isinstance(runtime_settings, dict):
                runtime_settings["workbook_path"] = source
            else:
                try:
                    runtime_settings.workbook_path = source
                except Exception:
                    runtime_settings = dict(getattr(runtime_settings, "__dict__", {}) or {})
                    runtime_settings["workbook_path"] = source
            finished = {"count": 0}
            item_started = {}

            def on_start(product):
                # 重试同一条目时不重置计时，时长覆盖该条的全部尝试
                item_key = product.get("row")
                if item_key is None:
                    item_key = str(product.get("product_id") or "")
                with self.lock:
                    item_started.setdefault(item_key, time.time())
                    self.current_row = product.get("row")
                    self.current_id = str(product.get("product_id") or "")
                    self.phase = "开始填写"
                    self.done = finished["count"]
                    if self.concurrency <= 1:
                        self.seen_steps = set()
                    self.activity_at = time.time()
                self.log(f"正在填写第 {product.get('row')} 行 {product.get('product_id') or ''}")

            def on_done(product, item):
                item_key = product.get("row")
                if item_key is None:
                    item_key = str(product.get("product_id") or "")
                with self.lock:
                    first_done = item_key not in self._completed_rows
                    if first_done:
                        self._completed_rows.add(item_key)
                        finished["count"] += 1
                    started = item_started.pop(item_key, None)
                if started:
                    item["duration_seconds"] = round(time.time() - started, 1)
                execution = item.get("execution") or ""
                notice = str(item.get("notice") or "").strip()
                serialized = serialize_row({**product, **item})
                flow_fields = {key: item.get(key) for key in FLOW_FIELDS
                               if item.get(key) not in (None, "") or (key == "video_warning" and key in item)}
                pause_code = pause_reason_code(notice) if execution == "暂停" else ""
                with self.lock:
                    self.done = finished["count"]
                    if first_done and item.get("duration_seconds"):
                        self.item_durations.append(float(item["duration_seconds"]))
                    if execution in ATTENTION_EXECUTIONS:
                        self._attention_rows.add(item_key)
                        self.attention_count = len(self._attention_rows)
                    if execution == "暂停" and not self.global_blocker:
                        self.blocker = notice
                    for row in self.rows:
                        if row.get("row") != product.get("row"):
                            continue
                        row["execution"] = serialized.get("execution") or row.get("execution")
                        row["notice"] = serialized.get("notice") or ""
                        row["taobao_item_id"] = serialized.get("taobao_item_id") or row.get("taobao_item_id") or ""
                        row["view_url"] = serialized.get("view_url") or row.get("view_url") or ""
                        row["edit_url"] = serialized.get("edit_url") or row.get("edit_url") or ""
                        if item.get("duration_seconds"):
                            row["duration_seconds"] = item["duration_seconds"]
                        row.update(flow_fields)
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
                        if item.get("duration_seconds"):
                            meta["duration_seconds"] = item["duration_seconds"]
                        meta.update(flow_fields)
                        bundle["meta"] = meta
                        break
                pid = product.get("product_id") or ""
                if execution in ("失败", "暂停", "提交失败"):
                    self.log(f"{pid} {execution}: {notice[:400]}", "error")
                else:
                    self.log(f"{pid} {execution}")
                with self.lock:
                    self.activity_at = time.time()
                if pause_code == "login":
                    self._reveal_chrome_for_login()
                elif pause_code:
                    self._reveal_chrome_for_attention()

            def on_retry(product, item, attempt, retry_limit):
                pid = product.get("product_id") or ""
                notice = str(item.get("notice") or "").strip()
                with self.lock:
                    self.phase = f"自动重试（第 {attempt}/{retry_limit} 次）"
                    self.activity_at = time.time()
                self.log(f"{pid} 第 {attempt}/{retry_limit} 次自动重试：{notice[:200]}", "warn")

            def on_flow(product, item):
                # 建品成功瞬间 ID/执行状态就已确定，必须随 flow 字段一起实时
                # 回写：否则明细里“已入库，待补图”配着“未执行/无ID”，已入库
                # 计数也停在 0，直到整条补图流程终态才纠正。
                fields = {
                    "execution_reset_id": item.get("execution_reset_id"),
                    "resume_checkpoint": item.get("resume_checkpoint"),
                    "last_browser_write": item.get("last_browser_write"),
                    "execution": item.get("execution"),
                    "taobao_item_id": item.get("taobao_item_id"),
                    "view_url": item.get("view_url"),
                    "edit_url": item.get("edit_url"),
                    "flow_version": item.get("flow_version"),
                    "sku_image_strategy": item.get("sku_image_strategy"),
                    "flow_stage": item.get("flow_stage"),
                    "spec_image_stage": item.get("spec_image_stage"),
                    "run_status": item.get("run_status"),
                    "sku_material_manifest": item.get("sku_material_manifest"),
                    "material_result": item.get("material_result"),
                    "material_preview": item.get("material_preview"),
                    "material_folder": item.get("material_folder"),
                    "last_error": item.get("last_error"),
                    "video_status": item.get("video_status"),
                }
                if "video_warning" in item:
                    fields["video_warning"] = item["video_warning"]
                fields = {key: value for key, value in fields.items()
                          if value not in (None, "") or (key == "video_warning" and value == "")}
                if not fields:
                    return
                if fields.get("taobao_item_id"):
                    # ID 就位时补齐查看/编辑链接；只在显式出现 ID 时处理，
                    # 避免中途 emit 缺 ID 字段时把已回填的链接清空。
                    link_module = _job_session()
                    if link_module is not None and hasattr(link_module, "apply_action_links"):
                        fields = {
                            key: value
                            for key, value in link_module.apply_action_links(fields).items()
                            if value not in (None, "") or (key == "video_warning" and value == "")
                        }
                module = _job_session()
                if module is None or not hasattr(module, "patch_flow_state"):
                    raise RuntimeError("续跑状态写入不可用")
                # A checkpoint write is part of the item outcome.  Let the
                # pipeline see the error so it cannot report a successful
                # item whose resume state was lost.
                module.patch_flow_state(
                    product.get("row"),
                    product.get("product_id") or "",
                    fields,
                )
                with self.lock:
                    self.activity_at = time.time()
                    for row in self.rows:
                        if row.get("row") != product.get("row"):
                            continue
                        for key, value in fields.items():
                            row[key] = value
                        break
                    for bundle in self.products:
                        meta = bundle.get("meta") or {}
                        if meta.get("row") != product.get("row"):
                            continue
                        for key, value in fields.items():
                            meta[key] = value
                        bundle["meta"] = meta
                        break

            executed = web_fill.run_batch(
                selected,
                confirm_submit=confirm_submit,
                cancel_event=self.cancel,
                on_item_start=on_start,
                on_item_done=on_done,
                on_item_retry=on_retry,
                on_flow_stage=on_flow,
                concurrency=concurrency,
                on_worker_event=self._on_worker_event,
                runtime_settings=runtime_settings,
                force_new=force_new,
                sku_template_import=self._setting(settings, "sku_template_import", False),
                skip_spec_images=self._setting(settings, "skip_spec_images", False),
                sku_image_strategy=self._setting(settings, "sku_image_strategy", "slim_material"),
                spec_upload_batch_size=self._setting(settings, "spec_upload_batch_size", 0),
                item_retry_limit=self._setting(settings, "item_retry_limit", 0),
            )
            by_row = {item.get("row"): item for item in executed or []}
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            results_dir = Path(self._setting(settings, "results_dir", paths.default_results_dir()))
            results_dir.mkdir(parents=True, exist_ok=True)
            source_path = Path(source)
            output = results_dir / f"{source_path.stem}.结果-{stamp}.xlsx"
            journal = results_dir / f"{source_path.stem}.结果-{stamp}.json"
            updated_rows = []
            report_rows = []
            attention = []
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
                        for key in FLOW_FIELDS:
                            if web_item.get(key) not in (None, "") or (key == "video_warning" and key in web_item):
                                item[key] = web_item.get(key)
                        if item.get("execution") in ATTENTION_EXECUTIONS:
                            attention.append(
                                f"第{item.get('row')}行 {item.get('product_id') or ''} "
                                f"{item.get('execution')}: {str(item.get('notice') or '')[:80]}"
                            )
                    serialized = serialize_row(item)
                    updated_rows.append(serialized)
                    report_rows.append(item)
                    bundle["meta"] = item
                self.rows = updated_rows
                self.done = len(executed or [])
                self.total = len(selected)
                self.attention_count = max(self.attention_count, len(attention))
            entries = [[
                stamp,
                r.get("row"),
                r.get("product_id"),
                ("校验" + r.get("validation", "")) if r.get("execution") == "未执行" else r.get("execution"),
                "; ".join(str(e).split(":", 1)[0] for e in (r.get("errors") or [])),
                (flow_stage_label(r) + "；" + r.get("notice")) if r.get("notice") else flow_stage_label(r) or "",
                "; ".join(r.get("errors") or []) or (r.get("notice") or ""),
                _action_links(r).get("taobao_item_id") or "",
                format_duration(r.get("duration_seconds")),
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
                "concurrency": concurrency,
                "attention_count": len(attention),
                "global_blocker": self.global_blocker,
                "total": len(selected),
                "done": len(executed or []),
                "started_at": self.started_at or None,
                "finished_at": time.time(),
                "duration_seconds": (
                    round(time.time() - self.started_at, 1) if self.started_at else None
                ),
                "results": [serialize_row(r) for r in report_rows],
            }
            journal.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            pause_code = ""
            with self.lock:
                self.finished_at = time.time()
                self.result_xlsx = str(output)
                self.result_json = str(journal)
                if self.global_blocker:
                    self.status = "paused"
                    self.phase = "需人工处理"
                    pause_code = pause_reason_code(self.global_blocker)
                elif self.cancel.is_set():
                    self.status = "stopped"
                    self.phase = "已停止"
                elif attention:
                    # 单条失败不再中断整批；跑完后统一汇总需人工处理的条目。
                    self.status = "paused"
                    self.phase = "需人工处理"
                    more = f" 等{len(attention)}条" if len(attention) > 3 else ""
                    self.blocker = f"{len(attention)} 条需人工处理：" + "；".join(attention[:3]) + more
                    pause_code = pause_reason_code(self.blocker)
                else:
                    self.status = "done"
                    self.phase = "完成"
            if pause_code == "login":
                self._reveal_chrome_for_login()
            elif pause_code:
                self._reveal_chrome_for_attention()
            self.log(f"任务结束，结果已保存: {output.name}")
            self._save_session()
        except Exception as exc:
            text = _plain(exc)
            pause_code = pause_reason_code(text)
            with self.lock:
                self.finished_at = time.time()
                if pause_code:
                    self.status = "paused"
                    self.blocker = text
                    self.phase = "需人工处理"
                else:
                    self.status = "error"
                    self.phase = "失败"
                self.message = text
            if pause_code == "login":
                self._reveal_chrome_for_login()
            elif pause_code:
                self._reveal_chrome_for_attention()
            self.log(text, "error")
            self.log(traceback.format_exc(), "error")
            self._save_session()
        finally:
            stop.set()
            if watcher is not None:
                watcher.join(timeout=1.5)
            with self.lock:
                self.active_worker_events.clear()
            self._finish_browser()
            self._save_session()

    def _finish_browser(self):
        # The pipeline keeps paused material pickers intact. Do not undo that
        # guarantee in desktop cleanup by closing every publishing tab.
        with self.lock:
            preserve = self.status != "done" or any(
                row.get("execution") in {"暂停", "失败", "结果待核实", "提交失败", "提交待核实"}
                for row in self.rows
            )
        if preserve:
            # 需人工检查的现场（图片/错误/待核实）跟随「显示自动化浏览器」
            # 开关：勾选时显示且登录轮询不收起，未勾选时保持隐藏不弹窗。
            debug_browser = self._saved_debug_browser()
            if debug_browser:
                self._reveal_chrome_for_attention()
            else:
                self._hide_chrome_for_fill()
            return
        # Worker sessions already released their own pages in the pool.  A
        # successful desktop run must not globally close legacy or user tabs
        # that have no ownership registry entry.
        self._hide_chrome_for_fill()


MANAGER = JobManager()
