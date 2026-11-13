"""真实页面验收：执行入库主表的行选中、操作隔离、分页筛选与主图预览。

本脚本沿用 ``test_acceptance_clear_batch.py`` 的启动方式：

* ``QIANNIU_APPDATA`` 使用临时目录；
* 启动真实 ``desktop.server``，加载已构建的 ``desktop/ui/dist``；
* Playwright 使用项目内置的浏览器解析；
* 商品行和图片包均为临时内存/目录数据，不点击“开始入库”，不上传。

验收还会真实请求 ``/api/item/preview``，确认图片包中的 ``主图01`` 能显示，
并确认预览地址返回 404 时列表回退为“暂无主图预览”。
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
import threading
import time
import unittest
from unittest import mock
import urllib.request
from pathlib import Path

_ACCEPT_DIR = Path(tempfile.mkdtemp(prefix="qianniu-accept-run-table-"))
_WORKSPACE_DIR = _ACCEPT_DIR / "workspace"
_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
_PREVIEW_PACK = _WORKSPACE_DIR / "预览商品-02"
_PREVIEW_PACK.mkdir(parents=True, exist_ok=True)
_MISSING_PACK = _WORKSPACE_DIR / "缺失商品-03"
_MISSING_PACK.mkdir(parents=True, exist_ok=True)

# 1x1 PNG，仅作为临时图片包素材，不代表任何真实商品。
_ONE_PIXEL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)
(_PREVIEW_PACK / "主图01.png").write_bytes(_ONE_PIXEL_PNG)

os.environ["QIANNIU_APPDATA"] = str(_ACCEPT_DIR)
os.environ.pop("QIANNIU_PORT", None)

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from desktop import license as license_module  # noqa: E402
from desktop import server as desktop_server  # noqa: E402
from desktop.jobs import MANAGER, serialize_row  # noqa: E402
from desktop.paths import browser_exe_path  # noqa: E402


def _preview_path(row: int, product_id: str) -> str:
    # 组件会通过 api.previewUrl() 加 API base；本地桌面页面的 base 为空。
    return f"/api/item/preview?row={row}&product_id={product_id}"


def _row(index: int, *, preview_url: str = "", view_url: str = "") -> dict:
    product_id = f"验收-{index:02d}"
    execution = "已入库" if index == 10 else "未执行"
    return {
        "row": index,
        "product_id": product_id,
        "title": f"执行入库验收商品 {index:02d}",
        "category": "",
        "brand": "",
        "validation": "通过",
        "execution": execution,
        "notice": "",
        "errors": [],
        "main_count": 1 if index == 2 else 0,
        "portrait_count": 0,
        "detail_count": 0,
        "sku_count": 0,
        "pack": "",
        "pack_found": index in {2, 3},
        "preview_url": preview_url,
        "taobao_item_id": "100000000010" if index == 10 else "",
        "view_url": view_url,
        "edit_url": "",
        "flow_stage": "created" if index == 10 else "pending",
        "duration_seconds": None,
    }


def _product(index: int) -> dict:
    product_id = f"验收-{index:02d}"
    if index == 2:
        pack_dir = _PREVIEW_PACK
        main_images = [str(pack_dir / "主图01.png")]
    elif index == 3:
        # 有地址但包里没有主图：接口会 404，供 onError 回退验收。
        pack_dir = _MISSING_PACK
        main_images = []
    else:
        pack_dir = _WORKSPACE_DIR / f"商品-{index:02d}"
        pack_dir.mkdir(parents=True, exist_ok=True)
        main_images = []
    return {
        "product_id": product_id,
        "title": f"执行入库验收商品 {index:02d}",
        "pack_dir": str(pack_dir),
        "main_images": main_images,
        "portrait_images": [],
        "detail_images": [],
        "skus": [],
    }


def _seed_rows() -> tuple[list[dict], list[dict]]:
    rows: list[dict] = []
    products: list[dict] = []
    for index in range(1, 11):
        product_id = f"验收-{index:02d}"
        preview_url = ""
        view_url = ""
        if index == 2:
            preview_url = _preview_path(index, product_id)
            view_url = "https://example.invalid/item/100000000002"
        elif index == 3:
            preview_url = _preview_path(index, product_id)
        product = _product(index)
        meta = _row(index, preview_url=preview_url, view_url=view_url)
        row = serialize_row({**meta, "product": product})
        if index == 2:
            row["view_url"] = view_url
        elif index == 3:
            # 模拟展示后主图被移除的旧地址，验证 img 的失败回退。
            row["preview_url"] = preview_url
        rows.append(row)
        products.append({"product": product, "meta": meta})
    return rows, products


class AcceptanceRunTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ["QIANNIU_APPDATA"] = str(_ACCEPT_DIR)

        # 仅在本验收进程内放行授权门禁。
        license_module.is_activated = lambda: True
        license_module.require_activated = lambda: None
        login_check = mock.patch.object(MANAGER, "begin_login_check", return_value=False)
        login_check.start()
        cls.addClassCleanup(login_check.stop)
        chrome_status = mock.patch.object(MANAGER, "chrome_status", return_value={"chrome_found": True, "logged_in": False, "cdp": False, "checking": False, "browser_source": "bundled"})
        chrome_status.start()
        cls.addClassCleanup(chrome_status.stop)
        license_module.state = lambda: {
            "activated": True,
            "machine_code": "",
            "expires_at": 0,
            "memo": "acceptance",
            "days_left": None,
            "issue": "",
        }

        rows, products = _seed_rows()
        MANAGER._restored = True
        MANAGER.status = "idle"
        MANAGER.rows = rows
        MANAGER.products = products
        MANAGER.workspace_path = str(_WORKSPACE_DIR)
        MANAGER.workbook_path = ""
        MANAGER.result_xlsx = ""
        MANAGER.result_json = ""
        MANAGER.blocker = ""
        MANAGER.message = ""
        MANAGER.phase = ""
        MANAGER.active_worker_events = {}

        cls.port = desktop_server.pick_free_port()
        cls.thread = threading.Thread(
            target=desktop_server.run_server,
            args=(cls.port,),
            daemon=True,
        )
        cls.thread.start()
        deadline = time.time() + 15
        while time.time() < deadline:
            try:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{cls.port}/api/health", timeout=1
                ) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.2)
        else:
            raise RuntimeError("验收服务未能在 15 秒内启动")

        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch(
            headless=True,
            executable_path=str(browser_exe_path()),
        )
        cls.page = cls.browser.new_page(viewport={"width": 1440, "height": 900})
        cls.page.route(
            "**/api/item/open",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": True, "url": "https://example.invalid/"}),
            ),
        )
        cls.addClassCleanup(cls.playwright.stop)
        cls.addClassCleanup(cls.browser.close)
        cls.page.goto(f"http://127.0.0.1:{cls.port}/", wait_until="domcontentloaded")
        cls.page.get_by_role("button", name="执行入库").click()
        expect(cls.page.get_by_role("table", name="商品执行列表")).to_be_visible(timeout=10000)

    @classmethod
    def tearDownClass(cls):
        # 保留一张可供人工复核的 1440x900 现场截图。
        output = Path("output/playwright/acceptance-run-table")
        output.mkdir(parents=True, exist_ok=True)
        cls.page.screenshot(path=str(output / "run-table-1440x900.png"), full_page=False)

    def setUp(self):
        # 重载前端状态，使各用例的选择集合互不影响；服务与临时数据继续复用。
        page = self.page
        page.evaluate("sessionStorage.clear()")
        page.reload(wait_until="domcontentloaded")
        page.get_by_role("button", name="执行入库").click()
        expect(self._table()).to_be_visible()

    def _table(self):
        return self.page.get_by_role("table", name="商品执行列表")

    def _row(self, product_id: str):
        return self._table().locator("tbody tr").filter(has_text=product_id).first

    def test_row_click_and_checkbox_each_toggle_once(self):
        row = self._row("验收-02")
        checkbox = row.locator("input[type='checkbox']")
        expect(checkbox).not_to_be_checked()

        # 点击商品信息单元格切换整行；第二次点击应切回未选中。
        row.locator("td").nth(1).click()
        expect(checkbox).to_be_checked()
        expect(row).to_have_attribute("data-selected", "true")
        row.locator("td").nth(1).click()
        expect(checkbox).not_to_be_checked()
        expect(row).to_have_attribute("data-selected", "false")

        # 直接点 checkbox 只触发一次 toggle，不会被 tr click 再反向抵消。
        checkbox.click()
        expect(checkbox).to_be_checked()
        checkbox.click()
        expect(checkbox).not_to_be_checked()

        row.focus()
        row.press("Space")
        expect(checkbox).to_be_checked()
        row.press("Enter")
        expect(checkbox).not_to_be_checked()

    def test_actions_do_not_select_row(self):
        row = self._row("验收-02")
        checkbox = row.locator("input[type='checkbox']")
        expect(checkbox).not_to_be_checked()

        # “查看”只验证操作事件与选择隔离；接口响应在本地拦截，不打开外部浏览器。
        with self.page.expect_response(
            lambda response: response.url.endswith("/api/item/open")
            and response.request.method == "POST"
        ) as response_info:
            row.get_by_role("button", name="查看商品 验收-02").click()
        self.assertEqual(response_info.value.status, 200)
        expect(checkbox).not_to_be_checked()

        # 详情弹窗同样不能改变主表的选中状态。
        row.get_by_role("button", name="详情 验收-02").click()
        dialog = self.page.get_by_role("dialog", name="商品详情", exact=True)
        expect(dialog).to_be_visible()
        expect(checkbox).not_to_be_checked()
        self.page.get_by_role("button", name="关闭商品详情").click()
        expect(dialog).to_be_hidden()

    def test_pagination_and_filters_preserve_selection(self):
        first = self._row("验收-02")
        first.locator("input[type='checkbox']").click()
        expect(first.locator("input[type='checkbox']")).to_be_checked()

        next_page = self.page.get_by_role("button", name="下一页商品")
        self.assertFalse(next_page.is_disabled(), "10 条临时数据应至少产生两页")
        next_page.click()
        expect(self.page.get_by_text(re.compile(r"已选\s*1\s*件")).first).to_be_visible()
        expect(self._row("验收-02")).to_have_count(0)

        # 状态筛选会隐藏被选行，但不得清空选择集合。
        completed = self.page.locator(
            '[role="group"][aria-label="筛选商品状态"]'
        ).get_by_role("button", name=re.compile(r"^已完成"))
        completed.click()
        expect(self._row("验收-02")).to_have_count(0)
        expect(self.page.get_by_text(re.compile(r"已选\s*1\s*件")).first).to_be_visible()

        self.page.locator(
            '[role="group"][aria-label="筛选商品状态"]'
        ).get_by_role("button", name=re.compile(r"^全部")).click()
        self.page.get_by_role("button", name="第 1 页商品").click()
        expect(self._row("验收-02").locator("input[type='checkbox']")).to_be_checked()

        # 搜索过滤同样保留选择，清空后可恢复原选中行。
        search = self.page.get_by_role("textbox", name="搜索商品名称或 ID")
        search.fill("验收-09")
        expect(self._row("验收-09")).to_be_visible()
        expect(self._row("验收-02")).to_have_count(0)
        expect(self.page.get_by_text(re.compile(r"已选\s*1\s*件")).first).to_be_visible()
        search.fill("")
        expect(self._row("验收-02").locator("input[type='checkbox']")).to_be_checked()

    def test_preview_main_image_and_missing_fallback(self):
        page = self.page
        valid = self._row("验收-02")
        image = valid.locator("img[alt*='主图预览']")
        expect(image).to_be_visible()
        expect(image).to_have_js_property("complete", True)
        self.assertTrue(
            image.evaluate("node => node.complete && node.naturalWidth > 0"),
            "主图01 预览接口应返回浏览器可解码的图片",
        )
        self.assertEqual(image.get_attribute("src"), MANAGER.rows[1]["preview_url"])

        # 该地址对应空图片包，接口 404 后组件应显示明确的回退图标。
        missing = self._row("验收-03")
        fallback = missing.locator('[role="img"][aria-label="暂无主图预览"]')
        expect(fallback).to_be_visible(timeout=5000)
        expect(missing.locator("img")).to_have_count(0)

        # 同时记录接口边界：有效包 200，缺失包 404，均为只读请求。
        good_response = page.request.get(
            f"http://127.0.0.1:{self.port}{image.get_attribute('src')}"
        )
        self.assertEqual(good_response.status, 200)
        self.assertIn("image/", good_response.headers.get("content-type", ""))
        missing_response = page.request.get(
            f"http://127.0.0.1:{self.port}{_preview_path(3, '验收-03')}"
        )
        self.assertEqual(missing_response.status, 404)

        stale_response = page.request.get(
            f"http://127.0.0.1:{self.port}{_preview_path(2, '验收-02')}&v=obsolete"
        )
        self.assertEqual(stale_response.status, 409)
        wrong_product = page.request.get(
            f"http://127.0.0.1:{self.port}{_preview_path(2, 'wrong-product')}"
        )
        self.assertEqual(wrong_product.status, 404)


if __name__ == "__main__":
    unittest.main()
