"""Build-time verification for the self-contained Windows distribution."""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.request import urlopen


SYSTEM_DLL_PREFIXES = ("api-ms-win-", "ext-ms-")


def require(path: Path, kind: str = "file") -> None:
    ok = path.is_dir() if kind == "dir" else path.is_file()
    if not ok:
        raise RuntimeError(f"missing required {kind}: {path}")


def verify_layout(app_dir: Path) -> dict[str, Path]:
    paths = {
        "app": app_dir / "千牛自动上架.exe",
        "node": app_dir / "node" / "node.exe",
        "cli": app_dir / "playwright-core" / "lib" / "tools" / "cli-client" / "cli.js",
        "browser": app_dir / "browser" / "chromium" / "chrome.exe",
        "browser_dll": app_dir / "browser" / "chromium" / "chrome.dll",
        "browser_resources": app_dir / "browser" / "chromium" / "resources.pak",
        "browser_locales": app_dir / "browser" / "chromium" / "locales",
        "webview": app_dir / "webview2" / "msedgewebview2.exe",
        "webview_dll": app_dir / "webview2" / "msedge.dll",
        "webview_resources": app_dir / "webview2" / "resources.pak",
        "webview_locales": app_dir / "webview2" / "locales",
        "manifest": app_dir / "runtime-manifest.json",
    }
    for name, path in paths.items():
        require(path, "dir" if name.endswith("locales") else "file")
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8-sig"))
    for key in ("application", "node", "playwright", "chromium", "webview2"):
        if not manifest.get(key):
            raise RuntimeError(f"runtime manifest is missing {key}")
    return paths


def dependency_search_dirs(app_dir: Path, binary: Path) -> list[Path]:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    return [binary.parent, app_dir / "_internal", app_dir, windir / "System32", windir / "SysWOW64"]


def verify_pe_dependencies(app_dir: Path, binaries: list[Path]) -> None:
    try:
        import pefile
    except ImportError as exc:
        raise RuntimeError("build Python is missing pefile; install PyInstaller/pefile before packaging") from exc

    bundled_names = {path.name.lower() for path in app_dir.rglob("*") if path.is_file()}
    for binary in binaries:
        pe = pefile.PE(str(binary), fast_load=True)
        pe.parse_data_directories(
            directories=[
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_IMPORT"],
                pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_DELAY_IMPORT"],
            ]
        )
        imports = []
        for attribute in ("DIRECTORY_ENTRY_IMPORT", "DIRECTORY_ENTRY_DELAY_IMPORT"):
            for entry in getattr(pe, attribute, []):
                name = entry.dll.decode("ascii", errors="ignore").lower()
                if name:
                    imports.append(name)
        missing = []
        for name in sorted(set(imports)):
            if name.startswith(SYSTEM_DLL_PREFIXES):
                continue
            if name in bundled_names:
                continue
            if not any((folder / name).is_file() for folder in dependency_search_dirs(app_dir, binary)):
                missing.append(name)
        if missing:
            raise RuntimeError(f"unresolved PE dependencies for {binary.name}: {', '.join(missing)}")


def free_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


def verify_browser_launch(browser: Path) -> None:
    port = free_port()
    # Chromium child processes may still be removing profile files after the
    # parent exits; this cleanup race must not fail a successful launch check.
    with tempfile.TemporaryDirectory(prefix="qianniu-browser-check-", ignore_cleanup_errors=True) as profile:
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        process = subprocess.Popen(
            [
                str(browser),
                f"--user-data-dir={profile}",
                f"--remote-debugging-port={port}",
                "--no-first-run",
                "--no-default-browser-check",
                "--headless=new",
                "--no-sandbox",
                "about:blank",
            ],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        try:
            deadline = time.time() + 20
            last_error: Exception | None = None
            while time.time() < deadline:
                if process.poll() is not None:
                    raise RuntimeError(f"bundled Chromium exited early with code {process.returncode}")
                try:
                    with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1) as response:
                        data = json.loads(response.read().decode("utf-8"))
                    if data.get("Browser"):
                        return
                except Exception as exc:  # noqa: PERF203 - bounded polling loop
                    last_error = exc
                    time.sleep(0.25)
            raise RuntimeError(f"bundled Chromium did not expose CDP: {last_error}")
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app-dir", required=True)
    args = parser.parse_args()
    app_dir = Path(args.app_dir).resolve()
    paths = verify_layout(app_dir)
    verify_pe_dependencies(
        app_dir,
        [paths["app"], paths["node"], paths["browser"], paths["browser_dll"], paths["webview"], paths["webview_dll"]],
    )
    verify_browser_launch(paths["browser"])
    print("runtime verification passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
