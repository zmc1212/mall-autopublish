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


class JsBridge:
    def pick_excel(self):
        return self._dialog("open", ("Excel 清单 (*.xlsx;*.xlsm)", "所有文件 (*.*)"))

    def pick_chrome(self):
        return self._dialog("open", ("Chrome (chrome.exe)", "可执行文件 (*.exe)"))

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
        # 退出清理不能覆盖主程序原始异常，也不能阻止进程退出。
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


def main(argv=None) -> int:
    freeze_support()
    try:
        argv = list(sys.argv[1:] if argv is None else argv)
        configure_environ()
        problems = _runtime_preflight(require_bundle=paths.is_frozen())
        _write_self_test(problems)
        if "--self-test" in argv:
            return 1 if problems else 0
        if problems:
            raise RuntimeError("运行环境不完整：\n- " + "\n- ".join(problems))
        from desktop.server import pick_free_port, run_server
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
        webview.create_window(
            "千牛自动上架",
            target,
            js_api=JsBridge(),
            width=1360,
            height=900,
            min_size=(1180, 760),
            background_color="#F8FAFC",
        )
        try:
            webview.start(
                gui="edgechromium",
                icon=str(window_icon),
                debug=debug,
                private_mode=False,
                storage_path=str(paths.appdata_dir() / "webview-profile"),
            )
        finally:
            _cleanup_automation_chrome()
        return 0
    except Exception as exc:
        _write_crash(exc)
        try:
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(exc), "千牛自动上架启动失败", 0x10)
        except Exception:
            print(exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
