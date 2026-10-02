"""桌面端离线激活：签发/校验闭环 + 失效原因诊断（state().issue 与 license.log）。"""

import base64
import hashlib
import importlib
import json
import os
import tempfile
import time
import unittest
import unittest.mock
from pathlib import Path

from desktop import license as lic


class LicenseStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.appdata = Path(self.temp.name)
        os.environ["QIANNIU_APPDATA"] = str(self.appdata)
        self.addCleanup(os.environ.pop, "QIANNIU_APPDATA", None)
        importlib.reload(lic)
        self.addCleanup(importlib.reload, lic)
        # 用一次性测试密钥替换内置公钥，测试不依赖开发者私钥
        self.seed = os.urandom(32)
        public_b64 = base64.b64encode(lic.ed25519_public_key(self.seed)).decode()
        patcher = unittest.mock.patch.object(lic, "PUBLIC_KEY_B64", public_b64)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _save_license(self, code: str, last_seen: float | None = None) -> None:
        path = lic.license_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"code": lic.normalize_code(code), "last_seen": last_seen or time.time()}),
            encoding="utf-8",
        )

    def _code(self, fp: str, exp: int = 0, memo: str = "测试") -> str:
        return lic.build_code({"v": 1, "fp": fp, "exp": exp, "memo": memo}, self.seed)

    def test_activate_roundtrip_and_reboot(self):
        code = self._code(lic._fingerprint(lic.machine_code()))
        state = lic.activate(code)
        self.assertTrue(state["activated"])
        self.assertEqual(state["memo"], "测试")
        self.assertEqual(lic.state()["issue"], "")
        # 模拟重新打开软件：缓存清空后从 license.json 重新校验
        lic._reset_cache()
        self.assertTrue(lic.is_activated())
        self.assertEqual(lic.state()["issue"], "")

    def test_missing_license_reports_no_issue(self):
        self.assertFalse(lic.is_activated())
        self.assertEqual(lic.state()["issue"], "")

    def test_machine_mismatch_explains_reason(self):
        self._save_license(self._code("0123456789ABCDEF", memo="别机"))
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        issue = lic.state()["issue"]
        self.assertIn("不匹配", issue)
        self.assertIn("0123-4567-89AB-CDEF", issue)
        self.assertIn(lic.machine_code(), issue)
        log = (self.appdata / "logs" / "license.log").read_text(encoding="utf-8")
        self.assertIn("不匹配", log)

    def test_corrupt_license_explains_reason(self):
        path = lic.license_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{broken", encoding="utf-8")
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("损坏", lic.state()["issue"])

    def test_expired_license_explains_reason(self):
        self._save_license(self._code(lic._fingerprint(lic.machine_code()), exp=int(time.time()) - 10))
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("过期", lic.state()["issue"])

    def test_wrong_key_license_explains_reason(self):
        wrong_seed = os.urandom(32)
        code = lic.build_code({"v": 1, "fp": lic._fingerprint(lic.machine_code()), "exp": 0, "memo": "x"}, wrong_seed)
        self._save_license(code)
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("激活码无效", lic.state()["issue"])

    def test_issue_cleared_after_reactivate(self):
        self._save_license(self._code("0123456789ABCDEF", memo="别机"))
        lic._reset_cache()
        self.assertIn("不匹配", lic.state()["issue"])
        lic.activate(self._code(lic._fingerprint(lic.machine_code()), memo="重新激活"))
        self.assertEqual(lic.state()["issue"], "")


class LicenseGateTests(unittest.TestCase):
    """FastAPI 中间件门禁：未激活业务接口 403，健康检查与激活接口放行。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["QIANNIU_APPDATA"] = str(Path(self.temp.name))
        self.addCleanup(os.environ.pop, "QIANNIU_APPDATA", None)
        importlib.reload(lic)
        self.addCleanup(importlib.reload, lic)
        from desktop.server import app

        self.app = app

    def test_gate_blocks_until_activated(self):
        from fastapi.testclient import TestClient

        client = TestClient(self.app)
        self.assertEqual(client.get("/api/status").status_code, 403)
        self.assertEqual(client.get("/api/health").status_code, 200)
        status = client.get("/api/license/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["activated"])

        with unittest.mock.patch("desktop.license.is_activated", return_value=True):
            self.assertEqual(client.get("/api/status").status_code, 200)


class MachineCodeStabilityTests(unittest.TestCase):
    """机器码派生：主公式绑定 MachineGuid；降级公式不得依赖 MAC/主机名。"""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        os.environ["QIANNIU_APPDATA"] = str(Path(self.temp.name))
        self.addCleanup(os.environ.pop, "QIANNIU_APPDATA", None)
        importlib.reload(lic)
        self.addCleanup(importlib.reload, lic)
        self.seed = os.urandom(32)
        public_b64 = base64.b64encode(lic.ed25519_public_key(self.seed)).decode()
        patcher = unittest.mock.patch.object(lic, "PUBLIC_KEY_B64", public_b64)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_guid_path_formula_pinned(self):
        # 契约固定：MachineGuid 机器的激活码跨版本永不漂移
        with unittest.mock.patch.object(lic, "_machine_guid", return_value="TEST-GUID"):
            code = lic.machine_code()
        digest = hashlib.sha256("qianniu-license-v1|guid|TEST-GUID".encode()).hexdigest()[:16].upper()
        self.assertEqual(code, "-".join(digest[i : i + 4] for i in range(0, 16, 4)))

    def test_fallback_ignores_mac_and_hostname(self):
        # 回归：降级公式曾用 MAC+主机名，网络/重启后机器码漂移导致重新激活
        patches = [
            unittest.mock.patch.object(lic, "_machine_guid", return_value=""),
            unittest.mock.patch.object(lic, "_product_id", return_value="PID-123"),
            unittest.mock.patch.object(lic, "_volume_serial", return_value="AABBCCDD"),
            unittest.mock.patch("uuid.getnode", side_effect=[0x0A0B0C0D0E0F, 0x1122334455]),
            unittest.mock.patch("platform.node", side_effect=["OLD-PC", "NEW-PC"]),
        ]
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            first = lic.machine_code()
            second = lic.machine_code()
        self.assertEqual(first, second)

        with patches[0], patches[1], unittest.mock.patch.object(lic, "_volume_serial", return_value="DDEEFF00"):
            changed = lic.machine_code()
        self.assertNotEqual(first, changed)

    def test_verify_code_accepts_legacy_machine_code(self):
        # 兼容：老公式（MAC 未变）签发的激活码继续有效，避免无谓重新激活
        with unittest.mock.patch.object(lic, "machine_code", return_value="AAAA-BBBB-CCCC-DDDD"), \
             unittest.mock.patch.object(lic, "_legacy_machine_code", return_value="1111-2222-3333-4444"):
            code = lic.build_code({"v": 1, "fp": "1111222233334444", "exp": 0, "memo": "老码"}, self.seed)
            state = lic.activate(code)
            self.assertTrue(state["activated"])
            self.assertEqual(lic.state()["issue"], "")

    def test_verify_code_rejects_unknown_machine(self):
        with unittest.mock.patch.object(lic, "machine_code", return_value="AAAA-BBBB-CCCC-DDDD"), \
             unittest.mock.patch.object(lic, "_legacy_machine_code", return_value="1111-2222-3333-4444"):
            code = lic.build_code({"v": 1, "fp": "9999888877776666", "exp": 0, "memo": "别机"}, self.seed)
            with self.assertRaises(lic.LicenseError):
                lic.verify_code(code)


class KeygenHistoryTests(unittest.TestCase):
    def test_history_roundtrip_filter_and_validity(self):
        os.environ["QIANNIU_LICENSE_KEY_DIR"] = tempfile.mkdtemp()
        self.addCleanup(os.environ.pop, "QIANNIU_LICENSE_KEY_DIR", None)
        import tools.license_keygen as kg

        importlib.reload(kg)
        self.addCleanup(importlib.reload, kg)

        kg.append_history({"fp": "0123456789ABCDEF", "exp": 0, "memo": "客户A"}, "CODE-1", 0)
        kg.append_history({"fp": "1111222233334444", "exp": int(time.time()) + 86400, "memo": "客户B"}, "CODE-2", 365)
        records = kg.load_history()
        self.assertEqual([rec["memo"] for rec in records], ["客户A", "客户B"])
        self.assertIn("CODE-1", records[0]["code"])
        self.assertEqual(kg.validity_text(records[0]), "永久")
        self.assertTrue(kg.validity_text(records[1]).startswith("到期 "))
        self.assertEqual(len(kg.filter_history(records, "客户b")), 1)
        self.assertEqual(kg.filter_history(records, "0123")[0]["memo"], "客户A")
        self.assertEqual(kg.filter_history(records, ""), records)


if __name__ == "__main__":
    unittest.main()
