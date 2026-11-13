"""暂停快速生效：cancel_event 置位时中断在跑的 CLI 调用并快速失败后续命令。

真实场景：单个 JS 阶段脚本最长 300 秒超时，滑块挡页时脚本内部每个元素
操作各烧一次超时，旧实现"等当前操作结束"让暂停最坏拖延数分钟。中断后
页面停在当下现场（与滑块硬暂停同构），由既有断点/服务器状态复核兜底。
"""

import shutil
import subprocess
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import 千牛网页执行 as qne
from web_fill import pipeline as p


def _stub_cli(script):
    return [sys.executable, "-c", script]


class PauseInterruptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_pause_interrupt_tmp"
        self.session = qne.CliSession(output_dir=self.tmp)
        self.session.cancel_event = threading.Event()

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_interrupts_in_flight_command_quickly(self):
        with patch.object(qne, "cli_executable", return_value=_stub_cli(
                "import time; print('x', flush=True); time.sleep(30)")):
            timer = threading.Timer(0.6, self.session.cancel_event.set)
            timer.start()
            begin = time.monotonic()
            with self.assertRaises(qne.CliInterrupted) as ctx:
                self.session._raw_cmd("eval", "() => 1", timeout=60)
            elapsed = time.monotonic() - begin
        timer.cancel()
        self.assertTrue(self.session._interrupted)
        self.assertIn("PAUSE:用户已暂停", str(ctx.exception))
        self.assertLess(elapsed, 10, f"中断耗时 {elapsed:.1f}s，暂停应当秒级生效")

    def test_interrupted_session_fail_fast_until_cancel_cleared(self):
        calls = []

        def fake_cli():
            calls.append(1)
            return _stub_cli("print('ok')")

        self.session.cancel_event.set()
        with patch.object(qne, "cli_executable", fake_cli):
            # cancel 已置位：sleep 桩活不过首个 0.2s 轮询窗口，即被中断。
            with patch.object(qne, "cli_executable", return_value=_stub_cli("import time; time.sleep(30)")):
                with self.assertRaises(qne.CliInterrupted):
                    self.session._raw_cmd("eval", "() => 1", timeout=15)
            self.assertTrue(self.session._interrupted)
            # 中断后：后续命令快速失败，不再拉起新的 CLI 进程。
            before = len(calls)
            with self.assertRaises(qne.CliInterrupted):
                self.session._raw_cmd("eval", "() => 1", timeout=15)
            self.assertEqual(len(calls), before)
            # 下一次任务重设 cancel_event（未置位）后自动解除。
            self.session.cancel_event = threading.Event()
            self.assertEqual(self.session._raw_cmd("eval", "() => 1", timeout=15).strip(), "ok")
            self.assertFalse(self.session._interrupted)

    def test_cancel_path_still_returns_normal_output_and_timeout(self):
        with patch.object(qne, "cli_executable", return_value=_stub_cli("print('ok')")):
            self.assertEqual(self.session._raw_cmd("eval", "() => 1", timeout=15).strip(), "ok")
        with patch.object(qne, "cli_executable", return_value=_stub_cli("import time; time.sleep(30)")):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.session._raw_cmd("eval", "() => 1", timeout=1)
        self.assertFalse(self.session._interrupted)

    def test_global_blocker_reason_interrupt_message(self):
        class Blocker:
            reason = "断点保存失败"

            @staticmethod
            def is_set():
                return True

        self.session.cancel_event = Blocker()
        with patch.object(qne, "cli_executable", return_value=_stub_cli("import time; time.sleep(30)")):
            with self.assertRaises(qne.CliInterrupted) as ctx:
                self.session._raw_cmd("eval", "() => 1", timeout=15)
        self.assertIn("断点保存失败", str(ctx.exception))
        self.assertNotIn("用户已暂停", str(ctx.exception))

    def test_run_script_converts_timeout_expired_to_runtime_error(self):
        """run-code 整段超时（冻结页面烧穿 verify 预算）必须归一为 RuntimeError
        并落 raw.txt：TimeoutExpired 原样穿透会绕过诊断与失败文本分类。"""
        with patch.object(qne, "cli_executable", return_value=_stub_cli("import time; time.sleep(30)")), \
             patch.object(p, "_ensure_automation_front"), \
             patch.dict("os.environ", {"QIANNIU_OUTPUT_DIR": str(self.tmp)}):
            with self.assertRaises(RuntimeError) as ctx:
                p.run_script(self.session, "sku_import.js", {"phase": "verify"}, timeout=1)
        self.assertIn("timed out after 1 seconds", str(ctx.exception))
        raw = (self.tmp / "web_fill_sku_import.raw.txt").read_text(encoding="utf-8")
        self.assertIn("timed out after 1 seconds", raw)


class PauseClassificationTests(unittest.TestCase):
    def test_gate_does_not_retry_user_pause_or_refuse(self):
        self.assertFalse(p.gate_error_retryable(qne.CliInterrupted()))
        self.assertFalse(p.gate_error_retryable(RuntimeError("PAUSE:用户已暂停；保留现场")))
        self.assertFalse(p.gate_error_retryable(RuntimeError("REFUSE: 危险操作被拒绝")))
        self.assertTrue(p.gate_error_retryable(RuntimeError("TimeoutError: 超时")))

    def test_item_retry_rejects_user_pause_notice(self):
        self.assertFalse(p.item_retryable_notice("用户已暂停；已中断当前页面操作并保留现场"))
        self.assertTrue(p.item_retryable_notice("TimeoutError: scrollIntoViewIfNeeded 超时"))


if __name__ == "__main__":
    unittest.main()
