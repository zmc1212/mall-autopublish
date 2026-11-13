# -*- coding: utf-8 -*-
"""两阶段实验:钩子记录文件上传请求 + 确认识别完整请求体。"""
import json
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import _load_web, ensure_new_category_tab, extract_result, render_script, run_script  # noqa: E402
from tools.experiment_import_filechooser import build_payload  # noqa: E402

TEMPLATE = ROOT / "testdata" / "SKU模板_潮玩盲盒.xls"


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    payload = build_payload()
    session = CliSession()
    web = _load_web()
    ensure_new_category_tab(session, web)
    run_script(session, "category.js", payload, timeout=90)
    seed = {**payload, "skus": payload["skus"][:1]}
    seed_result = run_script(session, "skus.js", seed, timeout=300)
    print("SEED:", json.dumps({k: seed_result.get(k) for k in ("opened", "log", "filled")}, ensure_ascii=False)[:200])
    try:
        run_script(session, "close_import_dialog.js", {}, timeout=30)
    except Exception:
        pass

    # 阶段1:hook + 打开弹窗 + 点虚线框(原生对话框挂起)
    p1 = render_script("probe_stage1_open_dialog.js", {})
    out1 = session.cmd("run-code", f"--filename={p1}", raw=False, timeout=90)
    r1 = extract_result(out1)
    print("STAGE1:", json.dumps(r1, ensure_ascii=False)[:200])

    # 代投文件给原生对话框
    try:
        session.upload_files(str(TEMPLATE), timeout=90)
        print("UPLOAD: delivered")
    except Exception as exc:
        print("UPLOAD ERR:", str(exc)[:300])

    # 阶段2:读钩子+确认识别
    p2 = render_script("probe_stage2_recognize.js", {})
    out2 = session.cmd("run-code", f"--filename={p2}", raw=False, timeout=120)
    r2 = extract_result(out2)
    if isinstance(r2, dict):
        print("CAPTURED_BEFORE:", json.dumps(r2.get("capturedBefore"), ensure_ascii=False)[:600])
        print("CAPTURED_AFTER_UPLOAD:", json.dumps(r2.get("capturedAfterUpload"), ensure_ascii=False)[:600])
        print("DLG_TEXT:", str(r2.get("dlgText"))[:300])
        print("CLICKED:", r2.get("clicked"))
        print("CAPTURED_RECOGNIZE:", json.dumps(r2.get("capturedRecognize"), ensure_ascii=False)[:900])
        print("DLG_AFTER:", json.dumps(r2.get("dlgAfter"), ensure_ascii=False)[:300])
        # 从 capturedRecognize 里解出 importSkuTemplate 的完整 body
        for entry in (r2.get("capturedRecognize") or []):
            body = entry.get("body") or ""
            if "jsonBody" in body:
                try:
                    params = dict(pair.split("=", 1) for pair in body.split("&") if "=" in pair)
                    jb = unquote(params.get("jsonBody", ""))
                    print("POST_PARAMS:", list(params.keys()))
                    print("JSONBODY_keys:", list(json.loads(jb).keys()) if jb.startswith("{") else jb[:100])
                    if jb.startswith("{"):
                        full = json.loads(jb)
                        for k, v in full.items():
                            print("  KEY:", k, "=", str(v)[:160])
                except Exception as exc:
                    print("DECODE:", str(exc)[:100], jb[:200])
    else:
        print("STAGE2 raw:", str(r2)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
