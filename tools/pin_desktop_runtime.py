"""固定桌面运行环境；只准备运行时缓存，不构建或发布应用。"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE = ROOT / "desktop" / "runtime-baseline.json"
COMPONENTS = ("node", "playwright-core", "browser", "webview2")
KEYS = ("architecture", "node", "playwright", "chromium", "chromium_revision", "webview2")


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_baseline(path: Path = BASELINE) -> dict:
    value = read_json(path)
    if not isinstance(value, dict) or any(not isinstance(value.get(k), str) or not value[k] for k in KEYS):
        raise ValueError("运行环境基准缺少版本字段")
    if value["architecture"] != "windows-x64":
        raise ValueError("仅支持 windows-x64 运行环境基准")
    return {k: value[k] for k in KEYS}


def assert_baseline(actual: dict, expected: dict) -> None:
    differences = [f"{k}: {actual.get(k, '缺失')} != {expected[k]}" for k in KEYS
                   if str(actual.get(k)) != expected[k]]
    if differences:
        raise ValueError("运行环境与固定基准不一致：" + "; ".join(differences))


def binary_version(path: Path) -> str:
    # 使用文件自身的 PE 版本资源，不读取宿主机安装版本。
    api = ctypes.windll.version
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ValueError(f"无法读取文件版本：{path}")
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):
        raise ValueError(f"无法读取文件版本：{path}")
    pointer, length = ctypes.c_void_p(), ctypes.c_uint()
    if not api.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length)) or length.value < 52:
        raise ValueError(f"无效的 PE 版本资源：{path}")
    info = struct.unpack("<13I", ctypes.string_at(pointer, 52))
    if info[0] != 0xFEEF04BD:
        raise ValueError(f"无效的 PE 版本签名：{path}")
    return ".".join(str(n) for n in (info[4] >> 16, info[4] & 0xFFFF, info[5] >> 16, info[5] & 0xFFFF))


def require_x64(path: Path) -> None:
    with path.open("rb") as stream:
        if stream.read(2) != b"MZ":
            raise ValueError(f"不是 Windows 程序：{path}")
        stream.seek(0x3C)
        offset, = struct.unpack("<I", stream.read(4))
        stream.seek(offset)
        if stream.read(6) != b"PE\0\0\x64\x86":
            raise ValueError(f"运行环境不是 x64：{path}")


def inspect_component(name: str, directory: Path) -> dict:
    if name == "playwright-core":
        package = read_json(directory / "package.json")
        browsers = read_json(directory / "browsers.json")["browsers"]
        revision = next(b["revision"] for b in browsers if b["name"] == "chromium")
        if not (directory / "cli.js").is_file():
            raise ValueError("Playwright cli.js 缺失")
        return {"playwright": package["version"], "chromium_revision": str(revision)}
    if name == "node":
        exe = directory / "node.exe"
        require_x64(exe)
        version = subprocess.check_output([str(exe), "--version"], text=True, timeout=15,
                                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).strip()
        return {"node": version}
    folder = directory / "chromium" if name == "browser" else directory
    exe_name, dll_name = ("chrome.exe", "chrome.dll") if name == "browser" else ("msedgewebview2.exe", "msedge.dll")
    for filename in (exe_name, dll_name, "resources.pak", "icudtl.dat"):
        if not (folder / filename).is_file():
            raise ValueError(f"运行环境文件缺失：{folder / filename}")
    if not (folder / "locales").is_dir() or not any((folder / "locales").iterdir()):
        raise ValueError(f"运行环境 locales 缺失：{folder}")
    require_x64(folder / exe_name)
    require_x64(folder / dll_name)
    version = binary_version(folder / exe_name)
    if binary_version(folder / dll_name) != version:
        raise ValueError(f"运行环境 EXE/DLL 版本不一致：{folder}")
    return {"chromium" if name == "browser" else "webview2": version}


def inventory(directory: Path) -> dict:
    import hashlib

    result = {}
    for name in COMPONENTS:
        root = directory / name
        for path in [root, *sorted(root.rglob("*"))]:
            if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
                raise ValueError(f"运行环境不能包含链接：{path}")
            if path.is_file():
                digest = hashlib.sha256()
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                result[path.relative_to(directory).as_posix()] = digest.hexdigest()
    return result


def verify_cache(cache: Path, baseline: dict) -> None:
    record = read_json(cache / "baseline.json")
    assert_baseline(record["runtime"], baseline)
    actual = {"architecture": "windows-x64"}
    for name in COMPONENTS:
        actual.update(inspect_component(name, cache / name))
    assert_baseline(actual, baseline)
    if inventory(cache) != record["files"]:
        raise ValueError("固定运行环境缓存校验失败；请恢复原缓存，不会自动切换系统版本")


def prepare(cache: Path, baseline: dict, sources: list[Path], webview_sources: list[Path]) -> Path:
    cache = cache.resolve()
    if cache.exists():
        verify_cache(cache, baseline)
        return cache
    selected = {}
    errors = []
    for name in COMPONENTS:
        candidates = [source / name for source in sources]
        if name == "webview2":
            candidates += webview_sources
        for candidate in candidates:
            if not candidate.is_dir():
                continue
            try:
                actual = inspect_component(name, candidate)
                if any(str(value) != baseline[key] for key, value in actual.items()):
                    errors.append(f"{candidate}: {actual}")
                    continue
                selected[name] = candidate
                break
            except (OSError, ValueError, KeyError, StopIteration, subprocess.SubprocessError) as exc:
                errors.append(f"{candidate}: {exc}")
        if name not in selected:
            raise ValueError(f"缺少固定运行环境 {name}；基准：{baseline}。"
                             "请通过 -RuntimeSource 指向匹配的完整安装目录，不会使用其他版本。\n"
                             + "\n".join(errors))
    cache.parent.mkdir(parents=True, exist_ok=True)
    # 独立复制，不与系统自动更新目录或旧构建共享硬链接。
    with tempfile.TemporaryDirectory(prefix="runtime-pin-", dir=cache.parent) as temporary:
        stage = Path(temporary) / "runtime"
        stage.mkdir()
        for name, source in selected.items():
            shutil.copytree(source, stage / name)
        record = {"runtime": baseline, "files": inventory(stage)}
        (stage / "baseline.json").write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        verify_cache(stage, baseline)
        stage.rename(cache)
    return cache


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", type=Path, default=ROOT / ".work" / "desktop-runtime-pinned")
    parser.add_argument("--source", type=Path)
    args = parser.parse_args()
    baseline = load_baseline()
    sources = [args.source.resolve()] if args.source else [ROOT / ".work" / "desktop-runtime", ROOT / "dist" / "千牛自动上架"]
    # 首次迁移只找固定版本目录，不枚举/选择系统最新版本。
    webviews = [] if args.source else [
        Path(os.environ[key]) / "Microsoft" / "EdgeWebView" / "Application" / baseline["webview2"]
        for key in ("ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA") if os.environ.get(key)
    ]
    try:
        cache = prepare(args.cache, baseline, sources, webviews)
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        parser.exit(1, f"固定运行环境准备失败：{exc}\n")
    print(f"固定运行环境已校验：{cache}")


if __name__ == "__main__":
    main()
