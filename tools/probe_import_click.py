# -*- coding: utf-8 -*-
"""点击批量导入并同脚本采样弹窗 DOM。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, render_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    path = render_script("probe_import_click.js", {})
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=60)
    print(extract_result(out) if "### Error" not in out else out[:800])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
