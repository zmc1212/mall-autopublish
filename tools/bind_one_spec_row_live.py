# -*- coding: utf-8 -*-
"""真实页面验证:盲盒编辑页第 1 行规格图单行绑定(项目已有 spec_row_images 流程)。

仅对第 1 行执行一次;结果不明确时不自动重复,直接报告现场。
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from web_fill.pipeline import (  # noqa: E402
    FileChooserNeeded, _human_upload_policy, _prepare_media_uploads, run_script,
)

IMAGE = Path(r"G:\workspace\淘宝自动上架\testdata\工作空间\潮玩盲盒"
             r"\HelloKitty苹果派对系列贴贴萌趣豆盲盒摆件萌粒潮玩女生桌面礼物"
             r"\颜色01-单个随机盲盒.jpg")
ROW = 0


def main() -> int:
    from 千牛网页执行 import CliSession  # noqa: E402

    session = CliSession()
    session.attach()
    print("页签:", session.href()[:120])
    image = str(_prepare_media_uploads([str(IMAGE)], compact=True)[0])
    args = {**_human_upload_policy(), "index": ROW, "image": image,
            "repairItemId": "1090746000625"}

    opened = run_script(session, "spec_row_images.js", {**args, "phase": "open"}, timeout=70)
    print("open:", json.dumps(opened, ensure_ascii=False)[:600])
    if opened.get("already"):
        print("第 1 行已有图,不再上传")
        return 0
    import time
    time.sleep(1)
    try:
        result = run_script(session, "spec_row_images.js", {**args, "phase": "select"}, timeout=240)
    except FileChooserNeeded:
        print("需要文件选择器,代投上传")
        session.upload_files(image, timeout=90)
        result = run_script(session, "spec_row_images.js", {**args, "phase": "finish"}, timeout=240)
    if result.get("needsFinish"):
        result = run_script(session, "spec_row_images.js", {**args, "phase": "finish"}, timeout=240)
    print("select/finish:", json.dumps(result, ensure_ascii=False)[:800])

    probe = run_script(session, "spec_row_images.js", {**args, "phase": "cell"}, timeout=30)
    print("cell:", json.dumps(probe, ensure_ascii=False))

    # 读取新版单元格上传后的真实 DOM(只读)
    dom = run_script(session, "spec_row_status.js", {}, timeout=60)
    print("spec_row_status:", json.dumps({k: dom.get(k) for k in ("total", "filled", "missing")}, ensure_ascii=False))
    print("sources:", json.dumps(dom.get("sources"), ensure_ascii=False)[:600])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
