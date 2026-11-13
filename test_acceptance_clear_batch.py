"""真实页面验收：执行明细的状态筛选、搜索与一键清除。

启动真实 FastAPI 服务（desktop.server）与打包后的前端（desktop/ui/dist），
用 Playwright 驱动浏览器验证：
- 状态筛选（全部/需处理/已入库/未执行）带数量徽章；
- 按商品名/ID/淘宝 ID 搜索；
- 一键清除全部与清除筛选记录（确认弹窗、已入库风险提示、成功 Toast）；
- 任务运行中清除按钮禁用；
- 清除后 job_session.json 落盘（rows 重置、保留清除标记，旧商品 ID 不再恢复）。

会话目录 QIANNIU_APPDATA 指向临时目录，不会影响本机真实会话；
授权门禁在本验收进程内放行（仅作用于该进程，不改变产品逻辑）。
"""

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

_ACCEPT_DIR = tempfile.mkdtemp(prefix="qianniu-accept-clear-")
os.environ["QIANNIU_APPDATA"] = _ACCEPT_DIR
os.environ.pop("QIANNIU_PORT", None)

from playwright.sync_api import expect, sync_playwright  # noqa: E402

from desktop import license as license_module  # noqa: E402
from desktop import server as desktop_server  # noqa: E402
from desktop.jobs import MANAGER  # noqa: E402
from desktop.paths import browser_exe_path  # noqa: E402

# 筛选 pill 的可访问名 = 标签 + 数量（组件内无空白节点，容错 \s*）。
# 晨光-001（失败但有商品 ID、flow_stage=created）同时计入"需处理"与"已入库"。
PILL_ALL = re.compile(r"全部\s*5$")
PILL_ATTENTION = re.compile(r"需关注\s*2$")
PILL_WAREHOUSED = re.compile(r"已入库\s*2$")
PILL_IDLE = re.compile(r"未执行\s*1$")


def _seed_rows():
    """一组覆盖各状态的校验通过商品：需处理 2、已入库 1、进行中 1、未执行 1。"""
    return [
        {
            "row": 2, "product_id": "晨光-001", "title": "晨光中性笔 2505 萌宠小狗按动款",
            "validation": "通过", "execution": "失败", "last_error": "上传失败", "errors": ["上传失败"],
            "taobao_item_id": "1087608952245", "flow_stage": "created", "duration_seconds": 12.5,
        },
        {
            "row": 3, "product_id": "晨光-002", "title": "晨光中性笔 宝特瓶 932S 大容量",
            "validation": "通过", "execution": "已入库", "taobao_item_id": "1087608952246",
            "flow_stage": "complete", "duration_seconds": 30.0,
        },
        {
            "row": 4, "product_id": "晨光-003", "title": "晨光中性笔 HelloKitty 苹果派对",
            "validation": "通过", "execution": "已填写未提交", "flow_stage": "filled", "duration_seconds": 20.0,
        },
        {
            "row": 5, "product_id": "晨光-004", "title": "晨光中性笔 直液式走珠君",
            "validation": "通过", "execution": "提交待核实", "flow_stage": "submit_pending",
        },
        {
            "row": 6, "product_id": "晨光-005", "title": "晨光中性笔 优品经济装",
            "validation": "通过", "execution": "未执行",
        },
    ]


def _seed_products(rows):
    return [{"product": {"product_id": row["product_id"]}, "meta": dict(row)} for row in rows]


class AcceptanceClearBatchTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 前序测试类可能改写或移除 QIANNIU_APPDATA，这里重新指向隔离目录。
        os.environ["QIANNIU_APPDATA"] = _ACCEPT_DIR
        cls.addClassCleanup(os.environ.pop, "QIANNIU_APPDATA", None)
        # 授权门禁只在本验收进程内放行，不影响产品逻辑与其他进程。
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
        MANAGER._restored = True
        MANAGER.status = "idle"
        MANAGER.rows = _seed_rows()
        MANAGER.products = _seed_products(MANAGER.rows)
        cls.port = desktop_server.pick_free_port()
        cls.thread = threading.Thread(
            target=desktop_server.run_server, args=(cls.port,), daemon=True
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
        # 复用项目自带的浏览器解析（自定义 → 随包 → 系统 Chrome）。
        cls.browser = cls.playwright.chromium.launch(
            headless=True, executable_path=str(browser_exe_path())
        )
        cls.page = cls.browser.new_page(viewport={"width": 1440, "height": 900})
        cls.addClassCleanup(cls.playwright.stop)
        cls.addClassCleanup(cls.browser.close)
        cls.page.goto(f"http://127.0.0.1:{cls.port}/")

    def _open_detail_dialog(self):
        page = self.page
        page.get_by_role("button", name="执行入库", exact=True).click()
        page.get_by_role("button", name="查看执行明细").click()
        return page.locator('[aria-labelledby="data-table-dialog-title"]')

    def test_filter_search_and_batch_clear_flow(self):
        page = self.page
        dialog = self._open_detail_dialog()

        # 筛选 pills 与数量：全部 5 / 需处理 2 / 已入库 2 / 未执行 1。
        expect(dialog.get_by_role("button", name=PILL_ALL)).to_be_visible()
        expect(dialog.get_by_role("button", name=PILL_ATTENTION)).to_be_visible()
        expect(dialog.get_by_role("button", name=PILL_WAREHOUSED)).to_be_visible()
        expect(dialog.get_by_role("button", name=PILL_IDLE)).to_be_visible()
        expect(dialog.get_by_role("button", name="一键清除全部")).to_be_visible()

        # 需处理筛选：2 行，按钮变为"清除筛选记录(2)"。
        dialog.get_by_role("button", name=PILL_ATTENTION).click()
        expect(dialog.locator("tbody tr")).to_have_count(2)
        expect(dialog.get_by_role("button", name="清除筛选记录(2)")).to_be_visible()

        # 搜索叠加筛选：需处理里没有 002，应显示空态文案。
        search = dialog.get_by_role("textbox", name="搜索执行明细")
        search.fill("002")
        expect(dialog.get_by_text("没有符合筛选条件的记录")).to_be_visible()

        # 搜索在"全部"下按标题匹配。
        dialog.get_by_role("button", name=PILL_ALL).click()
        search.fill("932S")
        expect(dialog.locator("tbody tr")).to_have_count(1)
        expect(dialog.get_by_text("晨光-002")).to_be_visible()
        search.fill("")

        # 清除筛选记录（已入库 2 行）：确认弹窗含重复建档警示。
        dialog.get_by_role("button", name=PILL_WAREHOUSED).click()
        expect(dialog.locator("tbody tr")).to_have_count(2)
        dialog.get_by_role("button", name="清除筛选记录(2)").click()
        confirm = page.locator('[aria-labelledby="confirm-dialog-title"]')
        expect(confirm).to_be_visible()
        expect(confirm.get_by_role("button", name="取消", exact=True)).to_be_focused()
        expect(confirm.get_by_text("其中 2 条已入库")).to_be_visible()
        expect(confirm.get_by_text("可能产生重复商品")).to_be_visible()
        confirm.get_by_role("button", name="清除", exact=True).click()
        expect(page.get_by_text("已清除 2 条执行记录")).to_be_visible()
        # 已入库行清空后，当前筛选下无记录。
        expect(dialog.get_by_text("没有符合筛选条件的记录")).to_be_visible()

        # 一键清除全部：重新播种后清除其余 4 条有记录的行（未执行行不计入）。
        MANAGER.rows = _seed_rows()
        MANAGER.products = _seed_products(MANAGER.rows)
        dialog.get_by_role("button", name=PILL_ALL).click()
        expect(dialog.get_by_role("button", name="一键清除全部")).to_be_enabled()
        dialog.get_by_role("button", name="一键清除全部").click()
        confirm = page.locator('[aria-labelledby="confirm-dialog-title"]')
        expect(confirm.get_by_text("确定要清除 4 条执行记录吗？")).to_be_visible()
        confirm.get_by_role("button", name="清除", exact=True).click()
        expect(page.get_by_text("已清除 4 条执行记录")).to_be_visible()
        expect(dialog.locator("tbody tr")).to_have_count(5)
        expect(
            dialog.locator("tbody tr").filter(has_text="晨光-001").get_by_text("未执行")
        ).to_be_visible()
        expect(dialog.get_by_role("button", name="一键清除全部")).to_be_disabled()

        # 会话落盘：rows 重置为未执行，历史只保留清除标记而不含旧商品 ID。
        session = json.loads(
            (Path(_ACCEPT_DIR) / "job_session.json").read_text(encoding="utf-8")
        )
        history = session.get("execution_history") or {}
        for pid in ("晨光-001", "晨光-002"):
            self.assertFalse(history[pid].get("taobao_item_id"))
            self.assertTrue(history[pid].get("execution_reset_id"))
        self.assertTrue(session.get("rows"))
        for item in session.get("rows") or []:
            self.assertEqual(item.get("execution"), "未执行")

        # 任务运行中：清除按钮全部禁用。
        MANAGER.status = "running"
        try:
            expect(dialog.get_by_role("button", name="一键清除全部")).to_be_disabled()
            expect(
                dialog.locator("tbody tr").filter(has_text="晨光-001")
                .get_by_role("button", name="清除记录")
            ).to_be_disabled()
        finally:
            MANAGER.status = "idle"


if __name__ == "__main__":
    unittest.main()
