# -*- coding: utf-8 -*-
"""点击确认识别并连续采样识别过程。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    path = render_script("probe_recognize.js", {})
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=120)
    result = extract_result(out)
    if isinstance(result, dict):
        print("BEFORE:", json.dumps(result.get("before"), ensure_ascii=False)[:600])
        print("CLICK:", result.get("clickState"))
        for i, s in enumerate(result.get("samples", [])):
            print(f"t+{(i+1)*3}s:", s)
    else:
        print(str(result)[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
