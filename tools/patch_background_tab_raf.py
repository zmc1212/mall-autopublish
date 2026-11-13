# -*- coding: utf-8 -*-
"""把 playwright-core 注入脚本的 stable 元素检查从 rAF 调度改为 setTimeout。

背景：Chromium 后台页签（同窗口内非激活页签）的 requestAnimationFrame 不会
触发，而 Playwright 的点击/填充/scrollIntoViewIfNeeded 等操作在动作前的
"stable" 检查（_checkElementIsStable）依赖连续两帧 rAF。并发入库时多个
worker 共用一个浏览器窗口，页签互相切换会把正在操作的页面挤到后台，
导致这些操作必然烧满超时（TimeoutError: locator.scrollIntoViewIfNeeded）。

千牛自动化 Chrome 启动参数已含 --disable-background-timer-throttling 与
--disable-renderer-backgrounding，setTimeout 在后台页签照常触发。替换后
语义不变：仍要求两次间隔约 16ms 的包围盒读数一致才判定稳定。

幂等：已打过补丁的文件再次运行只做确认，不重复替换。
重装 .work/node_modules 后需重新执行本工具；desktop/runtime 副本随打包进入安装目录。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

OLD = "this.utils.builtins.requestAnimationFrame(raf);"
NEW = "this.utils.builtins.setTimeout(raf, 16);"

# 开发环境实际使用的回退副本与随安装包分发的正式副本。
DEFAULT_TARGETS = (
    ROOT / "desktop" / "runtime" / "playwright-core" / "lib" / "coreBundle.js",
    ROOT / ".work" / "node_modules" / "playwright-core" / "lib" / "coreBundle.js",
)


def patch_file(path: Path) -> str:
    if not path.is_file():
        return "missing"
    text = path.read_text(encoding="utf-8")
    if NEW in text:
        if OLD in text:
            raise SystemExit(f"{path}: 同时存在新旧调度代码，请人工核对")
        print(f"already-patched: {path}")
        return "already"
    count = text.count(OLD)
    if count != 2:
        raise SystemExit(f"{path}: 预期 2 处 rAF 调度（递归+初次），实际 {count} 处；playwright-core 版本可能已变化，请人工核对")
    path.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print(f"patched: {path}（替换 {count} 处）")
    return "patched"


def main(argv: list[str]) -> int:
    targets = [Path(arg) for arg in argv[1:]] or list(DEFAULT_TARGETS)
    results = [patch_file(path) for path in targets]
    if "patched" not in results and "already" in results:
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
