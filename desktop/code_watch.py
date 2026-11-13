"""运行期代码版本监控：磁盘任务代码比进程内存新时，要求重启后再开任务。

桌面端进程加载过的 Python 模块（千牛网页执行、job_session、web_fill 等）
会驻留内存不再重载。开发期间改完代码不重启就开任务，会以
"内存旧模块 + 磁盘新逻辑"混跑（如 2026-10-03 三个并发入库因
``CliSession`` 内存副本缺少新方法而全部失败）。本模块在进程启动时给
任务代码文件拍快照，开任务前比对，失配即拦截并提示重启。
"""

from __future__ import annotations

from pathlib import Path

from .paths import project_root

# 加载后即驻留内存的代码文件。只监控 .py：页内注入脚本每次从磁盘读取，
# 天然使用最新版，不存在新旧混跑。
WATCH_FILES = (
    "千牛网页执行.py",
    "千牛自动上架.py",
    "job_session.py",
)
WATCH_DIRS = (
    "web_fill",
    "desktop",
)


def _watched_paths() -> list[Path]:
    root = project_root()
    items = [root / name for name in WATCH_FILES]
    for dirname in WATCH_DIRS:
        directory = root / dirname
        if not directory.is_dir():
            continue
        items.extend(sorted(directory.rglob("*.py")))
    return [path for path in items if path.is_file()]


def _fingerprint(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return (stat.st_mtime_ns, stat.st_size)


def snapshot_code_versions() -> dict[str, tuple[int, int]]:
    """进程启动时调用：记录各任务代码文件的 (mtime_ns, size)。"""
    snapshot: dict[str, tuple[int, int]] = {}
    for path in _watched_paths():
        fingerprint = _fingerprint(path)
        if fingerprint is not None:
            snapshot[str(path).lower()] = fingerprint
    return snapshot


STARTUP_SNAPSHOT = snapshot_code_versions()


def stale_code_files(snapshot: dict[str, tuple[int, int]] | None = None) -> list[str]:
    """返回启动后内容发生变化的代码文件相对路径；无变化返回空表。

    修改与新增都算失配：运行中的进程从未加载过新内容，开任务会混用
    新旧代码。删除不算——内存里的模块副本仍在，行为不变。
    """
    baseline = STARTUP_SNAPSHOT if snapshot is None else snapshot
    if not baseline:
        return []
    root = project_root()
    changed: list[str] = []
    for path in _watched_paths():
        fingerprint = _fingerprint(path)
        if fingerprint is None:
            continue
        if baseline.get(str(path).lower()) != fingerprint:
            try:
                changed.append(str(path.relative_to(root)))
            except ValueError:
                changed.append(str(path))
    return changed


def stale_code_notice(files: list[str]) -> str:
    shown = "、".join(files[:3])
    if len(files) > 3:
        shown += " 等"
    return f"检测到程序代码已更新（{shown}），请关闭并重新打开应用后再执行入库任务"
