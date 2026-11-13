"""独立的商品详情浏览器进程。

入库流程使用一个带 CDP 端口和登录 profile 的 Chromium。商品详情查看
需要与这个浏览器隔离，避免打开详情页时切换入库页面、复用登录 profile，
或被入库任务的标签页清理逻辑误关。因此这里维护一个单独的 Chromium 根
进程、调试端口和 profile；同一桌面进程内后续的详情链接复用这个浏览器，
但不会连接入库浏览器。打开前会通过 bundled Node/Playwright CLI 同步源
浏览器的 cookies 和同源 storage，两个浏览器仍然不共享 profile。
"""

from __future__ import annotations

import atexit
import json
import os
import socket
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from . import paths
from .session_sync import sync_login_session


DETAIL_PROFILE_DIRNAME = "detail-browser-profile"
DETAIL_HOST = "127.0.0.1"
DETAIL_ALLOWED_SUFFIXES = (".taobao.com", ".tmall.com", ".tmall.hk")
DETAIL_LOGIN_HOSTS = {
    "login.taobao.com",
    "login.tmall.com",
    "loginmyseller.taobao.com",
    "login.m.taobao.com",
    "passport.taobao.com",
}

_DETAIL_LOCK = threading.RLock()
_DETAIL_PROCESS: subprocess.Popen | None = None
_DETAIL_PORT = 0
_DETAIL_PROFILE: Path | None = None
_DETAIL_BROWSER: Path | None = None


def _url_host(url: str) -> str:
    try:
        return (urlparse(str(url)).hostname or "").lower().rstrip(".")
    except ValueError:
        return ""


def is_allowed_item_url(url: str) -> bool:
    """Only permit Taobao/Tmall HTTP(S) pages for the detail browser."""

    target = str(url or "").strip()
    try:
        parsed = urlparse(target)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    host = _url_host(target)
    if not host or host in DETAIL_LOGIN_HOSTS:
        return False
    return host in {"taobao.com", "tmall.com"} or any(
        host.endswith(suffix) for suffix in DETAIL_ALLOWED_SUFFIXES
    )


def _session_sync_error(result: dict) -> str:
    reason = str(result.get("reason") or "")
    if reason == "not_logged_in":
        return "入库浏览器尚未登录，请先完成店铺登录"
    if reason == "redirected_to_login":
        return "入库浏览器登录态已失效，请先完成店铺登录"
    if reason == "source_unavailable":
        return "无法连接入库浏览器，请先启动并保持入库浏览器登录"
    return "无法同步入库浏览器登录状态，请确认入库浏览器已启动且保持登录"


def _detail_profile() -> Path:
    configured = str(os.environ.get("QIANNIU_DETAIL_PROFILE") or "").strip()
    profile = Path(configured).expanduser() if configured else paths.appdata_dir() / DETAIL_PROFILE_DIRNAME
    source = os.environ.get("QIANNIU_PROFILE") or paths.load_settings().chrome_profile
    if source and profile.resolve() == Path(source).expanduser().resolve():
        raise RuntimeError("商品详情浏览器必须使用独立目录，不能复用入库浏览器的登录目录")
    profile.mkdir(parents=True, exist_ok=True)
    return profile


def _detail_browser() -> Path:
    """Prefer the application's bundled Chromium over a user browser."""

    configured = str(os.environ.get("QIANNIU_DETAIL_CHROME") or "").strip()
    if configured and Path(configured).is_file():
        return Path(configured)
    bundled = paths.bundled_browser_path()
    if bundled:
        return bundled
    if not paths.is_frozen():
        staged = paths.project_root() / ".work" / "desktop-runtime" / "browser" / "chromium" / "chrome.exe"
        if staged.is_file():
            return staged
    # Source checkouts without the staged runtime still get the same resolver
    # used by the desktop preflight as a development fallback.
    resolved = paths.browser_exe_path()
    if resolved:
        return resolved
    raise RuntimeError("未找到程序内置 Chromium，无法打开商品详情")


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((DETAIL_HOST, 0))
        return int(sock.getsockname()[1])


def _launch_args(browser: Path, profile: Path, port: int, url: str = "") -> list[str]:
    args = [
        str(browser),
        f"--user-data-dir={profile}",
        f"--remote-debugging-address={DETAIL_HOST}",
        f"--remote-debugging-port={int(port)}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        "--disable-background-timer-throttling",
        "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        "--disable-features=CalculateNativeWinOcclusion",
    ]
    bundled_candidates = [
        paths.bundled_browser_path(),
        paths.project_root() / ".work" / "desktop-runtime" / "browser" / "chromium" / "chrome.exe",
    ]
    if any(candidate and Path(candidate).resolve() == browser.resolve() for candidate in bundled_candidates):
        # Match the application's filling-browser / Playwright launch options
        # for its Chrome for Testing runtime. Leave custom/system Chrome alone.
        args.append("--no-sandbox")
    if url:
        args.append(url)
    return args


def _spawn_kwargs() -> dict:
    kwargs = {
        "stdin": subprocess.DEVNULL,
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = (
            getattr(subprocess, "DETACHED_PROCESS", 0x00000008)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0x00000200)
        )
    else:
        kwargs["start_new_session"] = True
    return kwargs


def _process_alive(process: subprocess.Popen | None) -> bool:
    if process is None:
        return False
    try:
        return process.poll() is None
    except (AttributeError, OSError):
        return False


def _debug_endpoint(port: int, path: str, *, timeout: float = 0.35, method: str = "GET") -> bytes:
    request = Request(f"http://{DETAIL_HOST}:{int(port)}{path}", method=method)
    with urlopen(request, timeout=timeout) as response:
        return response.read()


def _wait_for_debug_endpoint(port: int, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        try:
            payload = _debug_endpoint(port, "/json/version")
            info = json.loads(payload.decode("utf-8", errors="replace"))
            # Merely finding an HTTP listener on the selected port is not
            # enough: a race with another local service must not be reported
            # as a started Chromium instance.
            if isinstance(info, dict) and info.get("webSocketDebuggerUrl"):
                return True
        except Exception:
            pass
        time.sleep(0.05)
    return False


def _debug_targets(port: int) -> list[dict]:
    try:
        payload = _debug_endpoint(port, "/json/list", timeout=0.5)
        targets = json.loads(payload.decode("utf-8", errors="replace"))
    except Exception:
        return []
    return [item for item in targets if isinstance(item, dict)] if isinstance(targets, list) else []


def _target_is_open(port: int, url: str) -> bool:
    target = str(url or "").strip()
    if not target:
        return False
    # A product page may append a fragment or tracking query while loading;
    # requiring the requested URL to remain part of the target still rejects
    # an unrelated page while allowing that normal navigation detail.
    return any(target == str(item.get("url") or "") or target in str(item.get("url") or "")
               for item in _debug_targets(port))


def _wait_for_target(port: int, url: str, timeout: float = 3.0) -> bool:
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if _target_is_open(port, url):
            return True
        time.sleep(0.05)
    return False


def _open_new_tab(port: int, url: str) -> bool:
    encoded = quote(str(url), safe=":/?=&%#")
    path = "/json/new?" + encoded
    # Chromium versions differ on whether /json/new accepts PUT or GET.
    for method in ("PUT", "GET"):
        try:
            payload = _debug_endpoint(port, path, timeout=3.0, method=method)
            try:
                result = json.loads(payload.decode("utf-8", errors="replace"))
            except (TypeError, ValueError, UnicodeDecodeError):
                continue
            opened = str(result.get("url") or "") if isinstance(result, dict) else ""
            if opened and (opened == str(url) or str(url) in opened):
                return True
        except Exception:
            continue
    return False


def _spawn_fallback_tab(browser: Path, profile: Path, port: int, url: str) -> bool:
    """Ask Chromium to open a tab when its CDP endpoint is temporarily busy."""

    try:
        process = subprocess.Popen(_launch_args(browser, profile, port, url), **_spawn_kwargs())
    except OSError:
        return False
    # If the existing browser owns this profile, Chromium hands the URL to its
    # root process and exits quickly.  A successful Popen alone is not proof
    # that the page was opened: wait for the requested target to appear in the
    # CDP target list and reject a non-zero launcher exit code.
    deadline = time.monotonic() + 3.0
    while time.monotonic() < deadline:
        returncode = process.poll()
        if returncode is not None and returncode != 0:
            return False
        if _target_is_open(port, url):
            return True
        time.sleep(0.05)
    return False


def _start_browser(url: str = "") -> tuple[subprocess.Popen, int, Path, Path, bool]:
    browser = _detail_browser()
    if not browser.is_file():
        raise RuntimeError(f"未找到程序内置 Chromium: {browser}")
    profile = _detail_profile()
    port = _pick_free_port()
    try:
        process = subprocess.Popen(
            _launch_args(browser, profile, port, url),
            **_spawn_kwargs(),
        )
    except OSError as exc:
        raise RuntimeError(f"无法启动商品详情浏览器: {exc}") from exc
    global _DETAIL_PROCESS, _DETAIL_PORT, _DETAIL_PROFILE, _DETAIL_BROWSER
    _DETAIL_PROCESS = process
    _DETAIL_PORT = port
    _DETAIL_PROFILE = profile
    _DETAIL_BROWSER = browser
    # Starting with the URL does not require the endpoint to be ready before
    # returning internally, but a failed launch must not be reported as an
    # apparently successful open.
    ready = _wait_for_debug_endpoint(port)
    if not ready or not _process_alive(process):
        try:
            if _process_alive(process):
                process.terminate()
                process.wait(timeout=1.0)
        except Exception:
            pass
        _DETAIL_PROCESS = None
        _DETAIL_PORT = 0
        _DETAIL_PROFILE = None
        _DETAIL_BROWSER = None
        raise RuntimeError("商品详情浏览器启动后未就绪")
    return process, port, profile, browser, ready


def open_item_url(url: str) -> dict:
    """Open one item URL in the dedicated built-in Chromium process.

    A new root process starts on ``about:blank`` so the source login state can
    be copied before the first product navigation. Existing detail processes
    refresh cookies before each new tab, which also handles a source account
    switch without reusing stale detail cookies.
    """

    target = str(url or "").strip()
    if not is_allowed_item_url(target):
        raise RuntimeError("无法打开该商品链接")
    global _DETAIL_PROCESS, _DETAIL_PORT, _DETAIL_PROFILE, _DETAIL_BROWSER
    with _DETAIL_LOCK:
        reused = _process_alive(_DETAIL_PROCESS)
        ready = True
        sync_result: dict = {
            "ok": False,
            "source_available": False,
            "applied": False,
            "cookies": 0,
            "origins": 0,
        }
        if not reused:
            _DETAIL_PROCESS = None
            _DETAIL_PORT = 0
            _DETAIL_PROFILE = None
            _DETAIL_BROWSER = None
            process, port, profile, browser, ready = _start_browser("")
            sync_result = sync_login_session(
                f"http://{DETAIL_HOST}:{int(port)}",
                navigate_url=target,
            )
            if not sync_result.get("ok") or not sync_result.get("navigated"):
                # Do not report a detail page as opened when its session was
                # not synchronized. A login page here would look like a
                # browser bug and could tempt the caller to submit credentials
                # in the wrong isolated context.
                close_detail_browser()
                raise RuntimeError(_session_sync_error(sync_result))
        else:
            process = _DETAIL_PROCESS
            port = _DETAIL_PORT
            profile = _DETAIL_PROFILE or _detail_profile()
            browser = _DETAIL_BROWSER or _detail_browser()
            # Sync from the current filling browser on every navigation. The
            # sync helper only reads source pages and does not select, close,
            # reload, or otherwise mutate any filling tab.
            sync_result = sync_login_session(f"http://{DETAIL_HOST}:{int(port)}")
            if not sync_result.get("ok") or not sync_result.get("applied"):
                raise RuntimeError(_session_sync_error(sync_result))
            if not _open_new_tab(port, target):
                # Keep the root process isolated even when a transient CDP
                # failure forces Chromium's normal single-profile handoff.
                ready = _spawn_fallback_tab(browser, profile, port, target)
                if not ready:
                    raise RuntimeError("商品详情浏览器未能打开新标签页")
        pid = int(getattr(process, "pid", 0) or 0)
        return {
            "ok": True,
            "url": target,
            "via": "builtin-browser",
            "process_id": pid,
            "port": int(port),
            "profile": str(profile),
            "reused": reused,
            "ready": bool(ready),
            "session_sync": sync_result,
        }


def close_detail_browser(timeout: float = 3.0) -> bool:
    """Close only the dedicated detail browser process owned by this module."""

    global _DETAIL_PROCESS, _DETAIL_PORT, _DETAIL_PROFILE, _DETAIL_BROWSER
    with _DETAIL_LOCK:
        process = _DETAIL_PROCESS
        if not process:
            return False
        pid = int(getattr(process, "pid", 0) or 0)
        closed = False
        if _process_alive(process):
            if os.name == "nt" and pid:
                try:
                    taskkill_kwargs = {
                        "stdout": subprocess.DEVNULL,
                        "stderr": subprocess.DEVNULL,
                        "timeout": max(0.1, float(timeout)),
                    }
                    result = subprocess.run(
                        ["taskkill", "/PID", str(pid), "/T", "/F"],
                        **taskkill_kwargs,
                    )
                    closed = result.returncode == 0
                    try:
                        process.wait(timeout=max(0.1, float(timeout)))
                    except Exception:
                        pass
                except Exception:
                    closed = False
            else:
                try:
                    process.terminate()
                    process.wait(timeout=max(0.1, float(timeout)))
                    closed = True
                except Exception:
                    try:
                        process.kill()
                        process.wait(timeout=1.0)
                        closed = True
                    except Exception:
                        closed = False
        _DETAIL_PROCESS = None
        _DETAIL_PORT = 0
        _DETAIL_PROFILE = None
        _DETAIL_BROWSER = None
        return closed


def detail_browser_state() -> dict:
    """Return a compact diagnostic snapshot without starting a process."""

    with _DETAIL_LOCK:
        process = _DETAIL_PROCESS
        return {
            "running": _process_alive(process),
            "process_id": int(getattr(process, "pid", 0) or 0) if process else 0,
            "port": int(_DETAIL_PORT or 0),
            "profile": str(_DETAIL_PROFILE or ""),
            "browser": str(_DETAIL_BROWSER or ""),
        }


atexit.register(close_detail_browser)


__all__ = [
    "close_detail_browser",
    "detail_browser_state",
    "is_allowed_item_url",
    "open_item_url",
]
