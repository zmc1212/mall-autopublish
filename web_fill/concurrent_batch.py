"""Bounded product workers around the existing single-product workflow."""

import copy
import hashlib
import json
import re
import shutil
import threading
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .runtime import CheckpointError, WorkerRuntime, worker_runtime


# A no-ID record in any of these states may represent a page that was already
# filled or a submit whose server result was never confirmed.  It must never
# silently fall through to ``begin_item``'s new-page path.
_LEGACY_UNCERTAIN_EXECUTIONS = frozenset({
    "失败", "暂停", "提交失败", "提交待核实", "已填写未提交", "结果待核实", "已停止",
})
_LEGACY_PUBLISH_HOSTS = frozenset({
    "item.upload.taobao.com", "item.manager.taobao.com",
})


class BatchCancellation:
    def __init__(self, user_event):
        self.user_event = user_event
        self.blocked = threading.Event()
        self.reason = ""

    def is_set(self):
        return self.blocked.is_set() or bool(self.user_event and self.user_event.is_set())


def global_blocker(notice):
    """Only shared failures stop dispatch; a page's slider does not."""
    text = str(notice or "")
    if re.search(r"\bPAUSE\s*[:：]\s*login\b", text, flags=re.IGNORECASE):
        return text
    lowered = text.lower()
    # Playwright CLI emits this call-log phrase while a daemon is attaching
    # to the shared CDP browser.  A timeout/ECONN/disconnect here means every
    # worker will fail to attach; keep an ordinary page-level timeout item
    # scoped by requiring the websocket-retrieval marker as well.
    if ("retrieving websocket url" in lowered
            and any(marker in lowered for marker in (
                "timeout", "econn", "disconnected", "disconnect", "connection reset",
            ))):
        return text
    markers = (
        "当前店铺与上次执行店铺不一致", "登录页", "请先登录", "请登录", "请重新登录",
        "账号级", "账号已被限制", "账号被限制", "店铺访问被拒绝",
        "ECONNREFUSED", "ERR_CONNECTION_REFUSED", "Browser has been closed",
        "browser has been closed", "Browser closed", "browser disconnected",
        "断点保存失败",
    )
    if any(marker in text for marker in markers):
        return text
    if "登录失效" in text and "或需要人工处理" not in text:
        return text
    if any(host in text for host in ("login.taobao.com", "login.tmall.com")):
        return text
    return ""


def _browser_connection_lost(web):
    """Return a global blocker only when the shared browser is really gone.

    Page-level Playwright errors are deliberately left item-scoped.  The
    connection probe is used as the second signal for ambiguous errors such
    as ``Target page ... has been closed``.
    """
    probe = getattr(web, "cdp_available", None)
    if not callable(probe):
        # Test doubles and older packaged web modules may not expose the
        # optional probe; absence is not evidence of a browser outage.
        return ""
    try:
        available = bool(probe())
    except Exception:
        return ""
    return "浏览器调试连接已断开，已停止后续派发" if not available else ""


def _safe_legacy_publish_href(value):
    """Validate a fresh publish URL suitable for exact legacy adoption."""
    href = str(value or "").strip()
    if not href:
        return ""
    try:
        parsed = urlparse(href)
    except ValueError:
        return ""
    if parsed.scheme.lower() not in {"http", "https"}:
        return ""
    if (parsed.hostname or "").lower() not in _LEGACY_PUBLISH_HOSTS:
        return ""
    if parsed.path.rstrip("/").lower() != "/sell/v2/publish.htm":
        return ""
    # An itemId/edit URL is an existing product page, whose state cannot be
    # used as the old new-product checkpoint without an item ID audit.
    query = parse_qs(parsed.query, keep_blank_values=True)
    if any(str(name).lower() in {"itemid", "item_id"} for name in query):
        return ""
    if "itemid=" in parsed.query.lower() or "edit.htm" in parsed.path.lower():
        return ""
    return href


def _publish_checkpoint_keys(product, pipeline_module):
    payload = pipeline_module.product_to_payload(product)
    keys = {pipeline_module.resume_key(payload)}
    # The old page checkpoint predates the per-attribute SKU mapping.
    legacy = copy.deepcopy(payload)
    for sku in legacy.get("skus") or []:
        sku.pop("specs", None)
    keys.add(pipeline_module.resume_key(legacy))
    return keys


def _submit_is_uncertain(product):
    checkpoint = product.get("resume_checkpoint") or {}
    return (product.get("flow_stage") == "submit_pending"
            or product.get("spec_image_stage") == "submit_pending"
            or product.get("execution") in {"提交待核实", "结果待核实"}
            or (isinstance(checkpoint, dict) and checkpoint.get("submit_started") is True)
            or (product.get("last_browser_write") or {}).get("script") == "submit.js")


def _can_restart_before_submit(product):
    checkpoint = product.get("resume_checkpoint") or {}
    return (not product.get("taobao_item_id") and not _submit_is_uncertain(product)
            and isinstance(checkpoint, dict) and checkpoint.get("submit_started") is False
            and not checkpoint.get("media_pending")
            and "video_upload_pending" not in (checkpoint.get("completed") or []))


def _read_checkpoint(path):
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError):
        return {}


def _restore_previous_attempt(product, base, pipeline_module):
    """Migrate a matching old worker checkpoint without resetting uncertain writes."""
    product = dict(product)
    if (product.get("taobao_item_id") or _submit_is_uncertain(product)
            or product.get("execution") not in _LEGACY_UNCERTAIN_EXECUTIONS):
        return product
    if isinstance(product.get("resume_checkpoint"), dict):
        if product["resume_checkpoint"].get("submit_started") is not None:
            return product
    expected = pipeline_module.resume_key(pipeline_module.product_to_payload(product))
    accepted_keys = _publish_checkpoint_keys(product, pipeline_module)
    matches = []
    for path in base.glob("batches/*/worker-*/*/item_checkpoint.json"):
        item = _read_checkpoint(path).get("item") or {}
        if not isinstance(item, dict):
            continue
        if (item.get("product_id") != product.get("product_id")
                or item.get("row") != product.get("row")
                or item.get("execution_reset_id", "") != product.get("execution_reset_id", "")):
            continue
        saved_account = item.get("seller_account")
        if saved_account and product.get("seller_account") and saved_account != product["seller_account"]:
            continue
        if pipeline_module.resume_key(pipeline_module.product_to_payload(item)) != expected:
            continue
        try:
            matches.append((path.stat().st_mtime_ns, path, item))
        except OSError:
            continue
    matches.sort(reverse=True, key=lambda value: value[0])
    for _time, _path, item in matches:
        if item.get("taobao_item_id"):
            for key in ("taobao_item_id", "view_url", "edit_url", "flow_stage", "flow_version",
                        "spec_image_stage", "seller_account"):
                if item.get(key):
                    product[key] = item[key]
            return product
    if any(_submit_is_uncertain(item)
           or (any(path.parent.glob("web_fill_submit.*"))
               and not (item.get("resume_checkpoint") or {}).get("last_submit_failed"))
           for _time, path, item in matches):
        product.update(flow_stage="submit_pending", resume_checkpoint={"submit_started": True})
        return product
    upload_scripts = {"main_images.js", "details.js", "main_video.js", "sku_import.js",
                      "upload_files.js", "spec_images.js", "spec_row_images.js", "material_import.js"}
    for _time, path, item in matches:
        checkpoint = item.get("resume_checkpoint") or _read_checkpoint(path.parent / "web_fill_checkpoint.json")
        if not isinstance(checkpoint, dict) or checkpoint.get("key") not in accepted_keys:
            continue
        if not _safe_legacy_publish_href(checkpoint.get("href")):
            continue
        intent = item.get("last_browser_write") or {}
        explicit = checkpoint.get("submit_started") is False
        if not explicit:
            # Old workers recorded each media-write intent and marked a product
            # submit separately. A completed script response is required before
            # we infer that this interrupted attempt can safely start afresh.
            script = intent.get("script")
            response = _read_checkpoint(path.parent / f"web_fill_{Path(script or '').stem}.json")
            response_path = path.parent / f"web_fill_{Path(script or '').stem}.json"
            if (script not in upload_scripts or not response or response.get("dispatchUncertain")
                    or response.get("error") or (response.get("warning") and pipeline_module._upload_dispatched(response))):
                continue
            try:
                if response_path.stat().st_mtime + 2 < float(intent.get("recorded_at") or 0):
                    continue
            except (OSError, TypeError, ValueError):
                continue
        product["resume_checkpoint"] = {**checkpoint, "submit_started": False}
        if item.get("seller_account") and not product.get("seller_account"):
            product["seller_account"] = item["seller_account"]
        if intent:
            product["last_browser_write"] = intent
        return product
    return product


def _legacy_resume_checkpoint(product, pipeline_module):
    """Return ``(checkpoint, notice)`` for a no-ID uncertain legacy item.

    A confirmed pre-submit attempt may start afresh if its page is gone.
    Unknown or pending submits still require an existing page or server audit.
    """
    item = dict(product or {})
    if str(item.get("taobao_item_id") or "").strip():
        return None, ""
    execution = str(item.get("execution") or "").strip()
    stage = str(item.get("flow_stage") or "").strip()
    spec_stage = str(item.get("spec_image_stage") or "").strip()
    run_status = str(item.get("run_status") or "").strip()
    uncertain = (
        stage == "submit_pending"
        or spec_stage == "submit_pending"
        or execution in _LEGACY_UNCERTAIN_EXECUTIONS
        or run_status in {"paused", "error", "stopped"}
    )
    if not uncertain:
        return None, ""
    try:
        checkpoint_key = pipeline_module.resume_key(
            pipeline_module.product_to_payload(item)
        )
    except Exception as exc:
        return None, f"PAUSE:legacy_checkpoint:无法计算旧断点 key，已禁止新建页面：{exc}"

    supplied = item.get("resume_checkpoint") or item.get("legacy_checkpoint")
    supplied = dict(supplied) if isinstance(supplied, dict) else {}
    supplied_key = str(supplied.get("key") or "").strip()
    if supplied_key and supplied_key not in _publish_checkpoint_keys(item, pipeline_module):
        if _can_restart_before_submit(item):
            return None, ""
        return None, "PAUSE:legacy_checkpoint:旧断点 key 与当前商品不一致，已禁止新建页面"
    href = _safe_legacy_publish_href(supplied.get("href") or item.get("url"))
    if not href:
        if _can_restart_before_submit(item):
            return None, ""
        return None, (
            "PAUSE:legacy_checkpoint:旧商品存在未确认的发布断点，但页面 key/href "
            "无法可靠恢复；已禁止新建页面和重复写入"
        )
    return {"key": supplied_key or checkpoint_key, "href": href}, ""


def item_key(product, namespace=""):
    from . import pipeline

    identity = [namespace, product.get("row"), product.get("product_id"),
                product.get("pack_fingerprint"), pipeline.product_to_payload(product)]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, sort_keys=True,
                                     default=str).encode("utf-8")).hexdigest()


def _make_session(web, worker_id, run_id, directory, base, settings):
    port = settings.get("cdp_port")
    endpoint = f"http://127.0.0.1:{int(port)}" if port else web.CDP_ENDPOINT
    return web.CliSession(
        session_name=f"taobao-{run_id}-{worker_id}", output_dir=directory,
        isolated=True, cdp_endpoint=endpoint,
        registry_path=base / "owned_pages.json",
    )


def run_concurrent_batch(products, *, concurrency, cancel_event=None,
                         on_worker_event=None, runtime_settings=None, **options):
    from . import pipeline

    selected = copy.deepcopy(list(products))
    if not selected:
        return []
    settings = dict(runtime_settings if isinstance(runtime_settings, dict)
                    else vars(runtime_settings) if runtime_settings is not None else {})
    base = pipeline.get_output().resolve()
    selected = [_restore_previous_attempt(product, base, pipeline) for product in selected]
    scripts = pipeline.get_scripts().resolve()
    logs = pipeline.get_logs_dir().resolve()
    run_id = uuid.uuid4().hex[:12]
    run_dir = base / "batches" / run_id
    count = min(concurrency, len(selected))
    namespace = str(settings.get("workbook_path") or settings.get("workspace_path") or "")
    keys = [item_key(product, namespace) for product in selected]
    rows = [product.get("row") if product.get("row") is not None else key
            for product, key in zip(selected, keys)]
    if len(set(rows)) != len(rows):
        raise ValueError("入库清单包含重复行，不能同时领取同一条商品")
    queue = deque(enumerate(selected))
    dispatch_lock = threading.Lock()
    callback_lock = threading.RLock()
    cancellation = BatchCancellation(cancel_event)
    results = [None] * len(selected)
    web = pipeline._load_web()  # Import completely before any worker starts.
    web.start_persistent_chrome(focus=False)

    callbacks = {name: options.pop(name, None) for name in (
        "on_item_start", "on_item_done", "on_item_retry", "on_flow_stage")}

    def callback(name, *args):
        if callbacks[name]:
            with callback_lock:
                callbacks[name](*args)

    def worker(worker_id):
        session = None
        directory = run_dir / f"worker-{worker_id}"
        directory.mkdir(parents=True, exist_ok=True)
        try:
            while True:
                with dispatch_lock:
                    if cancellation.is_set() or not queue:
                        return
                    index, product = queue.popleft()
                output = directory / keys[index][:16]
                output.mkdir(parents=True, exist_ok=True)

                def emit(event, **extra):
                    payload = {
                        "event": event, "worker_id": worker_id,
                        "row": product.get("row"), "product_id": str(product.get("product_id") or ""),
                        "output_dir": str(output), "phase": "准备", "status": "running", **extra,
                    }
                    if on_worker_event:
                        with callback_lock:
                            on_worker_event(payload)

                def stop_dispatch(reason):
                    with dispatch_lock:
                        first = not cancellation.blocked.is_set()
                        cancellation.reason = cancellation.reason or str(reason)
                        cancellation.blocked.set()
                    if first:
                        emit("global_blocker", status="paused", phase="需处理全局故障", message=str(reason))

                runtime = WorkerRuntime(worker_id, product.get("row"), str(product.get("product_id") or ""),
                                        keys[index], output, scripts, logs / f"worker-{worker_id}",
                                        emit=emit, latest_item=dict(product))

                def checkpoint():
                    pending = dict(runtime.latest_item)
                    if pending.get("taobao_item_id"):
                        pending["spec_image_stage"] = "submit_pending"
                    else:
                        pending["flow_stage"] = "submit_pending"
                        pending["resume_checkpoint"] = {
                            **(pending.get("resume_checkpoint") or {}), "submit_started": True,
                        }
                        runtime.pending_creation = True
                    pending.update(execution="提交待核实", run_status="paused")
                    runtime.latest_item.update(pending)
                    pipeline._remember_item(product, pending)
                    pipeline._emit_flow(pending, product, lambda p, i: callback("on_flow_stage", p, i))

                runtime.checkpoint = checkpoint

                def on_flow(current, item):
                    # CLI users may have no desktop callback. The checkpoint
                    # must still be durable before upload/adoption proceeds.
                    pipeline._remember_item(current, item)
                    callback("on_flow_stage", current, item)

                result = None
                emit("start", phase="开始填写")
                with worker_runtime(runtime):
                    try:
                        if session is None:
                            session = _make_session(web, worker_id, run_id, directory, base, settings)
                        runtime.session = session
                        session.cancel_event = cancellation
                        resume_checkpoint, legacy_notice = _legacy_resume_checkpoint(product, pipeline)
                        if legacy_notice:
                            # Registry adoption has priority over the legacy
                            # URL guard.  ``allow_create=False`` proves that
                            # this path can only take over an existing parked
                            # lease; with no lease it cannot create a fresh
                            # page or repeat an uncertain write.
                            try:
                                session.begin_item(keys[index], allow_create=False)
                            except Exception as exc:
                                detail = str(exc).strip()
                                notice = legacy_notice
                                if detail and "没有已登记页面" not in detail:
                                    notice = f"{notice}；未能接管已有页面：{detail}"
                                result = {
                                    **runtime.latest_item,
                                    "execution": "暂停",
                                    "run_status": "paused",
                                    "notice": notice,
                                    "errors": [notice],
                                }
                                pipeline._remember_item(product, result, status="paused")
                        elif resume_checkpoint:
                            try:
                                session.begin_item(
                                    keys[index],
                                    resume_checkpoint={**resume_checkpoint, "item_key": keys[index]},
                                )
                            except RuntimeError as exc:
                                if ("legacy checkpoint 页面未能唯一匹配" not in str(exc)
                                        or not _can_restart_before_submit(product)):
                                    raise
                                emit("progress", phase="重新开始未提交商品",
                                     message="原填写页已失效，确认未提交，重新走入库流程")
                                session.begin_item(keys[index])
                        else:
                            session.begin_item(keys[index])
                        if result is None:
                            started = False

                            def on_start(current):
                                nonlocal started
                                if not started:
                                    started = True
                                    callback("on_item_start", current)

                            finished = pipeline._run_batch_serial(
                                [product], session=session, cancel_event=cancellation,
                                on_item_start=on_start,
                                on_flow_stage=on_flow,
                                on_item_retry=lambda *args: callback("on_item_retry", *args),
                                **options,
                            )
                            result = finished[0] if finished else {
                                **product, "execution": "已停止", "run_status": "stopped",
                                "notice": cancellation.reason or "用户停止任务", "errors": [],
                            }
                    except Exception as exc:
                        reason = str(exc)
                        result = {**runtime.latest_item, "execution": "暂停", "run_status": "paused",
                                  "notice": reason, "errors": [reason]}
                        connection_reason = _browser_connection_lost(web)
                        if (isinstance(exc, CheckpointError) or global_blocker(reason)
                                or connection_reason):
                            stop_dispatch(connection_reason or reason)
                        try:
                            pipeline._remember_item(product, result, status="paused")
                        except CheckpointError as save_error:
                            stop_dispatch(str(save_error))
                    finally:
                        if result is not None:
                            reason = global_blocker(" ".join([
                                str(result.get("notice") or ""), str(result.get("last_error") or ""),
                                *(str(error) for error in result.get("errors") or []),
                            ]))
                            if (not reason and result.get("run_status") in {"paused", "error", "stopped"}):
                                reason = _browser_connection_lost(web)
                            if reason:
                                stop_dispatch(reason)
                            # Preserve unresolved writes even when the user also pressed Stop.
                            if (cancel_event is not None and cancel_event.is_set()
                                    and result.get("flow_stage") != "submit_pending"
                                    and result.get("spec_image_stage") != "submit_pending"
                                    and "用户" in str(result.get("notice") or "")):
                                result.update(execution="已停止", run_status="stopped")
                            results[index] = result
                            try:
                                callback("on_item_done", product, result)
                            except Exception as exc:
                                result.update(execution="结果待核实", run_status="paused",
                                              notice=f"任务结果保存失败: {exc}")
                                stop_dispatch(result["notice"])
                                try:
                                    runtime.save_checkpoint(result)
                                except CheckpointError:
                                    pass  # Dispatch is already stopped; preserve the browser evidence.
                            emit("done", phase="已处理", status=result.get("run_status") or "completed", item=result)
                        preserve = (result is None or not options.get("confirm_submit")
                                    or result.get("execution") in {"暂停", "失败", "提交失败", "提交待核实", "结果待核实", "已停止"}
                                    or result.get("run_status") in {"paused", "error", "stopped"})
                        if session is not None:
                            try:
                                session.finish_item(preserve=preserve)
                            except Exception as exc:
                                stop_dispatch(f"页面归属收尾失败: {exc}")
                        snapshot = directory / "current.yml"
                        if snapshot.is_file():
                            try:
                                shutil.copy2(snapshot, output / "current.yml")
                            except OSError:
                                pass
        finally:
            if session is not None:
                session.detach()

    with ThreadPoolExecutor(max_workers=count, thread_name_prefix="qianniu-worker") as pool:
        futures = [pool.submit(worker, worker_id) for worker_id in range(1, count + 1)]
        for future in futures:
            future.result()
    # 全部 worker 已 detach，此刻没有并发页签在使用：对账回收历史泄漏
    # 页签（死租约、同商品重复页），避免常驻浏览器的页签跨任务累积。
    reconcile = getattr(web, "reconcile_browser_tabs", None)
    if callable(reconcile):
        try:
            reconcile()
        except Exception:
            pass
    return [item for item in results if item is not None]
