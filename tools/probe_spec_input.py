# -*- coding: utf-8 -*-
"""在款式描述空行输入规格名，观察校验/下拉/按钮启用状态。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    path = render_script("probe_spec_input.js", {"name": "单个随机盲盒"})
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=90)
    print(extract_result(out) if "### Error" not in out else out[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
