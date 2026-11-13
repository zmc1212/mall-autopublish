"""pywebview 窗口：加载本机控制面板。"""

from __future__ import annotations

import os
import sys
import threading
import time
import traceback
import webbrowser
from multiprocessing import freeze_support
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop import paths  # noqa: E402
from desktop.paths import configure_environ, logs_dir  # noqa: E402
from desktop.single_instance import acquire, activate_existing_window  # noqa: E402


class JsBridge:
    def pick_excel(self):
        return self._dialog("open", ("Excel 清单 (*.xlsx;*.xlsm)", "所有文件 (*.*)"))

    def pick_chrome(self):
        return self._dialog("open", ("Chrome (chrome.exe)", "可执行文件 (*.exe)"))

    def pick_update(self):
        return self._dialog("open", ("程序内更新包 (*.zip)",))

    def pick_folder(self):
        return self._dialog("folder")

    def save_template(self):
        return self._dialog("save", ("Excel 模板 (*.xlsx)",), "千牛商品清单模板.xlsx")

    def open_path(self, path=""):
        target = Path(str(path or "")).expanduser()
        if not target.exists():
            return False
        try:
            os.startfile(str(target))  # type: ignore[attr-defined]
            return True
        except OSError:
            webbrowser.open(target.as_uri())
            return True

    def _dialog(self, kind, file_types=None, save_filename=""):
        try:
            import webview
        except ImportError as exc:
            raise RuntimeError("当前环境没有 pywebview") from exc
        if not webview.windows:
            return ""
        window = webview.windows[0]
        dialog = getattr(webview, "FileDialog", None)
        if kind == "folder":
            mode = dialog.FOLDER if dialog else webview.FOLDER_DIALOG
            result = window.create_file_dialog(mode)
        elif kind == "save":
            mode = dialog.SAVE if dialog else webview.SAVE_DIALOG
            kwargs = {"file_types": file_types} if file_types else {}
            if save_filename:
                kwargs["save_filename"] = save_filename
            result = window.create_file_dialog(mode, **kwargs)
        else:
            mode = dialog.OPEN if dialog else webview.OPEN_DIALOG
            result = window.create_file_dialog(mode, file_types=file_types)
        if not result:
            return ""
        if isinstance(result, (list, tuple)):
            return str(result[0]) if result else ""
        return str(result)


def _write_crash(exc: BaseException) -> None:
    log = logs_dir() / "crash.log"
    log.write_text("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)), encoding="utf-8")


def _cleanup_automation_chrome() -> None:
    """在桌面窗口关闭后回收本程序启动的隐藏 Chrome。"""
    try:
        from desktop.modules import load_web

        load_web().close_automation_chrome()
    except Exception:
        pass
    try:
        from desktop.detail_browser import close_detail_browser

        close_detail_browser()
    except Exception:
        # 详情浏览器与入库浏览器隔离，只回收本模块持有的进程。
        pass


def _runtime_preflight(require_bundle: bool = False) -> list[str]:
    """Validate every runtime component needed on a clean Windows machine."""
    problems: list[str] = []
    root = paths.install_dir()
    browser = paths.browser_exe_path(paths.load_settings().chrome_path)
    if not browser or not browser.is_file():
        problems.append("缺少可用浏览器（browser\\chromium\\chrome.exe）")
    node = paths.node_exe_path()
    if not node or not node.is_file():
        problems.append("缺少 Node.js 运行时（node\\node.exe）")
    if not paths.cli_js_path().is_file():
        problems.append("缺少 Playwright CLI")
    if not (root / "web_fill" / "scripts" / "material_import.js").is_file():
        problems.append("缺少素材导入页面脚本 web_fill/scripts/material_import.js")
    try:
        import base64

        from desktop import license as license_module

        license_module.machine_code()
        if len(base64.b64decode(license_module.PUBLIC_KEY_B64)) != 32:
            problems.append("内置激活公钥格式异常")
    except Exception as exc:
        problems.append(f"激活模块异常：{exc}")
    if require_bundle:
        if not paths.bundled_browser_path():
            problems.append("正式安装包没有内置 Chromium")
        if not paths.webview2_runtime_dir():
            problems.append("正式安装包没有固定版 WebView2 Runtime")
        if not paths.find_resource("runtime-manifest.json").is_file():
            problems.append("正式安装包缺少 runtime-manifest.json")
    return problems


def _write_self_test(problems: list[str]) -> None:
    target = logs_dir() / "self-test.log"
    message = "运行时自检通过" if not problems else "运行时自检失败：\n- " + "\n- ".join(problems)
    target.write_text(message, encoding="utf-8")


def _log_build_fingerprint() -> None:
    """把运行时实际加载的页面脚本指纹写进 desktop.log。

    远程排查“更新是否真的装上”以这一行为准：main_video 指纹与打包机
    dist 不一致，说明更新包未生效（执行了旧包，或装到了另一个目录）。
    """
    import hashlib
    import json as _json
    from datetime import datetime

    try:
        scripts = paths.find_resource("web_fill", "scripts")
        main_video = scripts / "main_video.js"
        digest = hashlib.md5(main_video.read_bytes()).hexdigest()[:8] if main_video.is_file() else "缺失"
        generated = ""
        manifest = paths.find_resource("runtime-manifest.json")
        if manifest.is_file():
            try:
                generated = str(_json.loads(manifest.read_text(encoding="utf-8-sig")).get("generated_at") or "")
            except (OSError, ValueError):
                pass
        line = (f"{datetime.now().strftime('%H:%M:%S')} [info] 构建指纹 "
                f"main_video={digest} scripts={scripts} 打包时间={generated}\n")
        with (logs_dir() / "desktop.log").open("a", encoding="utf-8") as stream:
            stream.write(line)
    except OSError:
        pass


def main(argv=None) -> int:
    freeze_support()
    runtime_started = False
    instance_lock = None
    try:
        argv = list(sys.argv[1:] if argv is None else argv)
        # The installer and packer run --self-test without opening a desktop window.
        # The update worker is dispatched by run_desktop.py before this function.
        if "--self-test" not in argv:
            instance_lock = acquire()
            if instance_lock is None:
                activate_existing_window()
                return 0
        configure_environ()
        problems = _runtime_preflight(require_bundle=paths.is_frozen())
        _write_self_test(problems)
        if "--self-test" in argv:
            return 1 if problems else 0
        if problems:
            raise RuntimeError("运行环境不完整：\n- " + "\n- ".join(problems))
        _log_build_fingerprint()
        from desktop.server import MANAGER, UPDATER, pick_free_port, run_server
        from urllib.request import urlopen

        port = pick_free_port()
        def _run_api():
            try:
                (logs_dir() / "api.port").write_text(str(port), encoding="utf-8")
                run_server(port)
            except Exception:
                (logs_dir() / "server.log").write_text(traceback.format_exc(), encoding="utf-8")

        thread = threading.Thread(target=_run_api, daemon=True, name="qianniu-api")
        thread.start()
        runtime_started = True
        url = f"http://127.0.0.1:{port}/"
        for _ in range(80):
            try:
                urlopen(url + "api/health", timeout=0.25)
                break
            except Exception:
                time.sleep(0.1)
        else:
            raise RuntimeError("本机服务未能启动")
        debug = os.environ.get("QIANNIU_DEBUG") == "1"
        dev_ui = os.environ.get("QIANNIU_DEV_UI") or ""
        target = dev_ui or url
        try:
            import webview
        except ImportError:
            print(f"未安装 pywebview，请用浏览器打开 {url}")
            thread.join()
            return 0
        runtime = paths.webview2_runtime_dir()
        if runtime:
            webview.settings["WEBVIEW2_RUNTIME_PATH"] = str(runtime)
        window_icon = paths.find_resource(
            "logo", "40c40691-9747-453a-a1d1-f2c94d393f34.ico"
        )
        window = webview.create_window(
            "千牛自动上架",
            target,
            js_api=JsBridge(),
            width=1360,
            height=900,
            min_size=(1180, 760),
            background_color="#F8FAFC",
        )
        UPDATER.configure(MANAGER, window.destroy)
        webview.start(
            gui="edgechromium",
            icon=str(window_icon),
            debug=debug,
            private_mode=False,
            storage_path=str(paths.appdata_dir() / "webview-profile"),
        )
        return 0
    except Exception as exc:
        _write_crash(exc)
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(exc), "千牛自动上架启动失败", 0x10)
        except Exception:
            print(exc)
        return 1
    finally:
        try:
            # Keep the lock while closing our browser, so the next instance
            # cannot attach to a browser that is still shutting down.
            if runtime_started:
                _cleanup_automation_chrome()
        finally:
            if instance_lock is not None:
                instance_lock.close()


if __name__ == "__main__":
    raise SystemExit(main())
