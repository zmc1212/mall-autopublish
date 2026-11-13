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


class LicenseServerTests(unittest.TestCase):
    """联网激活与 14 天租约：服务端签名响应、吊销、换机与离线宽限。"""

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

        self.server_seed = os.urandom(32)
        server_public = base64.b64encode(lic.ed25519_public_key(self.server_seed)).decode()
        patcher = unittest.mock.patch.object(lic, "LICENSE_SERVER_PUBLIC_KEY_B64", server_public)
        patcher.start()
        self.addCleanup(patcher.stop)
        patcher = unittest.mock.patch.object(lic, "server_url", return_value="https://license.test")
        patcher.start()
        self.addCleanup(patcher.stop)
        # 心跳线程在单测里不启动，单独调用 _heartbeat_once 验证。
        patcher = unittest.mock.patch.object(lic, "_ensure_heartbeat", lambda *a, **k: None)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.device = lic.device_id()
        self.mode = "online"
        self.status = "active"
        self.reject_message = ""
        patcher = unittest.mock.patch.object(lic, "_post", side_effect=self._post)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _code(self, exp: int = 0, memo: str = "测试") -> str:
        return lic.build_code(
            {"v": 1, "fp": lic._fingerprint(lic.machine_code()), "exp": exp, "memo": memo}, self.seed
        )

    def _envelope(self, payload: dict) -> dict:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        signature = lic.ed25519_sign(self.server_seed, body)
        return {
            "body": base64.b64encode(body).decode("ascii"),
            "sig": base64.b64encode(signature).decode("ascii"),
        }

    def _lease(self, *, device: str | None = None, not_after: int | None = None) -> dict:
        return self._envelope({
            "v": 1,
            "status": "active",
            "device_id": device or self.device,
            "machine_code": lic.machine_code(),
            "exp": 0,
            "not_after": int(time.time()) + 14 * 86400 if not_after is None else not_after,
            "lease_days": 14,
            "server_time": int(time.time()),
            "nonce": "",
        })

    def _post(self, path, payload, timeout=None):
        if self.mode == "offline":
            raise lic.LicenseServerUnreachable("offline")
        if self.mode == "reject":
            raise lic.LicenseError(self.reject_message)
        now = int(time.time())
        if path == "/v1/activate":
            return self._envelope({
                "v": 1,
                "status": self.status,
                "code_hash": "x" * 64,
                "device_id": payload["device_id"],
                "machine_code": payload.get("machine_code", ""),
                "exp": payload.get("exp", 0),
                "not_after": now + 14 * 86400 if self.status == "active" else 0,
                "lease_days": 14,
                "server_time": now,
                "nonce": "",
            })
        if path == "/v1/heartbeat":
            return self._envelope({
                "v": 1,
                "status": self.status,
                "code_hash": "x" * 64,
                "device_id": payload["device_id"],
                "machine_code": lic.machine_code(),
                "exp": 0,
                "not_after": now + 14 * 86400 if self.status == "active" else 0,
                "lease_days": 14,
                "server_time": now,
                "nonce": payload.get("nonce", ""),
            })
        raise AssertionError("unexpected path " + path)

    def _write_license(self, data: dict) -> None:
        path = lic.license_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_license(self) -> dict:
        return json.loads(lic.license_path().read_text(encoding="utf-8"))

    def test_activation_requires_network(self):
        self.mode = "offline"
        with self.assertRaises(lic.LicenseError) as caught:
            lic.activate(self._code())
        self.assertIn("联网", str(caught.exception))
        self.assertFalse(lic.license_path().exists())

    def test_activation_saves_signed_lease_and_survives_restart(self):
        state = lic.activate(self._code())
        self.assertTrue(state["activated"])
        self.assertGreater(state["offline_until"], time.time())
        data = self._read_license()
        self.assertIn("lease", data)
        self.assertEqual(data["device"], self.device)
        # 模拟重新打开软件：断网也能在宽限期内继续使用
        self.mode = "offline"
        lic._reset_cache()
        self.assertTrue(lic.is_activated())

    def test_tampered_lease_is_not_trusted(self):
        lic.activate(self._code())
        data = self._read_license()
        data["lease"]["sig"] = base64.b64encode(os.urandom(64)).decode()
        self._write_license(data)
        self.mode = "offline"
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("联网", lic.state()["issue"])

    def test_expired_lease_blocks_offline_but_renews_online(self):
        code = self._code()
        self._write_license({
            "code": lic.normalize_code(code),
            "last_seen": time.time(),
            "device": self.device,
            "lease": self._lease(not_after=int(time.time()) - 60),
        })
        self.mode = "offline"
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("宽限期", lic.state()["issue"])

        self.mode = "online"
        lic._reset_cache()
        self.assertTrue(lic.is_activated())
        self.assertGreater(self._read_license()["lease"]["body"].__len__(), 0)

    def test_legacy_license_is_confirmed_online_once(self):
        code = self._code(memo="老客户")
        self._write_license({"code": lic.normalize_code(code), "last_seen": time.time()})
        lic._reset_cache()
        self.assertTrue(lic.is_activated())
        self.assertIn("lease", self._read_license())
        self.assertEqual(lic.state()["memo"], "老客户")

    def test_revoked_code_is_rejected_on_activation(self):
        self.mode = "reject"
        self.reject_message = lic._status_message("revoked")
        with self.assertRaises(lic.LicenseError) as caught:
            lic.activate(self._code())
        self.assertIn("停用", str(caught.exception))

    def test_heartbeat_detects_revocation_immediately(self):
        lic.activate(self._code())
        self.assertTrue(lic.is_activated())
        self.status = "revoked"
        outcome = lic._heartbeat_once(lic.normalize_code(self._code()), self.device)
        self.assertEqual(outcome, "revoked")
        self.assertFalse(lic.is_activated())
        self.assertIn("停用", lic.state()["issue"])

    def test_heartbeat_detects_device_mismatch(self):
        lic.activate(self._code())
        self.status = "device_mismatch"
        outcome = lic._heartbeat_once(lic.normalize_code(self._code()), self.device)
        self.assertEqual(outcome, "device_mismatch")
        self.assertFalse(lic.is_activated())
        self.assertIn("换绑", lic.state()["issue"])

    def test_lease_expiry_while_running_blocks_requests(self):
        lic.activate(self._code())
        lic._cached_confirmation["not_after"] = int(time.time()) - 1
        self.assertFalse(lic.is_activated())
        self.assertFalse(lic.state()["activated"])
        self.assertIn("宽限期", lic.state()["issue"])

    def test_lease_bound_to_other_device_is_rejected(self):
        code = self._code()
        self._write_license({
            "code": lic.normalize_code(code),
            "last_seen": time.time(),
            "device": "other-device-0001",
            "lease": self._lease(device="other-device-0001"),
        })
        self.mode = "offline"
        lic._reset_cache()
        self.assertFalse(lic.is_activated())
        self.assertIn("设备", lic.state()["issue"])


if __name__ == "__main__":
    unittest.main()
