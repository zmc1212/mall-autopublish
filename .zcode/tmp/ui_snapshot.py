# -*- coding: utf-8 -*-
"""批次1 UI 改动的视觉快照：mock 全部 /api/* 响应，截图各页面、toast 与确认弹窗。"""
import json
import os
import sys
import time

from playwright.sync_api import sync_playwright

OUT = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else "ui_shots")
BASE = "http://localhost:4173"

CHROME_STATUS = {
    "chrome_path": "", "chrome_found": True, "browser_source": "bundled", "profile": "D:/profile",
    "cdp_port": 9222, "debug_browser": False, "cdp": True, "browser": "Chromium 140",
    "logged_in": True, "blocker": "", "url": "https://myseller.taobao.com", "cli_js": "cli.js",
    "cli_js_found": True, "node": "node.exe", "node_found": True,
}
SETTINGS = {
    "chrome_path": "", "chrome_profile": "D:/profile", "cdp_port": 9222, "debug_browser": False,
    "confirm_submit": True, "sku_template_import": False, "skip_spec_images": False,
    "sku_image_strategy": "slim_material", "settings_version": 3, "limit": 0, "results_dir": "D:/results",
}
ROWS = [
    {
        "row": 1, "product_id": "ZXB-001", "title": "卡游中性笔 黑色 0.5mm 20支装", "category": "中性笔",
        "brand": "卡游", "validation": "通过", "execution": "结果待核实", "notice": "提交成功 商品ID: 1832457601",
        "errors": [], "main_count": 5, "portrait_count": 0, "detail_count": 8, "sku_count": 4,
        "pack": "D:/工作空间/ZXB-001", "pack_found": True, "taobao_item_id": "1832457601",
        "view_url": "https://item.taobao.com/item.htm?id=1832457601", "edit_url": "https://item.taobao.com/item.htm?id=1832457601&edit=1",
        "flow_stage": "complete", "sku_image_strategy": "slim_material",
    },
    {
        "row": 2, "product_id": "ZXB-002", "title": "卡游中性笔 红色 0.35mm 10支装", "category": "中性笔",
        "brand": "卡游", "validation": "通过", "execution": "暂停", "notice": "", "errors": ["检测到滑块验证"],
        "main_count": 5, "portrait_count": 0, "detail_count": 6, "sku_count": 2,
        "pack": "D:/工作空间/ZXB-002", "pack_found": True, "flow_stage": "filled",
    },
    {
        "row": 3, "product_id": "XZD-001", "title": "卡游修正带 30米装", "category": "修正带",
        "brand": "卡游", "validation": "未通过", "execution": "未执行", "notice": "",
        "errors": ["标题超过30个汉字"], "main_count": 3, "portrait_count": 0, "detail_count": 0, "sku_count": 1,
        "pack": "", "pack_found": False,
    },
]
LOGS = [
    {"time": "10:21:05", "level": "info", "message": "开始入库任务，共 3 条，确认提交已勾选"},
    {"time": "10:21:11", "level": "info", "message": "[ZXB-001] 打开发布页，开始填写类目"},
    {"time": "10:22:03", "level": "info", "message": "[ZXB-001] 主图上传完成（5/5）"},
    {"time": "10:23:47", "level": "info", "message": "[ZXB-001] 已提交放入仓库，商品ID: 1832457601"},
    {"time": "10:24:12", "level": "warn", "message": "[ZXB-002] 检测到滑块验证，任务已暂停，请人工处理"},
]
JOB = {
    "status": "paused", "phase": "需人工处理", "blocker": "检测到滑块验证，已保留现场等待人工处理", "message": "",
    "current_row": 2, "current_id": "ZXB-002", "done": 1, "total": 3,
    "workbook_path": "D:/工作空间/商品清单.xlsx", "workspace_path": "D:/工作空间",
    "result_xlsx": "D:/results/商品清单.结果-20260930-102455.xlsx", "result_json": "D:/results/商品清单.结果.json",
    "valid": 3, "failed": 1, "pending": 2, "can_resume": True, "restored": True, "count": 3,
    "rows": ROWS, "logs": LOGS,
}
WORKSPACE = {
    "path": "D:/工作空间", "workbook_path": "D:/工作空间/商品清单.xlsx",
    "defaults": {"brand": "卡游", "attributes_template": "中性笔", "logistics_template": "48小时",
                 "sales_template": "仓库多规格", "price": 9.9, "stock": 20},
    "registry": {"attributes": ["中性笔"], "logistics": ["48小时", "24小时"], "sales": ["仓库多规格"]},
    "scan": {
        "root": "D:/工作空间",
        "categories": [
            {"name": "中性笔", "path": "D:/工作空间/中性笔", "relative": "中性笔", "selected": True,
             "product_count": 2, "error_count": 0, "template_found": True, "notice": ""},
            {"name": "修正带", "path": "D:/工作空间/修正带", "relative": "修正带", "selected": False,
             "product_count": 1, "error_count": 1, "template_found": False, "notice": "未配置同名商品属性模板"},
        ],
    },
}


def handle(route):
    url = route.request.url
    path = url.split("4173")[-1].split("?")[0]
    if path == "/api/status":
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"chrome": CHROME_STATUS, "job": JOB, "workspace": WORKSPACE, "settings": SETTINGS}))
    elif path == "/api/workbook/import":
        route.fulfill(status=400, content_type="application/json",
                      body=json.dumps({"detail": "文件不存在：X:\\不存在\\商品清单.xlsx"}))
    elif path == "/api/settings" and route.request.method == "PUT":
        route.fulfill(status=200, content_type="application/json", body=json.dumps(SETTINGS))
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))


def shot(page, name):
    page.screenshot(path=os.path.join(OUT, name), full_page=False)
    print("saved", name)


def main():
    os.makedirs(OUT, exist_ok=True)
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.route("**/api/**", handle)
        page.goto(BASE)
        page.wait_for_selector("text=卖家中心已登录", timeout=10000)
        page.wait_for_timeout(600)
        shot(page, "01-connect.png")

        page.get_by_role("button", name="清单").click()
        page.wait_for_selector("text=批次默认", timeout=5000)
        page.wait_for_timeout(400)
        shot(page, "02-workbook.png")

        # 触发错误 toast：高级导入里输入不存在的路径
        page.locator("summary", has_text="高级").click()
        page.get_by_placeholder("选择或粘贴商品清单.xlsx").fill(r"X:\不存在\商品清单.xlsx")
        page.get_by_role("button", name="导入", exact=True).click()
        page.wait_for_selector("text=文件不存在", timeout=5000)
        shot(page, "03-workbook-error-toast.png")
        page.get_by_role("alert").get_by_label("关闭通知").click()

        page.get_by_role("button", name="执行", exact=True).click()
        page.wait_for_selector("text=实时步骤", timeout=5000)
        page.wait_for_timeout(600)
        shot(page, "04-run.png")

        page.get_by_role("button", name="查看执行明细").click()
        page.wait_for_selector("text=执行明细", timeout=5000)
        shot(page, "05-run-table.png")

        page.locator("tr", has_text="ZXB-001").get_by_role("button", name="清除记录").click()
        page.wait_for_selector("text=清除执行记录", timeout=5000)
        shot(page, "06-confirm-clear.png")
        page.keyboard.press("Escape")
        page.wait_for_timeout(300)
        # Escape 只应关闭顶层确认弹窗，底层明细弹窗保留
        assert page.get_by_role("heading", name="执行明细").is_visible(), "明细弹窗应保留"
        shot(page, "06b-confirm-closed-table-kept.png")
        page.get_by_label("关闭弹窗").first.click()  # 关明细弹窗（确认弹窗已先被 Escape 关闭）

        page.get_by_role("button", name="设置").click()
        page.wait_for_selector("text=高级设置", timeout=5000)
        page.wait_for_timeout(300)
        shot(page, "07-settings.png")
        # 非法端口应显式报错并禁用保存，而不是静默回退
        page.get_by_label("调试端口").fill("abc")
        page.wait_for_selector("text=请输入 1-65535 之间的端口号", timeout=5000)
        assert page.get_by_role("button", name="保存设置").is_disabled(), "非法端口时保存应禁用"
        shot(page, "09-settings-invalid-port.png")
        page.get_by_label("调试端口").fill("9333")
        page.wait_for_timeout(200)
        page.get_by_role("button", name="保存设置").click()
        page.wait_for_selector("text=设置已保存", timeout=5000)
        shot(page, "08-settings-saved.png")

        browser.close()
        print("all done")


if __name__ == "__main__":
    main()
