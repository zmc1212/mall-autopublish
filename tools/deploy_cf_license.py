"""部署授权服务（激活登记 + 心跳 + 吊销）到 Cloudflare Workers + KV。

用法（仓库根目录）：
  python tools/deploy_cf_license.py
  python tools/deploy_cf_license.py --domain license.example.com
  python tools/deploy_cf_license.py --account-id <id> --name qianniu-license --lease-days 14

首次运行会自动：创建/复用 KV namespace、生成服务端签名私钥（仅在本机）、
生成管理令牌（仅在本机）、部署 Worker 并写入 secret。
部署成功后 pack.ps1 会把服务地址写进 runtime-manifest.json，客户端据此强制联网激活。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import license as lic  # noqa: E402
from desktop import license_service as service  # noqa: E402
from tools.deploy_cf_updates import Wrangler, normalize_domain, say  # noqa: E402

WORK = ROOT / ".work" / "cloudflare-license"
WORKER = ROOT / "cloudflare" / "license-service" / "worker.mjs"


def config(account: str, worker_name: str, namespace_id: str, *, domain: str, lease_days: int, max_devices: int) -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", worker_name):
        raise ValueError("Worker 名称须为 3-63 位小写英文、数字或连字符")
    value = {
        "name": worker_name,
        "account_id": account,
        "main": str(WORKER),
        "compatibility_date": "2026-10-01",
        "workers_dev": True,
        "preview_urls": False,
        "kv_namespaces": [{"binding": "LICENSE_KV", "id": namespace_id}],
        "vars": {"LEASE_DAYS": str(lease_days), "MAX_DEVICES": str(max_devices)},
    }
    if domain:
        value["routes"] = [{"pattern": domain, "custom_domain": True}]
    return value


def post_json(url: str, payload: dict, attempts: int = 6) -> tuple[int, bytes]:
    last: Exception | None = None
    for _ in range(attempts):
        try:
            request = Request(
                url,
                data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                headers={"Content-Type": "application/json", "User-Agent": "QianniuLicenseDeploy/1"},
                method="POST",
            )
            with urlopen(request, timeout=20) as response:
                return response.status, response.read()
        except HTTPError as exc:
            return exc.code, exc.read()
        except OSError as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"授权服务暂时无法访问：{last}")


def verify_live(base: str, attempts: int = 30) -> None:
    """校验服务在线，且心跳响应确实由内置公钥对应的私钥签名。

    自定义域名首次部署后 DNS 与证书可能需要一点时间，这里做有限重试。
    """
    health = None
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            request = Request(base + "/health", headers={"User-Agent": "QianniuLicenseDeploy/1"})
            with urlopen(request, timeout=20) as response:
                health = json.load(response)
            break
        except (OSError, ValueError) as exc:
            last_error = exc
            if attempt + 1 < attempts:
                time.sleep(3)
    if health is None:
        raise RuntimeError(f"授权服务健康检查失败：{last_error}") from last_error
    if health.get("service") != "QianniuLicense":
        raise RuntimeError("授权服务健康检查返回了非预期内容")

    status, raw = post_json(base + "/v1/heartbeat", {
        "code": "A" * 64, "device_id": "deploy-probe-0001", "nonce": "deployprobe",
    })
    if status != 200:
        raise RuntimeError(f"授权服务心跳接口返回 HTTP {status}")
    envelope = json.loads(raw)
    body = base64.b64decode(str(envelope.get("body") or ""))
    signature = base64.b64decode(str(envelope.get("sig") or ""))
    public = base64.b64decode(lic.LICENSE_SERVER_PUBLIC_KEY_B64)
    if not lic.ed25519_verify(public, body, signature):
        raise RuntimeError("授权服务响应验签失败：服务端签名私钥与客户端内置公钥不匹配")
    payload = json.loads(body)
    if payload.get("status") != "unknown":
        raise RuntimeError("授权服务对未登记激活码的返回异常")

    status, _ = post_json(base + "/v1/activate", {"code": "short", "device_id": "deploy-probe-0001"})
    if status != 400:
        raise RuntimeError("授权服务未拒绝格式错误的激活码请求")


def deploy(args, cli: Wrangler | None = None, work: Path = WORK) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    state_path = work / "deployment.json"
    state = {}
    if state_path.is_file():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            state = {}

    domain = normalize_domain(args.domain) if getattr(args, "domain", "") else str(state.get("custom_domain") or "")
    cli = cli or Wrangler()
    say("[1/5] 检查已有 Cloudflare 登录…")
    account = cli.account(args.account_id or state.get("account_id", ""))
    worker_name = args.name or state.get("worker_name") or "qianniu-license-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:6]

    say("[2/5] 准备 KV namespace…")
    kv_title = state.get("kv_title") or "qianniu-license-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:6]
    namespace_id = cli.ensure_kv_namespace(kv_title)

    say("[3/5] 检查服务端签名密钥与管理令牌（仅保存在本机）…")
    seed = service.load_signing_seed(create=True)
    public_b64 = service.signing_public_b64(seed)
    if public_b64 != lic.LICENSE_SERVER_PUBLIC_KEY_B64:
        raise RuntimeError(
            "服务端签名公钥与 desktop/license.py 内置的 LICENSE_SERVER_PUBLIC_KEY_B64 不一致。\n"
            f"本机私钥对应公钥：{public_b64}\n"
            "请删除 %s 后重新生成，或把该公钥写入客户端后重新打包。" % service.signing_key_path()
        )
    admin_token = service.admin_token(create=True)

    stage = Path(tempfile.mkdtemp(prefix="deploy-", dir=work))
    try:
        say("[4/5] 部署 Workers 授权服务…")
        config_file = stage / "wrangler.json"
        config_file.write_text(json.dumps(
            config(account, worker_name, namespace_id, domain=domain,
                   lease_days=args.lease_days, max_devices=args.max_devices),
            ensure_ascii=False, indent=2,
        ), encoding="utf-8")
        output = cli.run("deploy", "--config", str(config_file))
        match = re.search(r"https://" + re.escape(worker_name) + r"\.[a-z0-9-]+\.workers\.dev", output)
        if not match:
            raise RuntimeError("部署命令未返回 workers.dev 地址；请确认账户已配置 workers.dev 子域名")

        cli.put_secret(worker_name, "LICENSE_SIGNING_KEY", base64.b64encode(seed).decode("ascii"), config_file)
        cli.put_secret(worker_name, "ADMIN_TOKEN", admin_token, config_file)

        base = "https://" + domain if domain else match[0]
        say("[5/5] 验证服务在线并校验签名…")
        verify_live(base)
        result = {
            "schema": 1,
            "account_id": account,
            "worker_name": worker_name,
            "kv_title": kv_title,
            "kv_id": namespace_id,
            "url": base,
            "custom_domain": domain,
            "lease_days": int(args.lease_days),
            "max_devices": int(args.max_devices),
            "public_key": public_b64,
            "verified": True,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        state_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        # 打包后的发码工具不在仓库目录里，用本机缓存文件找到服务地址。
        (service.key_dir() / "license-server.txt").write_text(base + "\n", encoding="utf-8")
        say("\n授权服务部署成功：" + base)
        say("签名私钥：" + str(service.signing_key_path()) + "（务必连同发码私钥一起备份）")
        say("管理令牌：" + str(service.admin_token_path()) + "（吊销/换绑用，勿外传）")
        say("下次打包会自动把服务地址写入 runtime-manifest.json；已有安装包需重新打包才能强制联网激活。")
        return result
    finally:
        # 只清理本次临时配置，部署产物在 Cloudflare 侧。
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="部署千牛授权服务（Cloudflare Workers + KV）")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--domain", help="绑定空闲的 Cloudflare 子域名，之后自动复用")
    parser.add_argument("--lease-days", type=int, default=14, help="离线宽限期天数（默认 14）")
    parser.add_argument("--max-devices", type=int, default=1, help="每个激活码允许的设备数（默认 1）")
    args = parser.parse_args()
    try:
        deploy(args)
    except Exception as exc:
        say("\n部署未完成：" + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
