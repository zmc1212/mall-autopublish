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
_managed_browser_env = ""


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


def bundled_browser_dir() -> Path:
    """Return the browser directory shipped beside the application, if present."""
    return find_resource("browser", "chromium")


def bundled_browser_path() -> Path | None:
    candidate = bundled_browser_dir() / "chrome.exe"
    return candidate if candidate.is_file() else None


def webview2_runtime_dir() -> Path | None:
    """Return the private WebView2 runtime shipped with the application."""
    candidate = find_resource("webview2")
    required = ("msedgewebview2.exe", "msedge.dll", "resources.pak", "icudtl.dat")
    if candidate.is_dir() and all((candidate / item).is_file() for item in required):
        return candidate
    return None


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


def detect_system_chrome() -> Path | None:
    """Find an installed Google Chrome without considering our bundled browser."""
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


def browser_exe_path(chrome_path: str | Path | None = None) -> Path | None:
    """Resolve the browser in custom -> bundled -> system order."""
    env_override = os.environ.get("QIANNIU_CHROME") or os.environ.get("CHROME_PATH") or ""
    if env_override == _managed_browser_env:
        env_override = ""
    override = str(chrome_path or env_override).strip()
    if override:
        candidate = Path(override).expanduser()
        if candidate.is_file():
            return candidate
    bundled = bundled_browser_path()
    if bundled:
        return bundled
    return detect_system_chrome()


def detect_chrome() -> Path | None:
    """Backward-compatible alias for the effective browser path."""
    return browser_exe_path()


def browser_source(chrome_path: str | Path | None = None) -> str:
    resolved = browser_exe_path(chrome_path)
    if not resolved:
        return "missing"
    try:
        if resolved.resolve() == (bundled_browser_path() or Path()).resolve():
            return "bundled"
    except OSError:
        pass
    if chrome_path and Path(str(chrome_path)).is_file():
        return "custom"
    env_override = os.environ.get("QIANNIU_CHROME") or os.environ.get("CHROME_PATH") or ""
    if env_override and env_override != _managed_browser_env and Path(env_override).is_file():
        return "custom"
    return "system"


@dataclass
class Settings:
    chrome_path: str = ""
    chrome_profile: str = ""
    cdp_port: int = CDP_DEFAULT
    debug_browser: bool = False
    sku_template_import: bool = False
    skip_spec_images: bool = False
    sku_image_strategy: str = "slim_material"
    settings_version: int = 3
    limit: int = 0
    # 入库后进编辑页每批补传的规格图行数；0 表示全部一次上传。
    spec_upload_batch_size: int = 2
    # 条目失败后的自动重试次数；0 表示失败不重试直接跳下一条。
    item_retry_limit: int = 1
    results_dir: str = ""

    def normalized(self) -> "Settings":
        # Keep an explicit override in settings; an empty value means bundled browser.
        chrome = Path(self.chrome_path).expanduser() if self.chrome_path and Path(self.chrome_path).expanduser().is_file() else None
        profile = Path(self.chrome_profile) if self.chrome_profile else chrome_profile_dir()
        results = Path(self.results_dir) if self.results_dir else default_results_dir()
        port = int(self.cdp_port or CDP_DEFAULT)
        return Settings(
            chrome_path=str(chrome) if chrome else "",
            chrome_profile=str(profile),
            cdp_port=port,
            # 可见性是用户设置，正式构建同样允许开启；默认值仍为 False。
            debug_browser=bool(self.debug_browser),
            sku_template_import=bool(self.sku_template_import),
            skip_spec_images=bool(self.skip_spec_images),
            sku_image_strategy=self.sku_image_strategy if self.sku_image_strategy in {"slim_material", "publish_page", "both"} else "slim_material",
            settings_version=max(3, int(self.settings_version or 3)),
            limit=max(0, int(self.limit or 0)),
            spec_upload_batch_size=max(0, min(99, int(self.spec_upload_batch_size or 0))),
            item_retry_limit=max(0, min(5, int(self.item_retry_limit or 0))),
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
    strategy = str(data.get("sku_image_strategy") or "slim_material")
    if int(data.get("settings_version") or 0) < 3:
        strategy = "slim_material"
    if strategy not in {"slim_material", "publish_page", "both"}:
        strategy = "slim_material"
    settings = Settings(
        chrome_path=str(data.get("chrome_path") or ""),
        chrome_profile=str(data.get("chrome_profile") or ""),
        cdp_port=int(data.get("cdp_port") or CDP_DEFAULT),
        debug_browser=bool(data.get("debug_browser")),
        sku_template_import=bool(data.get("sku_template_import", False)),
        skip_spec_images=bool(data.get("skip_spec_images", False)),
        sku_image_strategy=strategy,
        settings_version=int(data.get("settings_version") or 2),
        limit=int(data.get("limit") or 0),
        spec_upload_batch_size=max(0, int(data.get("spec_upload_batch_size", 2) or 0)),
        item_retry_limit=max(0, min(5, int(data.get("item_retry_limit", 1) or 0))),
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
    global _managed_browser_env
    current = (settings or load_settings()).normalized()
    os.environ["QIANNIU_APPDATA"] = str(appdata_dir())
    # Runtime resources copied next to the frozen executable live in install_dir,
    # while project_root points at PyInstaller's internal directory.
    os.environ["QIANNIU_ROOT"] = str(install_dir())
    os.environ["QIANNIU_PROFILE"] = current.chrome_profile
    effective_browser = browser_exe_path(current.chrome_path)
    if effective_browser:
        os.environ["QIANNIU_CHROME"] = str(effective_browser)
        _managed_browser_env = str(effective_browser)
    else:
        os.environ.pop("QIANNIU_CHROME", None)
        _managed_browser_env = ""
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
