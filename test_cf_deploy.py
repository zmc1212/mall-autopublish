"""部署脚本的本地发布事务验证，不在单元测试中创建云端资源。"""

import argparse
import base64
import io
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

import test_updater as fixtures
from tools import deploy_cf_updates as deployer
from desktop import license as lic
from desktop import paths


class CloudflareDeployTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.UpdateTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.package = self.fixture.package()
        self.feed = self.package.parent / "latest.json"
        self.work = self.fixture.root / "cloudflare-work"
        self.work.mkdir()

    def test_assets_rebuild_exact_zip_bytes(self):
        assets = self.work / "new-assets"
        with patch.object(deployer, "CHUNK_SIZE", 128):
            manifest = deployer.prepare_assets(assets, self.feed)
        release = manifest["releases"][manifest["feed"]["sha256"]]
        rebuilt = b"".join((assets / name.lstrip("/")).read_bytes() for name in release["chunks"])
        self.assertEqual(rebuilt, self.package.read_bytes())
        self.assertGreater(len(release["chunks"]), 1)
        self.assertTrue(manifest["feed"]["url"].startswith("/releases/"))

    def test_delta_and_full_fallback_are_both_published_with_exact_bytes(self):
        full, delta, feed = self.fixture.delta_packages()
        assets = self.work / "delta-assets"
        manifest = deployer.prepare_assets(assets, self.feed)
        self.assertEqual(manifest["feed"]["schema"], 1)
        self.assertTrue(manifest["feed"]["url"].endswith(full.name))
        self.assertEqual(len(manifest["feed"]["deltas"]), 1)
        self.assertEqual(manifest["feed"]["deltas"][0]["base_version"], "1.3.0.1")
        for item in [manifest["feed"], *manifest["feed"]["deltas"]]:
            release = manifest["releases"][item["sha256"]]
            rebuilt = b"".join((assets / name.lstrip("/")).read_bytes() for name in release["chunks"])
            expected = delta if item.get("base_version") else full
            self.assertEqual(rebuilt, expected.read_bytes())
            self.assertTrue(item["url"].startswith("/releases/"))

    def test_missing_or_unsafe_delta_refuses_publication(self):
        full, delta, feed = self.fixture.delta_packages()
        for url in ("../" + delta.name, "https://other.example/" + delta.name):
            feed["deltas"][0]["url"] = url
            deployer.write_json(self.feed, feed)
            with self.subTest(url=url), self.assertRaises(ValueError):
                deployer.prepare_assets(self.work / str(len(url)), self.feed)
        feed["deltas"][0]["url"] = delta.name
        deployer.write_json(self.feed, feed)
        delta.unlink()
        with self.assertRaisesRegex(ValueError, "不存在"):
            deployer.prepare_assets(self.work / "missing-delta", self.feed)

    def test_malformed_delta_list_refuses_publication(self):
        feed = deployer.read_json(self.feed)
        deployer.write_json(self.feed, feed | {"deltas": [None]})
        with self.assertRaisesRegex(ValueError, "差量下载清单"):
            deployer.prepare_assets(self.work / "bad-delta-list", self.feed)

    def test_zip_modified_while_preparing_is_not_published(self):
        original = deployer.verified_package

        def changing_package(feed):
            result = original(feed)
            self.package.write_bytes(self.package.read_bytes() + b"changed during deployment")
            return result

        with patch.object(deployer, "verified_package", side_effect=changing_package):
            with self.assertRaisesRegex(ValueError, "ZIP 发生变化"):
                deployer.prepare_assets(self.work / "changed", self.feed)

    def test_empty_setup_and_preservation_of_published_release(self):
        cache = self.work / "assets"
        initial = deployer.prepare_assets(cache, None)
        self.assertEqual(initial["feed"]["version"], "0.0.0")
        full = self.work / "full"
        published = deployer.prepare_assets(full, self.feed, existing=cache)
        kept = deployer.prepare_assets(self.work / "kept", None, existing=full)
        self.assertEqual(kept, published)

    def test_corrupt_zip_fails_before_any_cloudflare_call(self):
        self.package.write_bytes(b"tampered")
        cli = Mock()
        args = argparse.Namespace(updates_dir=self.package.parent, setup_only=False,
                                  account_id="", name="qianniu-test", no_configure_client=True)
        with self.assertRaises(ValueError):
            deployer.deploy(args, cli, self.work)
        cli.account.assert_not_called()
        cli.run.assert_not_called()

    def test_failed_deployment_preserves_existing_cache_and_settings(self):
        cache = self.work / "assets"
        deployer.prepare_assets(cache, None)
        before = (cache / "__updates/index.json").read_bytes()
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.run.side_effect = RuntimeError("模拟网络失败")
        args = argparse.Namespace(updates_dir=self.package.parent, setup_only=False,
                                  account_id="", name="qianniu-test", no_configure_client=False)
        settings = paths.settings_path().read_bytes()
        with self.assertRaisesRegex(RuntimeError, "网络失败"):
            deployer.deploy(args, cli, self.work)
        self.assertEqual((cache / "__updates/index.json").read_bytes(), before)
        self.assertEqual(paths.settings_path().read_bytes(), settings)

    def test_success_outputs_address_and_only_changes_update_setting(self):
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.run.return_value = "Deployed https://qianniu-test.account.workers.dev"
        args = argparse.Namespace(updates_dir=self.package.parent, setup_only=False,
                                  account_id="", name="qianniu-test", no_configure_client=False)
        before = json.loads(paths.settings_path().read_text())
        with patch.object(deployer, "verify_live") as verify:
            state = deployer.deploy(args, cli, self.work)
        self.assertEqual(state["feed_url"], "https://qianniu-test.account.workers.dev/latest.json")
        self.assertTrue(state["verified"])
        after = json.loads(paths.settings_path().read_text())
        self.assertEqual(after.pop("update_feed_url"), state["feed_url"])
        before.pop("update_feed_url")
        self.assertEqual(after, before)
        verify.assert_called_once()
        self.assertTrue((self.work / "assets/__updates/index.json").is_file())
        self.assertFalse(any(self.work.glob("deploy-*")))

    def test_security_denial_is_not_retried(self):
        denied = HTTPError("https://updates.example/latest.json", 403, "Forbidden",
                           {"CF-RAY": "test-ray"}, io.BytesIO(b"error code: 1010"))
        with patch.object(deployer, "open_url", side_effect=denied) as request:
            with patch.object(deployer.time, "sleep") as sleep:
                with self.assertRaisesRegex(RuntimeError, "HTTP 403.*1010"):
                    deployer.verify_live("https://updates.example", {"feed": {}})
        request.assert_called_once()
        sleep.assert_not_called()

    def test_verification_uses_real_updater_identity_for_get_and_head(self):
        from desktop import updater
        feed = {"version": "1.3.0.2", "sha256": "a" * 64,
                "url": "/releases/test.zip", "size": 123}

        def response(request, timeout):
            result = io.BytesIO(json.dumps(feed).encode() if request.method == "GET" else b"")
            result.geturl = lambda: request.full_url
            result.headers = {"Content-Length": "123"}
            return result

        with patch.object(updater, "urlopen", side_effect=response) as request:
            deployer.verify_live("https://updates.example.com", {"feed": feed})
        self.assertEqual([c.args[0].method for c in request.call_args_list], ["GET", "HEAD"])
        self.assertTrue(all(c.args[0].get_header("User-agent") == f"QianniuUpdater/{updater.VERSION}"
                            for c in request.call_args_list))

    def test_custom_domain_is_validated_and_routes_only_that_hostname(self):
        result = deployer.config("a" * 32, "qianniu-test", self.work, "Updates.Example.COM.")
        self.assertEqual(result["routes"], [{"pattern": "updates.example.com", "custom_domain": True}])
        for domain in ("https://updates.example.com", "updates.example.com/*", "*.example.com",
                       "example.com", "updates.example.com:443", "bad-.example.com"):
            with self.subTest(domain=domain), self.assertRaises(ValueError):
                deployer.normalize_domain(domain)

    def test_live_verification_rejects_a_damaged_chunk_stream(self):
        manifest = deployer.prepare_assets(self.work / "probe-test", None)
        probe = manifest["download_probe"]
        feed = io.BytesIO(json.dumps(manifest["feed"]).encode())
        damaged = io.BytesIO(b"truncated")
        damaged.headers = {"Content-Length": str(probe["size"])}
        with patch.object(deployer, "open_url", side_effect=[feed, damaged]):
            with patch.object(deployer.time, "sleep"):
                with self.assertRaisesRegex(RuntimeError, "分块下载完整性校验失败"):
                    deployer.verify_live("https://updates.example.com", manifest, attempts=1)

    def test_custom_domain_binding_refuses_conflicting_dns_or_worker(self):
        cli = deployer.Wrangler(prefix=["unused"])
        empty = {"added": [], "removed": [], "updated": [], "conflicting": []}
        cli.api = Mock(return_value=empty | {"conflicting": [{"hostname": "updates.example.com"}]})
        with self.assertRaisesRegex(RuntimeError, "冲突 DNS"):
            cli.check_domain("a" * 32, "qianniu-test", "updates.example.com")
        cli.api.side_effect = [empty | {"updated": [{"modified": True, "id": "other-domain"}]},
                               {"service": "other-worker"}]
        with self.assertRaisesRegex(RuntimeError, "其他 Worker"):
            cli.check_domain("a" * 32, "qianniu-test", "updates.example.com")

    def test_deployment_persists_and_reuses_custom_domain(self):
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.run.return_value = "Deployed https://qianniu-test.account.workers.dev"
        args = argparse.Namespace(updates_dir=self.package.parent, setup_only=True, domain="updates.example.com",
                                  account_id="", name="qianniu-test", no_configure_client=True)
        with patch.object(deployer, "verify_live") as verify:
            state = deployer.deploy(args, cli, self.work)
            args.domain = None
            again = deployer.deploy(args, cli, self.work)
        self.assertEqual(state["feed_url"], "https://updates.example.com/latest.json")
        self.assertEqual(again["custom_domain"], "updates.example.com")
        self.assertEqual(cli.check_domain.call_count, 2)
        self.assertTrue(all(c.args[0] == "https://updates.example.com" for c in verify.call_args_list))

    def test_failed_public_verification_keeps_evidence_without_changing_settings(self):
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.run.return_value = "Deployed https://qianniu-test.account.workers.dev"
        args = argparse.Namespace(updates_dir=self.package.parent, setup_only=True,
                                  account_id="", name="qianniu-test", no_configure_client=False)
        before = paths.settings_path().read_bytes()
        with patch.object(deployer, "verify_live", side_effect=RuntimeError("HTTP 403: error code 1010")):
            with self.assertRaisesRegex(RuntimeError, "HTTP 403"):
                deployer.deploy(args, cli, self.work)
        self.assertEqual(paths.settings_path().read_bytes(), before)
        self.assertFalse(deployer.load_state(self.work)["verified"])
        evidence = deployer.read_json(self.work / "verification-error.json")
        self.assertIn("1010", evidence["error"])
        self.assertTrue((self.work / "assets/__updates/index.json").is_file())

    def test_cleared_feed_stays_empty_and_missing_feed_uses_built_default(self):
        runtime = self.fixture.install / "runtime-manifest.json"
        data = json.loads(runtime.read_text())
        data["update_feed_url"] = "https://built.example/latest.json"
        runtime.write_text(json.dumps(data), encoding="utf-8")
        settings = json.loads(paths.settings_path().read_text())
        settings.pop("update_feed_url")
        paths.settings_path().write_text(json.dumps(settings), encoding="utf-8")
        with patch.object(paths, "find_resource", return_value=runtime):
            self.assertEqual(paths.load_settings().update_feed_url, data["update_feed_url"])
            settings["update_feed_url"] = ""
            paths.settings_path().write_text(json.dumps(settings), encoding="utf-8")
            self.assertEqual(paths.load_settings().update_feed_url, "")

    def test_deletion_guard_cannot_remove_outside_work_directory(self):
        with self.assertRaises(ValueError):
            deployer.remove_temporary(self.fixture.data, self.work)


class LicenseServiceDeployTests(unittest.TestCase):
    """授权服务部署：KV 绑定、签名私钥校验与 secret 写入（不触网）。"""

    def setUp(self):
        from tools import deploy_cf_license as license_deployer

        self.module = license_deployer
        self.work = Path(tempfile.mkdtemp(prefix="license-deploy-"))
        self.addCleanup(shutil.rmtree, self.work, True)
        os.environ["QIANNIU_LICENSE_KEY_DIR"] = str(self.work / "keys")
        self.addCleanup(os.environ.pop, "QIANNIU_LICENSE_KEY_DIR", None)
        self.seed = bytes(range(32))
        public = base64.b64encode(lic.ed25519_public_key(self.seed)).decode()
        for target, name, value in (
            (self.module.service, "load_signing_seed", lambda **_: self.seed),
            (self.module.lic, "LICENSE_SERVER_PUBLIC_KEY_B64", public),
        ):
            patcher = patch.object(target, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _args(self):
        return argparse.Namespace(account_id="", name="qianniu-license-test", domain=None,
                                  lease_days=14, max_devices=1)

    def test_kv_namespace_is_created_once_and_reused(self):
        cli = deployer.Wrangler(prefix=["unused"])
        cli.run = Mock(side_effect=["[]", json.dumps({"id": "b" * 32})])
        self.assertEqual(cli.ensure_kv_namespace("qianniu-license-abc"), "b" * 32)
        self.assertEqual(cli.run.call_args_list[0].args, ("kv", "namespace", "list"))
        self.assertEqual(cli.run.call_args_list[1].args, ("kv", "namespace", "create", "qianniu-license-abc"))

        again = deployer.Wrangler(prefix=["unused"])
        again.run = Mock(return_value=json.dumps([{"id": "b" * 32, "title": "qianniu-license-abc"}]))
        self.assertEqual(again.ensure_kv_namespace("qianniu-license-abc"), "b" * 32)
        self.assertEqual(again.run.call_count, 1)

    def test_config_binds_kv_and_lease_settings(self):
        result = self.module.config("a" * 32, "qianniu-license-test", "b" * 32,
                                    domain="", lease_days=14, max_devices=2)
        self.assertEqual(result["kv_namespaces"], [{"binding": "LICENSE_KV", "id": "b" * 32}])
        self.assertEqual(result["vars"], {"LEASE_DAYS": "14", "MAX_DEVICES": "2"})
        self.assertNotIn("routes", result)

    def test_deploy_writes_secrets_and_state(self):
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.ensure_kv_namespace.return_value = "b" * 32
        cli.run.return_value = "Deployed https://qianniu-license-test.account.workers.dev"
        with patch.object(self.module, "verify_live") as verify:
            state = self.module.deploy(self._args(), cli, self.work)

        self.assertTrue(state["verified"])
        self.assertEqual(state["url"], "https://qianniu-license-test.account.workers.dev")
        self.assertEqual(state["kv_id"], "b" * 32)
        self.assertEqual(state["public_key"], lic.LICENSE_SERVER_PUBLIC_KEY_B64)
        self.assertEqual([c.args[1] for c in cli.put_secret.call_args_list],
                         ["LICENSE_SIGNING_KEY", "ADMIN_TOKEN"])
        verify.assert_called_once_with(state["url"])
        saved = json.loads((self.work / "deployment.json").read_text(encoding="utf-8"))
        self.assertEqual(saved["url"], state["url"])
        cached = Path(os.environ["QIANNIU_LICENSE_KEY_DIR"]) / "license-server.txt"
        self.assertEqual(cached.read_text(encoding="utf-8").strip(), state["url"])

    def test_signing_key_mismatch_blocks_deployment(self):
        cli = Mock()
        cli.account.return_value = "a" * 32
        cli.ensure_kv_namespace.return_value = "b" * 32
        with patch.object(self.module.lic, "LICENSE_SERVER_PUBLIC_KEY_B64", base64.b64encode(b"x" * 32).decode()):
            with self.assertRaisesRegex(RuntimeError, "公钥"):
                self.module.deploy(self._args(), cli, self.work)
        cli.run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
