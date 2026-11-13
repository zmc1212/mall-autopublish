# -*- coding: utf-8 -*-
"""完整前置(建发布页+seed)后探测批量导入上传绑定与完整请求体。"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import _load_web, ensure_new_category_tab, extract_result, render_script, run_script  # noqa: E402
from tools.experiment_import_filechooser import build_payload  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    payload = build_payload()
    session = CliSession()
    web = _load_web()
    ensure_new_category_tab(session, web)
    category = run_script(session, "category.js", payload, timeout=90)
    print("category leaf:", category.get("leaf"))

    seed = {**payload, "skus": payload["skus"][:1]}
    seed_result = run_script(session, "skus.js", seed, timeout=300)
    print("SEED:", json.dumps({k: seed_result.get(k) for k in ("opened", "log", "filled")}, ensure_ascii=False)[:200])

    try:
        run_script(session, "close_import_dialog.js", {}, timeout=30)
    except Exception:
        pass

    experiment = {"file": str((ROOT / "testdata" / "SKU模板_潮玩盲盒.xls").resolve())}
    path = render_script("probe_upload_binding.js", experiment)
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=150)
    r = extract_result(out)
    if isinstance(r, dict):
        print("DUMP:", json.dumps(r.get("dump"), ensure_ascii=False)[:1000])
        print("CHOOSER:", json.dumps(r.get("chooser"), ensure_ascii=False))
        print("AFTER:", json.dumps(r.get("after"), ensure_ascii=False)[:300])
        rec = r.get("recognized") or {}
        print("RECOG.status:", rec.get("status"), "body:", rec.get("body"))
        jb = rec.get("jsonBodyHead") or ""
        for key in ["fileUrl", "fileName", "fileId", "attachment"]:
            for m in re.finditer(r'"' + key + r'"\s*:\s*("[^"]*"|null|{[^}]{0,80}})', jb):
                print("FIELD:", m.group(0)[:200])
        if not any(k in jb for k in ("fileUrl", "fileName", "fileId", "attachment")):
            print("FIELD: (无文件相关字段)")
        print("NET:", json.dumps(r.get("net"), ensure_ascii=False)[:900])
    else:
        print(str(r)[:900])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
