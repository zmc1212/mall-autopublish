"""安装目录、AppData、Chrome / Node / Playwright CLI 路径。"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

APP_NAME = "千牛自动上架"
CDP_DEFAULT = 9222
SELLER_HOME = "https://myseller.taobao.com/"


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def install_dir() -> Path:
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def meipass_dir() -> Path:
    raw = getattr(sys, "_MEIPASS", None)
    if raw:
        return Path(raw)
    return install_dir()


def project_root() -> Path:
    if is_frozen():
        return meipass_dir()
    return Path(__file__).resolve().parent.parent


def candidate_roots() -> list[Path]:
    roots: list[Path] = []
    for item in (install_dir(), meipass_dir(), project_root()):
        resolved = item.resolve()
        if resolved not in roots:
            roots.append(resolved)
    return roots


def find_resource(*parts: str) -> Path:
    for root in candidate_roots():
        path = root.joinpath(*parts)
        if path.exists():
            return path
    return candidate_roots()[0].joinpath(*parts)


def appdata_dir() -> Path:
    override = os.environ.get("QIANNIU_APPDATA")
    if override:
        path = Path(override)
    else:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def settings_path() -> Path:
    return appdata_dir() / "settings.json"


def logs_dir() -> Path:
    path = appdata_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def playwright_output_dir() -> Path:
    override = os.environ.get("QIANNIU_OUTPUT_DIR")
    path = Path(override) if override else logs_dir() / "playwright"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_results_dir() -> Path:
    path = appdata_dir() / "results"
    path.mkdir(parents=True, exist_ok=True)
    return path


def chrome_profile_dir() -> Path:
    override = os.environ.get("QIANNIU_PROFILE")
    path = Path(override) if override else appdata_dir() / "chrome-profile"
    path.mkdir(parents=True, exist_ok=True)
    return path


def templates_dir() -> Path:
    override = os.environ.get("QIANNIU_TEMPLATES_DIR")
    if override:
        return Path(override)
    return find_resource("templates")


def scripts_dir() -> Path:
    override = os.environ.get("QIANNIU_SCRIPTS_DIR")
    if override:
        return Path(override)
    return find_resource("web_fill", "scripts")


def mapping_path() -> Path:
    override = os.environ.get("QIANNIU_MAPPING")
    if override:
        return Path(override)
    return find_resource("千牛字段映射.json")


def web_dir() -> Path:
    return find_resource("web")


def cli_js_path() -> Path:
    override = os.environ.get("QIANNIU_CLI_JS")
    if override:
        return Path(override)
    bundled = find_resource("playwright-core", "lib", "tools", "cli-client", "cli.js")
    if bundled.is_file():
        return bundled
    return find_resource(".work", "node_modules", "playwright-core", "lib", "tools", "cli-client", "cli.js")


def node_exe_path() -> Path | None:
    override = os.environ.get("QIANNIU_NODE")
    if override and Path(override).is_file():
        return Path(override)
    bundled = find_resource("node", "node.exe")
    if bundled.is_file():
        return bundled
    import shutil

    found = shutil.which("node")
    if found:
        return Path(found)
    fallback = Path(r"D:\nodejs\node.exe")
    if fallback.is_file():
        return fallback
    return None


def detect_chrome() -> Path | None:
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

        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\chrome.exe") as key:
            value, _ = winreg.QueryValueEx(key, "")
            if value:
                candidates.insert(0, Path(value))
    except OSError:
        pass
    seen = set()
    for path in candidates:
        resolved = str(path)
        if resolved in seen:
            continue
        seen.add(resolved)
        if path.is_file():
            return path
    return None


@dataclass
class Settings:
    chrome_path: str = ""
    chrome_profile: str = ""
    cdp_port: int = CDP_DEFAULT
    debug_browser: bool = False
    confirm_submit: bool = False
    limit: int = 0
    results_dir: str = ""

    def normalized(self) -> "Settings":
        chrome = Path(self.chrome_path) if self.chrome_path else detect_chrome()
        profile = Path(self.chrome_profile) if self.chrome_profile else chrome_profile_dir()
        results = Path(self.results_dir) if self.results_dir else default_results_dir()
        port = int(self.cdp_port or CDP_DEFAULT)
        return Settings(
            chrome_path=str(chrome) if chrome else "",
            chrome_profile=str(profile),
            cdp_port=port,
            debug_browser=bool(self.debug_browser),
            confirm_submit=bool(self.confirm_submit),
            limit=max(0, int(self.limit or 0)),
            results_dir=str(results),
        )


def load_settings() -> Settings:
    path = settings_path()
    data = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            data = {}
    settings = Settings(
        chrome_path=str(data.get("chrome_path") or ""),
        chrome_profile=str(data.get("chrome_profile") or ""),
        cdp_port=int(data.get("cdp_port") or CDP_DEFAULT),
        debug_browser=bool(data.get("debug_browser")),
        confirm_submit=bool(data.get("confirm_submit")),
        limit=int(data.get("limit") or 0),
        results_dir=str(data.get("results_dir") or ""),
    ).normalized()
    return settings


def save_settings(settings: Settings) -> Settings:
    current = settings.normalized()
    path = settings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(current), ensure_ascii=False, indent=2), encoding="utf-8")
    configure_environ(current)
    return current


def configure_environ(settings: Settings | None = None) -> Settings:
    current = (settings or load_settings()).normalized()
    os.environ["QIANNIU_APPDATA"] = str(appdata_dir())
    os.environ["QIANNIU_ROOT"] = str(project_root())
    os.environ["QIANNIU_PROFILE"] = current.chrome_profile
    if current.chrome_path:
        os.environ["QIANNIU_CHROME"] = current.chrome_path
    os.environ["QIANNIU_CLI_JS"] = str(cli_js_path())
    node = node_exe_path()
    if node:
        os.environ["QIANNIU_NODE"] = str(node)
    os.environ["QIANNIU_OUTPUT_DIR"] = str(playwright_output_dir())
    os.environ["QIANNIU_RESULTS_DIR"] = current.results_dir
    os.environ["QIANNIU_TEMPLATES_DIR"] = str(templates_dir())
    os.environ["QIANNIU_SCRIPTS_DIR"] = str(scripts_dir())
    os.environ["QIANNIU_MAPPING"] = str(mapping_path())
    os.environ["QIANNIU_CDP_PORT"] = str(current.cdp_port)
    os.environ["QIANNIU_DEBUG_BROWSER"] = "1" if current.debug_browser else "0"
    Path(current.chrome_profile).mkdir(parents=True, exist_ok=True)
    Path(current.results_dir).mkdir(parents=True, exist_ok=True)
    playwright_output_dir()
    logs_dir()
    return current


def apply_to_loaded_modules() -> None:
    for name in ("千牛网页执行", "qianniu_web"):
        module = sys.modules.get(name)
        if module and hasattr(module, "reload_paths"):
            module.reload_paths()
    pipeline = sys.modules.get("web_fill.pipeline")
    if pipeline and hasattr(pipeline, "reload_paths"):
        pipeline.reload_paths()
    parser = sys.modules.get("商品解析")
    if parser and hasattr(parser, "reload_paths"):
        parser.reload_paths()
