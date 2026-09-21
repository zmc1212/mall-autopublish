import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import webbrowser
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
    candidates = []
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
)
OFFSCREEN_POS = (-32000, -32000)
_CHROME_PLACEMENTS = {}
_CHROME_PROC = None
_CHROME_ROOT_PID = 0
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
NODE_RE = re.compile(
    r'^\s*-\s+(?P<role>radio|textbox|button|tab|combobox|checkbox|listitem|heading|option|switch|link|generic)'
    r'(?:\s+"(?P<name>[^"]*)")?'
    r'(?P<attrs>(?:\s+\[[^\]]+\])*)'
    r'(?::\s*(?P<text>.*))?$'
)

class SessionLost(RuntimeError):
    pass


class UnsafeUrl(RuntimeError):
    pass


class PauseForUser(RuntimeError):
    pass


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


def cdp_available(timeout=1.0):
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
    profile = Path(profile or PROFILE)
    profile.mkdir(parents=True, exist_ok=True)
    default_dir = profile / "Default"
    default_dir.mkdir(parents=True, exist_ok=True)
    try:
        (profile / "First Run").touch(exist_ok=True)
    except OSError:
        pass
    prefs_path = default_dir / "Preferences"
    prefs = _read_json_file(prefs_path)
    if prefs is None:
        return
    session = prefs.setdefault("session", {})
    session["restore_on_startup"] = 1
    profile_pref = prefs.setdefault("profile", {})
    profile_pref["exit_type"] = "Normal"
    profile_pref["exited_cleanly"] = True
    try:
        _write_json_file(prefs_path, prefs)
    except OSError:
        return
    local_state_path = profile / "Local State"
    local_state = _read_json_file(local_state_path)
    if local_state is None:
        return
    profile_info = local_state.setdefault("profile", {})
    profile_info["exit_type"] = "Normal"
    try:
        _write_json_file(local_state_path, local_state)
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


def _spawn_chrome():
    global _CHROME_PROC, _CHROME_ROOT_PID
    if not CHROME.is_file():
        raise RuntimeError(f"未找到 Chrome: {CHROME}")
    kwargs = {
        "stdout": subprocess.DEVNULL,
        "stderr": subprocess.DEVNULL,
        "close_fds": True,
    }
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    _CHROME_PROC = subprocess.Popen(chrome_launch_args(), **kwargs)
    _CHROME_ROOT_PID = int(_CHROME_PROC.pid or 0)


def _process_command_line(pid):
    """读取 Windows 进程命令行；失败时返回空字符串。"""
    if os.name != "nt" or not pid:
        return ""
    try:
        # 只查询一个已知 PID，并不遍历或结束其他进程。
        script = (
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
    text = str(command_line or "").replace('"', "").replace("'", "").lower()
    profile = str(PROFILE).replace("/", "\\").rstrip("\\").lower()
    port = f"--remote-debugging-port={int(CDP_PORT)}"
    return bool(profile and f"--user-data-dir={profile}" in text and port in text)


def _adopt_connected_automation_chrome():
    """识别之前由本程序启动但尚未退出的独立 profile Chrome。"""
    global _CHROME_ROOT_PID
    if _CHROME_ROOT_PID:
        return _CHROME_ROOT_PID
    root = listening_pid_on_port()
    if root and _is_automation_chrome_command(_process_command_line(root)):
        _CHROME_ROOT_PID = int(root)
        return _CHROME_ROOT_PID
    return 0


def close_automation_chrome(timeout=3.0):
    """关闭本进程启动的自动化 Chrome 及其子进程。

    自动化 Chrome 使用独立 profile 和调试端口，并以 detached 模式启动，
    所以 Python 进程退出时不会由操作系统自动回收。这里只处理当前模块
    启动或明确识别为本程序独立 profile 的进程，不根据端口盲杀用户自己打开的 Chrome。
    """
    global _CHROME_PROC, _CHROME_ROOT_PID
    proc = _CHROME_PROC
    if proc is None and not _CHROME_ROOT_PID:
        # 即使用户没有再次点击“打开 Chrome”，退出时也尝试接管上次
        # 异常退出留下的独立 profile；命令行不匹配时不会按端口猜测。
        _adopt_connected_automation_chrome()
    root_pid = 0
    if proc is not None:
        try:
            root_pid = int(proc.pid)
        except (AttributeError, TypeError, ValueError):
            root_pid = 0
    if not root_pid:
        root_pid = int(_CHROME_ROOT_PID or 0)
    if not root_pid:
        return False

    # Chrome 会再派生 renderer/gpu 等进程；Windows 下 taskkill 的 /T
    # 能一次性结束整棵进程树，避免只关掉 browser 根进程后留下托盘进程。
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
    _CHROME_PROC = None
    _CHROME_ROOT_PID = 0
    _CHROME_PLACEMENTS.clear()
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
    if "publish.htm" in wanted:
        fill_kept = True
    if "category.htm" in wanted:
        cat_kept = True
    for tab in pages:
        url = str(tab.get("url") or "")
        low = url.lower()
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


def activate_seller_tab(tabs=None):
    tabs = tabs if tabs is not None else cdp_tabs()
    chosen = pick_seller_tab(tabs)
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
        rect = wintypes.RECT()
        user32.GetWindowRect(hwnd, ctypes.byref(rect))
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


def _set_window_rect(hwnd, x, y, w=0, h=0, show=None, activate=False):
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    handle = wintypes.HWND(int(hwnd))
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
            user32.SetForegroundWindow(handle)
            user32.AttachThreadInput(current, target, False)
        else:
            user32.SetForegroundWindow(handle)
    return True


def hide_automation_chrome(pids=None, root_pid=None, port=None):
    targets = {int(pid) for pid in (pids or []) if pid}
    if not targets:
        targets = automation_chrome_pids(port=port, root_pid=root_pid)
    if not targets:
        return False
    moved = False
    for hwnd, _title, rect in _hwnds_for_pids(targets):
        left, top, right, bottom = rect
        if left <= OFFSCREEN_POS[0] + 100 and top <= OFFSCREEN_POS[1] + 100:
            continue
        _CHROME_PLACEMENTS[hwnd] = rect
        width = max(1, right - left)
        height = max(1, bottom - top)
        try:
            _set_window_rect(hwnd, OFFSCREEN_POS[0], OFFSCREEN_POS[1], width, height, activate=False)
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


def reveal_seller_chrome():
    try:
        activate_seller_tab()
    except Exception:
        pass
    try:
        reveal_automation_chrome()
    except Exception:
        pass


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
        _spawn_chrome()
        if not _wait_cdp_ready(10) and not cdp_available():
            raise RuntimeError(f"已启动 Chrome，但 {CDP_PORT} 调试端口未就绪")
        started = True
        time.sleep(1.0)
    else:
        # 兼容上一次桌面端异常退出后遗留的隐藏窗口：只接管命令行
        # 同时匹配独立 profile 和调试端口的 Chrome，不碰普通用户浏览器。
        _adopt_connected_automation_chrome()
    status = {"logged_in": False}
    try:
        if cdp_available():
            status = login_status_from_tabs()
    except Exception:
        pass
    if status.get("logged_in"):
        if hide_if_logged_in:
            try:
                hide_automation_chrome()
            except Exception:
                pass
            return "started" if started else "hidden"
        if focus:
            reveal_seller_chrome()
            return "started" if started else "focused"
        return "started" if started else "connected"
    if focus or started:
        reveal_seller_chrome()
        if started:
            wait_for_seller_login_status()
        return "started" if started else "focused"
    return "connected"


def cdp_version():
    with urlopen(CDP_ENDPOINT + "/json/version", timeout=3) as response:
        return json.loads(response.read().decode("utf-8", errors="replace"))


def cdp_tabs(timeout=3):
    with urlopen(CDP_ENDPOINT + "/json/list", timeout=timeout) as response:
        data = json.loads(response.read().decode("utf-8", errors="replace"))
    return data if isinstance(data, list) else []


def login_status_from_tabs(tabs=None):
    try:
        tabs = tabs if tabs is not None else cdp_tabs()
    except Exception:
        return {"logged_in": False, "blocker": "无法读取浏览器标签", "url": ""}
    urls = [str(tab.get("url") or "") for tab in tabs if str(tab.get("url") or "").startswith("http")]
    seller_urls = [url for url in urls if is_seller_url(url)]
    login_urls = [url for url in urls if is_login_url(url)]
    if seller_urls:
        return {"logged_in": True, "blocker": "", "url": seller_urls[0]}
    if login_urls:
        return {"logged_in": False, "blocker": "登录页", "url": login_urls[0]}
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
    def __init__(self, runner=None):
        self._runner = runner

    def cmd(self, *args, raw=True, timeout=60):
        if self._runner:
            return self._runner(args, raw=raw)
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        command = cli_executable() + [f"-s={SESSION}"]
        if raw:
            command.append("--raw")
        command.extend(str(arg) for arg in args)
        result = subprocess.run(
            command,
            cwd=str(OUTPUT_DIR),
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

    def attach(self):
        start_persistent_chrome(focus=False)
        try:
            href = self.href()
            if href:
                return href
        except Exception:
            pass
        self.cmd("attach", "--cdp", CDP_ENDPOINT, raw=False)
        return self.href()

    def href(self):
        return (self.cmd("eval", "location.href") or "").strip().strip('"').strip("'")

    def body_text(self, limit=4000):
        script = f"() => (document.body && document.body.innerText || '').slice(0, {int(limit)})"
        return self.cmd("eval", script) or ""

    def snapshot(self):
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        path = OUTPUT_DIR / "current.yml"
        self.cmd("snapshot", f"--filename={path}")
        if path.is_file():
            return path.read_text(encoding="utf-8", errors="replace")
        return self.cmd("snapshot")

    def goto(self, url):
        assert_safe_url(url)
        self.cmd("goto", url)
        time.sleep(0.6)

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
        try:
            self.cmd("detach", raw=False)
        except Exception:
            pass

    def tab_list(self):
        return self.cmd("tab-list", raw=False)

    def tab_new(self, url=None):
        if url:
            return self.cmd("tab-new", url, raw=False)
        return self.cmd("tab-new", raw=False)

    def tab_select(self, index):
        return self.cmd("tab-select", str(index), raw=False)

    def tab_close(self, index=None):
        if index is None:
            return self.cmd("tab-close", raw=False)
        return self.cmd("tab-close", str(index), raw=False)

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
    assert_safe_url(session.href())
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
