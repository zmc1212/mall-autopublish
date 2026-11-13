"""授权服务端（Cloudflare Worker）的管理侧客户端：密钥、管理令牌与注册/吊销接口。

只被发码工具和部署脚本使用，不随客户端分发。客户端侧的验签逻辑在
desktop/license.py，两边共用同一套 Ed25519 实现。
"""

from __future__ import annotations

import base64
import json
import os
import secrets
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_TIMEOUT = 8.0


class LicenseServiceError(Exception):
    """与授权服务通信失败，message 面向开发者或最终用户。"""


def key_dir() -> Path:
    override = os.environ.get("QIANNIU_LICENSE_KEY_DIR")
    base = Path(override) if override else Path.home() / ".qianniu-license"
    base.mkdir(parents=True, exist_ok=True)
    return base


def signing_key_path() -> Path:
    """服务端响应签名私钥（32 字节种子，Base64 存 JSON）。"""
    return key_dir() / "server-signing.key"


def admin_token_path() -> Path:
    return key_dir() / "admin-token.txt"


def deployment_path() -> Path:
    return Path(__file__).resolve().parent.parent / ".work" / "cloudflare-license" / "deployment.json"


def server_url() -> str:
    """授权服务根地址：环境变量 > 本机缓存 > 部署脚本写下的 deployment.json。"""
    override = str(os.environ.get("QIANNIU_LICENSE_SERVER") or "").strip()
    if override:
        return override.rstrip("/")
    cached = key_dir() / "license-server.txt"
    if cached.is_file():
        try:
            value = cached.read_text(encoding="utf-8").strip()
        except OSError:
            value = ""
        if value:
            return value.rstrip("/")
    path = deployment_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return str(data.get("url") or "").rstrip("/")
        except (OSError, ValueError):
            return ""
    return ""


def admin_token(*, create: bool = False) -> str:
    """管理令牌：环境变量优先，其次本机文件；create=True 时缺失自动生成。"""
    override = str(os.environ.get("QIANNIU_LICENSE_ADMIN_TOKEN") or "").strip()
    if override:
        return override
    path = admin_token_path()
    if path.is_file():
        value = path.read_text(encoding="utf-8").strip()
        if value:
            return value
    if not create:
        return ""
    value = secrets.token_urlsafe(32)
    path.write_text(value + "\n", encoding="utf-8")
    return value


def load_signing_seed(*, create: bool = False) -> bytes:
    """读取服务端签名私钥；缺失且 create=True 时生成并落盘。"""
    path = signing_key_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            seed = base64.b64decode(str(data.get("seed") or ""))
        except (OSError, ValueError) as exc:
            raise LicenseServiceError(f"服务端签名私钥损坏：{path}（{exc}）") from exc
        if len(seed) != 32:
            raise LicenseServiceError(f"服务端签名私钥长度异常：{path}")
        return seed
    if not create:
        raise LicenseServiceError(f"未找到服务端签名私钥：{path}（请先运行部署脚本）")
    seed = os.urandom(32)
    path.write_text(json.dumps({"seed": base64.b64encode(seed).decode("ascii")}, indent=2), encoding="utf-8")
    return seed


def signing_public_b64(seed: bytes) -> str:
    from .license import ed25519_public_key

    return base64.b64encode(ed25519_public_key(seed)).decode("ascii")


def request(path: str, payload: dict | None = None, *, admin: bool = False, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """调用授权服务；网络或 HTTP 错误统一转成 LicenseServiceError。"""
    base = server_url()
    if not base:
        raise LicenseServiceError("未配置授权服务地址（请先运行 tools/deploy_cf_license.py 部署）")
    body = json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    headers = {"Content-Type": "application/json", "User-Agent": "QianniuLicenseAdmin/1"}
    if admin:
        token = admin_token()
        if not token:
            raise LicenseServiceError("未找到管理令牌（%s）" % admin_token_path())
        headers["Authorization"] = "Bearer " + token
    req = urllib.request.Request(base + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace").strip()
        try:
            message = str(json.loads(detail).get("error") or detail)
        except ValueError:
            message = detail
        raise LicenseServiceError(message or f"授权服务返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LicenseServiceError(f"无法连接授权服务：{exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise LicenseServiceError("授权服务返回内容异常") from exc
    if not isinstance(data, dict):
        raise LicenseServiceError("授权服务返回内容异常")
    return data


def register(code: str, *, fingerprint: str, expires_at: int, memo: str, max_devices: int = 1) -> dict:
    return request(
        "/admin/register",
        {
            "code": code,
            "machine_code": fingerprint,
            "exp": int(expires_at or 0),
            "memo": memo,
            "max_devices": max(1, int(max_devices or 1)),
        },
        admin=True,
    )


def revoke(code: str) -> dict:
    return request("/admin/revoke", {"code": code}, admin=True)


def unrevoke(code: str) -> dict:
    return request("/admin/unrevoke", {"code": code}, admin=True)


def rebind(code: str) -> dict:
    """清空绑定设备，客户换机/重装后可重新激活。"""
    return request("/admin/rebind", {"code": code}, admin=True)


def lookup(code: str) -> dict:
    return request("/admin/lookup", {"code": code}, admin=True)
