# -*- coding: utf-8 -*-
"""只读诊断:盲盒编辑页规格列读数(spec_row_status.js / probe_state.js)。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script, run_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    session.attach()
    href = session.href()
    print("当前页签:", href[:150])

    probe = run_script(session, "probe_state.js", {"waitForReady": True}, timeout=60)
    print("== probe_state ==")
    print(json.dumps({k: probe.get(k) for k in
                      ("title", "skuRows", "specImgs", "mainImgs", "detailImgs",
                       "popup", "specDialog", "href")}, ensure_ascii=False, indent=1))

    status = run_script(session, "spec_row_status.js", {}, timeout=90)
    print("== spec_row_status ==")
    slim = {k: status.get(k) for k in ("total", "filled", "missing")}
    print(json.dumps(slim, ensure_ascii=False))
    for row in (status.get("sources") or []):
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
