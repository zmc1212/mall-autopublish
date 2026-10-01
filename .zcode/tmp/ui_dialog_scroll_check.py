# -*- coding: utf-8 -*-
"""验证执行明细弹窗可纵向滚动：mock 8 条通过校验的商品，打开弹窗检查滚动并截图。"""
import json
import os

from playwright.sync_api import sync_playwright

OUT = os.path.dirname(os.path.abspath(__file__))
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

# 8 条全部通过校验、已入库的商品，复现用户截图场景（操作按钮换行导致行很高）
ROWS = []
for i in range(1, 9):
    ROWS.append({
        "row": i, "product_id": f"DM-{i:03d}", "title": f"东米测试商品 {i:03d}", "category": "中性笔",
        "brand": "东米", "validation": "通过", "execution": "已入库，图片已核验", "notice": f"提交成功 商品ID: 108840000000{i}",
        "errors": [], "main_count": 5, "portrait_count": 0, "detail_count": 8, "sku_count": 4,
        "pack": f"D:/工作空间/DM-{i:03d}", "pack_found": True, "taobao_item_id": f"108840000000{i}",
        "view_url": "https://item.taobao.com/item.htm?id=10884000000",
        "edit_url": "https://item.taobao.com/item.htm?id=10884000000&edit=1",
        "flow_stage": "complete", "sku_image_strategy": "slim_material",
    })

JOB = {
    "status": "idle", "phase": "", "blocker": "", "message": "",
    "current_row": 0, "current_id": "", "done": 8, "total": 8,
    "workbook_path": "D:/工作空间/商品清单.xlsx", "workspace_path": "D:/工作空间",
    "result_xlsx": "", "result_json": "",
    "valid": 8, "failed": 0, "pending": 0, "can_resume": False, "restored": True, "count": 8,
    "rows": ROWS, "logs": [],
}
WORKSPACE = {
    "path": "D:/工作空间", "workbook_path": "D:/工作空间/商品清单.xlsx",
    "defaults": {"brand": "东米", "attributes_template": "中性笔", "logistics_template": "48小时",
                 "sales_template": "仓库多规格", "price": 9.9, "stock": 20},
    "registry": {"attributes": ["中性笔"], "logistics": ["48小时"], "sales": ["仓库多规格"]},
    "scan": {"root": "D:/工作空间", "categories": []},
}


def handle(route):
    path = route.request.url.split("4173")[-1].split("?")[0]
    if path == "/api/status":
        route.fulfill(status=200, content_type="application/json",
                      body=json.dumps({"chrome": CHROME_STATUS, "job": JOB, "workspace": WORKSPACE, "settings": SETTINGS}))
    else:
        route.fulfill(status=200, content_type="application/json", body=json.dumps({"ok": True}))


def main():
    exe = os.path.expandvars(r"%LOCALAPPDATA%\ms-playwright\chromium-1234\chrome-win64\chrome.exe")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=exe)
        # 用与用户接近的窗口高度，弹窗限高 100dvh-2rem
        page = browser.new_page(viewport={"width": 1600, "height": 860})
        page.route("**/api/**", handle)
        page.goto(BASE)
        page.wait_for_selector("text=卖家中心已登录", timeout=10000)
        page.wait_for_timeout(500)

        page.get_by_role("button", name="执行", exact=True).click()
        page.wait_for_selector("text=实时步骤", timeout=5000)
        page.get_by_role("button", name="查看执行明细").click()
        page.wait_for_selector("text=共 8 条", timeout=5000)
        page.wait_for_timeout(300)

        box = page.locator(".data-table-scroll")
        metrics = box.evaluate(
            "el => ({scrollHeight: el.scrollHeight, clientHeight: el.clientHeight, scrollTop: el.scrollTop})"
        )
        print("before:", metrics)
        assert metrics["scrollHeight"] > metrics["clientHeight"], (
            f"内容应超出可视高度才会出现滚动 (scrollHeight={metrics['scrollHeight']}, clientHeight={metrics['clientHeight']})"
        )

        # 旧实现 overflow-y-hidden 时该值为 hidden；新实现应为 auto
        overflow_y = box.evaluate("el => getComputedStyle(el).overflowY")
        print("overflow-y:", overflow_y)
        assert overflow_y == "auto", f"overflow-y 应为 auto，实际 {overflow_y}"

        box.evaluate("el => el.scrollTo(el.scrollHeight, el.scrollHeight)")
        page.wait_for_timeout(300)
        after = box.evaluate("el => ({scrollTop: el.scrollTop, scrollHeight: el.scrollHeight, clientHeight: el.clientHeight})")
        print("after:", after)
        assert after["scrollTop"] > 0, "滚动后 scrollTop 应大于 0"

        last_row = page.locator("tr", has_text="DM-008")
        assert last_row.is_visible(), "滚动到底后最后一行应可见"
        print("最后一行 DM-008 可见 ✓")

        page.screenshot(path=os.path.join(OUT, "dialog-scroll-top.png"))
        box.evaluate("el => el.scrollTo(0, 0)")
        page.wait_for_timeout(200)
        page.screenshot(path=os.path.join(OUT, "dialog-scroll-bottom.png"))
        browser.close()
        print("PASS: 明细弹窗纵向可滚动")


if __name__ == "__main__":
    main()
