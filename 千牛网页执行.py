import importlib.util
import json
import ntpath
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import webbrowser
from contextlib import nullcontext
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

SESSION = "taobao"
CATEGORY_ENTRY = "https://item.upload.taobao.com/sell/ai/category.htm"
SELLER_HOME = "https://myseller.taobao.com/"


def _env_path(name, fallback):
    raw = os.environ.get(name)
    return Path(raw) if raw else fallback


def detect_chrome():
    override = os.environ.get("QIANNIU_CHROME") or os.environ.get("CHROME_PATH")
    if override and Path(override).is_file():
        return Path(override)
    module_dir = Path(__file__).resolve().parent
    candidates = [module_dir / "browser" / "chromium" / "chrome.exe"]
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(key)
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    candidates.extend(
        [
            Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
            Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
        ]
    )
    try:
        import winreg

        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe",
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
            if value:
                candidates.insert(0, Path(value))
    except OSError:
        pass
    for path in candidates:
        if path.is_file():
            return path
    return candidates[0] if candidates else Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")


def _appdata_home():
    override = os.environ.get("QIANNIU_APPDATA")
    if override:
        return Path(override)
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "千牛自动上架"


def reload_paths():
    global ROOT, MAPPING_PATH, REMOTE_CONFIG, CLI_CONFIG, CLI_JS, OUTPUT_DIR
    global CDP_ENDPOINT, CDP_PORT, CHROME, PROFILE
    ROOT = _env_path("QIANNIU_ROOT", Path(__file__).resolve().parent)
    PROFILE = _env_path("QIANNIU_PROFILE", _appdata_home() / "chrome-profile")
    OUTPUT_DIR = _env_path("QIANNIU_OUTPUT_DIR", _appdata_home() / "logs" / "playwright")
    mapping = os.environ.get("QIANNIU_MAPPING")
    MAPPING_PATH = Path(mapping) if mapping else ROOT / "千牛字段映射.json"
    REMOTE_CONFIG = ROOT / ".playwright" / "remote.config.json"
    CLI_CONFIG = ROOT / ".playwright" / "cli.config.json"
    bundled_cli = ROOT / "playwright-core" / "lib" / "tools" / "cli-client" / "cli.js"
    work_cli = ROOT / ".work" / "node_modules" / "playwright-core" / "lib" / "tools" / "cli-client" / "cli.js"
    CLI_JS = _env_path("QIANNIU_CLI_JS", bundled_cli if bundled_cli.is_file() else work_cli)
    try:
        CDP_PORT = int(os.environ.get("QIANNIU_CDP_PORT") or 9222)
    except ValueError:
        CDP_PORT = 9222
    CDP_ENDPOINT = f"http://127.0.0.1:{CDP_PORT}"
    chrome = detect_chrome()
    CHROME = chrome if chrome else Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
    _try_restore_desktop_job()


def _try_restore_desktop_job():
    try:
        here = Path(__file__).resolve().parent
        exe_dir = Path(sys.executable).resolve().parent
        for folder in (here, exe_dir):
            if str(folder) not in sys.path:
                sys.path.insert(0, str(folder))
            candidate = folder / "job_session.py"
            if candidate.is_file() and "job_session" not in sys.modules:
                spec = importlib.util.spec_from_file_location("job_session", candidate)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                sys.modules["job_session"] = module
                spec.loader.exec_module(module)
        import job_session
        job_session.restore_desktop_manager()
    except Exception:
        pass


reload_paths()
PUBLISH_PREFIX = "https://item.upload.taobao.com/sell/v2/publish.htm"
CHROME_ANTI_THROTTLE_ARGS = (
    "--disable-background-timer-throttling",
    "--disable-renderer-backgrounding",
    "--disable-backgrounding-occluded-windows",
    # 屏幕外（完全不可见区域）的窗口会被原生遮挡检测判为遮挡，禁用后
    # "移出屏幕但保持可见"的隐藏窗口才能持续渲染动画帧。
    "--disable-features=CalculateNativeWinOcclusion",
)
OFFSCREEN_POS = (-32000, -32000)
_CHROME_PLACEMENTS = {}
_CHROME_EXSTYLES = {}
_CHROME_START_LOCK = threading.RLock()
_BROWSER_REGISTRY_PATHS = set()
_CHROME_PROC = None
_CHROME_ROOT_PID = 0
_CHROME_SESSION_PREFS_KEY = None
EDIT_MARKERS = ("itemid=", "item_num_id=", "/edit.htm", "/subitem/publish.htm")
ALLOWED_ITEM_ID = "1085558349142"
LOGIN_MARKERS = ("login.taobao.com", "login.tmall.com", "loginmyseller.taobao.com")
LOGIN_HOSTS = (
    "login.taobao.com",
    "login.tmall.com",
    "loginmyseller.taobao.com",
    "login.m.taobao.com",
    "passport.taobao.com",
)
SELLER_HOSTS = ("myseller.taobao.com", "item.upload.taobao.com", "qn.taobao.com")
BLOCKER_TEXTS = ("请登录", "扫码登录", "验证码", "请完成验证", "滑块", "请拖动", "请按住滑块")
SELLER_ACCOUNT_HOME = "https://myseller.taobao.com/home.htm"
NODE_RE = re.compile(
    r'^\s*-\s+(?P<role>radio|textbox|button|tab|combobox|checkbox|listitem|heading|option|switch|link|generic)'
    r'(?:\s+"(?P<name>[^"]*)")?'
    r'(?P<attrs>(?:\s+\[[^\]]+\])*)'
    r'(?::\s*(?P<text>.*))?$'
)

# ``Browser.close()`` on a Playwright ``connectOverCDP`` handle only detaches
# the Playwright transport.  During application shutdown we need Chromium's
# own CDP command so it can flush the profile and exit normally.  The helper
# receives only endpoint/package metadata; it never reads or emits page data.
_GRACEFUL_CLOSE_SCRIPT = r'''
"use strict";
const chunks = [];
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => chunks.push(chunk));
process.stdin.on("end", () => {
  let input;
  try { input = JSON.parse(chunks.join("")); }
  catch (_) { emit(false); return; }
  closeBrowser(input).then(emit).catch(() => emit(false));
});

function emit(ok) {
  try { process.stdout.write(JSON.stringify({ ok: Boolean(ok) })); }
  catch (_) {}
}

async function closeBrowser(input) {
  let browser;
  try {
    const playwright = require(String(input.playwrightPath || ""));
    browser = await playwright.chromium.connectOverCDP(String(input.endpoint || ""), { timeout: 3000 });
    const contexts = browser.contexts();
    if (!contexts.length) return false;
    const context = contexts[0];
    let pages = context.pages();
    const page = pages[0] || await context.newPage();
    const session = await context.newCDPSession(page);
    // This is Chromium's normal shutdown command. It is distinct from
    // Playwright Browser.close(), which only disconnects a CDP attachment.
    await session.send("Browser.close");
    return true;
  } catch (_) {
    return false;
  } finally {
    try { await browser?.close(); } catch (_) {}
  }
}
'''

# Startup preferences are protected by Chromium. Editing Preferences on disk
# can leave a value of 1 there while the running browser has reset it to 5.
# Set and verify the preference through Chromium itself, without touching any
# cookies, account pages or the preference integrity metadata.
_SESSION_PREFS_SCRIPT = r'''
"use strict";
const chunks = [];
process.stdin.setEncoding("utf8");
process.stdin.on("data", chunk => chunks.push(chunk));
process.stdin.on("end", () => {
  let input;
  try { input = JSON.parse(chunks.join("")); }
  catch (_) { emit({ ok: false, reason: "invalid_input" }); return; }
  configure(input).then(emit).catch(() => emit({ ok: false, reason: "unavailable" }));
});
function emit(result) { process.stdout.write(JSON.stringify(result)); }
async function configure(input) {
  let browser, page;
  try {
    const { chromium } = require(input.playwrightPath);
    browser = await chromium.connectOverCDP(input.endpoint, { timeout: 4000 });
    const context = browser.contexts()[0];
    if (!context?.pages().length) return { ok: false, reason: "no_window" };
    page = await context.newPage();
    await page.goto("chrome://settings/onStartup", { timeout: 8000 });
    await page.waitForFunction(() => Boolean(globalThis.chrome?.settingsPrivate), null, { timeout: 5000 });
    return await page.evaluate(async () => {
      const api = chrome.settingsPrivate;
      const name = "session.restore_on_startup";
      const get = () => new Promise(resolve => api.getPref(name, resolve));
      const pref = await get();
      if (!pref) return { ok: false, reason: "missing_pref" };
      if (pref.value !== 1) {
        if (pref.enforcement === "ENFORCED") return { ok: false, reason: "policy_locked" };
        const success = await new Promise(resolve => api.setPref(name, 1, "", resolve));
        if (!success) return { ok: false, reason: "write_failed" };
      }
      const actual = await get();
      return actual?.value === 1
        ? { ok: true, value: 1 }
        : { ok: false, reason: "verify_failed" };
    });
  } finally {
    try { await page?.close(); } catch (_) {}
    // On a CDP attachment this only disconnects Playwright.
    try { await browser?.close(); } catch (_) {}
  }
}
'''

class SessionLost(RuntimeError):
    pass


class UnsafeUrl(RuntimeError):
    pass


class PauseForUser(RuntimeError):
    pass


class CliInterrupted(RuntimeError):
    """cancel_event 触发时中断当前 CLI 调用。

    消息必须带 PAUSE: 前缀：pipeline 按 "PAUSE:" 字样把异常分诊为
    "暂停"（保留现场、不重试），而不是普通失败。
    """

    def __init__(self, message=""):
        super().__init__(message or INTERRUPT_PAUSE_MESSAGE)


# 暂停中断的默认文案：不含 登录/验证码/滑块 等硬暂停词，避免被误分类；
# 含"用户"字样，供并发批次把用户停止的条目归为"已停止"。
INTERRUPT_PAUSE_MESSAGE = "PAUSE:用户已暂停；已中断当前页面操作并保留现场，点击继续可接着填写"


def load_mapping():
    return json.loads(MAPPING_PATH.read_text(encoding="utf-8"))


def leaf_name(category):
    text = str(category or "").replace(">>", ">").strip()
    return text.split(">")[-1].strip() if text else ""


def category_id_for(category, mapping=None):
    mapping = mapping or load_mapping()
    leaf = leaf_name(category)
    profiles = mapping.get("category_profiles") or {}
    for name, profile in profiles.items():
        if name == leaf or name in str(category):
            return str(profile.get("category_id") or "")
    if leaf == "修正带":
        return str(mapping.get("category_id") or "")
    return ""


def cdp_available(timeout=0.25):
    # 状态轮询每 1.2 秒调用一次本函数；预算必须给 /api/status 留出
    # 前端超时（10 秒）以内的余量，Chrome 繁忙时也不能拖垮轮询。
    try:
        with socket.create_connection(("127.0.0.1", CDP_PORT), timeout=timeout):
            return True
    except OSError:
        return False


def url_host(url):
    try:
        return (urlparse(url or "").hostname or "").lower()
    except ValueError:
        return ""


def is_login_url(url):
    host = url_host(url)
    if not host:
        return False
    if host in LOGIN_HOSTS:
        return True
    if host.startswith("login") and (host.endswith(".taobao.com") or host.endswith(".tmall.com")):
        return True
    return False


def is_seller_url(url):
    if is_login_url(url):
        return False
    host = url_host(url)
    if not host:
        return False
    for mark in SELLER_HOSTS:
        if host == mark or host.endswith("." + mark):
            return True
    return False


def is_allowed_item_url(url):
    text = str(url or "").strip()
    parsed = urlparse(text)
    if parsed.scheme not in {"http", "https"}:
        return False
    if is_login_url(text):
        return False
    host = url_host(text)
    if not host:
        return False
    suffixes = (".taobao.com", ".tmall.com", ".tmall.hk")
    return host in {"taobao.com", "tmall.com"} or any(host.endswith(suffix) for suffix in suffixes)


def open_in_default_browser(url):
    target = str(url or "").strip()
    if not target:
        return False
    if os.name == "nt":
        try:
            os.startfile(target)  # type: ignore[attr-defined]
            return True
        except OSError:
            pass
    return bool(webbrowser.open(target, new=2))


def open_item_url(url):
    target = str(url or "").strip()
    if not is_allowed_item_url(target):
        raise RuntimeError("无法打开该商品链接")
    try:
        prune_automation_tabs()
    except Exception:
        pass
    if not open_in_default_browser(target):
        raise RuntimeError("无法用系统默认浏览器打开该链接")
    return {"ok": True, "url": target, "via": "default-browser"}


def open_item_url_in_builtin_browser(url):
    """Open a product page in the isolated Chromium used for detail viewing.

    The normal ``open_item_url`` API remains the compatibility entry point for
    callers that explicitly want the system browser.  The desktop item action
    uses this separate entry point so it cannot reuse the filling browser's
    profile or CDP port.
    """
    from desktop.detail_browser import open_item_url

    return open_item_url(url)


def _read_json_file(path):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError, TypeError):
        return None
    return data if isinstance(data, dict) else None


def _write_json_file(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def profile_has_saved_session(profile=None):
    default = Path(profile or PROFILE) / "Default"
    candidates = [
        default / "Network" / "Cookies",
        default / "Cookies",
        default / "Last Session",
        default / "Current Session",
        default / "Sessions",
    ]
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_size > 0:
                return True
            if path.is_dir() and any(path.iterdir()):
                return True
        except OSError:
            continue
    return False


def ensure_chrome_session_prefs(profile=None):
    """Prepare the profile directory; protected preferences need a live browser."""
    profile = Path(profile or PROFILE)
    profile.mkdir(parents=True, exist_ok=True)
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    try:
        (profile / "First Run").touch(exist_ok=True)
    except OSError:
        pass


def chrome_launch_args(chrome=None, profile=None, port=None, url=None):
    reload_paths()
    chrome = Path(chrome or CHROME)
    profile = Path(profile or PROFILE)
    port = int(port or CDP_PORT)
    profile.mkdir(parents=True, exist_ok=True)
    ensure_chrome_session_prefs(profile)
    args = [
        str(chrome),
        f"--user-data-dir={profile}",
        f"--remote-debugging-port={port}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--hide-crash-restore-bubble",
        *CHROME_ANTI_THROTTLE_ARGS,
    ]
    bundled = ROOT / "browser" / "chromium" / "chrome.exe"
    try:
        if chrome.resolve() == bundled.resolve():
            # Playwright's Chrome for Testing build is distributed for automation
            # and requires the same sandbox opt-out used by Playwright launchers.
            args.append("--no-sandbox")
    except OSError:
        pass
    if url:
        args.append(url)
    elif profile_has_saved_session(profile):
        args.append("--restore-last-session")
    return args


def _hidden_subprocess_kwargs():
    env = os.environ.copy()
    env["NO_COLOR"] = "1"
    env["FORCE_COLOR"] = "0"
    env["TERM"] = "dumb"
    kwargs = {"env": env, "stdin": subprocess.DEVNULL}
    if os.name == "nt":
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0
        kwargs["startupinfo"] = startupinfo
        kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    return kwargs


def _spawn_chrome(hidden=False):
    global _CHROME_PROC, _CHROME_ROOT_PID
    if not CHROME.is_file():
        raise RuntimeError(f"未找到 Chrome: {CHROME}")
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        # 不用 STARTF_USESHOWWINDOW 的 SW_HIDE：SW_HIDE 过的窗口 Chrome 停止
        # 渲染动画帧，自动化点击必超时。隐藏靠 --window-position 移出屏幕 +
        # hide_automation_chrome 的 TOOLWINDOW 样式，窗口保持可见。
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    args = chrome_launch_args()
    if hidden:
        args.append(f"--window-position={OFFSCREEN_POS[0]},{OFFSCREEN_POS[1]}")
    _CHROME_PROC = subprocess.Popen(args, **kwargs)
    _CHROME_ROOT_PID = int(_CHROME_PROC.pid or 0)


def _native_process_command_line(pid):
    """Read a Windows process command line as Unicode without PowerShell/WMI."""
    if os.name != "nt" or not pid:
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        class UNICODE_STRING(ctypes.Structure):
            _fields_ = [("Length", wintypes.USHORT), ("MaximumLength", wintypes.USHORT),
                        ("Buffer", ctypes.c_void_p)]

        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle.restype = wintypes.BOOL
        query = ctypes.WinDLL("ntdll").NtQueryInformationProcess
        query.argtypes = [wintypes.HANDLE, wintypes.ULONG, ctypes.c_void_p,
                          wintypes.ULONG, ctypes.POINTER(wintypes.ULONG)]
        query.restype = wintypes.LONG
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.ULONG()
            query(handle, 60, None, 0, ctypes.byref(size))  # ProcessCommandLineInformation
            if not ctypes.sizeof(UNICODE_STRING) <= size.value <= 1024 * 1024:
                return ""
            buffer = ctypes.create_string_buffer(size.value)
            if query(handle, 60, buffer, len(buffer), ctypes.byref(size)) < 0:
                return ""
            value = UNICODE_STRING.from_buffer(buffer)
            start = int(value.Buffer or 0)
            lower = ctypes.addressof(buffer) + ctypes.sizeof(UNICODE_STRING)
            upper = ctypes.addressof(buffer) + len(buffer)
            if not value.Length or value.Length % 2 or not lower <= start <= upper - value.Length:
                return ""
            return ctypes.string_at(start, value.Length).decode("utf-16-le")
        finally:
            kernel32.CloseHandle(handle)
    except (OSError, AttributeError, TypeError, ValueError, UnicodeError):
        return ""


def _process_command_line(pid):
    """读取 Windows 进程命令行；失败时返回空字符串。"""
    if os.name != "nt" or not pid:
        return ""
    command = _native_process_command_line(pid)
    if command:
        return command
    try:
        # 只查询一个已知 PID，并不遍历或结束其他进程。
        script = (
            "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false); "
            "(Get-CimInstance Win32_Process -Filter 'ProcessId = "
            + str(int(pid))
            + "').CommandLine"
        )
        return subprocess.check_output(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=3,
            **_hidden_subprocess_kwargs(),
        ).strip()
    except Exception:
        return ""


def _is_automation_chrome_command(command_line):
    # Match whole arguments, including quoted paths. Substring checks accept
    # profile-other / port 92221 and reject equivalent slash-normalized paths.
    text = str(command_line or "")
    if text.count('"') % 2:
        return False
    args = [part.replace('"', "") for part in re.findall(r'(?:[^\s"]|"[^"]*")+', text)]
    switches = {}
    for index, arg in enumerate(args):
        name, sep, value = arg.partition("=")
        if name not in {"--user-data-dir", "--remote-debugging-port"}:
            continue
        if name in switches:
            return False
        if not sep:
            value = args[index + 1] if index + 1 < len(args) else ""
        switches[name] = value
    profile = switches.get("--user-data-dir")
    return bool(profile and ntpath.normcase(ntpath.normpath(profile))
                == ntpath.normcase(ntpath.normpath(str(PROFILE)))
                and switches.get("--remote-debugging-port") == str(int(CDP_PORT)))


def _adopt_connected_automation_chrome():
    """识别之前由本程序启动但尚未退出的独立 profile Chrome。"""
    global _CHROME_ROOT_PID
    with _CHROME_START_LOCK:
        root = listening_pid_on_port()
        if not root:
            return 0
        owned = _owned_chrome_root(_CHROME_PROC, _CHROME_ROOT_PID)
        if owned and (root == owned or root in process_tree_pids(owned)):
            return owned
        if not _is_automation_chrome_command(_process_command_line(root)):
            return 0
        # A browser can restart while the desktop app keeps an exited Popen
        # handle / old root PID. Drop those only after verifying the new owner.
        _clear_chrome_runtime_state()
        _CHROME_ROOT_PID = int(root)
        return _CHROME_ROOT_PID


def _owned_chrome_root(proc=None, root_pid=0):
    """Return a root PID only while its ownership boundary is verifiable."""

    candidate = 0
    if proc is not None:
        try:
            if proc.poll() is not None:
                return 0
            candidate = int(proc.pid or 0)
        except (AttributeError, TypeError, ValueError, OSError):
            return 0
        # A live Popen handle belongs to this process.  If Windows lets us
        # read its command line, still require the configured profile and CDP
        # port to match; an empty query is treated as an unavailable probe.
        command = _process_command_line(candidate)
        if command and not _is_automation_chrome_command(command):
            return 0
    else:
        try:
            candidate = int(root_pid or 0)
        except (TypeError, ValueError):
            return 0
        if not candidate or not _is_automation_chrome_command(_process_command_line(candidate)):
            return 0
    if not candidate:
        return 0
    try:
        recorded = int(_CHROME_ROOT_PID or 0)
    except (TypeError, ValueError):
        recorded = 0
    if recorded and recorded != candidate:
        return 0
    return candidate


def _cdp_listener_owned(root_pid):
    """Check that the configured CDP listener belongs to the owned tree."""

    try:
        listener = int(listening_pid_on_port(CDP_PORT) or 0)
    except (TypeError, ValueError, OSError):
        return False
    if not listener:
        return False
    if listener == int(root_pid):
        return True
    try:
        return listener in process_tree_pids(root_pid)
    except Exception:
        return False


def _playwright_package_path():
    try:
        candidate = Path(CLI_JS).parents[3]
    except (AttributeError, IndexError, TypeError):
        return None
    return candidate if (candidate / "index.js").is_file() else None


def ensure_chrome_runtime_session_prefs():
    """Enable session-cookie retention once per owned Chromium instance."""
    global _CHROME_SESSION_PREFS_KEY
    with _CHROME_START_LOCK:
        try:
            endpoint = cdp_version().get("webSocketDebuggerUrl", "")
        except Exception:
            endpoint = ""
        if not endpoint:
            raise RuntimeError("无法确认入库浏览器实例，登录状态保留设置未完成")
        key = (str(Path(PROFILE).resolve()), endpoint)
        if _CHROME_SESSION_PREFS_KEY == key:
            return
        root_pid = _owned_chrome_root(_CHROME_PROC, _CHROME_ROOT_PID)
        if not root_pid or not _cdp_listener_owned(root_pid):
            listener = listening_pid_on_port()
            command = _process_command_line(listener) if listener else ""
            reason = ("未找到监听进程" if not listener else
                      "无法读取监听进程启动参数" if not command else
                      "监听进程与配置的浏览器不匹配")
            raise RuntimeError(
                f"无法确认调试端口对应的入库浏览器，登录状态保留设置未完成"
                f"（端口 {CDP_PORT}，监听 PID {listener or '未知'}，{reason}；profile={PROFILE}）"
            )
        package = _playwright_package_path()
        if package is None:
            raise RuntimeError("未找到 Playwright，无法设置入库浏览器登录状态保留")
        try:
            kwargs = _hidden_subprocess_kwargs()
            kwargs.pop("stdin", None)
            kwargs.update({
                "input": json.dumps({"endpoint": endpoint, "playwrightPath": str(package)}, ensure_ascii=False),
                "capture_output": True, "text": True, "encoding": "utf-8",
                "errors": "replace", "timeout": 22,
            })
            completed = subprocess.run([str(node_executable()), "-e", _SESSION_PREFS_SCRIPT], **kwargs)
            result = json.loads(completed.stdout or "{}") if completed.returncode == 0 else {}
        except Exception:
            result = {}
        if not isinstance(result, dict) or result.get("ok") is not True or result.get("value") != 1:
            if isinstance(result, dict) and result.get("reason") == "policy_locked":
                raise RuntimeError("入库浏览器的启动设置被管理策略锁定，无法启用登录状态保留")
            raise RuntimeError("入库浏览器未能启用并确认登录状态保留，请重试打开浏览器")
        _CHROME_SESSION_PREFS_KEY = key


def _request_graceful_chrome_close(root_pid, timeout=3.0):
    """Ask the owned Chromium to flush and close through its CDP endpoint."""

    if not root_pid or not _cdp_listener_owned(root_pid):
        return False
    package = _playwright_package_path()
    if package is None:
        return False
    try:
        node = node_executable()
        payload = json.dumps(
            {
                "endpoint": f"http://127.0.0.1:{int(CDP_PORT)}",
                "playwrightPath": str(package),
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        kwargs = _hidden_subprocess_kwargs()
        # ``input=`` asks subprocess.run to create its own stdin pipe.
        kwargs.pop("stdin", None)
        kwargs.update(
            {
                "input": payload,
                "capture_output": True,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
                "timeout": max(1.0, float(timeout)),
            }
        )
        completed = subprocess.run([str(node), "-e", _GRACEFUL_CLOSE_SCRIPT], **kwargs)
        if completed.returncode != 0:
            return False
        result = json.loads(str(completed.stdout or ""))
        return isinstance(result, dict) and bool(result.get("ok"))
    except Exception:
        return False


def _wait_for_chrome_exit(proc, root_pid, timeout=3.0):
    deadline = time.monotonic() + max(0.0, float(timeout))
    while time.monotonic() < deadline:
        if proc is not None:
            try:
                if proc.poll() is not None:
                    return True
            except (AttributeError, OSError):
                return True
        else:
            try:
                if int(listening_pid_on_port(CDP_PORT) or 0) != int(root_pid):
                    return True
            except (TypeError, ValueError, OSError):
                return False
        time.sleep(0.05)
    if proc is not None:
        try:
            return proc.poll() is not None
        except (AttributeError, OSError):
            return True
    try:
        return int(listening_pid_on_port(CDP_PORT) or 0) != int(root_pid)
    except (TypeError, ValueError, OSError):
        return False


def _clear_chrome_runtime_state():
    global _CHROME_PROC, _CHROME_ROOT_PID, _CHROME_SESSION_PREFS_KEY
    _CHROME_PROC = None
    _CHROME_ROOT_PID = 0
    _CHROME_SESSION_PREFS_KEY = None
    _CHROME_PLACEMENTS.clear()
    _CHROME_EXSTYLES.clear()


def close_automation_chrome(timeout=3.0):
    """正常关闭本进程启动的 Chrome，超时后才回收其进程树。

    自动化 Chrome 使用独立 profile 和调试端口，并以 detached 模式启动，
    所以 Python 进程退出时不会由操作系统自动回收。这里只处理当前模块
    启动或明确识别为本程序独立 profile 的进程，不根据端口盲杀用户自己打开的 Chrome。
    先通过 Chromium CDP 的 ``Browser.close`` 让 profile 正常落盘；只有
    端口/进程树仍匹配同一 owned browser 且正常关闭超时，才使用强制回收。
    """
    proc = _CHROME_PROC
    if proc is not None:
        try:
            if proc.poll() is not None:
                proc = None
        except (AttributeError, OSError):
            proc = None
    if proc is None and not _CHROME_ROOT_PID:
        # 即使用户没有再次点击“打开 Chrome”，退出时也尝试接管上次
        # 异常退出留下的独立 profile；命令行不匹配时不会按端口猜测。
        _adopt_connected_automation_chrome()
    root_pid = _owned_chrome_root(proc, _CHROME_ROOT_PID)
    if not root_pid:
        return False

    # Playwright Browser.close() on a CDP attachment is only a detach. The
    # Node helper sends Chromium's own Browser.close command so cookies and
    # Preferences have a chance to be flushed before the process exits.
    _request_graceful_chrome_close(root_pid, timeout=timeout)
    # Browser.close may close the CDP transport before the Node helper can
    # serialize a success response. Always give Chromium one full graceful
    # wait window before deciding that a forceful fallback is necessary.
    if _wait_for_chrome_exit(proc, root_pid, timeout=timeout):
        if proc is not None:
            try:
                proc.wait(timeout=max(0.1, float(timeout)))
            except Exception:
                pass
        _clear_chrome_runtime_state()
        return True

    # Revalidate ownership immediately before any forceful action. A stale
    # PID or a port reused by another browser must never be taskkilled.
    root_pid = _owned_chrome_root(proc, root_pid)
    if not root_pid:
        return False

    # Chrome 会再派生 renderer/gpu 等进程；Windows 下 taskkill 的 /T
    # 能一次性结束整棵已验证的 owned 进程树，避免只关掉 browser 根进程后
    # 留下托盘进程。
    closed = False
    if root_pid:
        if os.name == "nt":
            try:
                result = subprocess.run(
                    ["taskkill", "/PID", str(root_pid), "/T", "/F"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=max(1.0, float(timeout)),
                    **_hidden_subprocess_kwargs(),
                )
                closed = result.returncode == 0
            except Exception:
                closed = False
        else:
            # 主要用于源码测试/非 Windows 开发环境。
            try:
                for pid in sorted(process_tree_pids(root_pid), reverse=True):
                    if pid == os.getpid():
                        continue
                    os.kill(pid, __import__("signal").SIGTERM)
                closed = True
            except Exception:
                closed = False

    # taskkill 可能因为 Chrome 已自行退出而返回非零；此时仍尝试回收
    # Popen 句柄，确保下次启动不会误判为仍由本进程持有。
    if proc is not None:
        try:
            proc.wait(timeout=max(0.1, float(timeout)))
        except Exception:
            try:
                if proc.poll() is None:
                    proc.terminate()
                    proc.wait(timeout=1.0)
            except Exception:
                pass
    _clear_chrome_runtime_state()
    return closed


def pick_seller_tab(tabs):
    ranked = []
    for tab in tabs or []:
        url = str(tab.get("url") or "")
        if not is_seller_url(url):
            continue
        host = url_host(url)
        rank = 0 if host == "myseller.taobao.com" or host.endswith(".myseller.taobao.com") else 1
        ranked.append((rank, tab))
    ranked.sort(key=lambda item: item[0])
    return ranked[0][1] if ranked else None


def _cdp_request(path, timeout=3, method="GET"):
    req = Request(CDP_ENDPOINT + path, method=method)
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def _cdp_get(path, timeout=3):
    return _cdp_request(path, timeout=timeout, method="GET")


def _cdp_new_tab(url, timeout=5):
    path = "/json/new?" + quote(str(url or ""), safe=":/")
    last = None
    for method in ("PUT", "GET"):
        try:
            return _cdp_request(path, timeout=timeout, method=method)
        except Exception as exc:
            last = exc
    raise RuntimeError(f"无法新建浏览器标签: {last}")


def _cdp_close_tab(tab_id, timeout=1):
    target = str(tab_id or "").strip()
    if not target:
        return b""
    return _cdp_get("/json/close/" + quote(target, safe=""), timeout=timeout)


def _page_tabs(tabs=None):
    tabs = tabs if tabs is not None else cdp_tabs()
    pages = []
    for tab in tabs or []:
        kind = str(tab.get("type") or "page").lower()
        if kind and kind != "page":
            continue
        if not tab.get("id"):
            continue
        pages.append(tab)
    return pages


def _browser_pool_module():
    """Load the ownership module without requiring ``web_fill.__init__``.

    Some packaged builds load this file before the package facade is complete;
    a direct fallback keeps the browser safety layer usable in that order.
    """
    try:
        from web_fill import browser_pool

        return browser_pool
    except Exception:
        name = "_qianniu_browser_pool"
        existing = sys.modules.get(name)
        if existing is not None:
            return existing
        path = Path(__file__).resolve().parent / "web_fill" / "browser_pool.py"
        spec = importlib.util.spec_from_file_location(name, path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"缺少浏览器页面租约模块: {path}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
        return module


def _all_registry_paths():
    """当前进程已知且可能存在的页面租约 registry 文件路径集合。

    The concurrent batch manager keeps one explicit registry beside the
    shared output root (``<output>/owned_pages.json``) and calls global
    prune before worker sessions are constructed.  Include that stable
    path even before a worker has registered it in this process.
    """
    paths = set(_BROWSER_REGISTRY_PATHS)
    paths.add(Path(OUTPUT_DIR).resolve() / "owned_pages.json")
    configured = str(os.environ.get("QIANNIU_BROWSER_REGISTRY") or "").strip()
    if configured:
        paths.add(Path(configured).resolve())
    return paths


def _protected_page_urls():
    """读取 worker registry 中所有仍归属 worker 的页面 URL。

    标签清理发生在连接层，而租约由 ``web_fill.browser_pool`` 管理；
    使用惰性导入避免浏览器模块在打包和单元测试中形成循环依赖。读取失败
    时返回空集合，清理函数仍保持原有行为。active 页面和已暂停的
    protected 页面都必须保留，避免 manager 在 worker 运行期间误关页。
    """
    try:
        pool = _browser_pool_module()
        paths = _all_registry_paths()
        paths.add(pool.default_registry_path(OUTPUT_DIR))
        owned = set()
        for path in paths:
            owned.update(pool.PageOwnershipRegistry(path).owned_urls())
        return owned
    except Exception:
        # A present but unreadable registry is a safety boundary: do not
        # assume pages are unowned and let the global cleanup close them.
        return None


def _is_protected_page_url(url, protected_urls=None):
    value = str(url or "").strip().rstrip("/")
    if not value:
        return False
    protected = protected_urls if protected_urls is not None else _protected_page_urls()
    if protected is None:
        return True
    return value in protected


def close_redundant_seller_home_tabs():
    """连接前关闭独立 Chrome 中多余的工作台首页，保留业务页和登录页。

    Playwright 会等待所有已有页面初始化；失去响应的历史首页会阻塞
    整个连接。仅当另有卖家业务页时清理确定的首页，不处理发布断点。
    """
    if not _adopt_connected_automation_chrome():
        return []
    pages = _page_tabs()
    if any(is_login_url(str(tab.get("url") or "")) for tab in pages):
        return []

    def is_home(tab):
        url = urlparse(str(tab.get("url") or ""))
        return (url.hostname or "").lower() == "myseller.taobao.com" and url.path.rstrip("/").lower() == "/home.htm/qnworkbenchhome"

    if not any(is_seller_url(str(tab.get("url") or "")) and not is_home(tab) for tab in pages):
        return []
    closed = []
    protected_urls = _protected_page_urls()
    if protected_urls is None:
        return []
    for tab in pages:
        if _is_protected_page_url(tab.get("url"), protected_urls):
            continue
        if is_home(tab):
            try:
                _cdp_close_tab(tab["id"])
                closed.append(tab["id"])
            except Exception:
                pass
    return closed


def tab_should_keep(url, keep_url=""):
    text = str(url or "").strip()
    wanted = str(keep_url or "").strip()
    if wanted and text.rstrip("/") == wanted.rstrip("/"):
        return True
    if is_login_url(text):
        return True
    host = url_host(text)
    if host == "myseller.taobao.com" or host.endswith(".myseller.taobao.com"):
        return True
    return False


def prune_automation_tabs(keep_url="", keep_fill_pages=False, tabs=None):
    """关掉调试 Chrome 里历史发布/成功/空白标签，只留卖家中心和登录页。"""
    if tabs is None and not cdp_available():
        return {"closed": 0, "kept": 0}
    pages = _page_tabs(tabs)
    keep = []
    close = []
    fill_kept = False
    cat_kept = False
    wanted = str(keep_url or "").lower()
    protected_urls = _protected_page_urls()
    if "publish.htm" in wanted:
        fill_kept = True
    if "category.htm" in wanted:
        cat_kept = True
    for tab in pages:
        url = str(tab.get("url") or "")
        low = url.lower()
        if _is_protected_page_url(url, protected_urls):
            keep.append(tab)
            continue
        if tab_should_keep(url, keep_url):
            keep.append(tab)
            continue
        if keep_fill_pages:
            if "publish.htm" in low and "itemid=" not in low and "edit.htm" not in low and not fill_kept:
                keep.append(tab)
                fill_kept = True
                continue
            if "category.htm" in low and not cat_kept:
                keep.append(tab)
                cat_kept = True
                continue
        close.append(tab)
    if not keep and close:
        keep.append(close.pop())
    closed = 0
    for tab in close:
        try:
            _cdp_close_tab(tab.get("id"))
            closed += 1
        except Exception:
            continue
    return {"closed": closed, "kept": len(keep)}


def reconcile_browser_tabs(registry_paths=None, keep_fill_pages=False):
    """无并发任务运行时的全局页签对账：清死租约、同商品去重、再跑 prune。

    浏览器进程跨任务常驻，而 prune 只能跳过所有有租约的页签，历史运行
    泄漏/遗留的页签因此永不回收。这里只处理明确安全的对象：

    - registry 中 target_id 已不在 CDP 页签列表里的租约：页签本身早已
      不存在，删除记录让保护集不再膨胀；
    - 同一商品 key 的可回收租约（parked，或 active 但记录进程已死亡）：
      保留 created_at 最新的现场页，其余关闭页签并删除记录；
    - myseller 白名单域名下完全同 URL 的重复页签（历史遗留的工作台
      首页/核验页副本）：只保留最后一个，受保护与登录页跳过；
    - 其余无主页签交给 ``prune_automation_tabs`` 按既有规则兜底（保留
      卖家中心/登录页；registry 不可读时 fail-closed 全保留）。

    active 且进程存活的租约一律不动，绝不影响正在运行或可续跑的任务；
    调用方必须保证此刻没有并发 worker 在跑（批次收尾、打开浏览器等）。
    """
    if not cdp_available():
        return {"released": 0, "closed": 0}
    live_targets = {
        str(tab.get("id") or "") for tab in _page_tabs() if tab.get("id")
    }
    if not live_targets:
        # CDP 读不到任何页签（瞬时故障/浏览器正在重启）时无法核实租约
        # 死活，宁可全部保留，不能把仍在的页签记录误删。
        return {"released": 0, "closed": 0}
    pool = _browser_pool_module()
    paths = _all_registry_paths()
    paths.add(pool.default_registry_path(OUTPUT_DIR))
    for extra in registry_paths or []:
        paths.add(str(extra))
    released = 0
    closed = 0
    registries_ok = True
    skip_targets = set()
    skip_urls = set()
    for path in paths:
        try:
            registry = pool.PageOwnershipRegistry(path)
            leases = registry.list()
        except Exception:
            # 损坏的 registry 是安全边界：跳过该文件的全部关闭动作。
            registries_ok = False
            continue
        for lease in leases:
            if lease.target_id and lease.target_id not in live_targets:
                try:
                    registry.release(lease, force=True)
                    released += 1
                except Exception:
                    continue
                continue
            # 受保护现场与活跃进程的页签按 target 精确豁免；旧记录没有
            # target id 时退化为按 URL 豁免。
            live_active = lease.state == "active" and pool._process_alive(lease.pid)
            if lease.protected or live_active:
                if lease.target_id:
                    skip_targets.add(lease.target_id)
                elif lease.url:
                    skip_urls.add(lease.url.strip().rstrip("/"))
        groups = {}
        for lease in leases:
            if not lease.target_id or lease.target_id not in live_targets:
                continue
            if lease.state == "active" and pool._process_alive(lease.pid):
                continue
            groups.setdefault(lease.key, []).append(lease)
        for group in groups.values():
            if len(group) < 2:
                continue
            group.sort(key=lambda item: item.created_at, reverse=True)
            for stale in group[1:]:
                try:
                    _cdp_close_tab(stale.target_id)
                    closed += 1
                except Exception:
                    pass
                try:
                    registry.release(stale, force=True)
                except Exception:
                    pass
    if registries_ok:
        closed += _close_duplicate_myseller_tabs(skip_urls=skip_urls,
                                                 skip_targets=skip_targets)
    pruned = prune_automation_tabs(keep_fill_pages=keep_fill_pages)
    return {
        "released": released,
        "closed": closed + int(pruned.get("closed") or 0),
    }


def _close_duplicate_myseller_tabs(skip_urls=frozenset(), skip_targets=frozenset(),
                                   tabs=None):
    """同 URL 的卖家中心页签只保留最后一个，返回关闭数量。

    prune 把整个 myseller 域名列入白名单（串页安全的停靠区），代价是
    历史运行遗留的重复工作台首页/核验页（all_skucenter 等）永不回收，
    浏览器跨任务常驻时就是页签堆积的主体。这里只关完全同 URL 的多余
    副本：保留最后一个（最接近最近一次使用的现场）。豁免按 target 精确
    匹配（受保护现场、活跃 worker 的页签），无 target 的旧受保护记录按
    URL 匹配；登录页永不回收。CDP 页签列表为空时不动手。
    """
    pages = _page_tabs(tabs)
    if not pages:
        return 0
    skip = {str(target or "") for target in skip_targets}
    urls = {str(url or "").strip().rstrip("/") for url in skip_urls}
    by_url = {}
    for tab in pages:
        url = str(tab.get("url") or "").strip().rstrip("/")
        if not url or not is_seller_url(url) or is_login_url(url):
            continue
        if url in urls or str(tab.get("id") or "") in skip:
            continue
        by_url.setdefault(url, []).append(tab)
    closed = 0
    for duplicates in by_url.values():
        for tab in duplicates[:-1]:
            if not tab.get("id"):
                continue
            try:
                _cdp_close_tab(tab["id"])
                closed += 1
            except Exception:
                continue
    return closed


def activate_seller_tab(tabs=None):
    tabs = tabs if tabs is not None else cdp_tabs()
    # 登录窗口可能与旧卖家标签同时存在。人工登录时应激活真正的登录页，
    # 否则用户只看到旧标签，以为弹出的窗口无法输入账号密码。
    chosen = next(
        (tab for tab in tabs or [] if is_login_url(str(tab.get("url") or "")) and tab.get("id")),
        None,
    ) or pick_seller_tab(tabs)
    if chosen and chosen.get("id"):
        _cdp_get("/json/activate/" + str(chosen["id"]))
        return chosen
    _cdp_new_tab(SELLER_HOME)
    return None


def parse_listening_pid(netstat_text, port):
    port = str(int(port))
    for line in str(netstat_text or "").splitlines():
        if "LISTENING" not in line.upper():
            continue
        parts = line.split()
        if len(parts) < 4:
            continue
        proto = parts[0].upper()
        if proto not in {"TCP", "TCPV6"}:
            continue
        local = parts[1]
        if local.startswith("[") and "]:" in local:
            local_port = local.rsplit("]:", 1)[-1]
        else:
            local_port = local.rsplit(":", 1)[-1]
        if local_port != port:
            continue
        try:
            return int(parts[-1])
        except ValueError:
            continue
    return 0


def listening_pid_on_port(port=None):
    port = int(port or CDP_PORT)
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=8,
            **_hidden_subprocess_kwargs(),
        )
    except Exception:
        return 0
    return parse_listening_pid(out, port)


def _process_parent_map():
    if os.name != "nt":
        return {}
    import ctypes
    from ctypes import wintypes

    TH32CS_SNAPPROCESS = 0x2

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    kernel32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    invalid = ctypes.c_void_p(-1).value
    if not snap or int(snap) == int(invalid):
        return {}
    mapping = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not kernel32.Process32FirstW(snap, ctypes.byref(entry)):
            return {}
        while True:
            mapping[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
            if not kernel32.Process32NextW(snap, ctypes.byref(entry)):
                break
        return mapping
    finally:
        kernel32.CloseHandle(snap)


def process_tree_pids(root_pid):
    try:
        root = int(root_pid or 0)
    except (TypeError, ValueError):
        return set()
    if not root:
        return set()
    children = {}
    for pid, parent in _process_parent_map().items():
        children.setdefault(int(parent), []).append(int(pid))
    found = {root}
    stack = [root]
    while stack:
        current = stack.pop()
        for child in children.get(current, ()):
            if child not in found:
                found.add(child)
                stack.append(child)
    return found


def automation_chrome_pids(port=None, root_pid=None):
    root = 0
    try:
        root = int(root_pid or 0)
    except (TypeError, ValueError):
        root = 0
    if not root:
        root = listening_pid_on_port(port)
    if not root:
        proc = globals().get("_CHROME_PROC")
        if proc is not None and getattr(proc, "poll", lambda: 0)() is None:
            try:
                root = int(proc.pid)
            except (TypeError, ValueError, AttributeError):
                root = 0
    if not root:
        return set()
    return process_tree_pids(root)


def _hwnds_for_pids(pids):
    pids = {int(pid) for pid in (pids or []) if pid}
    if os.name != "nt" or not pids:
        return []
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in pids:
            return True
        if not user32.IsWindow(hwnd):
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, len(class_name))
        if class_name.value == "Chrome_WidgetWin_0":
            # Older versions of this app could expose Chrome's blank helper
            # window. Hide that stray black window when enumerating the browser.
            if user32.IsWindowVisible(hwnd) and not user32.GetWindowTextLengthW(hwnd):
                user32.ShowWindow(hwnd, 0)
            return True
        if class_name.value != "Chrome_WidgetWin_1":
            return True
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        # Chrome 同一进程树里还有消息窗口和渲染辅助窗口。它们没有可用
        # 的用户区域，若被当作第一个窗口激活，会表现为窗口可见但无法输入。
        if rect.right - rect.left < 200 or rect.bottom - rect.top < 150:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title = ""
        if length:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value
        found.append((int(hwnd), title, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(callback, 0)
    return found


def _set_window_taskbar_visible(hwnd, visible):
    """Prevent tab activation from recreating a taskbar button for hidden Chrome."""
    if os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handle = wintypes.HWND(int(hwnd))
    get_style = user32.GetWindowLongW
    get_style.argtypes = [wintypes.HWND, ctypes.c_int]
    get_style.restype = wintypes.LONG
    set_style = user32.SetWindowLongW
    set_style.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.LONG]
    set_style.restype = wintypes.LONG
    style = get_style(handle, -20)
    if visible:
        original = _CHROME_EXSTYLES.pop(int(hwnd), None)
        # Recover windows hidden by a previous app instance as well.
        next_style = original if original is not None else (style & ~0x80)
    else:
        _CHROME_EXSTYLES.setdefault(int(hwnd), style & ~0x80)
        next_style = (style | 0x80) & ~0x40000  # TOOLWINDOW, clear APPWINDOW
    set_style(handle, -20, next_style)
    user32.SetWindowPos(handle, 0, 0, 0, 0, 0, 0x0037)  # FRAMECHANGED, no move/size/activate


def _set_window_rect(hwnd, x, y, w=0, h=0, show=None, activate=False, taskbar_visible=None):
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handle = wintypes.HWND(int(hwnd))
    if show is not None:
        _set_window_taskbar_visible(
            hwnd,
            visible=(show != 0) if taskbar_visible is None else bool(taskbar_visible),
        )
    SWP_NOSIZE = 0x0001
    SWP_NOZORDER = 0x0004
    SWP_NOACTIVATE = 0x0010
    flags = SWP_NOZORDER | SWP_NOACTIVATE
    width, height = int(w or 0), int(h or 0)
    if width <= 0 or height <= 0:
        flags |= SWP_NOSIZE
        width, height = 0, 0
    user32.SetWindowPos(handle, 0, int(x), int(y), width, height, flags)
    if show is not None:
        user32.ShowWindow(handle, int(show))
    if activate:
        user32.ShowWindow(handle, 9)
        foreground = user32.GetForegroundWindow()
        if foreground != handle:
            current = user32.GetWindowThreadProcessId(foreground, None)
            target = user32.GetWindowThreadProcessId(handle, None)
            user32.AttachThreadInput(current, target, True)
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
            user32.AttachThreadInput(current, target, False)
        else:
            user32.BringWindowToTop(handle)
            user32.SetForegroundWindow(handle)
    return True


def hide_automation_chrome(pids=None, root_pid=None, port=None):
    targets = {int(pid) for pid in (pids or []) if pid}
    if not targets:
        targets = automation_chrome_pids(port=port, root_pid=root_pid)
    if not targets:
        return False
    moved = False
    import ctypes

    user32 = ctypes.windll.user32
    for hwnd, _title, rect in _hwnds_for_pids(targets):
        left, top, right, bottom = rect
        # Even an offscreen window may have been made visible by tab-select.
        # Reapply the hidden state without replacing its saved on-screen placement.
        if left > OFFSCREEN_POS[0] + 100 or top > OFFSCREEN_POS[1] + 100:
            _CHROME_PLACEMENTS.setdefault(hwnd, rect)
        width = max(1, right - left)
        height = max(1, bottom - top)
        try:
            # 隐藏 = 移出屏幕 + 移除任务栏按钮（TOOLWINDOW 样式），但必须保持
            # IsWindowVisible：SW_HIDE/最小化的窗口里 Chrome 停止渲染动画帧，
            # 自动化点击必超时。屏幕外可见窗口配合防节流启动参数继续渲染，
            # 入库任务因此可以全程隐藏运行。
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 8)  # SW_SHOWNA：最小化窗口先无焦点还原
            _set_window_rect(hwnd, OFFSCREEN_POS[0], OFFSCREEN_POS[1], width, height,
                             show=8, taskbar_visible=False, activate=False)
            moved = True
        except Exception:
            continue
    return moved


def reveal_automation_chrome(pids=None, root_pid=None, port=None):
    targets = {int(pid) for pid in (pids or []) if pid}
    if not targets:
        targets = automation_chrome_pids(port=port, root_pid=root_pid)
    if not targets:
        return False
    shown = False
    windows = _hwnds_for_pids(targets)
    keywords = ("卖家中心", "千牛", "淘宝", "Taobao", "tmall", "天猫")
    windows.sort(key=lambda item: 0 if any(word in (item[1] or "") for word in keywords) else 1)
    for index, (hwnd, _title, rect) in enumerate(windows):
        left, top, right, bottom = _CHROME_PLACEMENTS.get(hwnd) or rect
        if left <= OFFSCREEN_POS[0] + 100 and top <= OFFSCREEN_POS[1] + 100:
            left, top = 80, 80
        width = max(400, (right - left) if right > left else 1200)
        height = max(300, (bottom - top) if bottom > top else 800)
        try:
            _set_window_rect(hwnd, left, top, width, height, show=9, activate=(index == 0))
            shown = True
        except Exception:
            continue
        _CHROME_PLACEMENTS.pop(hwnd, None)
    return shown


def focus_chrome_windows():
    return reveal_automation_chrome()


def _automation_windows(pids=None, root_pid=None, port=None):
    """枚举自动化 Chrome 的顶层窗口（Chrome_WidgetWin_1 且有标题）。

    restore_automation_chrome 与 automation_window_hidden 共用：都不走
    _hwnds_for_pids 的 200x150 尺寸过滤——最小化/隐藏窗口（-32000 异形
    矩形）会被该过滤跳过，而这正是需要检查与还原的对象。
    """
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    targets = {int(pid) for pid in (pids or []) if pid}
    if not targets:
        targets = automation_chrome_pids(port=port, root_pid=root_pid)
    if not targets:
        return []
    windows = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def callback(hwnd, _lparam):
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value not in targets:
            return True
        class_name = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_name, 256)
        if class_name.value != "Chrome_WidgetWin_1":
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if not length:
            return True
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
        windows.append((int(hwnd), buf.value, (rect.left, rect.top, rect.right, rect.bottom)))
        return True

    user32.EnumWindows(callback, 0)
    return windows


def automation_window_hidden(pids=None, root_pid=None, port=None):
    """自动化 Chrome 是否整体处于渲染冻结状态（最小化/SW_HIDE）。

    最小化或 SW_HIDE 的窗口里 Chrome 停止渲染动画帧，locator.click 的"元素稳定"前置
    检查会全部超时——run_script 的前台化兜底以此判断是否需要还原窗口。
    移出屏幕但保持可见的隐藏窗口渲染正常，按"可作业"放行；
    找不到任何窗口（未启动/正在退出）时同样返回 False，按"无需处理"放行。
    """
    import ctypes

    user32 = ctypes.windll.user32
    windows = _automation_windows(pids=pids, root_pid=root_pid, port=port)
    if not windows:
        return False
    for hwnd, _title, _rect in windows:
        try:
            # 屏幕（含移出屏幕）上可见且未最小化的窗口渲染正常，按"可作业"放行；
            # 只有最小化/SW_HIDE 的冻结窗口才需要还原。
            if user32.IsWindowVisible(hwnd) and not user32.IsIconic(hwnd):
                return False
        except Exception:
            continue
    return True


def restore_automation_chrome(pids=None, root_pid=None, port=None):
    """还原最小化/隐藏的自动化 Chrome 主窗口。

    reveal_automation_chrome 依赖 _hwnds_for_pids 的 200x150 尺寸过滤，
    最小化窗口（-32000 异形矩形）会被跳过；虚拟滚动表格在最小化窗口里
    停止渲染，需要先还原窗口再等表格补完。
    """
    windows = _automation_windows(pids=pids, root_pid=root_pid, port=port)
    if not windows:
        return False
    import ctypes

    user32 = ctypes.windll.user32
    keywords = ("卖家中心", "千牛", "淘宝", "Taobao", "tmall", "天猫")
    windows.sort(key=lambda item: 0 if any(word in (item[1] or "") for word in keywords) else 1)
    restored = False
    for index, (hwnd, _title, rect) in enumerate(windows):
        try:
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
                time.sleep(0.15)
            left, top, right, bottom = _CHROME_PLACEMENTS.get(hwnd) or rect
            if left <= OFFSCREEN_POS[0] + 100 and top <= OFFSCREEN_POS[1] + 100:
                left, top = 80, 80
            width = max(400, (right - left) if right > left else 1200)
            height = max(300, (bottom - top) if bottom > top else 800)
            _set_window_rect(hwnd, left, top, width, height, show=9, activate=(index == 0))
            _CHROME_PLACEMENTS.pop(hwnd, None)
            restored = True
        except Exception:
            continue
    return restored


def reveal_seller_chrome(timeout=4.0):
    try:
        activate_seller_tab()
    except Exception:
        pass
    deadline = time.time() + max(0.0, float(timeout))
    while True:
        try:
            if reveal_automation_chrome():
                return True
        except Exception:
            pass
        if time.time() >= deadline:
            return False
        # Chrome 的 CDP 端口通常早于原生窗口就绪；首次启动时等待 HWND
        # 出现，避免按钮已经返回但登录窗口仍留在屏幕外或尚不可交互。
        time.sleep(0.1)


def _wait_cdp_ready(timeout=10):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if cdp_available():
            try:
                if cdp_tabs():
                    return True
            except Exception:
                pass
        time.sleep(0.25)
    return cdp_available()


def wait_for_seller_login_status(timeout=6.0):
    deadline = time.time() + timeout
    last = {"logged_in": False, "blocker": "未打开卖家中心", "url": ""}
    last_url = None
    stable_at = time.time()
    while time.time() < deadline:
        try:
            last = login_status_from_tabs()
        except Exception:
            time.sleep(0.2)
            continue
        url = last.get("url") or ""
        if last.get("logged_in"):
            return last
        if is_login_url(url):
            return last
        if url == last_url:
            if url and time.time() - stable_at >= 0.9:
                return last
        else:
            last_url = url
            stable_at = time.time()
        time.sleep(0.2)
    return last


def start_persistent_chrome(focus=False, hide_if_logged_in=None):
    if hide_if_logged_in is None:
        hide_if_logged_in = os.environ.get("QIANNIU_DEBUG_BROWSER", "0").lower() not in {
            "1",
            "true",
            "yes",
        }
    reload_paths()
    started = False
    if not cdp_available():
        _spawn_chrome(hidden=not focus and bool(hide_if_logged_in))
        if not _wait_cdp_ready(10) and not cdp_available():
            raise RuntimeError(f"已启动 Chrome，但 {CDP_PORT} 调试端口未就绪")
        started = True
        time.sleep(1.0)
    else:
        # 兼容上一次桌面端异常退出后遗留的隐藏窗口：只接管命令行
        # 同时匹配独立 profile 和调试端口的 Chrome，不碰普通用户浏览器。
        _adopt_connected_automation_chrome()
    ensure_chrome_runtime_session_prefs()
    status = {"logged_in": False}
    try:
        if cdp_available():
            status = login_status_from_tabs()
    except Exception:
        pass
    if not focus and hide_if_logged_in:
        # Background attachment must never reveal the window. Login/captcha
        # blockers are handled by the desktop pause-and-reveal flow.
        hide_automation_chrome()
        return "started" if started else "hidden"
    # Chrome 首次打开卖家中心时，未登录用户也会短暂出现在卖家域名，
    # 随后才重定向到登录页。新启动的窗口必须先显示，不能在这个过渡
    # 阶段按“已登录”收起；桌面端会在状态稳定后再自动收起。
    if status.get("logged_in") and not started:
        if hide_if_logged_in:
            try:
                hide_automation_chrome()
            except Exception:
                pass
            return "started" if started else "hidden"
        if focus:
            if os.name == "nt" and not reveal_seller_chrome():
                raise RuntimeError("Chrome 已连接，但未找到可显示的浏览器窗口；请重试打开浏览器")
            return "started" if started else "focused"
        return "started" if started else "connected"
    if focus or started:
        if os.name == "nt" and not reveal_seller_chrome():
            raise RuntimeError("Chrome 已启动，但未找到可操作的浏览器窗口；请关闭残留的自动化 Chrome 后重试")
        if started:
            wait_for_seller_login_status()
        return "started" if started else "focused"
    return "connected"


def cdp_version():
    with urlopen(CDP_ENDPOINT + "/json/version", timeout=1.0) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def cdp_tabs(timeout=1.0):
    with urlopen(CDP_ENDPOINT + "/json/list", timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    return data if isinstance(data, list) else []


def seller_account_from_page(page):
    """从卖家中心页面提取当前登录账号标识（无登录态时返回空串）。

    不声称返回昵称/用户 ID：只有当页面明确出现「店铺名」「掌柜名」等
    卖家中心字段时才提取；用于防止切店后沿用上一店铺的商品 ID。
    """
    return str(page.get("sellerName") or page.get("seller_name") or page.get("shopName") or "").strip()


def login_status_from_tabs(tabs=None):
    try:
        tabs = tabs if tabs is not None else cdp_tabs()
    except Exception:
        return {"logged_in": False, "blocker": "无法读取浏览器标签", "url": ""}
    urls = [str(tab.get("url") or "") for tab in tabs if str(tab.get("url") or "").startswith("http")]
    seller_urls = [url for url in urls if is_seller_url(url)]
    login_urls = [url for url in urls if is_login_url(url)]
    # 登录页优先。Chrome 会保留旧卖家标签，也可能在重定向期间同时暴露
    # 卖家页和登录页；只要仍有登录页，就不能宣称已经登录。
    if login_urls:
        return {"logged_in": False, "blocker": "登录页", "url": login_urls[0]}
    if seller_urls:
        return {"logged_in": True, "blocker": "", "url": seller_urls[0]}
    return {"logged_in": False, "blocker": "未打开卖家中心", "url": urls[0] if urls else ""}


def node_executable():
    env = os.environ.get("QIANNIU_NODE")
    if env and Path(env).is_file():
        return env
    bundled = ROOT / "node" / "node.exe"
    if bundled.is_file():
        return str(bundled)
    found = shutil.which("node")
    if found:
        return found
    fallback = Path(r"D:\nodejs\node.exe")
    if fallback.is_file():
        return str(fallback)
    raise RuntimeError("未找到 node，无法调用 Playwright CLI")


def cli_executable():
    if CLI_JS.is_file():
        return [node_executable(), str(CLI_JS)]
    npx = shutil.which("npx.cmd") or shutil.which("npx")
    if not npx:
        raise RuntimeError("未找到项目内 Playwright CLI，也未找到 npx")
    return [npx, "--yes", "--package", "@playwright/cli", "playwright-cli"]


def parse_nodes(snapshot):
    nodes = []
    for line in str(snapshot or "").splitlines():
        match = NODE_RE.match(line)
        if not match:
            continue
        attrs = match.group("attrs") or ""
        ref_match = re.search(r"ref=([^\]]+)", attrs)
        nodes.append({
            "role": match.group("role"),
            "name": (match.group("name") or "").strip(),
            "text": (match.group("text") or "").strip(),
            "ref": ref_match.group(1) if ref_match else "",
            "checked": "[checked]" in attrs,
            "disabled": "[disabled]" in attrs,
        })
    return nodes


def find_node(snapshot, role, name):
    for node in parse_nodes(snapshot):
        if node["role"] == role and node["name"] == name and node["ref"]:
            return node
    return None


def require_ref(snapshot, role, name):
    node = find_node(snapshot, role, name)
    if not node:
        raise PauseForUser(f"页面上未找到 {role} {name}")
    if node["disabled"]:
        raise PauseForUser(f"{name} 当前不可用")
    return node["ref"]


def unlabeled_textbox_after(snapshot, label):
    lines = str(snapshot or "").splitlines()
    start = next((i for i, line in enumerate(lines) if f'"{label}"' in line), None)
    if start is None:
        return ""
    for line in lines[start:start + 16]:
        match = re.search(r'textbox(?: "[^"]*")?.*\[ref=([^\]]+)\]', line)
        if match:
            return match.group(1)
    return ""


def upload_refs_after(snapshot, label, limit=5):
    lines = str(snapshot or "").splitlines()
    start = next((i for i, line in enumerate(lines) if f'"{label}"' in line), None)
    if start is None:
        return []
    refs = []
    for line in lines[start:start + 90]:
        if "heading " in line and f'"{label}"' not in line:
            break
        if "上传图片" in line:
            match = re.search(r"\[ref=([^\]]+)\]", line)
            if match:
                refs.append(match.group(1))
        if len(refs) >= limit:
            break
    return refs


def warehouse_selected(snapshot):
    warehouse = find_node(snapshot, "radio", "放入仓库")
    instant = find_node(snapshot, "radio", "立刻上架")
    timed = find_node(snapshot, "radio", "定时上架")
    if not warehouse or not warehouse["checked"]:
        return False
    if instant and instant["checked"]:
        return False
    if timed and timed["checked"]:
        return False
    return True


def assert_safe_url(url):
    u = url or ""
    if ALLOWED_ITEM_ID in u:
        return
    lowered = u.lower()
    if any(marker in lowered for marker in EDIT_MARKERS):
        raise UnsafeUrl(f"拒绝使用已有商品编辑页: {url}")


def is_publish_page(url):
    lowered = (url or "").lower()
    return PUBLISH_PREFIX.split("://", 1)[-1] in lowered and "itemid=" not in lowered


def detect_blocker(url, text=""):
    if is_login_url(url):
        return "登录页"
    for marker in BLOCKER_TEXTS:
        if marker in (text or ""):
            return marker
    return ""


def assert_logged_in(url, text=""):
    blocker = detect_blocker(url, text)
    if blocker:
        raise SessionLost(f"登录失效或需要人工处理: {blocker} @ {url}")


class CliSession:
    """A Playwright CLI connection with optional per-worker page ownership.

    ``isolated=False`` preserves the historical single-session behavior for
    callers that intentionally manage the current tab themselves.  Parallel
    workers must pass ``isolated=True`` and a distinct ``session_name`` and
    ``output_dir``.  In that mode ``begin_item`` creates or resumes a page
    lease, and page-affecting commands fail if the daemon's current page no
    longer carries that lease's marker.
    """

    _PAGE_COMMANDS = {
        "eval", "run-code", "snapshot", "goto", "click", "fill", "check",
        "drop", "press", "upload",
    }

    def __init__(
        self,
        runner=None,
        *,
        session_name=None,
        output_dir=None,
        isolated=False,
        cdp_endpoint=None,
        registry_path=None,
        worker_id=None,
        cleanup_on_attach=None,
    ):
        self._runner = runner
        self._session_name = str(session_name or SESSION)
        self._output_dir = Path(output_dir or OUTPUT_DIR).resolve()
        self._isolated = bool(isolated)
        self._cdp_endpoint = str(cdp_endpoint or CDP_ENDPOINT)
        self._worker_id = str(worker_id or self._session_name)
        self._pid = os.getpid()
        self._epoch = f"{self._session_name}:{time.time_ns()}"
        self._cleanup_on_attach = (
            not self._isolated if cleanup_on_attach is None else bool(cleanup_on_attach)
        )
        self._attached = False
        self._interrupted = False
        self._current_item = ""
        # ``begin_item`` records whether this item was resumed from registry
        # pages.  The fill flow can then skip a speculative whole-tab scan for
        # a brand-new item: its only page is the freshly claimed seller-home
        # lease and a category tab can be opened directly.
        self._item_had_existing_pages = False
        self._active_marker = ""
        self._leases = {}
        self._registry = None
        self._registry_path = registry_path
        if self._isolated:
            self._registry = self._make_registry(registry_path)
            _BROWSER_REGISTRY_PATHS.add(str(self._registry.path))

    def _make_registry(self, path=None):
        pool = _browser_pool_module()
        return pool.PageOwnershipRegistry(path or pool.default_registry_path(self._output_dir))

    @property
    def session_name(self):
        return self._session_name

    @property
    def output_dir(self):
        return self._output_dir

    @property
    def cdp_endpoint(self):
        return self._cdp_endpoint

    @property
    def isolated(self):
        return self._isolated

    @property
    def current_item_key(self):
        return self._current_item

    @property
    def item_had_existing_pages(self):
        """Whether ``begin_item`` adopted pages already in the registry."""
        return bool(self._item_had_existing_pages)

    @property
    def active_lease(self):
        return self._leases.get(self._active_marker) if self._active_marker else None

    def _raw_cmd(self, *args, raw=True, timeout=60):
        if self._runner:
            return self._runner(args, raw=raw)
        # 暂停等待"当前页面操作结束"最坏要耗尽单个脚本的超时（最长 300 秒，
        # 滑块挡页时每个元素操作各烧一次超时）。取消事件一旦置位就终止在跑的
        # CLI 调用：页面停在当下现场，与滑块硬暂停同构，断点/服务器状态复核
        # 由既有续跑框架兜底。中断后的会话命令快速失败，避免清理动作重新驱动
        # 已暂停的页面；下一次任务重设 cancel_event 时自动解除。
        cancel_event = getattr(self, "cancel_event", None)
        if cancel_event is not None and not callable(getattr(cancel_event, "is_set", None)):
            cancel_event = None
        if cancel_event is not None and not cancel_event.is_set():
            self._interrupted = False
        if self._interrupted:
            raise CliInterrupted()
        self._output_dir.mkdir(parents=True, exist_ok=True)
        command = cli_executable() + [f"-s={self._session_name}"]
        if raw:
            command.append("--raw")
        command.extend(str(arg) for arg in args)
        if cancel_event is None:
            result = subprocess.run(
                command,
                cwd=str(self._output_dir),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                **_hidden_subprocess_kwargs(),
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "").strip()
                raise RuntimeError(detail or f"playwright-cli 失败: {' '.join(map(str, args))}")
            return result.stdout
        process = subprocess.Popen(
            command,
            cwd=str(self._output_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_hidden_subprocess_kwargs(),
        )
        deadline = time.monotonic() + max(1.0, float(timeout or 60))
        while True:
            try:
                stdout, stderr = process.communicate(timeout=0.2)
                break
            except subprocess.TimeoutExpired:
                if cancel_event.is_set():
                    self._interrupted = True
                    reason = str(getattr(cancel_event, "reason", "") or "")
                    message = (
                        f"PAUSE:全局故障，已中断当前页面操作并保留断点：{reason}"
                        if reason
                        else INTERRUPT_PAUSE_MESSAGE
                    )
                    process.kill()
                    process.communicate()
                    raise CliInterrupted(message) from None
                if time.monotonic() >= deadline:
                    process.kill()
                    stdout, stderr = process.communicate()
                    raise subprocess.TimeoutExpired(
                        command, timeout, output=stdout or "") from None
        if process.returncode != 0:
            detail = (stderr or stdout or "").strip()
            raise RuntimeError(detail or f"playwright-cli 失败: {' '.join(map(str, args))}")
        return stdout or ""

    def _assert_current_owned(self):
        if not self._isolated or not self._active_marker:
            return
        lease = self.active_lease
        if lease is None:
            raise RuntimeError("当前 worker 没有 active 页面租约；已停止以免串页")
        if lease.target_id:
            current_id = self._current_target_id(required=True)
            if current_id == lease.target_id:
                return
        else:
            # Old registry records may not have a target id.  Keep the marker
            # fallback only for those records; every new isolated lease gets a
            # Target.getTargetInfo id before it is committed.
            if self._read_marker() == self._active_marker:
                return
        # 守卫触发先尝试自愈：daemon 的"当前页"可能只是漂移（同浏览器里别的
        # 页签被选走/本页签被外部关闭后 daemon 回落到首页），而租约页签本身
        # 还活着。按 target id 在全浏览器页签里找回自己的页签并重新选中——
        # 只选自己租约的页签，不会触碰其他 worker 的页面。找回失败才报错。
        if lease.target_id and self._recover_lease_target(lease):
            return
        # 带上租约/当前页的 target 与 URL：守卫误报（如提交成功后的回执核实
        # 阶段）必须能从报错直接看出 daemon 当前页漂移到了哪里。
        current_url = ""
        try:
            current_url = str(self._raw_cmd("eval", "location.href") or "").strip().strip('"')
        except Exception:
            pass
        raise RuntimeError(
            f"当前 Playwright 页面不属于商品 {self._current_item or '(unknown)'}；"
            f"已停止以免串页（lease.target={str(lease.target_id)[:12]} "
            f"current.target={str(current_id)[:12] if lease.target_id else '未读取'} "
            f"current.url={current_url[:120]}）"
        )

    def _recover_lease_target(self, lease):
        """daemon 当前页漂移时按租约 target id 找回自己的页签；成功返回 True。"""
        try:
            import json as _json
            import urllib.request as _request

            endpoint = str(self._cdp_endpoint or "").strip()
            if not endpoint:
                return False
            with _request.urlopen(f"{endpoint}/json", timeout=3) as response:
                tabs = _json.load(response)
            wanted = str(lease.target_id)
            target = next((tab for tab in tabs
                           if tab.get("type") == "page" and str(tab.get("id") or "") == wanted), None)
            if target is None:
                return False
            self._select_lease(lease, _locked=False)
            return self._page_matches_lease(lease)
        except Exception:
            return False

    def cmd(self, *args, raw=True, timeout=60):
        command = str(args[0] if args else "")
        if self._isolated and self._active_marker and command in self._PAGE_COMMANDS:
            self._assert_current_owned()
        return self._raw_cmd(*args, raw=raw, timeout=timeout)

    def attach(self):
        if self._attached:
            try:
                return self.href()
            except Exception:
                self._attached = False
        # Startup is shared and serialized, but attach never performs a global
        # tab cleanup for isolated workers.  A legacy non-isolated caller keeps
        # the old cleanup behavior until it opts into the worker API.
        with _CHROME_START_LOCK:
            if not self._isolated and self._cdp_endpoint == CDP_ENDPOINT:
                start_persistent_chrome(focus=False)
            if self._cleanup_on_attach and not self._isolated:
                close_redundant_seller_home_tabs()
        try:
            href = self.href()
            if href:
                self._attached = True
                return href
        except Exception:
            pass
        self._raw_cmd("attach", "--cdp", self._cdp_endpoint, raw=False)
        self._attached = True
        return self.href()

    @staticmethod
    def _parse_tab_rows(text):
        rows = []
        for line in str(text or "").splitlines():
            match = re.search(r"(https?://\S+)", line)
            if not match:
                continue
            prefix = line[: match.start()]
            index_match = re.search(r"(?:^|\s)(\d+)\s*[:.)-]?\s*$", prefix)
            if not index_match:
                index_match = re.search(r"(\d+)", prefix)
            if not index_match:
                continue
            rows.append((int(index_match.group(1)), match.group(1).rstrip("],)")))
        return rows

    @classmethod
    def _current_tab_index(cls, text):
        """Read the CLI's explicit current marker without URL matching."""
        for line in str(text or "").splitlines():
            if "(current)" not in line.lower():
                continue
            rows = cls._parse_tab_rows(line)
            if rows:
                return rows[0][0]
        return None

    def _read_marker(self):
        raw = self._raw_cmd("eval", "() => window.name") or ""
        return str(raw).strip().strip('"').strip("'")

    @staticmethod
    def _json_object_from_cli(raw):
        text = str(raw or "").strip()
        decoder = json.JSONDecoder()
        # CLI output may include a result prefix or diagnostic lines.  Decode
        # JSON objects from the end, but skip JavaScript fragments such as
        # ``catch (_) {}`` that may appear after the result.  Prefer the
        # object carrying target metadata.
        fallback = {}
        for offset in range(len(text) - 1, -1, -1):
            if text[offset] != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[offset:])
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
            if isinstance(value, dict):
                if "targetId" in value or "targetInfo" in value:
                    return value
                if not fallback:
                    fallback = value
        return fallback

    def _current_target_id(self, *, required=False):
        """Read the current Playwright page's stable Chromium target id.

        The CDP session is created through the current Playwright ``page``
        object, so duplicate URLs and cross-origin navigations cannot make a
        worker accidentally bind to another page.  The session is detached
        immediately after the read; this does not create a browser connection
        outside the existing Playwright CLI daemon.
        """
        script = (
            "async page => {"
            " const cdp = await page.context().newCDPSession(page);"
            " try { return await cdp.send('Target.getTargetInfo'); }"
            " finally { try { await cdp.detach(); } catch (_) {} }"
            "}"
        )
        try:
            raw = self._raw_cmd("run-code", script, raw=False, timeout=15)
            value = self._json_object_from_cli(raw)
            target_info = value.get("targetInfo") if isinstance(value, dict) else None
            if not isinstance(target_info, dict):
                target_info = value
            target_id = str(target_info.get("targetId") or "").strip()
            if target_id:
                return target_id
        except Exception:
            pass
        if required:
            raise RuntimeError("无法通过当前 Playwright page 读取 Target.getTargetInfo")
        return ""

    def _set_marker(self, marker):
        expression = "() => { window.name = %s; return window.name; }" % json.dumps(marker)
        value = self._raw_cmd("eval", expression) or ""
        parsed = str(value).strip().strip('"').strip("'")
        if parsed and parsed != marker:
            raise RuntimeError("无法确认 worker 页面归属标记")

    def _claim_current_page(self, key, *, close_on_conflict=True):
        PageLease = _browser_pool_module().PageLease
        marker = f"qn-page-{self._worker_id}-{self._session_name}-{time.time_ns()}"
        self._set_marker(marker)
        # A new tab is not owned until its marker is written; use the raw
        # command here so the previous item's guard cannot reject the first
        # read from the newly-created page.
        url = str(self._raw_cmd("eval", "location.href") or "").strip().strip('"').strip("'")
        target_id = self._current_target_id(required=True)
        lease = PageLease.new(
            self._worker_id,
            str(key),
            self._session_name,
            marker=marker,
            # Indexes are mutable and duplicate URLs are common.  Refresh the
            # target-id -> index mapping only after the lease is committed.
            index=None,
            target_id=target_id,
            url=url,
            pid=self._pid,
            epoch=self._epoch,
        )
        try:
            lease = self._registry.claim(lease)
        except Exception:
            # The marker is unique, but do not leave an unregistered tab after
            # a registry conflict or an unavailable registry.
            if close_on_conflict:
                try:
                    self._raw_cmd("tab-close", raw=False)
                except Exception:
                    pass
            raise
        # ``tab-new`` leaves this page current.  Capture that explicit CLI
        # marker once so the first later refresh can verify the newly claimed
        # target directly; the index remains only a hint and is always checked
        # against Target.getTargetInfo before use.
        try:
            index = self._current_tab_index(self._raw_cmd("tab-list", raw=False))
            if index is not None:
                lease = self._registry.update(lease, index=index)
        except Exception:
            pass
        self._leases[lease.marker] = lease
        self._current_item = str(key)
        self._active_marker = lease.marker
        return lease

    @staticmethod
    def _result_from_cli(raw):
        """Decode the first JSON value following a Playwright CLI result."""
        lines = str(raw or "").splitlines()
        result_seen = False
        for line in lines:
            text = line.strip()
            if text == "### Result":
                result_seen = True
                continue
            if not result_seen or text.startswith("###") or not text:
                continue
            try:
                return json.loads(text)
            except (json.JSONDecodeError, TypeError, ValueError):
                continue
        return None

    def _legacy_checkpoint(self, key, expected_key, expected_href):
        """Find one unowned legacy publish page by checkpoint key *and* URL."""
        with self._page_operation_lock():
            # Keep the complete scan -> unique target verification -> claim
            # sequence under one short cross-session lock.  A second daemon
            # must not close/reindex a candidate between the two scans, or
            # make two workers adopt the same legacy page.
            rows = self._parse_tab_rows(self._raw_cmd("tab-list", raw=False))
            matches = []
            for index, _listed_url in rows:
                try:
                    self._raw_cmd("tab-select", str(index), raw=False)
                    target_id = self._current_target_id(required=True)
                    current_url = str(self._raw_cmd("eval", "location.href") or "").strip().strip('"').strip("'")
                    if current_url != expected_href:
                        continue
                    # A registered page is never adopted as a legacy page,
                    # even when another owned page happens to have the same
                    # URL.  Target ID is primary; URL is only a fail-closed
                    # fallback for old registry records that predate target
                    # IDs, and only when their marker cannot disambiguate.
                    registered = self._registry.list()
                    if any(lease.target_id == target_id for lease in registered):
                        continue
                    legacy_records = [lease for lease in registered if not lease.target_id]
                    current_marker = self._read_marker() if legacy_records else ""
                    if any(
                        lease.marker == current_marker
                        or (not current_marker and lease.url.rstrip("/") == current_url.rstrip("/"))
                        for lease in legacy_records
                    ):
                        continue
                    checkpoint_raw = self._raw_cmd(
                        "eval",
                        "() => { const value = sessionStorage.getItem('qianniu-fill-checkpoint');"
                        " try { return value ? JSON.parse(value) : null; } catch (_) { return null; } }",
                        raw=False,
                    )
                    checkpoint = self._result_from_cli(checkpoint_raw)
                    if (
                        isinstance(checkpoint, dict)
                        and str(checkpoint.get("key") or "") == expected_key
                        and str(checkpoint.get("href") or "") == current_url
                    ):
                        matches.append((index, target_id, current_url))
                except Exception:
                    continue
            if len(matches) != 1:
                return None
            # The scan left this daemon on the last examined tab.  Locate the
            # unique candidate again by target id before claiming; no URL-only
            # selection is allowed when duplicate legacy pages exist.
            wanted_id = matches[0][1]
            for index, _listed_url in self._parse_tab_rows(self._raw_cmd("tab-list", raw=False)):
                try:
                    self._raw_cmd("tab-select", str(index), raw=False)
                    if self._current_target_id(required=True) == wanted_id:
                        return self._claim_current_page(key, close_on_conflict=False)
                except Exception:
                    continue
            return None

    def begin_item(self, key, url=None, resume_checkpoint=None, *, allow_create=True):
        """Attach and create/resume a page exclusively owned by ``key``.

        A new item defaults to the seller home so the caller can validate the
        logged-in account on its own page before navigating to the category or
        publish flow.  A resumed item reuses its registered page instead.
        ``resume_checkpoint`` is an explicit legacy-adoption guard: it must
        contain the exact checkpoint ``key`` and ``href`` and matches one
        unowned page by sessionStorage plus stable target id.  A dict may
        carry ``item_key`` when the current registry key is namespaced by
        workbook/row while the old page stores the payload-only key.
        ``allow_create=False`` only permits adoption of an existing registry
        lease and is used when an old uncertain record has no reliable URL.
        """
        if not self._isolated:
            raise RuntimeError("begin_item 需要 CliSession(isolated=True)")
        key = str(key or "").strip()
        if not key:
            raise ValueError("商品页面租约缺少 item key")
        if not self._attached:
            self.attach()
        existing = self._registry.acquire_key(
            key,
            owner=self._worker_id,
            session_name=self._session_name,
            pid=self._pid,
            epoch=self._epoch,
        )
        if existing:
            self._item_had_existing_pages = True
            for lease in existing:
                self._leases[lease.marker] = lease
            self._current_item = key
            # 上次 preserve/detach 留下的租约可能指向已消失的页签（手动
            # 关闭、浏览器重启、历史缺陷泄漏的重复页）。优先选最新的
            # 现场页，死租约当场清记录继续；全部死亡才落入 legacy/新建
            # 逻辑，不再让整条商品续跑失败。
            chosen = None
            for lease in sorted(existing, key=lambda item: item.created_at,
                                reverse=True):
                try:
                    chosen = self._select_lease(lease)
                    break
                except Exception:
                    self._leases.pop(lease.marker, None)
                    try:
                        self._registry.release(lease, force=True)
                    except Exception:
                        pass
            if chosen is None:
                self._item_had_existing_pages = False
                self._current_item = ""
                self._active_marker = ""
            else:
                # 同商品历史副本页签（旧 preserve 与泄漏遗留）当场回收，
                # 只保留刚选中的现场页；关不掉的留给全局对账清理。
                for stale in list(self._leases.values()):
                    if stale.marker == chosen.marker or stale.key != key:
                        continue
                    try:
                        self.tab_close(stale, force=True)
                    except Exception:
                        self._leases.pop(stale.marker, None)
                        try:
                            self._registry.release(stale, force=True)
                        except Exception:
                            pass
                return chosen
        if resume_checkpoint is not None:
            if isinstance(resume_checkpoint, str):
                expected_key = str(resume_checkpoint).strip()
                expected_href = str(url or "").strip()
                checkpoint_item_key = key
            elif isinstance(resume_checkpoint, dict):
                expected_key = str(resume_checkpoint.get("key") or "").strip()
                expected_href = str(resume_checkpoint.get("href") or "").strip()
                checkpoint_item_key = str(resume_checkpoint.get("item_key") or key).strip()
            else:
                expected_key = expected_href = checkpoint_item_key = ""
            if (not expected_key or not expected_href
                    or checkpoint_item_key != key
                    or (isinstance(resume_checkpoint, str) and expected_key != key)):
                raise RuntimeError("legacy checkpoint 缺少与商品匹配的 key/href，已拒绝认领")
            legacy = self._legacy_checkpoint(key, expected_key, expected_href)
            if legacy is None:
                raise RuntimeError("legacy checkpoint 页面未能唯一匹配，已拒绝新建页面")
            self._item_had_existing_pages = True
            return legacy
        if not allow_create:
            raise RuntimeError("商品没有已登记页面，已拒绝新建页面")
        self._item_had_existing_pages = False
        self.tab_new(url or SELLER_HOME, owner_key=key)
        lease = self.active_lease
        if lease is None:
            raise RuntimeError("新建页面后未取得页面租约")
        return lease

    def _leases_for_current_item(self):
        if not self._isolated or not self._current_item:
            return []
        leases = self._registry.list(owner=self._worker_id, key=self._current_item)
        for lease in leases:
            self._leases[lease.marker] = lease
        return leases

    def _resolve_lease(self, target=None):
        if target is None:
            lease = self.active_lease
        elif hasattr(target, "marker"):
            lease = self._leases.get(str(target.marker)) or self._registry.get_marker(str(target.marker))
        elif isinstance(target, int) or str(target).isdigit():
            index = int(target)
            lease = next((item for item in self._leases_for_current_item() if item.index == index), None)
        else:
            value = str(target)
            lease = self._leases.get(value) or self._registry.get_marker(value)
            if lease is None:
                candidates = [
                    item for item in self._leases_for_current_item()
                    if item.target_id == value or item.url.rstrip("/") == value.rstrip("/")
                ]
                if len(candidates) == 1:
                    lease = candidates[0]
                elif len(candidates) > 1:
                    raise RuntimeError("同 URL 页面超过一个；必须使用稳定 target id")
        if lease is None:
            raise RuntimeError("目标页面不属于当前 worker/item")
        if lease.owner != self._worker_id or lease.key != self._current_item:
            raise RuntimeError("禁止访问其他 worker 或其他商品的页面")
        return lease

    def _page_operation_lock(self):
        if self._isolated and self._registry is not None:
            return self._registry.operation_lock()
        return nullcontext()

    def _page_matches_lease(self, lease):
        if lease.target_id:
            return self._current_target_id(required=True) == lease.target_id
        return self._read_marker() == lease.marker

    def _select_lease(self, lease, *, _locked=False):
        if not _locked:
            with self._page_operation_lock():
                return self._select_lease(lease, _locked=True)
        candidates = []
        if lease.index is not None:
            candidates.append(lease.index)
        rows = self._parse_tab_rows(self._raw_cmd("tab-list", raw=False))
        candidates.extend(index for index, _ in rows if index not in candidates)
        # The index is only a hint.  Every candidate is verified by the
        # Playwright page's stable target id before it becomes current.
        for index in candidates:
            try:
                # A page closed in another daemon can make the cached index
                # invalid.  Treat that as a stale hint and continue with the
                # refreshed rows instead of failing before target validation.
                self._raw_cmd("tab-select", str(index), raw=False)
                matches = self._page_matches_lease(lease)
            except Exception:
                matches = False
            if not matches:
                continue
            url = self._raw_cmd("eval", "location.href") or lease.url
            url = str(url).strip().strip('"').strip("'")
            lease = self._registry.update(lease, index=index, url=url, state="active")
            self._leases[lease.marker] = lease
            self._active_marker = lease.marker
            self._current_item = lease.key
            return lease
        raise RuntimeError(f"无法定位商品 {lease.key} 的自有页面；已停止以免串页")

    def _refresh_owned_pages(self):
        """Refresh each current-item lease's target id, index and URL.

        ``tab-list`` exposes only mutable indexes and URLs.  We briefly hold
        the shared operation lock while selecting each index and reading its
        target id, then restore the worker's active page.  The caller only
        receives pages already owned by this worker and current item.
        """
        leases = self._leases_for_current_item()
        if not leases:
            return []
        by_target = {lease.target_id: lease for lease in leases if lease.target_id}
        by_marker = {lease.marker: lease for lease in leases}
        active = self.active_lease
        with self._page_operation_lock():
            rows = self._parse_tab_rows(self._raw_cmd("tab-list", raw=False))
            row_indexes = [index for index, _ in rows]
            pending = {lease.marker: lease for lease in leases}
            checked_indexes = set()

            def inspect_index(index):
                """Verify one mutable index and retire a matching lease."""
                if index in checked_indexes or not pending:
                    return
                checked_indexes.add(index)
                try:
                    self._raw_cmd("tab-select", str(index), raw=False)
                    target_id = self._current_target_id(required=bool(by_target))
                except Exception:
                    return
                lease = by_target.get(target_id) if target_id else None
                if lease is None:
                    marker = self._read_marker()
                    marker_lease = by_marker.get(marker)
                    # A marker is only a compatibility fallback for registry
                    # records from before stable Target IDs were persisted.
                    # Never let a cloned/stale window.name move a lease that
                    # already has a target_id onto an unrelated target.
                    if marker_lease is not None and not marker_lease.target_id:
                        lease = marker_lease
                if lease is None or lease.marker not in pending:
                    return
                url = str(self._raw_cmd("eval", "location.href") or "").strip().strip('"').strip("'")
                changes = {"index": index, "url": url}
                if target_id and not lease.target_id:
                    changes["target_id"] = target_id
                lease = self._registry.update(lease, **changes)
                self._leases[lease.marker] = lease
                pending.pop(lease.marker, None)

            # Registry indexes are only hints, but they are usually current.
            # Verify those hints first so a worker with two owned pages does
            # not inspect every unrelated tab in the shared Chrome instance.
            for lease in leases:
                if not pending:
                    break
                if lease.index is not None and lease.index in row_indexes:
                    inspect_index(lease.index)

            # A closed/reordered page leaves its lease pending.  Only then do
            # we scan the remaining indexes, retaining target-id verification
            # and never using URL equality to claim ownership.
            if pending:
                for index in row_indexes:
                    if not pending:
                        break
                    inspect_index(index)
            if active is not None:
                try:
                    self._select_lease(active, _locked=True)
                except RuntimeError:
                    # Leave the daemon on the last verified page; the next
                    # guarded command will fail rather than select a stranger.
                    pass
        return self._leases_for_current_item()

    def ensure_owned_page(self):
        if not self._isolated:
            return None
        return self._select_lease(self._resolve_lease())

    def href(self):
        return (self.cmd("eval", "location.href") or "").strip().strip('"').strip("'")

    def body_text(self, limit=4000):
        script = f"() => (document.body && document.body.innerText || '').slice(0, {int(limit)})"
        return self.cmd("eval", script) or ""

    def snapshot(self):
        self._output_dir.mkdir(parents=True, exist_ok=True)
        path = self._output_dir / "current.yml"
        self.cmd("snapshot", f"--filename={path}")
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return self.cmd("snapshot")

    def eval_json(self, expression):
        """执行页面 JS 并解析 JSON，返回 dict；失败返回空 dict。"""
        raw = self.cmd("eval", expression) or ""
        text = raw.strip().strip('"').strip("'")
        try:
            value = json.loads(text)
            return value if isinstance(value, dict) else {}
        except (json.JSONDecodeError, ValueError):
            return {}

    def seller_account(self):
        """读取当前登录账号标识；用于把商品记录绑定到店铺身份。"""
        if not is_seller_url(self.href()):
            return ""
        try:
            page = self.eval_json(
                "() => ({"
                " sellerName: (document.querySelector('.sellerName') || {}).innerText || '',"
                " shopName: (document.querySelector('.shopName') || {}).innerText || ''"
                " })"
            )
        except Exception:
            page = {}
        return seller_account_from_page(page)

    def goto(self, url):
        assert_safe_url(url)
        self.cmd("goto", url)
        time.sleep(0.6)
        if self._isolated and self._active_marker:
            lease = self._resolve_lease()
            lease = self._registry.update(lease, url=self.href())
            self._leases[lease.marker] = lease

    def click(self, ref):
        self.cmd("click", ref)

    def fill(self, ref, value):
        self.cmd("fill", ref, str(value))

    def check(self, ref):
        self.cmd("check", ref)

    def drop_file(self, ref, path):
        self.cmd("drop", ref, f"--path={path}")

    def press(self, key):
        self.cmd("press", key)

    def detach(self):
        # Detaching the CLI daemon deliberately leaves Chrome and all leases
        # alive; protected pages can be resumed by a later worker.
        if self._isolated and self._registry is not None:
            self._registry.park_owner(self._worker_id, epoch=self._epoch)
        try:
            self._raw_cmd("detach", raw=False)
        except Exception:
            pass
        self._attached = False
        self._active_marker = ""
        self._current_item = ""
        self._item_had_existing_pages = False

    def tab_list(self, owned_only=None):
        if not self._isolated:
            return self.cmd("tab-list", raw=False)
        if owned_only is None:
            owned_only = True
        if not owned_only:
            raise RuntimeError("isolated session 禁止读取其他 worker 的页面列表")
        leases = self._refresh_owned_pages()
        return "\n".join(
            f"- {lease.index}: {'(current) ' if lease.marker == self._active_marker else ''}({lease.url})"
            for lease in leases if lease.index is not None
        )

    def owned_page_leases(self, *, refresh=True):
        """Return this item’s leases without exposing other workers' tabs.

        ``refresh=False`` is intended for a caller that has just completed a
        guarded refresh and only needs to inspect the committed URL/target-id
        cache.  Any later selection still verifies the stable target id.
        """
        if not self._isolated:
            return []
        leases = (self._refresh_owned_pages() if refresh
                  else self._leases_for_current_item())
        return list(leases)

    def tab_new(self, url=None, owner_key=None):
        if not self._isolated:
            if url:
                return self.cmd("tab-new", url, raw=False)
            return self.cmd("tab-new", raw=False)
        key = str(owner_key or self._current_item or "").strip()
        if not key:
            raise RuntimeError("isolated session 新建页面前必须先指定 item key")
        if self._current_item and key != self._current_item:
            raise RuntimeError("isolated session 不能为其他商品新建页面")
        with self._page_operation_lock():
            existing_key_leases = self._registry.list(key=key)
            if not self._current_item and existing_key_leases:
                raise RuntimeError("商品已有 parked 页面，必须先 begin_item 接管")
            if any(lease.owner != self._worker_id for lease in existing_key_leases):
                raise RuntimeError(f"商品页面已被其他 worker 占用: {key}")
            if url:
                result = self.cmd("tab-new", url, raw=False)
            else:
                result = self.cmd("tab-new", raw=False)
            self._claim_current_page(key)
            return result

    def tab_select(self, target):
        if not self._isolated:
            return self.cmd("tab-select", str(target), raw=False)
        # ``tab_list`` has already refreshed and committed the index -> target
        # mapping in the normal caller path.  Selecting by that index still
        # goes through ``_select_lease``, which verifies Target.getTargetInfo
        # and falls back to a fresh tab-list on a stale/closed index.  Avoid a
        # second full scan here; the stable target check keeps this shortcut
        # fail-closed when another worker changes tab indexes between calls.
        lease = self._resolve_lease(target)
        return self._select_lease(lease)

    def tab_close(self, target=None, *, force=False):
        if not self._isolated:
            if target is None:
                return self.cmd("tab-close", raw=False)
            return self.cmd("tab-close", str(target), raw=False)
        lease = self._resolve_lease(target)
        if lease.protected and not force:
            raise RuntimeError("受保护页面不能关闭")
        active = self.active_lease
        with self._page_operation_lock():
            self._select_lease(lease, _locked=True)
            result = self._raw_cmd("tab-close", raw=False)
            self._registry.release(lease, force=force)
            self._leases.pop(lease.marker, None)
            remaining = self._leases_for_current_item()
            if active is not None and active.marker == lease.marker:
                # ``active`` still points to the closed lease object.  Clear
                # it before choosing a remaining page so selection never
                # targets a detached/closed page.
                active = None
            elif active is not None:
                active = next((item for item in remaining if item.marker == active.marker), None)
            if active is None and remaining:
                active = remaining[0]
            if active is not None:
                self._select_lease(active, _locked=True)
            else:
                self._active_marker = ""
                self._current_item = ""
                self._item_had_existing_pages = False
            return result

    def finish_item(self, preserve=False):
        """Finish the current item, optionally retaining its page for review."""
        if not self._isolated:
            return None
        key = self._current_item
        leases = self._leases_for_current_item()
        if not key or not leases:
            return None
        active = self.active_lease
        with self._page_operation_lock():
            if preserve:
                # Refresh each page while it is known to belong to this item.
                # A single item may have home/category/material/edit tabs.
                refreshed = []
                for lease in list(leases):
                    try:
                        self._select_lease(lease, _locked=True)
                        current_url = str(self._raw_cmd("eval", "location.href") or "").strip().strip('"').strip("'")
                        if current_url:
                            lease = self._registry.update(lease, url=current_url)
                            self._leases[lease.marker] = lease
                        refreshed.append(lease)
                    except Exception:
                        # Keep the registry record as evidence even if a page
                        # disappeared during a blocker/verification handoff.
                        continue
                # 只保留当前现场页为受保护断点；同商品历史副本页签（分批
                # 补传遗留的旧 success/编辑页、历史 home 页）当场回收，
                # 否则 protected 页签会随暂停条目无限累积。现场判定优先
                # active（暂停发生的页面），退化取最新租约。
                keep_lease = None
                if active is not None:
                    keep_lease = next(
                        (item for item in refreshed if item.marker == active.marker),
                        None,
                    )
                if keep_lease is None and refreshed:
                    keep_lease = max(refreshed, key=lambda item: item.created_at)
                for stale in refreshed:
                    if keep_lease is not None and stale.marker == keep_lease.marker:
                        continue
                    try:
                        self._select_lease(stale, _locked=True)
                        self._raw_cmd("tab-close", raw=False)
                    except Exception:
                        pass
                    try:
                        self._registry.release(stale, force=True)
                    except Exception:
                        pass
                    self._leases.pop(stale.marker, None)
                if keep_lease is not None:
                    try:
                        self._select_lease(keep_lease, _locked=True)
                    except Exception:
                        pass
                parked = self._registry.park_owner(
                    self._worker_id, epoch=self._epoch, key=key, protected=True
                )
                for lease in parked:
                    self._leases[lease.marker] = lease
                lease = parked[0] if parked else leases[0]
            else:
                # Terminal success closes every page owned by this item.  Use
                # target-id verification before each close; stale registry
                # entries are released without touching an unowned page.
                for lease in list(leases):
                    try:
                        self._select_lease(lease, _locked=True)
                        self._raw_cmd("tab-close", raw=False)
                    except Exception:
                        pass
                    try:
                        self._registry.release(lease, force=True)
                    except Exception:
                        pass
                    self._leases.pop(lease.marker, None)
                lease = None
            self._active_marker = ""
            self._current_item = ""
            self._item_had_existing_pages = False
            return lease

    def upload_files(self, *paths, timeout=120):
        files = [str(Path(path).resolve()) for path in paths if path]
        if not files:
            return ""
        outputs = []
        for path in files:
            outputs.append(self.cmd("upload", path, raw=False, timeout=timeout))
            time.sleep(0.6)
        return "\n".join(outputs)


def click_role(session, role, name, snapshot=None):
    snap = snapshot if snapshot is not None else session.snapshot()
    ref = require_ref(snap, role, name)
    session.click(ref)
    return snap


def fill_role(session, role, name, value, snapshot=None):
    snap = snapshot if snapshot is not None else session.snapshot()
    session.fill(require_ref(snap, role, name), value)


def fill_labeled_textbox(session, label, value, snapshot=None):
    snap = snapshot if snapshot is not None else session.snapshot()
    ref = unlabeled_textbox_after(snap, label)
    if not ref:
        raise PauseForUser(f"未找到{label}输入框")
    session.fill(ref, value)


def choose_visible(session, value):
    snap = session.snapshot()
    node = find_node(snap, "option", value) or find_node(snap, "generic", value)
    if not node and value:
        for item in parse_nodes(snap):
            if item["ref"] and (item["name"] == value or item["text"] == value):
                node = item
                break
    if not node:
        raise PauseForUser(f"未找到选项: {value}")
    session.click(node["ref"])


def open_new_publish(session, category, brand=""):
    # 当前标签可能停在上一条成功商品残留的编辑页（URL 含 itemId），
    # 这是正常状态；直接导航去类目页，保留对类目页与新发布页的守卫。
    session.goto(CATEGORY_ENTRY)
    snap = session.snapshot()
    assert_logged_in(session.href(), snap)
    assert_safe_url(session.href())
    leaf = leaf_name(category)
    tab = find_node(snap, "tab", leaf)
    if tab:
        session.click(tab["ref"])
    else:
        fill_role(session, "textbox", "可输入产品名称、类目关键词、条码信息", leaf or category, snap)
        click_role(session, "button", "搜索")
        time.sleep(0.8)
        snap = session.snapshot()
        item = find_node(snap, "listitem", leaf)
        if not item:
            raise PauseForUser(f"类目页未找到叶子类目: {leaf}")
        session.click(item["ref"])
    time.sleep(0.5)
    snap = session.snapshot()
    if brand:
        brand_box = find_node(snap, "combobox", "请输入")
        if brand_box:
            session.click(brand_box["ref"])
            session.fill(brand_box["ref"], brand)
            time.sleep(0.4)
            choose_visible(session, brand)
            snap = session.snapshot()
    click_role(session, "button", "确认，下一步", snap)
    for _ in range(30):
        href = session.href()
        assert_safe_url(href)
        if is_publish_page(href):
            break
        time.sleep(1)
    else:
        raise PauseForUser(f"未进入新建发布页: {session.href()}")
    snap = session.snapshot()
    if leaf not in snap:
        raise PauseForUser(f"发布页类目与预期不符，未看到 {leaf}")


def fill_attributes(session, attributes):
    for name, value in (attributes or {}).items():
        if value in (None, ""):
            continue
        snap = session.snapshot()
        radio = find_node(snap, "radio", str(value))
        if radio:
            session.click(radio["ref"])
            continue
        combo = None
        lines = snap.splitlines()
        start = next((i for i, line in enumerate(lines) if f'"{name}"' in line or line.endswith(f": {name}")), None)
        if start is not None:
            for line in lines[start:start + 12]:
                match = re.search(r'combobox(?: "[^"]*")?.*\[ref=([^\]]+)\]', line)
                if match:
                    combo = match.group(1)
                    break
        if combo:
            session.click(combo)
            time.sleep(0.3)
            try:
                choose_visible(session, value)
                session.press("Escape")
                continue
            except PauseForUser:
                pass
        box = unlabeled_textbox_after(snap, name)
        if box:
            session.fill(box, value)
            continue
        raise PauseForUser(f"属性填写失败: {name}={value}")


def upload_labeled_images(session, label, paths):
    files = [str(path) for path in paths if path]
    if not files:
        return
    snap = session.snapshot()
    refs = upload_refs_after(snap, label)
    if not refs:
        raise PauseForUser(f"未找到{label}上传控件")
    for ref, file in zip(refs, files[:5]):
        session.drop_file(ref, file)


def fill_skus(session, dimensions, skus):
    if not dimensions and not skus:
        return
    snap = session.snapshot()
    button = find_node(snap, "button", "+ 创建规格")
    if not button:
        raise PauseForUser("多规格商品需要创建规格，但未找到“+ 创建规格”")
    session.click(button["ref"])
    raise PauseForUser("规格面板已打开，SKU 表格需在窗口中核对后再提交")


def select_warehouse(session):
    snap = session.snapshot()
    session.click(require_ref(snap, "radio", "放入仓库"))
    time.sleep(0.3)
    snap = session.snapshot()
    if not warehouse_selected(snap):
        raise RuntimeError("已点击放入仓库，但页面未保持选中，已停止以免立刻上架")
    return snap


def fill_product(session, product):
    href = session.href()
    snap = session.snapshot()
    assert_logged_in(href, snap)
    assert_safe_url(href)
    fill_role(session, "textbox", "最多允许输入30个汉字（60字符）", product["title"], snap)
    if product.get("guide_title"):
        fill_role(session, "textbox", "最多输入30字符（15个汉字）", product["guide_title"])
    fill_attributes(session, product.get("attributes") or {})
    upload_labeled_images(session, "1:1主图", product.get("main_images") or [])
    upload_labeled_images(session, "3:4主图", product.get("portrait_images") or [])
    upload_labeled_images(session, "宝贝详情", product.get("detail_images") or [])
    has_sku = bool(product.get("dimensions") or product.get("skus"))
    fill_labeled_textbox(session, "一口价", product["price"])
    if not has_sku:
        fill_labeled_textbox(session, "总库存", product["stock"])
    if product.get("outer_id"):
        fill_labeled_textbox(session, "商家编码", product["outer_id"])
    if product.get("ship_time"):
        click_role(session, "radio", product["ship_time"])
    if product.get("ship_from"):
        destination = "大陆及港澳台" if "其他" not in str(product["ship_from"]) else "其他国家或地区"
        click_role(session, "radio", destination)
    if product.get("freight"):
        snap = session.snapshot()
        start = next((i for i, line in enumerate(snap.splitlines()) if "物流服务" in line), None)
        combo = ""
        if start is not None:
            for line in snap.splitlines()[start:start + 20]:
                match = re.search(r'combobox(?: "[^"]*")?.*\[ref=([^\]]+)\]', line)
                if match:
                    combo = match.group(1)
                    break
        if combo:
            session.click(combo)
            time.sleep(0.3)
            choose_visible(session, product["freight"])
    if product.get("stock_deduction"):
        snap = session.snapshot()
        node = next((n for n in parse_nodes(snap) if "库存扣减方式" in (n["name"] + n["text"]) and n["ref"]), None)
        if node:
            session.click(node["ref"])
            time.sleep(0.2)
        click_role(session, "radio", product["stock_deduction"])
    snap = session.snapshot()
    logistics = find_node(snap, "checkbox", "使用物流配送") or find_node(snap, "checkbox", " 使用物流配送")
    if logistics and not logistics["checked"]:
        session.click(logistics["ref"])
    select_warehouse(session)
    if has_sku:
        fill_skus(session, product.get("dimensions") or {}, product.get("skus") or [])


def maybe_submit(session, confirm_submit, snapshot=None):
    snap = snapshot if snapshot is not None else session.snapshot()
    if not warehouse_selected(snap):
        raise RuntimeError("提交前复核失败：放入仓库未选中")
    instant = find_node(snap, "radio", "立刻上架")
    if instant and instant["checked"]:
        raise RuntimeError("提交前复核失败：当前仍是立刻上架")
    if not confirm_submit:
        return "已填写未提交"
    session.click(require_ref(snap, "button", "提交宝贝信息"))
    time.sleep(1.2)
    text = session.body_text(8000)
    if any(word in text for word in ("成功", "已提交", "仓库")):
        return "结果待核实"
    if any(word in text for word in ("失败", "错误", "未通过")):
        return "提交失败"
    return "结果待核实"


def probe():
    session = CliSession()
    href = session.attach()
    text = session.snapshot()
    blocker = detect_blocker(href, text)
    version = cdp_version() if cdp_available() else {}
    return {
        "engine": "playwright-cli",
        "session": SESSION,
        "cdp": CDP_ENDPOINT,
        "browser": version.get("Browser"),
        "url": href,
        "blocker": blocker,
        "logged_in": not blocker,
        "safe": not any(marker in (href or "").lower() for marker in EDIT_MARKERS),
    }


def run_one(session, product, confirm_submit=False):
    open_new_publish(session, product["category"], product.get("brand") or "")
    fill_product(session, product)
    snap = session.snapshot()
    execution = maybe_submit(session, confirm_submit and not product.get("skus"), snap)
    notice = "已选择放入仓库" if warehouse_selected(snap) else "放入仓库状态未知"
    if product.get("skus") and confirm_submit:
        execution = "已填写未提交"
        notice = "多规格需人工核对SKU后再提交"
    return execution, notice


def run_batch(products, confirm_submit=False, limit=None):
    if not products:
        return []
    session = CliSession()
    session.attach()
    href = session.href()
    assert_logged_in(href, session.snapshot())
    updated = []
    selected = products[:limit] if limit else products
    for product in selected:
        item = dict(product)
        try:
            execution, notice = run_one(session, product, confirm_submit=confirm_submit)
            item["execution"] = execution
            item["notice"] = notice
            item["errors"] = []
        except SessionLost as exc:
            item["execution"] = "暂停"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
            updated.append(item)
            break
        except PauseForUser as exc:
            item["execution"] = "暂停"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
        except Exception as exc:
            item["execution"] = "失败"
            item["notice"] = str(exc)
            item["errors"] = [str(exc)]
        updated.append(item)
    session.detach()
    return updated


def main():
    import argparse
    parser = argparse.ArgumentParser(description="千牛网页执行器（Playwright CLI）")
    parser.add_argument("--probe", action="store_true", help="检查9222登录态，不填写商品")
    args = parser.parse_args()
    if args.probe:
        print(json.dumps(probe(), ensure_ascii=False, indent=2))
        return 0
    parser.error("请使用 千牛自动上架.py --submit，或加 --probe 检查浏览器")


if __name__ == "__main__":
    raise SystemExit(main())
