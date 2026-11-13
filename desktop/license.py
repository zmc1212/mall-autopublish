"""离线激活码：Ed25519 验签 + 机器码绑定，纯标准库实现，无网络请求。

激活码格式：对 JSON payload（机器指纹、到期时间、备注、版本）的 Ed25519 签名，
Base32 编码后按 5 字符分组。程序内只内置公钥，私钥保存在开发者的
tools/license_keygen.py 发码工具里，不随软件分发。
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

# 程序内置的 Ed25519 公钥（32 字节，Base64）。私钥绝不放入本仓库或安装包。
PUBLIC_KEY_B64 = "diDdNVZi5+v/9ZCvEqYAq8eOLDEPS2doYwBiSHY7vJU="

# 授权服务响应签名公钥（与发码私钥无关）：客户端只认服务端签名，防止伪造“已授权”。
LICENSE_SERVER_PUBLIC_KEY_B64 = "GObbwzb1FTcREe3nHzkMyKG3bYCM7s5vR1EcR4rvx4U="

# 机器码派生盐：更换盐会使所有已签发激活码失效，发布后不可改动。
_MACHINE_SALT = "qianniu-license-v1"
_PAYLOAD_VERSION = 1
# 限期码防系统时间回拨的容忍窗口；永久码不做任何时间检查。
_CLOCK_ROLLBACK_TOLERANCE = 24 * 3600
_LAST_SEEN_UPDATE_INTERVAL = 3600
# 联网确认间隔与请求超时：每 6 小时心跳一次，吊销会在一个周期内生效。
_HEARTBEAT_INTERVAL = 6 * 3600
_SERVER_TIMEOUT = 6.0


class LicenseError(Exception):
    """激活失败，message 面向最终用户展示。"""


class LicenseServerUnreachable(LicenseError):
    """暂时连不上授权服务：已有租约时可继续离线使用，但不能算激活成功。"""


# ---------------------------------------------------------------------------
# Ed25519（RFC 8032 参考实现的纯 Python 移植，公有领域）。启动时验签一次
# 约 0.1 秒，之后走内存缓存，无需考虑性能优化。
# ---------------------------------------------------------------------------
_P = 2**255 - 19
_L = 2**252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _P - 2, _P)) % _P
_I = pow(2, (_P - 1) // 4, _P)


def _inv(x: int) -> int:
    return pow(x, _P - 2, _P)


def _xrecover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_P + 3) // 8, _P)
    if (x * x - xx) % _P != 0:
        x = (x * _I) % _P
    if x % 2 != 0:
        x = _P - x
    return x


_By = (4 * _inv(5)) % _P
_Bx = _xrecover(_By)
_B = (_Bx % _P, _By % _P)
_IDENT = (0, 1)


def _is_on_curve(point: tuple[int, int]) -> bool:
    x, y = point
    return (-x * x + y * y - 1 - _D * x * x * y * y) % _P == 0


def _edwards_add(p: tuple[int, int], q: tuple[int, int]) -> tuple[int, int]:
    x1, y1 = p
    x2, y2 = q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + _D * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - _D * x1 * x2 * y1 * y2)
    return (x3 % _P, y3 % _P)


def _scalarmult(point: tuple[int, int], e: int) -> tuple[int, int]:
    if e == 0:
        return _IDENT
    q = _scalarmult(point, e // 2)
    q = _edwards_add(q, q)
    if e & 1:
        q = _edwards_add(q, point)
    return q


def _point_compress(point: tuple[int, int]) -> bytes:
    x, y = point
    return int.to_bytes(y | ((x & 1) << 255), 32, "little")


def _point_decompress(data: bytes) -> tuple[int, int] | None:
    if len(data) != 32:
        return None
    y = int.from_bytes(data, "little")
    sign = y >> 255
    y &= (1 << 255) - 1
    if y >= _P:
        return None
    x = _xrecover(y)
    if x & 1 != sign:
        x = _P - x
    point = (x, y)
    if not _is_on_curve(point):
        return None
    return point


def _secret_expand(seed: bytes) -> tuple[int, bytes]:
    h = hashlib.sha512(seed).digest()
    a = int.from_bytes(h[:32], "little")
    a &= (1 << 254) - 8
    a |= 1 << 254
    return a, h[32:]


def ed25519_public_key(seed: bytes) -> bytes:
    a, _ = _secret_expand(seed)
    return _point_compress(_scalarmult(_B, a))


def ed25519_sign(seed: bytes, message: bytes) -> bytes:
    a, prefix = _secret_expand(seed)
    public = _point_compress(_scalarmult(_B, a))
    r = int.from_bytes(hashlib.sha512(prefix + message).digest(), "little") % _L
    r_encoded = _point_compress(_scalarmult(_B, r))
    h = int.from_bytes(hashlib.sha512(r_encoded + public + message).digest(), "little") % _L
    s = (r + h * a) % _L
    return r_encoded + int.to_bytes(s, 32, "little")


def ed25519_verify(public: bytes, message: bytes, signature: bytes) -> bool:
    if len(public) != 32 or len(signature) != 64:
        return False
    a = _point_decompress(public)
    if a is None:
        return False
    r_encoded = signature[:32]
    r = _point_decompress(r_encoded)
    if r is None:
        return False
    s = int.from_bytes(signature[32:], "little")
    if s >= _L:
        return False
    h = int.from_bytes(hashlib.sha512(r_encoded + public + message).digest(), "little") % _L
    left = _scalarmult(_B, s)
    right = _edwards_add(r, _scalarmult(a, h))
    return _point_compress(left) == _point_compress(right)


# ---------------------------------------------------------------------------
# 机器码
# ---------------------------------------------------------------------------
def _read_hklm_value(path: str, name: str = "") -> str:
    try:
        import winreg

        for flags in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path, 0, winreg.KEY_READ | flags) as key:
                    value, _ = winreg.QueryValueEx(key, name)
                    if value:
                        return str(value)
            except OSError:
                continue
    except Exception:
        pass
    return ""


def _machine_guid() -> str:
    return _read_hklm_value(r"SOFTWARE\Microsoft\Cryptography\MachineGuid")


def _product_id() -> str:
    return _read_hklm_value(r"SOFTWARE\Microsoft\Windows NT\CurrentVersion", "ProductId")


def _volume_serial() -> str:
    """系统盘卷序列号：装机后稳定（重装/重新分区才会变），普通用户可读。"""
    try:
        import ctypes

        serial = ctypes.c_ulong(0)
        drive = os.environ.get("SystemDrive", "C:") + "\\"
        if ctypes.windll.kernel32.GetVolumeInformationW(
            ctypes.c_wchar_p(drive), None, 0, ctypes.byref(serial), None, None, None, 0
        ):
            return f"{serial.value & 0xFFFFFFFF:08X}"
    except Exception:
        pass
    return ""


def machine_code() -> str:
    """本机机器码：XXXX-XXXX-XXXX-XXXX。重装系统会变化，重新发码即可。

    主来源 MachineGuid（装机固定）；读不到时（精简/克隆系统）用
    ProductId + 系统盘卷序列号——都是安装级稳定标识。绝不能用网卡 MAC
    或计算机名：虚拟网卡/换网络会让已激活机器的机器码漂移，导致升级或
    重启后要求重新激活。
    """
    guid = _machine_guid()
    if guid:
        raw = f"{_MACHINE_SALT}|guid|{guid}"
    else:
        raw = f"{_MACHINE_SALT}|fallback2|{_product_id()}|{_volume_serial()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


def machine_code_source() -> str:
    """机器码来源，写进 license.log 便于远程判断稳定性。"""
    if _machine_guid():
        return "MachineGuid"
    if _volume_serial() or _product_id():
        return "ProductId+卷序列号"
    return "降级(无稳定标识)"


def _legacy_machine_code() -> str:
    """v1 降级公式（MAC+主机名），仅用于兼容校验老激活码，不再对外展示。"""
    import platform
    import uuid

    raw = f"{_MACHINE_SALT}|fallback|{uuid.getnode():012x}|{platform.node()}|{platform.machine()}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16].upper()
    return "-".join(digest[i : i + 4] for i in range(0, 16, 4))


def machine_code_candidates() -> list[str]:
    """可用于指纹比对的全部机器码：现行公式 + 兼容老激活码的历史公式。"""
    codes = [machine_code()]
    try:
        legacy = _legacy_machine_code()
    except Exception:
        legacy = ""
    if legacy and legacy not in codes:
        codes.append(legacy)
    return codes


def _fingerprint(code: str) -> str:
    return code.replace("-", "").replace(" ", "").upper()


# ---------------------------------------------------------------------------
# 激活码编解码与校验
# ---------------------------------------------------------------------------
_BASE32_ALPHABET = set("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")


def normalize_code(text: str) -> str:
    """清洗用户输入：兼容横线、空格、换行和大小写。"""
    return "".join(ch for ch in str(text).upper() if ch in _BASE32_ALPHABET)


def build_code(payload: dict, seed: bytes) -> str:
    """签发激活码（发码工具使用）：payload 签名后 Base32 按 5 字符分组。"""
    payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    blob = payload_bytes + ed25519_sign(seed, payload_bytes)
    encoded = base64.b32encode(blob).decode("ascii").rstrip("=")
    return "-".join(encoded[i : i + 5] for i in range(0, len(encoded), 5))


def check_signature(code: str, public_key: bytes | None = None) -> dict:
    """只验签解码，不限机器、不查有效期（发码工具自检使用）。"""
    key = public_key if public_key is not None else base64.b64decode(PUBLIC_KEY_B64)
    cleaned = normalize_code(code)
    if len(cleaned) < 20:
        raise LicenseError("激活码格式不正确，请完整复制粘贴激活码（含横线也可以）。")
    padded = cleaned + "=" * (-len(cleaned) % 8)
    try:
        blob = base64.b32decode(padded)
    except Exception as exc:
        raise LicenseError("激活码格式不正确，请完整复制粘贴激活码。") from exc
    if len(blob) <= 64:
        raise LicenseError("激活码不完整，请重新复制完整内容。")
    payload_bytes, signature = blob[:-64], blob[-64:]
    if not ed25519_verify(key, payload_bytes, signature):
        raise LicenseError("激活码无效，请核对后重新输入。")
    try:
        payload = json.loads(payload_bytes.decode("utf-8"))
    except Exception as exc:
        raise LicenseError("激活码内容异常，请联系开发者重新发码。") from exc
    if not isinstance(payload, dict) or payload.get("v") != _PAYLOAD_VERSION:
        raise LicenseError("激活码版本不受支持，请联系开发者重新发码。")
    return payload


def verify_code(code: str, public_key: bytes | None = None) -> dict:
    """校验激活码：验签 → 比对本机机器码 → 检查有效期。返回 payload。

    机器码比对接受 machine_code_candidates()：现行稳定公式为主，另兼容
    v1 历史公式（MAC+主机名），保证老激活码在 MAC 未变的机器上继续有效。
    """
    payload = check_signature(code, public_key)
    licensed_fp = _fingerprint(str(payload.get("fp") or ""))
    if licensed_fp not in {_fingerprint(item) for item in machine_code_candidates()}:
        raise LicenseError(f"激活码与本机不匹配。请确认页面上的机器码（{machine_code()}）后重新申请。")
    expires_at = int(payload.get("exp") or 0)
    if expires_at and time.time() > expires_at:
        raise LicenseError("激活码已过期，请联系开发者重新发码。")
    return payload


# ---------------------------------------------------------------------------
# 授权服务：设备标识、签名响应校验与联网确认
# ---------------------------------------------------------------------------
def server_url() -> str:
    """授权服务地址：环境变量优先，其次构建时写入的 runtime-manifest.json。"""
    override = str(os.environ.get("QIANNIU_LICENSE_SERVER") or "").strip()
    if override:
        return override.rstrip("/")
    try:
        from . import paths

        return paths.default_license_server_url().rstrip("/")
    except Exception:
        return ""


def device_id() -> str:
    """本机安装标识（首次生成后固定），服务端据此限制同时使用的设备数。"""
    from . import paths

    path = paths.appdata_dir() / "device.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        value = str(data.get("id") or "")
    except (OSError, ValueError, AttributeError):
        value = ""
    if not re.fullmatch(r"[A-Za-z0-9_-]{8,64}", value):
        value = uuid.uuid4().hex
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({"id": value}, indent=2), encoding="utf-8")
        except OSError:
            pass
    return value


def _post(path: str, payload: dict, timeout: float = _SERVER_TIMEOUT) -> dict:
    """POST 授权服务；服务端明确拒绝抛 LicenseError，网络问题抛 LicenseServerUnreachable。"""
    base = server_url()
    if not base:
        raise LicenseServerUnreachable("本版本未配置授权服务，无法联网激活。")
    request = urllib.request.Request(
        base + path,
        data=json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "QianniuLicense/1"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", "replace").strip()
        try:
            message = str(json.loads(detail).get("error") or detail)
        except ValueError:
            message = detail
        raise LicenseError(message or f"授权服务返回 HTTP {exc.code}") from exc
    except (urllib.error.URLError, OSError) as exc:
        raise LicenseServerUnreachable(f"无法连接授权服务器（{exc}）") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except ValueError as exc:
        raise LicenseServerUnreachable("授权服务返回内容异常") from exc
    if not isinstance(data, dict):
        raise LicenseServerUnreachable("授权服务返回内容异常")
    return data


def _open_envelope(envelope) -> dict:
    """校验服务端签名并返回 payload；验签失败一律按“未确认”处理，不当作激活成功。"""
    if not isinstance(envelope, dict):
        raise LicenseServerUnreachable("授权服务响应格式异常")
    try:
        body = base64.b64decode(str(envelope.get("body") or ""))
        signature = base64.b64decode(str(envelope.get("sig") or ""))
    except (ValueError, TypeError) as exc:
        raise LicenseServerUnreachable("授权服务响应格式异常") from exc
    public = base64.b64decode(LICENSE_SERVER_PUBLIC_KEY_B64)
    if not ed25519_verify(public, body, signature):
        raise LicenseServerUnreachable("授权服务响应验签失败，已按未确认处理")
    try:
        payload = json.loads(body.decode("utf-8"))
    except ValueError as exc:
        raise LicenseServerUnreachable("授权服务响应内容异常") from exc
    if not isinstance(payload, dict):
        raise LicenseServerUnreachable("授权服务响应内容异常")
    return payload


def _status_message(status: str) -> str:
    return {
        "revoked": "该授权已被停用（订单已退款或违规使用），如需恢复请联系卖家。",
        "device_mismatch": "该激活码已绑定其他设备，请联系卖家换绑后再激活。",
        "expired": "激活码已过期，请联系卖家续期。",
        "unknown": "授权服务没有该激活码记录，请联系卖家重新发码。",
    }.get(status, "授权状态无法确认，请联系卖家。")


def _request_activation(code: str, device: str, payload: dict) -> dict:
    """首次激活/租约失效后的联网确认；返回服务端签名凭据。"""
    envelope = _post("/v1/activate", {
        "code": normalize_code(code),
        "device_id": device,
        "machine_code": machine_code(),
        "exp": int(payload.get("exp") or 0),
        "memo": str(payload.get("memo") or ""),
    })
    confirmation = _open_envelope(envelope)
    status = str(confirmation.get("status") or "")
    if status != "active":
        raise LicenseError(_status_message(status))
    if str(confirmation.get("device_id") or "") != device:
        raise LicenseServerUnreachable("授权服务返回的设备标识不一致，请重试")
    return {"confirmation": confirmation, "envelope": envelope}


def _lease_status(lease, device: str) -> tuple[dict | None, str]:
    """校验本地租约；返回 (确认信息, 失效原因)。"""
    if not isinstance(lease, dict) or not lease:
        return None, "首次激活需要联网确认，请连网后重新打开软件。"
    try:
        confirmation = _open_envelope(lease)
    except LicenseServerUnreachable:
        return None, "本机授权凭据异常，请联网后重新打开软件确认。"
    if str(confirmation.get("device_id") or "") != device:
        return None, "本机授权凭据与设备不匹配，请联网后重新激活。"
    status = str(confirmation.get("status") or "")
    if status != "active":
        return None, _status_message(status)
    not_after = int(confirmation.get("not_after") or 0)
    if not_after and time.time() > not_after:
        return None, "离线已超过宽限期，请联网后重新打开软件确认授权。"
    return confirmation, ""


# ---------------------------------------------------------------------------
# 授权状态：license.json 只存激活码原文，每次启动重新验签，篡改无效
# ---------------------------------------------------------------------------
_license_lock = threading.Lock()
_cached_payload: dict | None = None
_cached_confirmation: dict | None = None
_last_issue = ""
_loaded = False
_heartbeat_lock = threading.Lock()
_heartbeat_running = False
_heartbeat_stop = threading.Event()


def _log_event(message: str) -> None:
    """授权加载结果写一次 logs/license.log，供日志导出远程排查失效原因。

    只记录原因与机器码，不记录激活码原文。
    """
    try:
        from datetime import datetime

        from . import paths

        path = paths.appdata_dir() / "logs" / "license.log"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{datetime.now().isoformat(timespec='seconds')} {message}\n")
    except OSError:
        pass


def _group_fp(fp: str) -> str:
    clean = _fingerprint(fp)
    return "-".join(clean[i : i + 4] for i in range(0, len(clean), 4)) if clean else "?"


def _record_issue(message: str) -> None:
    """记录失效原因：写入 license.log 并通过 state().issue 展示到激活页。"""
    global _last_issue
    _last_issue = message
    _log_event(message)


def license_path() -> Path:
    from . import paths

    return paths.appdata_dir() / "license.json"


def _write_file(code: str, last_seen: float) -> None:
    _save_state({"code": code, "last_seen": last_seen})


def _save_state(data: dict) -> None:
    """原子写入 license.json，避免进程中断留下半截文件。"""
    path = license_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temp, path)


def _verify_saved(data: dict) -> dict | None:
    """校验 license.json 中的激活码；无效一律返回 None（含时间回拨防护）。

    失败原因写入 _last_issue（激活页展示 + license.log），便于远程排查
    “更新后又被要求激活”一类问题。
    """
    code = str(data.get("code") or "")
    if not code:
        _record_issue("本机授权文件缺少激活码内容，请重新输入激活码。")
        return None
    try:
        payload = verify_code(code)
    except LicenseError as exc:
        reason = str(exc)
        if "不匹配" in reason:
            licensed_fp = ""
            try:
                licensed_fp = _group_fp(str(check_signature(code).get("fp") or ""))
            except LicenseError:
                pass
            reason = (
                f"{reason}该激活码绑定的机器码是 {licensed_fp}。"
                "若因重装系统、更换电脑或网络环境变化导致机器码变化，请把激活页显示的机器码发给开发者重新领取激活码。"
            )
        _record_issue(reason)
        return None
    except Exception as exc:  # 意外异常同样不能阻断启动，按未激活处理
        _record_issue(f"本机授权校验异常（{exc.__class__.__name__}），请重新输入激活码。")
        return None
    expires_at = int(payload.get("exp") or 0)
    last_seen = float(data.get("last_seen") or 0)
    now = time.time()
    # 仅限期码做回拨检查：永久码回拨无利可图，不做时间检查避免误伤。
    if expires_at and last_seen and now < last_seen - _CLOCK_ROLLBACK_TOLERANCE:
        _record_issue("检测到系统时间明显回退，限期授权暂时失效，请校准系统时间后重启软件。")
        return None
    if expires_at and now - last_seen > _LAST_SEEN_UPDATE_INTERVAL:
        try:
            _save_state({**data, "code": code, "last_seen": now})
        except OSError:
            pass

    base = server_url()
    confirmation = None
    if base:
        device = device_id()
        confirmation, reason = _lease_status(data.get("lease"), device)
        if confirmation is None:
            # 首次激活、老版本升级或租约过期：再联网确认一次，成功后继续离线使用。
            try:
                result = _request_activation(code, device, payload)
            except LicenseServerUnreachable as exc:
                _record_issue(reason or str(exc))
                return None
            except LicenseError as exc:
                _record_issue(str(exc))
                return None
            except Exception as exc:
                _record_issue(f"联网确认授权异常（{exc.__class__.__name__}），请检查网络后重新打开软件。")
                return None
            confirmation = result["confirmation"]
            now = time.time()
            data = {**data, "code": code, "lease": result["envelope"],
                    "device": device, "last_heartbeat": now}
            try:
                _save_state(data)
            except OSError:
                pass
        _ensure_heartbeat(code, device)

    global _last_issue, _cached_confirmation
    _cached_confirmation = confirmation
    _last_issue = ""
    memo = str(payload.get("memo") or "")
    licensed_fp = _fingerprint(str(payload.get("fp") or ""))
    matched = "主机器码" if licensed_fp == _fingerprint(machine_code()) else "历史机器码(兼容)"
    _log_event(
        f"授权有效：memo={memo or '—'} 到期={expires_at or '永久'} "
        f"机器码={machine_code()}（{machine_code_source()}，{matched}）"
    )
    return payload


def _ensure_loaded() -> None:
    global _loaded, _cached_payload, _cached_confirmation, _last_issue
    if _loaded:
        return
    _last_issue = ""
    _loaded = True
    _cached_confirmation = None
    path = license_path()
    if not path.is_file():
        _cached_payload = None
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        _cached_payload = None
        _record_issue(f"本机授权文件无法读取（{exc.__class__.__name__}），请重新输入激活码。")
        return
    except ValueError as exc:  # JSONDecodeError / 二进制损坏导致的 UnicodeDecodeError
        _cached_payload = None
        _record_issue(f"本机授权文件内容损坏（{exc.__class__.__name__}），请重新输入激活码。")
        return
    if not isinstance(data, dict):
        _cached_payload = None
        _record_issue("本机授权文件格式异常，请重新输入激活码。")
        return
    _cached_payload = _verify_saved(data)


def _reset_cache() -> None:
    global _loaded, _cached_payload, _cached_confirmation, _last_issue
    _loaded = False
    _cached_payload = None
    _cached_confirmation = None
    _last_issue = ""


def _lease_expired() -> bool:
    """联网确认的离线宽限期是否已过（未启用联网确认时永远为 False）。"""
    not_after = int((_cached_confirmation or {}).get("not_after") or 0)
    return bool(not_after and time.time() > not_after)


def is_activated() -> bool:
    global _last_issue
    with _license_lock:
        _ensure_loaded()
        if _cached_payload is None:
            return False
        # 长时间挂着软件也要执行离线宽限期：租约到期即要求联网确认。
        if _lease_expired():
            _last_issue = "离线已超过宽限期，请联网后重新打开软件确认授权。"
            return False
        return True


def _state_unlocked() -> dict:
    """持锁状态下组装授权状态（activate 与 state 共用）。"""
    payload = _cached_payload
    expired = payload is not None and _lease_expired()
    activated = payload is not None and not expired
    issue = ""
    if not activated:
        issue = _last_issue or ("离线已超过宽限期，请联网后重新打开软件确认授权。" if expired else "")
    result = {
        "activated": activated,
        "machine_code": machine_code(),
        "expires_at": 0,
        "memo": "",
        "days_left": None,
        # 已联网确认过时，本次离线可用的截止时间；0 表示未启用联网确认。
        "offline_until": 0,
        # 未激活且本机存在失效授权时，向激活页解释原因；正常未激活为空串。
        "issue": issue,
    }
    if payload:
        expires_at = int(payload.get("exp") or 0)
        result["expires_at"] = expires_at
        result["memo"] = str(payload.get("memo") or "")
        if expires_at:
            result["days_left"] = max(0, int((expires_at - time.time()) // 86400) + 1)
        if _cached_confirmation:
            result["offline_until"] = int(_cached_confirmation.get("not_after") or 0)
    return result


def state() -> dict:
    """授权状态，供 /api/license/status 与前端门禁使用。"""
    with _license_lock:
        _ensure_loaded()
        return _state_unlocked()


def _ensure_heartbeat(code: str, device: str) -> None:
    """启动后台心跳（每进程一个）：定期复查吊销/换机状态并续租。"""
    global _heartbeat_running
    with _heartbeat_lock:
        if _heartbeat_running:
            return
        _heartbeat_running = True
        _heartbeat_stop.clear()
    threading.Thread(target=_heartbeat_loop, args=(normalize_code(code), device), daemon=True).start()


def _heartbeat_loop(code: str, device: str) -> None:
    global _heartbeat_running
    try:
        while not _heartbeat_stop.is_set():
            outcome = _heartbeat_once(code, device)
            if outcome not in {"active", "network"}:
                return
            if _heartbeat_stop.wait(_HEARTBEAT_INTERVAL):
                return
    finally:
        with _heartbeat_lock:
            _heartbeat_running = False


def _heartbeat_once(code: str, device: str) -> str:
    """一次心跳：active 表示续租成功，network 表示暂时连不上，其余为服务端判定失效。"""
    global _cached_payload, _cached_confirmation
    try:
        envelope = _post("/v1/heartbeat", {
            "code": code,
            "device_id": device,
            "nonce": secrets.token_hex(8),
        })
        confirmation = _open_envelope(envelope)
    except LicenseError:
        return "network"
    status = str(confirmation.get("status") or "")
    if status != "active":
        with _license_lock:
            _cached_payload = None
            _cached_confirmation = None
            _record_issue(_status_message(status))
        return status
    with _license_lock:
        try:
            data = json.loads(license_path().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return "stop"
        if not isinstance(data, dict) or _fingerprint(str(data.get("code") or "")) != _fingerprint(code):
            return "stop"
        data.update({"lease": envelope, "last_heartbeat": time.time(), "device": device})
        try:
            _save_state(data)
        except OSError:
            pass
        _cached_confirmation = confirmation
    return "active"


def activate(code: str) -> dict:
    """校验并保存激活码；首次激活必须联网确认（失败抛 LicenseError）。"""
    with _license_lock:
        payload = verify_code(code)
        now = time.time()
        confirmation = None
        device = ""
        data = {"code": normalize_code(code), "last_seen": now}
        if server_url():
            device = device_id()
            try:
                result = _request_activation(code, device, payload)
            except LicenseServerUnreachable as exc:
                raise LicenseError("首次激活需要联网确认，请检查网络后重试。") from exc
            confirmation = result["confirmation"]
            data.update({"lease": result["envelope"], "device": device, "last_heartbeat": now})
        _save_state(data)
        global _loaded, _cached_payload, _cached_confirmation, _last_issue
        _loaded = True
        _cached_payload = payload
        _cached_confirmation = confirmation
        _last_issue = ""
        _log_event(f"激活成功：memo={payload.get('memo') or '—'} 机器码={machine_code()}")
        if device:
            _ensure_heartbeat(normalize_code(code), device)
        return _state_unlocked()


def deactivate() -> None:
    """删除本机授权（换机转移前使用），并停止后台心跳。"""
    _heartbeat_stop.set()
    with _license_lock:
        global _loaded, _cached_payload, _cached_confirmation, _last_issue
        _loaded = True
        _cached_payload = None
        _cached_confirmation = None
        _last_issue = ""
        try:
            license_path().unlink()
        except FileNotFoundError:
            pass


def require_activated() -> None:
    """关键业务入口的独立校验点；未激活抛 LicenseError。"""
    if not is_activated():
        raise LicenseError("软件未激活，请先在激活页输入激活码。")
