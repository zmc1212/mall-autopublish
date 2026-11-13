"""离线分析并发入库验收证据。

这个工具只读取验收目录中的 JSON 和商品输出目录，不导入浏览器模块，也不
连接 CDP。它把原始 ``report.json`` 当作证据输入，另写 ``offline-analysis.json``，
避免覆盖原始验收记录。

用法::

    python tools/analyze_concurrent_live.py output/playwright/concurrency-live/<run>

分析结果会明确区分：

* start/done 是否能按商品唯一配对；
* 商品业务区间和 progress 事件是否确实重叠；
* 销售规格图的行 index、预期 SKU 顺序和图片 source；
* 已核验的非图片字段，以及当前证据没有覆盖的字段；
* 资源采样是观测值，不把包含既有浏览器页面的进程树误当成 worker 专属资源。
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable


_EVENT_FILE_RE = re.compile(r"^events-(?P<concurrency>\d+)\.json$")
_NUMERIC_FIELDS = {"price", "stock"}
_SKU_FIELDS = ("sku_id", "price", "stock", "search_title", "merchant_code", "attributes_text")
_NON_IMAGE_FIELDS = (
    "sku_id",
    "price",
    "stock",
    "search_title",
    "merchant_code",
    "attributes_text",
    "title",
    "warehouse",
    "freight",
    "ship48",
)


def _read_json(path: Path) -> tuple[Any | None, str | None]:
    try:
        return json.loads(path.read_text(encoding="utf-8")), None
    except FileNotFoundError:
        return None, "文件不存在"
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _event_time(event: dict[str, Any]) -> float | None:
    """优先使用单调时钟；兼容旧 harness 只有 wall-clock ``at`` 的事件。"""
    monotonic = _number(event.get("monotonic_at"))
    return monotonic if monotonic is not None else _number(event.get("at"))


def _item_key(event: dict[str, Any]) -> tuple[Any, Any]:
    return event.get("row"), event.get("product_id")


def _event_sort_key(pair: tuple[int, dict[str, Any]]) -> tuple[float, int]:
    index, event = pair
    return (_event_time(event) if _event_time(event) is not None else float("inf"), index)


def _safe_worker(event: dict[str, Any]) -> int | None:
    value = event.get("worker_id")
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def analyze_events(events: list[dict[str, Any]], expected: dict[tuple[Any, Any], dict[str, Any]],
                   concurrency: int) -> dict[str, Any]:
    """验证事件生命周期，并区分槽位占用和实际 progress 重叠。

    ``start`` 到 ``done`` 只证明执行槽被该商品占用，期间可能包含等待。
    每个商品的首个到最后一个 ``progress`` 构成可观察的业务活动区间，只有
    两个活动区间有正长度交集时，才报告已证明的业务执行重叠。时间相同的
    事件按落盘顺序处理，这样不会凭排序制造重叠。
    """
    errors: list[str] = []
    attempts_by_key: dict[tuple[Any, Any], list[dict[str, Any]]] = defaultdict(list)
    open_attempts: dict[tuple[Any, Any], dict[str, Any]] = {}
    global_blockers: list[dict[str, Any]] = []
    stray_progress = 0

    def validate_lifecycle_event(kind: str, event: dict[str, Any], key: tuple[Any, Any]) -> None:
        worker = _safe_worker(event)
        if worker is None or not 1 <= worker <= max(1, concurrency):
            errors.append(f"{kind} worker_id 无效: {event.get('worker_id')!r}")
        if _event_time(event) is None:
            errors.append(f"{kind} 缺少有效时间: row={key[0]!r}")

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            errors.append(f"event[{index}] 不是对象")
            continue
        kind = event.get("event")
        key = _item_key(event)
        if kind == "global_blocker":
            global_blockers.append(event)
        elif kind == "start":
            validate_lifecycle_event(kind, event, key)
            if key in open_attempts:
                errors.append(f"start 在上一尝试结束前重复: row={key[0]!r}")
            attempt = {"start": event, "start_event_index": index, "done": None,
                       "done_event_index": None, "progress": []}
            attempts_by_key[key].append(attempt)
            open_attempts[key] = attempt
        elif kind == "progress":
            if key in open_attempts:
                open_attempts[key]["progress"].append(event)
            else:
                stray_progress += 1
        elif kind == "done":
            validate_lifecycle_event(kind, event, key)
            attempt = open_attempts.pop(key, None)
            if attempt is None:
                errors.append(f"done 没有对应 start: row={key[0]!r}, product_id={key[1]!r}")
                attempts_by_key[key].append({"start": None, "start_event_index": None,
                                             "done": event, "done_event_index": index, "progress": []})
            else:
                attempt["done"] = event
                attempt["done_event_index"] = index

    expected_keys = set(expected)
    for key in sorted(expected_keys, key=repr):
        attempts = attempts_by_key.get(key, [])
        if not attempts:
            errors.append(f"缺少 start: row={key[0]!r}, product_id={key[1]!r}")
        if key in open_attempts:
            errors.append(f"缺少 done: row={key[0]!r}, product_id={key[1]!r}")
    for key in set(attempts_by_key) - expected_keys:
        errors.append(f"事件包含未预期商品: row={key[0]!r}, product_id={key[1]!r}")

    # A resumed run may legitimately contain one completed failed attempt and
    # a later attempt for the same row. Keep every attempt in the report, but
    # use only the latest attempt for the current concurrency interval.
    intervals: dict[tuple[Any, Any], dict[str, Any]] = {}
    attempt_records: list[dict[str, Any]] = []
    for key in sorted(expected_keys, key=repr):
        attempts = attempts_by_key.get(key, [])
        for attempt_number, attempt in enumerate(attempts, 1):
            start = attempt.get("start")
            done = attempt.get("done")
            start_time = _event_time(start) if isinstance(start, dict) else None
            done_time = _event_time(done) if isinstance(done, dict) else None
            paired = isinstance(start, dict) and isinstance(done, dict)
            worker_start = _safe_worker(start) if isinstance(start, dict) else None
            worker_done = _safe_worker(done) if isinstance(done, dict) else None
            if paired and worker_start != worker_done:
                errors.append(f"start/done worker 不一致: row={key[0]!r}, attempt={attempt_number}")
            if paired and start_time is not None and done_time is not None and done_time < start_time:
                errors.append(f"done 早于 start: row={key[0]!r}, attempt={attempt_number}")
            if paired and start.get("product_id") != expected[key].get("product_id"):
                errors.append(f"start product_id 不匹配: row={key[0]!r}, attempt={attempt_number}")
            if paired and done.get("product_id") != expected[key].get("product_id"):
                errors.append(f"done product_id 不匹配: row={key[0]!r}, attempt={attempt_number}")
            attempt_records.append({
                "row": key[0], "product_id": key[1], "attempt": attempt_number,
                "paired": paired, "worker_start": worker_start, "worker_done": worker_done,
                "start": start_time, "done": done_time,
                "duration_seconds": round(done_time - start_time, 3)
                if start_time is not None and done_time is not None and done_time >= start_time else None,
                "done_status": done.get("status") if isinstance(done, dict) else None,
                "progress_count": len(attempt.get("progress") or []),
                "phases": sorted({event.get("phase") for event in attempt.get("progress", [])
                                  if event.get("phase")}),
            })
        if not attempts:
            continue
        selected = attempts[-1]
        start = selected.get("start")
        done = selected.get("done")
        start_time = _event_time(start) if isinstance(start, dict) else None
        done_time = _event_time(done) if isinstance(done, dict) else None
        start_worker = _safe_worker(start) if isinstance(start, dict) else None
        done_worker = _safe_worker(done) if isinstance(done, dict) else None
        progress_times = [
            value for event in selected.get("progress") or []
            if (value := _event_time(event)) is not None
            and (start_time is None or value >= start_time)
            and (done_time is None or value <= done_time)
        ]
        intervals[key] = {
            "row": key[0],
            "product_id": key[1],
            "worker_id": start_worker,
            "start": start_time,
            "done": done_time,
            "done_status": done.get("status") if isinstance(done, dict) else None,
            "progress": selected.get("progress") or [],
            "progress_start": min(progress_times) if progress_times else None,
            "progress_end": max(progress_times) if progress_times else None,
            "progress_interval_seconds": round(max(progress_times) - min(progress_times), 3)
            if len(progress_times) >= 2 else 0.0,
            "start_event_index": selected.get("start_event_index"),
            "done_event_index": selected.get("done_event_index"),
        }
        if start_worker != done_worker and done is not None:
            errors.append(f"最新尝试 start/done worker 不一致: row={key[0]!r}")

    # Sweep the complete business intervals.  The active set uses item keys so
    # a malformed worker that starts two rows concurrently is still visible;
    # active_workers separately measures distinct worker slots.
    lifecycle = []
    for key, interval in intervals.items():
        if interval["start"] is not None:
            lifecycle.append((interval["start"], interval["start_event_index"], "start", key, interval))
        if interval["done"] is not None:
            lifecycle.append((interval["done"], interval["done_event_index"], "done", key, interval))
    lifecycle.sort(key=lambda row: (row[0], row[1]))
    active_items: set[tuple[Any, Any]] = set()
    active_workers: set[int] = set()
    maximum_items = 0
    maximum_workers = 0
    slot_overlap_seconds = 0.0
    previous_time: float | None = None
    for current_time, _event_index, kind, key, interval in lifecycle:
        if previous_time is not None:
            delta = max(0.0, current_time - previous_time)
            if len(active_workers) >= 2:
                slot_overlap_seconds += delta
        if kind == "start":
            if key in active_items:
                errors.append(f"业务区间重复 start: row={key[0]!r}")
            active_items.add(key)
            if interval["worker_id"] is not None:
                active_workers.add(interval["worker_id"])
        else:
            if key not in active_items:
                errors.append(f"业务区间 done 没有 active start: row={key[0]!r}")
            active_items.discard(key)
            worker = interval["worker_id"]
            if worker is not None and not any(item_interval["worker_id"] == worker
                                             for item_key, item_interval in intervals.items()
                                             if item_key in active_items):
                active_workers.discard(worker)
        maximum_items = max(maximum_items, len(active_items))
        maximum_workers = max(maximum_workers, len(active_workers))
        previous_time = current_time

    if active_items:
        errors.append("业务区间结束后仍有 active 商品")

    # A start/done interval can overlap because one worker is waiting.  Use the
    # first-to-last progress intervals to prove that both workers were active
    # during a common positive-length interval.
    pair_overlaps: list[dict[str, Any]] = []
    progress_overlap_seconds = 0.0
    keys = list(intervals)
    for left_index, left_key in enumerate(keys):
        left = intervals[left_key]
        if left["start"] is None or left["done"] is None:
            continue
        for right_key in keys[left_index + 1:]:
            right = intervals[right_key]
            if right["start"] is None or right["done"] is None:
                continue
            common_start = max(left["start"], right["start"])
            common_done = min(left["done"], right["done"])
            if common_done <= common_start:
                continue
            left_progress = [event for event in left.get("progress", [])
                             if (_event_time(event) is not None
                                 and common_start <= _event_time(event) <= common_done)]
            right_progress = [event for event in right.get("progress", [])
                              if (_event_time(event) is not None
                                  and common_start <= _event_time(event) <= common_done)]
            left_progress_start = left.get("progress_start")
            left_progress_done = left.get("progress_end")
            right_progress_start = right.get("progress_start")
            right_progress_done = right.get("progress_end")
            progress_start = (
                max(left_progress_start, right_progress_start)
                if left_progress_start is not None and right_progress_start is not None else None
            )
            progress_done = (
                min(left_progress_done, right_progress_done)
                if left_progress_done is not None and right_progress_done is not None else None
            )
            progress_seconds = (
                round(max(0.0, progress_done - progress_start), 3)
                if progress_start is not None and progress_done is not None else 0.0
            )
            progress_overlap_seconds += progress_seconds
            progress_interval_overlap = progress_seconds > 0
            pair_overlaps.append({
                "items": [list(left_key), list(right_key)],
                "workers": [left["worker_id"], right["worker_id"]],
                "start": common_start,
                "done": common_done,
                "seconds": round(common_done - common_start, 3),
                "left_progress_count": len(left_progress),
                "right_progress_count": len(right_progress),
                "left_progress_start": left_progress_start,
                "left_progress_done": left_progress_done,
                "right_progress_start": right_progress_start,
                "right_progress_done": right_progress_done,
                "progress_intersection_start": progress_start,
                "progress_intersection_done": progress_done,
                "progress_overlap_seconds": progress_seconds,
                "progress_interval_overlap": progress_interval_overlap,
                # Compatibility alias retained for existing consumers.
                "phase_progress_overlap": progress_interval_overlap,
                "left_phases": sorted({event.get("phase") for event in left_progress if event.get("phase")}),
                "right_phases": sorted({event.get("phase") for event in right_progress if event.get("phase")}),
            })

    return {
        "valid_pairing": not errors,
        "errors": errors,
        "expected_item_count": len(expected_keys),
        "start_count": sum(len(attempts) for attempts in attempts_by_key.values()),
        "done_count": sum(1 for attempts in attempts_by_key.values() for attempt in attempts
                           if attempt.get("done") is not None),
        "attempts": attempt_records,
        "resume_detected": any(sum(1 for record in attempt_records
                                    if (record["row"], record["product_id"]) == key) > 1
                                for key in expected_keys),
        "stray_progress_count": stray_progress,
        "global_blocker_count": len(global_blockers),
        "global_blocker": bool(global_blockers),
        "latest_done_statuses": [interval["done_status"] for interval in intervals.values()],
        "latest_all_completed": bool(intervals) and all(
            interval["done_status"] == "completed" for interval in intervals.values()
        ),
        "max_active_items": maximum_items,
        "max_active_workers": maximum_workers,
        "slot_occupancy_overlap_seconds": round(slot_overlap_seconds, 3),
        "slot_occupancy_overlap": bool(slot_overlap_seconds > 0),
        "progress_overlap_seconds": round(progress_overlap_seconds, 3),
        "progress_overlap": bool(progress_overlap_seconds > 0),
        # ``business_overlap`` now means observed progress overlap.  Keep the
        # old key for callers while exposing the slot metric separately.
        "business_overlap_seconds": round(progress_overlap_seconds, 3),
        "business_overlap": bool(progress_overlap_seconds > 0),
        "pair_overlaps": pair_overlaps,
        "phase_progress_overlap": any(item["phase_progress_overlap"] for item in pair_overlaps),
        "intervals": list(intervals.values()),
    }


def _same_value(left: Any, right: Any, field: str) -> bool:
    if field in _NUMERIC_FIELDS:
        try:
            return float(left) == float(right)
        except (TypeError, ValueError):
            return str(left) == str(right)
    return str(left) == str(right)


def _display_title(title: Any) -> str:
    """与 pipeline.display_title 相同的 60 宽度截断，避免导入生产模块。"""
    result: list[str] = []
    width = 0
    for char in str(title or "").strip():
        char_width = 2 if ord(char) > 127 else 1
        if width + char_width > 60:
            break
        result.append(char)
        width += char_width
    return "".join(result)


def _load_evidence(directory: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """Load server evidence plus any durable probes left by a paused item.

    ``verify_concurrent_live`` writes ``acceptance-server-evidence.json`` only
    after a completed item has passed the fresh-server comparison.  A paused
    item can still have valuable probes in its worker directory, so absence of
    that aggregate file must not discard them.
    """
    errors: list[str] = []
    sources: list[str] = []
    evidence, error = _read_json(directory / "acceptance-server-evidence.json")
    if isinstance(evidence, dict):
        evidence = copy.deepcopy(evidence)
        sources.append("acceptance-server-evidence.json")
    elif error:
        errors.append(f"acceptance-server-evidence.json: {error}")
        evidence = {}

    def load_first(names: tuple[str, ...], label: str) -> Any | None:
        for name in names:
            path = directory / name
            if not path.exists():
                continue
            value, read_error = _read_json(path)
            if read_error:
                errors.append(f"{name}: {read_error}")
                return None
            if value is not None:
                sources.append(name)
                return value
        return None

    # The prefixed names are produced by the Playwright CLI workflow.  Keep
    # the unprefixed aliases for older local runs and hand-written evidence.
    probe = load_first(("web_fill_probe_state.json", "probe_state.json"), "product_probe")
    if "product_probe" not in evidence and isinstance(probe, dict):
        evidence["product_probe"] = probe
    spec_probe = load_first(("web_fill_spec_row_status.json", "spec_row_status.json"), "spec_probe")
    if "spec_probe" not in evidence and isinstance(spec_probe, dict):
        evidence["spec_probe"] = spec_probe
    material = load_first(("web_fill_material_import.json", "material_import.json"), "material_preview")
    if isinstance(material, dict):
        rows = material.get("rows")
        if "preview" not in evidence and isinstance(rows, list):
            evidence["preview"] = rows
        evidence.setdefault("material_preview_state", material)

    if not evidence:
        return None, errors
    evidence["_evidence_sources"] = sources
    if sources and "acceptance-server-evidence.json" not in sources:
        errors.append("已使用暂停商品的独立 probe/preview 证据；未生成 acceptance-server-evidence.json")
    return evidence, errors


def analyze_item(product: dict[str, Any], directory: Path, report_check: dict[str, Any] | None = None,
                 report_item: dict[str, Any] | None = None) -> dict[str, Any]:
    """分析单商品证据；缺文件时报告 unknown，不把数量提升成身份结论。"""
    expected_skus = list(product.get("skus") or [])
    expected_names = [str(sku.get("name", "")) for sku in expected_skus]
    result: dict[str, Any] = {
        "row": product.get("row"),
        "product_id": product.get("product_id"),
        "output_dir": str(directory),
        "search_main_images": {"status": "无法判断", "presence": "unknown", "identity": "unknown"},
        "sales_spec_images": {"status": "无法判断", "rows": [], "mapping_basis": "unknown"},
        "non_image_fields": {"status": "无法判断", "verified": [], "missing": list(_NON_IMAGE_FIELDS),
                              "differences": []},
        "material_evidence": {
            "sku_material_manifest": [],
            "material_result": [],
            "material_preview": [],
            "server_result_present": False,
            "preview_present": False,
            "sources": [],
        },
        "evidence_errors": [],
    }
    evidence, errors = _load_evidence(directory)
    result["evidence_errors"].extend(errors)
    report_item = report_item if isinstance(report_item, dict) else {}

    # Keep the durable item fields even when the fresh-server aggregate is
    # absent.  ``material_result`` is the adopted/server result; preview rows
    # are deliberately tracked separately and never promoted to server state.
    report_baseline = report_item.get("sku_material_manifest")
    evidence_baseline = evidence.get("baseline") if isinstance(evidence, dict) else None
    baseline = (copy.deepcopy(report_baseline)
                if isinstance(report_baseline, list) and report_baseline
                else copy.deepcopy(evidence_baseline) if isinstance(evidence_baseline, list) else [])
    report_actual = report_item.get("material_result")
    evidence_actual = evidence.get("actual") if isinstance(evidence, dict) else None
    server_actual = (copy.deepcopy(report_actual)
                     if isinstance(report_actual, list) and report_actual
                     else copy.deepcopy(evidence_actual) if isinstance(evidence_actual, list) else [])
    report_preview = report_item.get("material_preview")
    evidence_preview = evidence.get("preview") if isinstance(evidence, dict) else None
    preview = (copy.deepcopy(report_preview)
               if isinstance(report_preview, list) and report_preview
               else copy.deepcopy(evidence_preview) if isinstance(evidence_preview, list) else [])
    result["material_evidence"].update({
        "sku_material_manifest": copy.deepcopy(baseline),
        "material_result": copy.deepcopy(server_actual),
        "material_preview": copy.deepcopy(preview),
        "server_result_present": bool(server_actual),
        "preview_present": bool(preview),
        "sources": list((evidence or {}).get("_evidence_sources") or []) if isinstance(evidence, dict) else [],
    })
    # Top-level aliases make the preserved checkpoint fields easy to consume
    # in a report without requiring callers to know the nested schema.
    result["sku_material_manifest"] = copy.deepcopy(baseline)
    result["material_result"] = copy.deepcopy(server_actual)
    result["material_preview"] = copy.deepcopy(preview)
    # A report item can still carry material checkpoint evidence when all
    # probe files are absent.  Continue with an empty evidence object so those
    # fields are preserved instead of returning early.
    if evidence is None:
        evidence = {}

    # ``server_actual`` is intentionally kept separate from ``preview``.  A
    # preview can show a URL and changed attributes before the user adopts it;
    # that is evidence of a UI preview only, not of a server-side write.
    actual = server_actual if isinstance(server_actual, list) else []
    if actual:
        actual_names = [str(row.get("name", "")) for row in actual if isinstance(row, dict)]
        expected_name_set = set(expected_names)
        actual_name_set = set(actual_names)
        images_present = (len(actual) == len(expected_skus)
                          and actual_name_set == expected_name_set
                          and all(str(row.get("image") or "").strip() for row in actual if isinstance(row, dict)))
        result["search_main_images"]["presence"] = "通过" if images_present else "失败"
        result["search_main_images"]["actual_rows"] = len(actual)
        result["search_main_images"]["expected_rows"] = len(expected_skus)
        result["search_main_images"]["actual_names"] = actual_names
        result["search_main_images"]["source"] = "server_result"
    elif preview:
        preview_names = [str(row.get("name", "")) for row in preview if isinstance(row, dict)]
        preview_images_present = (
            len(preview) == len(expected_skus)
            and set(preview_names) == set(expected_names)
            and all(str(row.get("image") or "").strip() for row in preview if isinstance(row, dict))
        )
        result["search_main_images"].update({
            "status": "无法判断",
            "presence": "preview",
            "preview_presence": "通过" if preview_images_present else "失败",
            "preview_rows": len(preview),
            "preview_names": preview_names,
            "identity": "preview_not_adopted",
            "source": "material_preview",
            "identity_note": "素材预览尚未采纳，不能据此认定服务器搜索主图已被修改",
        })
    if (report_check and report_check.get("search_main_images") == "通过"
            and actual and result["search_main_images"].get("identity") != "preview_not_adopted"):
        result["search_main_images"]["identity"] = "pipeline_reported"
        result["search_main_images"]["identity_note"] = (
            "页面端 material_import verify 已报告通过；离线分析器没有重新下载或比较图片内容"
        )
    elif actual and result["search_main_images"]["presence"] == "通过":
        result["search_main_images"]["identity"] = "presence_only"

    specs = evidence.get("spec_probe") or {}
    sources = specs.get("sources") if isinstance(specs, dict) else None
    if not isinstance(sources, list):
        sources = []
    expected_indexes = set(range(1, len(expected_skus) + 1))
    spec_rows: list[dict[str, Any]] = []
    seen_indexes: set[int] = set()
    malformed = False
    for source in sources:
        if not isinstance(source, dict):
            malformed = True
            continue
        try:
            index = int(source.get("index"))
        except (TypeError, ValueError):
            malformed = True
            continue
        if index in seen_indexes:
            malformed = True
        seen_indexes.add(index)
        sku_name = expected_names[index - 1] if 1 <= index <= len(expected_names) else None
        spec_rows.append({"index": index, "sku": sku_name, "src_present": bool(str(source.get("src") or "").strip()),
                          "src": source.get("src") or ""})
    mapping_complete = (not malformed and seen_indexes == expected_indexes
                        and specs.get("total") == len(expected_skus)
                        and not specs.get("missing")
                        and all(row["src_present"] for row in spec_rows))
    result["sales_spec_images"].update({
        "status": "无法判断",
        "presence": ("通过" if mapping_complete else "失败") if specs else "无法判断",
        "total": specs.get("total"),
        "filled": specs.get("filled"),
        "missing": specs.get("missing") or [],
        "rows": spec_rows,
        "mapping_basis": "1-based DOM row index -> inputs.json SKU order",
        "identity": "source_presence_only",
        "identity_status": "无法判断",
        "identity_basis": "仅确认保存后的图片 source 存在；未比较图片内容身份",
        "identity_note": "spec_row_status 没有返回 SKU 名称；source 非空不能证明图片内容等于输入素材",
    })

    probe = evidence.get("product_probe") or {}
    prior = {str(row.get("name")): row for row in baseline if isinstance(row, dict)}
    verified: list[str] = []
    preview_verified: list[str] = []
    differences: list[dict[str, Any]] = []
    preview_differences: list[dict[str, Any]] = []

    def compare_material_rows(rows: list[Any], source: str, verified_target: list[str],
                              difference_target: list[dict[str, Any]]) -> None:
        if not prior:
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            name = str(row.get("name", ""))
            before = prior.get(name)
            if not before:
                difference_target.append({"field": "sku_name", "expected": list(prior), "actual": name,
                                          "source": source})
                continue
            for field in _SKU_FIELDS:
                if field not in before:
                    continue
                verified_target.append(f"sku.{field}")
                if not _same_value(before.get(field), row.get(field, ""), field):
                    difference_target.append({"sku": name, "field": field, "before": before.get(field),
                                              "after": row.get(field), "source": source})

    compare_material_rows(actual, "server_result", verified, differences)
    compare_material_rows(preview, "material_preview", preview_verified, preview_differences)
    if preview_differences:
        for difference in preview_differences:
            difference["server_state"] = "无法判断"
            difference["note"] = "预览尚未采纳，不能认定服务器已被修改"
        differences.extend(preview_differences)

    expected_title = product.get("title")
    if probe.get("title") is not None:
        verified.append("title")
        # display_title may add the standard suffix; the original harness has
        # already compared this value. Preserve that result when available.
        if report_check and any(item.get("field") == "title" for item in report_check.get("differences", [])):
            differences.extend(item for item in report_check["differences"] if item.get("field") == "title")
        else:
            title_match = str(probe.get("title")) in {str(expected_title), _display_title(expected_title)}
            if not title_match:
                differences.append({"field": "title", "expected": expected_title, "actual": probe.get("title")})
    if "warehouse" in probe:
        warehouse_ok = any(row.get("checked") and row.get("t") == "放入仓库" for row in probe.get("warehouse") or []
                           if isinstance(row, dict))
        verified.append("warehouse")
        if not warehouse_ok:
            differences.append({"field": "warehouse", "expected": True, "actual": probe.get("warehouse")})

    for field in ("freight", "ship48"):
        if field in probe:
            verified.append(field)
            if probe.get(field) is not True:
                differences.append({"field": field, "expected": True, "actual": probe.get(field)})

    if probe.get("skuRows") is not None:
        verified.append("skuRows")
        if probe.get("skuRows") != len(expected_skus):
            differences.append({"field": "skuRows", "expected": len(expected_skus), "actual": probe.get("skuRows")})
    if isinstance(probe.get("skuNames"), list):
        verified.append("skuNames")
        if set(map(str, probe["skuNames"])) != set(expected_names):
            differences.append({"field": "skuNames", "expected": expected_names, "actual": probe["skuNames"]})

    # These are intentionally listed as missing when no direct probe or
    # baseline evidence exists. A completed pipeline is not silently promoted
    # to complete field coverage.
    # SKU evidence is recorded with a ``sku.`` prefix, while the missing list
    # uses the public field names. Normalize before calculating coverage.
    covered = {field.split(".", 1)[-1] for field in verified}
    preview_covered = {field.split(".", 1)[-1] for field in preview_verified}
    server_differences = [item for item in differences if item.get("source") != "material_preview"]
    if server_differences:
        field_status = "失败"
    elif verified and not preview_differences:
        field_status = "通过"
    else:
        # A preview can be structurally complete while its values are not yet
        # server state. Keep that distinction visible to the caller.
        field_status = "无法判断"
    result["non_image_fields"] = {
        "status": field_status,
        "verified": sorted(covered),
        "missing": [field for field in _NON_IMAGE_FIELDS if field not in covered],
        "differences": differences,
        "server_differences": server_differences,
        "preview_verified": sorted(preview_covered),
        "preview_differences": preview_differences,
        "preview_note": (
            "预览中的字段差异只反映未采纳的素材预览，服务器实际值无法判断"
            if preview_differences else ""
        ),
        "evidence_sources": result["material_evidence"]["sources"],
    }
    return result


def _correctness_basis(item: dict[str, Any]) -> dict[str, Any]:
    """Summarize whether an item has enough evidence for a passed conclusion.

    A completed lifecycle only proves that the worker returned.  The three
    material categories still need their own evidence.  In particular,
    ``presence_only`` and ``preview_not_adopted`` deliberately remain review
    states because a URL or an unadopted preview does not prove server-side
    image identity.
    """
    reasons: list[str] = []
    search = item.get("search_main_images") or {}
    if search.get("status") != "通过":
        reasons.append("搜索主图没有服务器通过结论")
    elif search.get("identity") in {"unknown", "preview_not_adopted", "presence_only"}:
        reasons.append("搜索主图只有存在性或预览证据，图片身份无法确认")

    sales = item.get("sales_spec_images") or {}
    if sales.get("presence") != "通过":
        reasons.append("销售规格图保存状态未通过")
    if sales.get("identity_status") != "通过":
        reasons.append("销售规格图图片身份尚未核验")

    non_image = item.get("non_image_fields") or {}
    missing = non_image.get("missing") or []
    if non_image.get("status") != "通过" or missing:
        reasons.append("非图片字段仍有未核验项或差异")

    return {
        "status": "通过" if not reasons else "需复核",
        "ready": not reasons,
        "reasons": reasons,
        "evidence_sources": (item.get("material_evidence") or {}).get("sources", []),
    }


def _expected_products(inputs: Any) -> dict[tuple[Any, Any], dict[str, Any]]:
    if not isinstance(inputs, list):
        return {}
    result: dict[tuple[Any, Any], dict[str, Any]] = {}
    for product in inputs:
        if isinstance(product, dict):
            result[(product.get("row"), product.get("product_id"))] = product
    return result


def _event_output_dir(events: Iterable[dict[str, Any]], key: tuple[Any, Any]) -> Path | None:
    for event in reversed(list(events)):
        if _item_key(event) == key and event.get("output_dir"):
            return Path(str(event["output_dir"]))
    return None


def _report_summary(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        return {"status": "unknown", "batches": []}
    return {
        "status": report.get("status"),
        "reason": report.get("reason"),
        "batches": [
            {
                "concurrency": batch.get("concurrency"),
                "started_at": batch.get("started_at"),
                "finished_at": batch.get("finished_at"),
                "duration_seconds": batch.get("duration_seconds"),
                "result_count": len(batch.get("results", [])) if isinstance(batch.get("results"), list) else None,
            }
            for batch in report.get("batches", []) if isinstance(batch, dict)
        ],
    }


def analyze_run(run_dir: Path, _include_nested: bool = True) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    inputs, input_error = _read_json(run_dir / "inputs.json")
    report, report_error = _read_json(run_dir / "report.json")
    products = _expected_products(inputs)
    input_list = inputs if isinstance(inputs, list) else []
    input_rows = [item.get("row") for item in input_list if isinstance(item, dict)]
    input_ids = [item.get("product_id") for item in input_list if isinstance(item, dict)]
    sku_counts = [len(item.get("skus") or []) for item in input_list if isinstance(item, dict)]
    result: dict[str, Any] = {
        "source_directory": str(run_dir),
        "source_report_preserved": True,
        "input_error": input_error,
        "report_error": report_error,
        "input_contract": {
            "product_count": len(input_list),
            "expected_product_count": 3,
            "rows": input_rows,
            "unique_rows": len(input_rows) == len(set(input_rows)),
            "product_ids": input_ids,
            "unique_product_ids": len(input_ids) == len(set(input_ids)),
            "sku_counts": sku_counts,
            "two_skus_each": bool(input_list) and all(count == 2 for count in sku_counts),
            "valid_shape": (len(input_list) == 3 and len(input_rows) == 3
                            and len(input_ids) == 3 and len(set(input_rows)) == 3
                            and len(set(input_ids)) == 3 and len(sku_counts) == 3
                            and all(count == 2 for count in sku_counts)),
        },
        "batches": [],
        "resource_observation": {},
        "status": "needs_review",
    }
    source_report, source_report_error = _read_json(run_dir / "source-report.json")
    if isinstance(source_report, dict):
        result["source_snapshot"] = {
            "path": str(run_dir / "source-report.json"),
            **_report_summary(source_report),
        }
    elif source_report_error and (run_dir / "source-report.json").exists():
        result["source_snapshot"] = {"path": str(run_dir / "source-report.json"),
                                      "read_error": source_report_error}
    report_batches = report.get("batches", []) if isinstance(report, dict) else []
    report_by_concurrency = {batch.get("concurrency"): batch for batch in report_batches
                             if isinstance(batch, dict)}

    for event_path in sorted(run_dir.glob("events-*.json")):
        match = _EVENT_FILE_RE.match(event_path.name)
        if not match:
            continue
        concurrency = int(match.group("concurrency"))
        events, error = _read_json(event_path)
        batch_result: dict[str, Any] = {"concurrency": concurrency, "event_file": str(event_path),
                                        "read_error": error}
        if not isinstance(events, list):
            batch_result["event_analysis"] = {"valid_pairing": False, "errors": [error or "事件文件不是数组"]}
            result["batches"].append(batch_result)
            continue
        event_items = {_item_key(event) for event in events if isinstance(event, dict)
                       and event.get("event") in {"start", "done", "progress"}}
        report_batch = report_by_concurrency.get(concurrency) or {}
        report_keys = {(item.get("row"), item.get("product_id"))
                       for item in report_batch.get("results", []) if isinstance(item, dict)}
        # The live harness deliberately assigns the first product to batch 1
        # and the remaining two to batch 2. Use that contract when a batch file
        # exists but has only partial events, otherwise a file with no events
        # could be (incorrectly) reported as a valid empty batch.
        if report_keys:
            candidate_keys = report_keys
        elif concurrency == 1 and isinstance(inputs, list) and inputs:
            candidate_keys = {(inputs[0].get("row"), inputs[0].get("product_id"))}
        elif concurrency == 2 and isinstance(inputs, list) and len(inputs) >= 3:
            candidate_keys = {(item.get("row"), item.get("product_id")) for item in inputs[1:3]
                              if isinstance(item, dict)}
        else:
            candidate_keys = event_items
        candidate_keys.update(event_items)
        expected = {key: products[key] for key in candidate_keys if key in products}
        # For a partially written file, still show unexpected/missing rows. The
        # pairing analyser reports extra rows if they are not in inputs.
        analysis = analyze_events(events, expected, concurrency)
        batch_result["event_analysis"] = analysis
        item_results: list[dict[str, Any]] = []
        report_checks = {check.get("row"): check for check in report_batch.get("verification", [])
                         if isinstance(check, dict)}
        report_items = {item.get("row"): item for item in report_batch.get("results", [])
                        if isinstance(item, dict)}
        # A live/paused attempt may not have written report.results yet, while
        # its done event already contains the durable item checkpoint.  Reuse
        # that item for offline evidence instead of dropping material fields.
        event_items_by_key = {
            _item_key(event): event.get("item")
            for event in events
            if isinstance(event, dict) and event.get("event") == "done"
            and isinstance(event.get("item"), dict)
        }
        for key, product in expected.items():
            directory = _event_output_dir(events, key)
            if directory is None:
                directory = run_dir
            report_item = report_items.get(key[0]) or event_items_by_key.get(key)
            item_result = analyze_item(product, directory, report_checks.get(key[0]), report_item)
            item_result["correctness_basis"] = _correctness_basis(item_result)
            item_results.append(item_result)
        batch_result["items"] = item_results
        batch_result["duration_seconds"] = report_batch.get("duration_seconds")
        batch_result["reported_started_at"] = report_batch.get("started_at")
        batch_result["reported_finished_at"] = report_batch.get("finished_at")
        batch_result["attempt_durations_seconds"] = [
            {"row": attempt.get("row"), "product_id": attempt.get("product_id"),
             "attempt": attempt.get("attempt"), "seconds": attempt.get("duration_seconds"),
             "done_status": attempt.get("done_status")}
            for attempt in analysis.get("attempts", [])
        ]
        batch_result["resource_samples"] = report_batch.get("resource_samples", [])
        result["batches"].append(batch_result)

    resources, resource_error = _read_json(run_dir / "resources.json")
    if isinstance(resources, list):
        numeric_samples = [sample for sample in resources
                           if isinstance(sample, dict) and _number(sample.get("at")) is not None]
        result["resource_observation"] = {
            "sample_count": len(resources),
            "peak_rss_bytes": max((sample.get("rss_bytes", 0) for sample in resources
                                    if isinstance(sample, dict)), default=None),
            "scope": (report.get("resource_scope") if isinstance(report, dict) else None),
            "attribution": "不可归因到 worker；原始 harness 采样包含测试进程及既有授权浏览器进程树",
        }
        for batch in result["batches"]:
            analysis = batch.get("event_analysis") or {}
            intervals = [item for item in analysis.get("intervals", [])
                         if _number(item.get("start")) is not None and _number(item.get("done")) is not None]
            start = _number(batch.get("reported_started_at"))
            done = _number(batch.get("reported_finished_at"))
            if start is None and intervals:
                start = min(item["start"] for item in intervals)
            if done is None and intervals:
                done = max(item["done"] for item in intervals)
            scoped = [sample for sample in numeric_samples
                      if start is not None and done is not None and start <= _number(sample.get("at")) <= done]
            batch["resource_observation"] = {
                "sample_count": len(scoped),
                "peak_rss_bytes": max((sample.get("rss_bytes", 0) for sample in scoped), default=None),
                "scope": "全局采样窗口；包含既有授权浏览器进程树，不能归因到本 batch worker",
                "window_start": start,
                "window_done": done,
            }
    else:
        result["resource_observation"] = {"read_error": resource_error or "resources.json 不是数组"}

    all_items = [item for batch in result["batches"] for item in batch.get("items", [])
                 if isinstance(item, dict)]
    correctness_items = [
        {
            "row": item.get("row"),
            "product_id": item.get("product_id"),
            **(item.get("correctness_basis") or _correctness_basis(item)),
        }
        for item in all_items
    ]
    correctness_ready = bool(correctness_items) and all(
        item.get("ready") is True for item in correctness_items
    )
    result["correctness_basis"] = {
        "status": "通过" if correctness_ready else "需复核",
        "ready": correctness_ready,
        "items": correctness_items,
        "unverified_items": [
            {"row": item.get("row"), "product_id": item.get("product_id"),
             "reasons": item.get("reasons", [])}
            for item in correctness_items if not item.get("ready")
        ],
        "note": "仅有 completed 生命周期或预览/存在性证据时，不能将整体结论标为 passed",
    }

    completed_pairs = all(batch.get("event_analysis", {}).get("valid_pairing")
                          for batch in result["batches"] if batch.get("event_analysis"))
    concurrency_two = next((batch for batch in result["batches"] if batch.get("concurrency") == 2), None)
    if (result["input_contract"].get("valid_shape") and completed_pairs and concurrency_two):
        event_analysis = concurrency_two.get("event_analysis", {})
        all_batches_completed = all(
            batch.get("event_analysis", {}).get("latest_all_completed")
            for batch in result["batches"]
        )
        result["status"] = (
            "passed"
            if (event_analysis.get("progress_overlap")
                and event_analysis.get("latest_all_completed")
                and all_batches_completed
                and not event_analysis.get("global_blocker")
                and correctness_ready)
            else "needs_review"
        )
    elif result["batches"]:
        result["status"] = "needs_review"

    # Resume runs are stored under attempts/<id>/ to keep the first report,
    # events and resource samples immutable. Analyze each child independently
    # and retain it as history instead of merging events into one false pair.
    if _include_nested:
        attempts_root = run_dir / "attempts"
        nested = []
        if attempts_root.is_dir():
            for attempt_dir in sorted(path for path in attempts_root.iterdir() if path.is_dir()):
                nested.append(analyze_run(attempt_dir, _include_nested=False))
        result["nested_attempts"] = nested
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="verify_concurrent_live.py 的验收目录")
    parser.add_argument("--output", type=Path, help="离线分析输出 JSON；默认写入 run_dir/offline-analysis.json")
    args = parser.parse_args(argv)
    run_dir = args.run_dir.resolve()
    if not run_dir.is_dir():
        parser.error(f"验收目录不存在: {run_dir}")
    output = (args.output or run_dir / "offline-analysis.json").resolve()
    if output == (run_dir / "report.json").resolve():
        parser.error("禁止覆盖原始 report.json")
    analysis = analyze_run(run_dir)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(analysis, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"status": analysis["status"], "output": str(output),
                      "batches": len(analysis["batches"])}, ensure_ascii=False))
    return 0 if analysis["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
