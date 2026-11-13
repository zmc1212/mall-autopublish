"""从已验证的桌面目录生成程序内更新 ZIP 和 latest.json；不会构建或发布程序。"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.update_worker import (DIRECTORIES, FILES, RUNTIME_KEYS, digest, read_json,
                                   safe_relative, validate_manifest, version_key, within, write_json)
from tools.pin_desktop_runtime import BASELINE, assert_baseline, load_baseline


def read_base(package: Path) -> dict:
    with zipfile.ZipFile(package) as archive:
        header = archive.getinfo("update.json")
        if header.file_size > 8 * 1024**2:
            raise ValueError("基线更新包清单过大")
        manifest = validate_manifest(json.loads(archive.read(header).decode("utf-8-sig")))
        if manifest["schema"] != 1:
            raise ValueError("差量基线必须是完整应用更新 ZIP")
        entries = archive.infolist()
        if (len(entries) != len(manifest["files"]) + 1
                or {item.filename for item in entries} != set(manifest["files"]) | {"update.json"}
                or any(item.file_size != manifest["files"][item.filename]["size"]
                       for item in entries if item.filename != "update.json")):
            raise ValueError("基线更新包文件清单不一致")
    return manifest


def select_base(output: Path, manifest: dict, explicit: Path | None) -> dict | None:
    candidates = [explicit] if explicit else sorted(
        (p for p in output.glob("QianniuApp-*.zip")
         if re.fullmatch(r"QianniuApp-\d+(?:\.\d+){1,5}\.zip", p.name)
         and version_key(p.stem.removeprefix("QianniuApp-")) < version_key(manifest["version"])),
        key=lambda p: version_key(p.stem.removeprefix("QianniuApp-")), reverse=True)
    for package in candidates:
        try:
            base = read_base(package)
            if (version_key(base["version"]) >= version_key(manifest["version"])
                    or any(str(base["runtime"][k]) != str(manifest["runtime"][k]) for k in RUNTIME_KEYS)):
                raise ValueError("差量基线版本或运行环境不匹配")
            return base
        except (OSError, ValueError, KeyError, RuntimeError, EOFError, zipfile.BadZipFile):
            if explicit:
                raise
    return None


def write_package(package: Path, manifest: dict, app_dir: Path, names) -> None:
    temporary = package.with_suffix(".zip.part")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_LZMA) as archive:
            archive.writestr("update.json", json.dumps(manifest, ensure_ascii=False))
            for name in names:
                archive.write(app_dir / name, name)
        temporary.replace(package)
    finally:
        temporary.unlink(missing_ok=True)


def package_info(package: Path) -> dict:
    return {"url": package.name, "sha256": digest(package), "size": package.stat().st_size}


def build(app_dir: Path, output: Path, notes: str = "", url: str = "", *,
          baseline_path: Path = BASELINE, base_package: Path | None = None,
          deltas: bool = True) -> tuple[Path, Path]:
    app_dir, output = app_dir.resolve(), output.resolve()
    runtime = read_json(app_dir / "runtime-manifest.json")
    # 在创建 ZIP 或覆盖 latest.json 前阻止宿主机运行环境版本漂移。
    assert_baseline(runtime, load_baseline(baseline_path))
    selected = []
    for name in sorted(FILES | DIRECTORIES):
        item = app_dir / name
        if item.is_file():
            selected.append(item)
        elif item.is_dir():
            selected.extend(sorted(p for p in item.rglob("*") if p.is_file()))
    files = {}
    for item in selected:
        relative = safe_relative(item.relative_to(app_dir).as_posix())
        within(app_dir, relative)
        if item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError(f"构建目录不能包含链接：{relative}")
        files[relative] = {"size": item.stat().st_size, "sha256": digest(item)}
    manifest = validate_manifest({
        "schema": 1, "version": runtime["application"], "notes": notes,
        "runtime": {key: runtime.get(key) for key in RUNTIME_KEYS}, "files": files,
    })
    base = select_base(output, manifest, base_package) if deltas else None
    output.mkdir(parents=True, exist_ok=True)
    package = output / f"QianniuApp-{manifest['version']}.zip"
    write_package(package, manifest, app_dir, files)
    delta_feeds = []
    if base:
        changed = sorted(name for name, info in files.items() if base["files"].get(name) != info)
        delta = validate_manifest(manifest | {"schema": 2, "kind": "delta", "base": base,
                                             "changed": changed, "deleted": sorted(set(base["files"]) - set(files))})
        delta_package = output / f"QianniuApp-{manifest['version']}-from-{base['version']}.delta.zip"
        write_package(delta_package, delta, app_dir, changed)
        if delta_package.stat().st_size < package.stat().st_size:
            delta_feeds.append(package_info(delta_package) | {"base_version": base["version"]})
        else:
            delta_package.unlink()  # 无收益时只发布完整包。
    feed = output / "latest.json"
    write_json(feed, {
        "schema": 1, "version": manifest["version"], **package_info(package),
        "url": url or package.name, "notes": notes, "deltas": delta_feeds,
    })
    return package, feed


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--notes", default="")
    parser.add_argument("--url", default="", help="ZIP 的 HTTPS 地址；默认与 latest.json 位于同目录")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--base-package", type=Path, help="指定旧版完整应用 ZIP；默认自动选择输出目录内最近的兼容旧版本")
    group.add_argument("--no-delta", action="store_true", help="仅生成完整应用更新 ZIP")
    args = parser.parse_args()
    package, feed = build(args.app_dir, args.output, args.notes, args.url,
                          base_package=args.base_package, deltas=not args.no_delta)
    print(f"更新 ZIP：{package}\n版本信息：{feed}")


if __name__ == "__main__":
    main()
