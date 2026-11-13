# -*- coding: utf-8 -*-
"""只读探测潮玩盲盒发布页 SKU 区域结构（复用项目 Playwright 会话）。"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import extract_result, get_output, render_script  # noqa: E402


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    path = render_script("probe_chaowan_sku.js", {"phase": "probe"})
    out = session.cmd("run-code", f"--filename={path}", raw=False, timeout=90)
    result = extract_result(out)
    (get_output() / "probe_chaowan_sku.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
