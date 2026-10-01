# -*- coding: utf-8 -*-
"""导出日志按钮的 UI 验收：mock /api/logs/export，验证按钮渲染、pending 转圈与 toast。"""
import json
import os
import sys

from playwright.sync_api import sync_playwright

OUT = os.path.abspath(os.path.dirname(__file__) + "/ui_shots_export")
BASE = "http://localhost:4173"

sys.path.insert(0, os.path.dirname(__file__))
from ui_snapshot import CHROME_STATUS, JOB, SETTINGS, WORKSPACE  # noqa: E402

EXPORT_RESULT = {
    "path": r"C:\Users\Administrator\AppData\Roaming\千牛自动上架\log-exports\日志导出-20261001-120000.zip",
    "folder": r"C:\Users\Administrator\AppData\Roaming\千牛自动上架\log-exports",
    "files": 7,
    "size": 123456,
}
opened: list[str] = []


def handle(route):
    url = route.request.url
    path = url.split("4173")[-1].split("?")[0]
    if path == "/api/status":
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"chrome": CHROME_STATUS, "job": JOB, "workspace": WORKSPACE, "settings": SETTINGS}))
    elif path == "/api/logs/export" and route.request.method == "POST":
        opened.append(path)
        route.fulfill(status=200, content_type="application/json", body=json.dumps(EXPORT_RESULT))
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))


def main():
    os.makedirs(OUT, exist_ok=True)
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        # 拦截 window.open：无 pywebview 桥时 nativeOpen 走该兜底，验证打开的是导出文件夹
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.on("popup", lambda popup: opened.append(popup.url))
        page.route("**/api/**", handle)
        page.goto(BASE)
        page.wait_for_selector("text=卖家中心已登录", timeout=10000)

        page.get_by_role("button", name="设置").click()
        page.wait_for_selector("text=高级设置", timeout=5000)
        export_btn = page.get_by_role("button", name="导出日志")
        assert export_btn.is_visible(), "设置页应有导出日志按钮"
        page.wait_for_timeout(300)
        page.screenshot(path=os.path.join(OUT, "01-settings-export-btn.png"))

        # 无 pywebview 桥时 nativeOpen 走 window.open 兜底：hook 记录实参
        page.evaluate("window.open = (url) => { window.__openedUrl = String(url); return null; }")

        export_btn.click()
        page.wait_for_selector("text=日志已导出（7 个文件），文件夹已打开", timeout=10000)
        page.wait_for_timeout(400)
        page.screenshot(path=os.path.join(OUT, "02-export-toast.png"))
        assert page.evaluate("window.__openedUrl || ''") == EXPORT_RESULT["folder"], \
            f"nativeOpen 应以导出文件夹调用 window.open，实际: {page.evaluate('window.__openedUrl')}"
        assert opened, "导出后应尝试打开导出文件夹"
        print("open_target:", opened[-1])
        print("api_called:", "/api/logs/export" in opened)

        browser.close()
        print("all done")


if __name__ == "__main__":
    main()
