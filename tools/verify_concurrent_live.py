"""Opt-in acceptance harness using the application's existing upload workflow.

Creates three distinct, labelled warehouse test items: one with concurrency=1,
then two with concurrency=2. Never run this as an ordinary unit test.
"""

import argparse
import copy
import json
import os
import shutil
import sys
import threading
import time
import uuid
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


_RESUME_FIELDS = (
    "execution", "notice", "errors", "taobao_item_id", "view_url", "edit_url", "url",
    "flow_version", "sku_image_strategy", "seller_account", "flow_stage", "spec_image_stage",
    "run_status", "sku_material_manifest", "material_result", "material_preview",
    "material_folder", "last_error",
)


def read_json(path, *, required=True):
    path = Path(path)
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        if not required:
            return None
        raise ValueError(f"缺少验收断点文件: {path}")
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"无法读取验收断点文件 {path}: {exc}") from exc


def _item_identity(item):
    if not isinstance(item, dict):
        return None
    row = item.get("row")
    product_id = str(item.get("product_id") or "")
    if row is None and not product_id:
        return None
    return row, product_id


def _resolve_identity(item, known):
    identity = _item_identity(item)
    if identity in known:
        return identity
    if identity is None:
        return None
    matches = [key for key in known if key[0] == identity[0]]
    return matches[0] if len(matches) == 1 else identity


def _merge_resume_state(target, source):
    """Merge a later execution record without losing an earlier page URL."""
    if not isinstance(source, dict):
        return target
    execution = str(source.get("execution") or "").strip()
    meaningful_execution = bool(execution and execution != "未执行")
    if meaningful_execution:
        target["execution"] = execution
        for field in ("notice", "errors"):
            if field in source:
                target[field] = copy.deepcopy(source[field])
    for field in _RESUME_FIELDS:
        if field in {"execution", "notice", "errors"}:
            continue
        value = source.get(field)
        if value not in (None, ""):
            target[field] = copy.deepcopy(value)
    return target


def _collect_resume_state(output, inputs, base_report, session):
    """Collect report/events/job_session state in chronological order."""
    known = {_item_identity(item) for item in inputs}
    known.discard(None)
    state = {key: {} for key in known}

    def apply(item, *, product_id=""):
        if not isinstance(item, dict):
            return
        source = dict(item)
        if not source.get("product_id") and product_id:
            source["product_id"] = product_id
        key = _resolve_identity(source, known)
        if key not in state:
            return
        _merge_resume_state(state[key], source)

    report_paths = [Path(output) / "report.json"]
    report_paths.extend(sorted((Path(output) / "attempts").glob("*/report.json")))
    reports = []
    for path in report_paths:
        report = base_report if path == Path(output) / "report.json" else read_json(path, required=False)
        if not isinstance(report, dict):
            continue
        reports.append(report)
        for batch in report.get("batches") or []:
            for item in batch.get("results") or []:
                apply(item)
            for item in batch.get("verification") or []:
                # Verification has only row-level evidence; it must not erase
                # the execution state collected above.
                if isinstance(item, dict) and item.get("row") is not None:
                    apply({"row": item.get("row"), "product_id": item.get("product_id", "")})

    event_paths = sorted(Path(output).glob("events-*.json"))
    event_paths.extend(sorted((Path(output) / "attempts").glob("*/events-*.json")))
    for path in event_paths:
        events = read_json(path, required=False)
        for event in events or []:
            if not isinstance(event, dict):
                continue
            item = event.get("item")
            if isinstance(item, dict):
                apply(item, product_id=str(event.get("product_id") or ""))

    session = session if isinstance(session, dict) else {}
    for item in session.get("rows") or []:
        apply(item)
    for bundle in session.get("products") or []:
        if not isinstance(bundle, dict):
            continue
        apply(bundle.get("meta") or {})
    return state, reports, event_paths


def _is_completed(item):
    return isinstance(item, dict) and item.get("run_status") == "completed"


def _resume_context(output):
    output = Path(output).resolve()
    input_path = output / "inputs.json"
    report_path = output / "report.json"
    session_path = output / "state" / "job_session.json"
    inputs = read_json(input_path)
    report = read_json(report_path)
    session = read_json(session_path)
    if not isinstance(inputs, list) or not inputs:
        raise ValueError(f"{input_path} 不是有效商品清单")
    if not isinstance(report, dict):
        raise ValueError(f"{report_path} 不是有效验收报告")
    if not isinstance(session, dict):
        raise ValueError(f"{session_path} 不是有效 job_session")
    state, reports, event_paths = _collect_resume_state(output, inputs, report, session)
    products = []
    for original in inputs:
        product = copy.deepcopy(original)
        key = _item_identity(original)
        _merge_resume_state(product, state.get(key) or {})
        # Inputs are immutable acceptance identities.  A stale result file must
        # never change the title, row, product_id, or workbook key on resume.
        for field in ("title", "row", "product_id"):
            if field in original:
                product[field] = copy.deepcopy(original[field])
        products.append(product)
    workbook_path = str(session.get("workbook_path") or output / "acceptance.xlsx")
    completed = {key for key, item in state.items() if _is_completed(item)}
    return {
        "output": output,
        "inputs": inputs,
        "products": products,
        "state": state,
        "completed": completed,
        "report": report,
        "reports": reports,
        "event_paths": event_paths,
        "session": session,
        "session_path": session_path,
        "workbook_path": workbook_path,
        "registry_path": output / "browser" / "owned_pages.json",
    }


def _resume_groups(products, completed):
    """Keep the original acceptance order: one serial item, then the pair."""
    groups = []
    for concurrency, source in ((1, products[:1]), (2, products[1:])):
        pending = [
            item for item in source
            if _item_identity(item) not in completed
        ]
        if pending:
            groups.append((concurrency, pending))
    return groups


def _new_attempt_id():
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return f"{stamp}-{uuid.uuid4().hex[:6]}"


def _prepare_attempt(output, *, resume, attempt_id, context=None):
    if not resume:
        return Path(output), None
    attempt = Path(output) / "attempts" / attempt_id
    attempt.mkdir(parents=True, exist_ok=False)
    source_report = Path(output) / "report.json"
    if source_report.is_file():
        shutil.copy2(source_report, attempt / "source-report.json")
    for path in sorted(Path(output).glob("events-*.json")):
        shutil.copy2(path, attempt / f"source-{path.name}")
    if context and Path(context["session_path"]).is_file():
        shutil.copy2(context["session_path"], attempt / "job_session-before.json")
    if context and (Path(output) / "inputs.json").is_file():
        shutil.copy2(Path(output) / "inputs.json", attempt / "inputs.json")
    return attempt, source_report


def _verification_passed(report):
    checks = []
    if not isinstance(report, dict):
        return False
    for batch in report.get("batches") or []:
        checks.extend(batch.get("verification") or [])
    return bool(checks) and all(
        check.get(field) == "通过"
        for check in checks
        for field in ("search_main_images", "sales_spec_images", "non_image_fields")
    )


def _all_verification_passed(reports, products):
    known = {_item_identity(item) for item in products}
    known.discard(None)
    checks = {}
    for report in reports or []:
        if not isinstance(report, dict):
            continue
        for batch in report.get("batches") or []:
            for check in batch.get("verification") or []:
                key = _resolve_identity(check, known)
                if key in known:
                    checks[key] = check
    return bool(known) and all(
        key in checks
        and all(checks[key].get(field) == "通过"
                for field in ("search_main_images", "sales_spec_images", "non_image_fields"))
        for key in known
    )


def _write_report_latest(output, current_report):
    output = Path(output)
    aggregate = copy.deepcopy(read_json(output / "report.json", required=False) or {})
    all_batches = list(aggregate.get("batches") or [])
    attempts = []
    for path in sorted((output / "attempts").glob("*/report.json")):
        attempt = read_json(path, required=False)
        if not isinstance(attempt, dict):
            continue
        all_batches.extend(copy.deepcopy(attempt.get("batches") or []))
        attempts.append({
            "attempt_id": attempt.get("attempt_id") or path.parent.name,
            "report": str(path),
            "status": attempt.get("status"),
            "started_at": attempt.get("started_at"),
            "finished_at": attempt.get("finished_at"),
        })
    aggregate.update({
        "report_kind": "aggregate",
        "source_report": str(output / "report.json"),
        "latest_attempt": current_report.get("attempt_id"),
        "attempts": attempts,
        "batches": all_batches,
        "status": current_report.get("status"),
        "verification": current_report.get("verification") or aggregate.get("verification") or {},
        "finished_at": current_report.get("finished_at") or time.time(),
    })
    if current_report.get("reason"):
        aggregate["reason"] = current_report["reason"]
    else:
        aggregate.pop("reason", None)
    path = output / "report-latest.json"
    write_json(path, aggregate)
    return path


def verify_evidence(product, item, directory):
    """Compare saved fresh-server probes; completion labels alone are insufficient."""
    from web_fill import material_import, pipeline

    checks = {"search_main_images": "无法判断", "sales_spec_images": "无法判断",
              "non_image_fields": "无法判断", "differences": []}
    if item.get("run_status") != "completed":
        return checks
    baseline = item.get("sku_material_manifest") or []
    actual = item.get("material_result") or []
    try:
        if not baseline or not actual:
            raise ValueError("缺少服务器 SKU 基线或刷新核验结果")
        material_import.check_rows(actual, product, baseline, images=True)
        checks["search_main_images"] = "通过"
        prior = {row["name"]: row for row in baseline}
        for row in actual:
            for key in ("sku_id", "price", "stock", "search_title", "merchant_code", "attributes_text"):
                if key not in prior[row["name"]]:
                    continue
                before_value, after_value = prior[row["name"]][key], row.get(key, "")
                different = (Decimal(str(before_value)) != Decimal(str(after_value))
                             if key in {"price", "stock"} else str(before_value) != str(after_value))
                if different:
                    checks["differences"].append({"sku": row["name"], "field": key,
                                                   "before": prior[row["name"]][key], "after": row.get(key)})
        probe = json.loads((directory / "web_fill_probe_state.json").read_text(encoding="utf-8"))
        specs = json.loads((directory / "web_fill_spec_row_status.json").read_text(encoding="utf-8"))
        write_json(directory / "acceptance-server-evidence.json",
                   {"baseline": baseline, "actual": actual, "product_probe": probe, "spec_probe": specs})
        if (specs.get("total") != len(product["skus"]) or specs.get("missing")
                or len([row for row in specs.get("sources", []) if row.get("src")]) != len(product["skus"])):
            raise ValueError("刷新后销售规格图片数量不符")
        checks["sales_spec_images"] = "通过"
        if probe.get("title") != pipeline.display_title(product["title"]):
            checks["differences"].append({"field": "title", "expected": product["title"], "actual": probe.get("title")})
        if not any(row.get("checked") and row.get("t") == "放入仓库" for row in probe.get("warehouse", [])):
            checks["differences"].append({"field": "warehouse", "expected": True, "actual": probe.get("warehouse")})
        checks["non_image_fields"] = "通过" if not checks["differences"] else "失败"
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        checks["reason"] = str(exc)
    return checks


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="明确执行已获授权的测试入库")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--resume", action="store_true", help="沿用指定验收目录的商品及断点，保留历史证据")
    parser.add_argument("--skip-row", action="append", type=int, default=[], help="续跑时保留指定待复核行，继续其他测试商品")
    args = parser.parse_args()
    if not args.execute:
        parser.error("此验收会创建仓库商品；需先获得授权再传 --execute")
    if args.resume and args.output is None:
        parser.error("--resume 必须指定原验收目录 --output")
    if args.skip_row and not args.resume:
        parser.error("--skip-row 只能用于 --resume，不会清除待复核状态")

    from desktop import paths
    settings = paths.load_settings()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = (args.output or ROOT / "output" / "playwright" / "concurrency-live" / stamp).resolve()
    if not args.resume and output.exists() and any(output.iterdir()):
        parser.error("验收目录已有记录，禁止覆盖或自动重跑；请先核对原任务结果")
    try:
        context = _resume_context(output) if args.resume else None
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if context and set(args.skip_row) - {item["row"] for item in context["inputs"]}:
        parser.error("--skip-row 包含原验收清单中不存在的行")
    output.mkdir(parents=True, exist_ok=True)
    attempt_id = _new_attempt_id()
    artifacts, _ = _prepare_attempt(output, resume=args.resume, attempt_id=attempt_id, context=context)
    workbook_path = context["workbook_path"] if context else str(output / "acceptance.xlsx")
    # Set all writable paths before importing the browser module: its legacy
    # import hook can restore/remember a desktop session.
    os.environ["QIANNIU_APPDATA"] = str(output / "state")
    os.environ["QIANNIU_OUTPUT_DIR"] = str(output / "browser")
    settings.results_dir = str(output / "results")
    paths.configure_environ(settings)
    from desktop.modules import load_web
    from web_fill import pipeline
    import job_session

    web = load_web()
    report = {"started_at": time.time(), "status": "preflight", "batches": [],
              "attempt_id": attempt_id, "resumed": args.resume,
              "deferred_rows": args.skip_row,
              "workbook_path": workbook_path, "output_root": str(output),
              "verification": {"search_main_images": "无法判断", "sales_spec_images": "无法判断",
                               "non_image_fields": "无法判断"}}
    write_json(artifacts / "report.json", report)
    print("REPORT=" + str(artifacts), flush=True)
    if not web.cdp_available():
        report.update(status="blocked", reason="现有授权浏览器未连接；未创建商品")
        write_json(artifacts / "report.json", report)
        if args.resume:
            _write_report_latest(output, report)
        return 2

    if context:
        products = context["products"]
        groups = _resume_groups(products, context["completed"])
        groups = [(n, [item for item in selected if item["row"] not in args.skip_row]) for n, selected in groups]
        groups = [(n, selected) for n, selected in groups if selected]
    else:
        source = pipeline.resolve_naruto_product()
        products = []
        for index in range(3):
            product = copy.deepcopy(source)
            product.update(row=90001 + index, product_id=f"concurrency-{stamp}-{index + 1}",
                           title=f"并发验收{stamp[-6:]}-{index + 1}卡游火影忍者中性笔",
                           guide_title="", main_video="", sku_image_strategy="both")
            product["skus"] = product["skus"][:2]
            product["main_images"] = product["main_images"][:1]
            product["portrait_images"] = product.get("portrait_images", [])[:1]
            product["detail_images"] = product["detail_images"][:1]
            products.append(product)
        write_json(output / "inputs.json", products)
        job_session.save_session({"status": "idle", "workbook_path": workbook_path,
                                  "rows": products, "products": [{"product": p, "meta": p} for p in products]})
        groups = [(1, products[:1]), (2, products[1:])]
    original_pages = {tab["id"]: tab.get("url") for tab in web.cdp_tabs() if tab.get("type") == "page"}
    report["pages_before"] = original_pages

    samples = []
    stop_metrics = threading.Event()
    try:
        import psutil
        chrome_pid = web.listening_pid_on_port(settings.cdp_port)

        def monitor():
            while not stop_metrics.is_set():
                processes = {}
                for pid in (os.getpid(), chrome_pid):
                    if not pid:
                        continue
                    try:
                        parent = psutil.Process(pid)
                        for process in [parent, *parent.children(recursive=True)]:
                            processes[process.pid] = process
                    except psutil.Error:
                        pass
                rss = cpu = 0
                for process in processes.values():
                    try:
                        rss += process.memory_info().rss
                        times = process.cpu_times()
                        cpu += times.user + times.system
                    except psutil.Error:
                        pass
                samples.append({"at": time.time(), "rss_bytes": rss, "cpu_seconds": cpu,
                                "process_count": len(processes)})
                stop_metrics.wait(2)

        metrics_thread = threading.Thread(target=monitor, daemon=True)
        metrics_thread.start()
    except ImportError:
        metrics_thread = None

    try:
        for concurrency, selected in groups:
            events = []
            event_lock = threading.Lock()

            def observe(event):
                current = {**event, "at": time.time()}
                with event_lock:
                    events.append(current)
                    write_json(artifacts / f"events-{concurrency}.json", events)
                if event.get("event") in {"start", "done", "global_blocker"}:
                    print(json.dumps({k: current.get(k) for k in ("event", "worker_id", "row", "phase", "message")},
                                     ensure_ascii=False), flush=True)

            started = time.time()
            results = pipeline.run_batch(
                selected, confirm_submit=True, concurrency=concurrency,
                on_worker_event=observe, sku_image_strategy="both", spec_upload_batch_size=2,
                item_retry_limit=0,
                runtime_settings={**vars(settings), "workbook_path": workbook_path},
            )
            batch = {"concurrency": concurrency, "started_at": started, "finished_at": time.time(),
                     "duration_seconds": round(time.time() - started, 2), "results": results}
            active = set()
            maximum = 0
            overlap = 0.0
            previous = started
            for event in events:
                if len(active) > 1:
                    overlap += max(0, event["at"] - previous)
                previous = event["at"]
                if event.get("event") == "start":
                    active.add(event["worker_id"])
                elif event.get("event") == "done":
                    active.discard(event["worker_id"])
                maximum = max(maximum, len(active))
            batch.update(max_active_workers=maximum, overlap_seconds=round(overlap, 2))
            event_dirs = {event["row"]: Path(event["output_dir"]) for event in events if event.get("output_dir")}
            expected = {product["row"]: product for product in selected}
            batch["verification"] = [
                {"row": item["row"], **verify_evidence(expected[item["row"]], item, event_dirs[item["row"]])}
                for item in results if item.get("row") in event_dirs
            ]
            report["batches"].append(batch)
            write_json(artifacts / "report.json", report)
            if any(event.get("event") == "global_blocker" for event in events):
                report.update(status="blocked", reason="全局故障，保留断点；未派发后续批次")
                break
            # Per-item uncertainty preserves that item's evidence. Only the
            # global blocker above stops dispatching other authorized items.
            if any(item.get("execution") in {"暂停", "提交待核实", "结果待核实", "失败", "提交失败", "已停止"}
                   for item in results):
                report.update(status="needs_review", reason="测试商品需复核，保留证据和页面")
        latest = dict(context["state"]) if context else {}
        for batch in report["batches"]:
            for item in batch["results"]:
                latest[_item_identity(item)] = item
        reports = [*(context["reports"] if context else []), report]
        if (len(latest) == 3 and all(item.get("run_status") == "completed" for item in latest.values())
                and _all_verification_passed(reports, products)
                and any(batch.get("max_active_workers") == 2 and batch.get("overlap_seconds", 0) > 0
                        for prior_report in reports for batch in prior_report.get("batches", []))):
            report["status"] = "passed"
            report["verification"] = {"search_main_images": "通过", "sales_spec_images": "通过",
                                      "non_image_fields": "通过"}
        elif report["status"] == "preflight":
            report["status"] = "needs_review"
    except Exception as exc:
        report.update(status="blocked", reason=str(exc))
    finally:
        stop_metrics.set()
        if metrics_thread:
            metrics_thread.join(timeout=3)
        write_json(artifacts / "resources.json", samples)
        report["peak_observed_rss_bytes"] = max((sample["rss_bytes"] for sample in samples), default=None)
        report["resource_scope"] = "测试进程树及既有授权浏览器进程树，包含其原有标签页"
        report["finished_at"] = time.time()
        try:
            report["pages_after"] = {tab["id"]: tab.get("url") for tab in web.cdp_tabs() if tab.get("type") == "page"}
        except Exception as exc:
            report["pages_after_error"] = str(exc)
        write_json(artifacts / "report.json", report)
        if args.resume:
            _write_report_latest(output, report)
    print(json.dumps({"status": report["status"], "verification": report["verification"],
                      "reason": report.get("reason", "")}, ensure_ascii=False), flush=True)
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
