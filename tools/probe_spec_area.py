# -*- coding: utf-8 -*-
"""探测潮玩盲盒销售属性区 DOM 结构。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    path = render_script("probe_spec_area.js", {})
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=60)
    result = extract_result(out)
    print(json.dumps(result, ensure_ascii=False, indent=1)[:5000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
