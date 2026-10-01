"""一键导出诊断日志：把 AppData 下的日志与结果打包成 zip，便于离线分析。"""

from __future__ import annotations

import json
import platform
import time
import zipfile
from pathlib import Path

from . import paths

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_EXPORTS_KEPT = 10
RESULT_LIMIT = 5
# 上传图片缓存体积大且无诊断价值
EXCLUDED_DIR_NAMES = {"media-upload-cache"}
# material_flow 下是素材批量导入下载的图片副本，同样排除；目录内的状态 JSON 保留
MATERIAL_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def export_logs_zip() -> dict:
    """收集日志/结果文件打包 zip，返回 {"path", "folder", "files", "size"}。"""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    out_dir = paths.appdata_dir() / "log-exports"
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"日志导出-{stamp}.zip"

    included: list[tuple[str, int]] = []
    skipped: list[str] = []
    seen: set[str] = set()

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for file, arcname in _collect_sources():
            if arcname in seen:
                continue
            seen.add(arcname)
            try:
                size = file.stat().st_size
                if size > MAX_FILE_BYTES:
                    skipped.append(f"{file}（超过 10MB）")
                    continue
                archive.write(file, arcname)
                included.append((arcname, size))
            except OSError as exc:
                skipped.append(f"{file}（读取失败：{exc}）")
        archive.writestr("manifest.txt", _manifest(included, skipped))

    _prune_old_exports(out_dir, keep=MAX_EXPORTS_KEPT)
    return {
        "path": str(zip_path),
        "folder": str(out_dir),
        "files": len(included),
        "size": zip_path.stat().st_size,
    }


def _collect_sources() -> list[tuple[Path, str]]:
    sources: list[tuple[Path, str]] = []
    logs_dir = paths.logs_dir()
    for file in sorted(logs_dir.rglob("*")):
        if not file.is_file():
            continue
        rel = file.relative_to(logs_dir)
        if any(part in EXCLUDED_DIR_NAMES for part in rel.parts):
            continue
        if any(part == "material_flow" for part in rel.parts) and file.suffix.lower() in MATERIAL_IMAGE_EXTS:
            continue
        sources.append((file, f"logs/{rel.as_posix()}"))

    appdata = paths.appdata_dir()
    for name in ("job_session.json", "settings.json"):
        file = appdata / name
        if file.is_file():
            sources.append((file, name))

    results_dir = Path(paths.load_settings().results_dir)
    if results_dir.is_dir():
        latest = sorted(results_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        latest = [p for p in latest if ".结果-" in p.name][:RESULT_LIMIT]
        for json_file in latest:
            sources.append((json_file, f"results/{json_file.name}"))
            xlsx = json_file.with_suffix(".xlsx")
            if xlsx.is_file():
                sources.append((xlsx, f"results/{xlsx.name}"))
    return sources


def _manifest(included: list[tuple[str, int]], skipped: list[str]) -> str:
    settings = paths.load_settings()
    lines = [
        "千牛自动上架 日志导出",
        f"导出时间：{time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"系统：{platform.platform()}",
        f"Python：{platform.python_version()}",
        f"打包运行：{paths.is_frozen()}",
        f"AppData：{paths.appdata_dir()}",
        f"日志目录：{paths.logs_dir()}",
        f"Playwright 输出：{paths.playwright_output_dir()}",
        f"结果目录：{settings.results_dir}",
        "",
        "== 包含文件 ==",
        *(f"{name}（{size} 字节）" for name, size in included),
        "",
        "== 跳过 ==",
        *(skipped or ["无"]),
        "",
        "== 当前暂停/阻塞 ==",
        _blocker_text(),
    ]
    return "\n".join(lines) + "\n"


def _blocker_text() -> str:
    file = paths.appdata_dir() / "job_session.json"
    try:
        data = json.loads(file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "无（job_session.json 不存在或无法读取）"
    if not isinstance(data, dict):
        return "无"
    parts = [str(data.get(key) or "").strip() for key in ("phase", "blocker")]
    parts = [item for item in parts if item]
    return " ｜ ".join(parts) if parts else "无"


def _prune_old_exports(out_dir: Path, keep: int) -> None:
    exports = sorted(out_dir.glob("日志导出-*.zip"), key=lambda p: p.stat().st_mtime, reverse=True)
    for old in exports[keep:]:
        try:
            old.unlink()
        except OSError:
            pass
