"""独立更新进程。仅依赖标准库，从安装目录之外运行，避免锁住待替换 DLL。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path, PurePosixPath

EXE_NAME = "千牛自动上架.exe"
DIRECTORIES = {"_internal", "web", "templates", "web_fill"}
FILES = {EXE_NAME, "runtime-manifest.json", "千牛字段映射.json", "千牛自动上架.py",
         "千牛网页执行.py", "商品解析.py", "job_session.py", "workspace.py"}
RUNTIME_KEYS = ("architecture", "node", "playwright", "chromium_revision", "webview2")
MAX_UNPACKED = 4 * 1024**3


def read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON 必须是对象：{path.name}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def version_key(value: str) -> tuple[int, ...]:
    if not isinstance(value, str) or not re.fullmatch(r"\d+(?:\.\d+){1,5}", value):
        raise ValueError("更新版本号必须由数字和点组成")
    parts = tuple(int(item) for item in value.split("."))
    return parts + (0,) * (6 - len(parts))


def safe_relative(name: str) -> str:
    """按 Windows 规则验证路径，同时拒绝 ADS、设备名和大小写别名。"""
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError(f"更新包路径不合法：{name!r}")
    parts = name.split("/")
    for part in parts:
        if (part in {"", ".", ".."} or part[-1:] in {" ", "."}
                or re.search(r'[\x00-\x1f<>:"|?*]', part)
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])", part.split(".")[0])):
            raise ValueError(f"更新包路径不合法：{name!r}")
    if PurePosixPath(name).is_absolute():
        raise ValueError(f"更新包不允许绝对路径：{name}")
    if not ((len(parts) > 1 and parts[0] in DIRECTORIES) or name in FILES):
        raise ValueError(f"更新包不允许修改此路径：{name}")
    return name


def within(root: Path, name: str) -> Path:
    target = root / name
    if not target.resolve().is_relative_to(root.resolve()) or target.is_symlink():
        raise ValueError(f"路径超出更新目录：{name}")
    # Windows junction/reparse point 同样不能跟随。
    for item in [target, *target.parents]:
        if item == root.parent:
            break
        if item.exists() and (item.is_symlink() or getattr(item.lstat(), "st_file_attributes", 0) & 0x400):
            raise ValueError(f"更新目录包含链接：{item.name}")
    return target


def full_manifest(manifest: dict) -> dict:
    """差量传输完成后仍交给原有的完整目录替换和回滚事务。"""
    return {key: manifest[key] for key in ("version", "runtime", "files", "notes") if key in manifest} | {"schema": 1}


def payload_files(manifest: dict) -> dict:
    files = manifest["files"]
    return {name: files[name] for name in manifest["changed"]} if manifest["schema"] == 2 else files


def validate_manifest(manifest: dict) -> dict:
    if not isinstance(manifest, dict):
        raise ValueError("更新清单必须是对象")
    if manifest.get("schema") == 2:
        if manifest.get("kind") != "delta":
            raise ValueError("不支持的差量更新格式")
        validate_manifest(full_manifest(manifest))
        base = manifest.get("base")
        if not isinstance(base, dict) or base.get("schema") != 1:
            raise ValueError("差量更新缺少完整基线清单")
        validate_manifest(base)
        if version_key(base["version"]) >= version_key(manifest["version"]):
            raise ValueError("差量更新的基线版本必须低于目标版本")
        if any(str(base["runtime"][key]) != str(manifest["runtime"][key]) for key in RUNTIME_KEYS):
            raise ValueError("差量更新不能改变浏览器或运行环境")
        expected = {
            "changed": {name for name, info in manifest["files"].items() if base["files"].get(name) != info},
            "deleted": set(base["files"]) - set(manifest["files"]),
        }
        for key, names in expected.items():
            value = manifest.get(key)
            if (not isinstance(value, list) or not all(isinstance(name, str) for name in value)
                    or len(value) != len(set(value)) or set(value) != names):
                raise ValueError(f"差量更新的 {key} 清单不一致")
        return manifest
    if manifest.get("schema") != 1:
        raise ValueError("不支持的更新包格式")
    version_key(manifest.get("version"))
    files = manifest.get("files")
    if not isinstance(files, dict) or not files or len(files) > 30000:
        raise ValueError("更新包文件清单无效")
    seen, total = set(), 0
    for name, info in files.items():
        safe_relative(name)
        if name.casefold() in seen:
            raise ValueError("更新包包含大小写冲突路径")
        seen.add(name.casefold())
        if (not isinstance(info, dict) or not isinstance(info.get("size"), int)
                or isinstance(info["size"], bool) or info["size"] < 0
                or not re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256", "")))):
            raise ValueError(f"文件校验信息无效：{name}")
        total += info["size"]
    if total > MAX_UNPACKED:
        raise ValueError("更新包解压后超过 4 GB")
    required = {EXE_NAME, "web/index.html", "runtime-manifest.json"}
    if not required.issubset(files) or not any(name.startswith("_internal/") for name in files):
        raise ValueError("更新包缺少主程序、内部依赖、前端或版本信息")
    if not isinstance(manifest.get("runtime"), dict) or any(not manifest["runtime"].get(k) for k in RUNTIME_KEYS):
        raise ValueError("更新包缺少运行环境兼容信息")
    # 一旦更新某目录就提供它的完整内容，替换时删除旧版本的残留文件。
    return manifest


def validate_payload(stage: Path, manifest: dict) -> None:
    validate_manifest(manifest)
    actual = set()
    for path in stage.rglob("*"):
        if path.is_symlink() or getattr(path.lstat(), "st_file_attributes", 0) & 0x400:
            raise ValueError("更新文件不能包含链接")
        if path.is_file():
            actual.add(path.relative_to(stage).as_posix())
    if actual != set(manifest["files"]):
        raise ValueError("更新文件与清单不一致")
    for name, info in manifest["files"].items():
        path = within(stage, safe_relative(name))
        if path.stat().st_size != info["size"] or digest(path) != info["sha256"]:
            raise ValueError(f"更新文件校验失败：{name}")
    runtime = read_json(stage / "runtime-manifest.json")
    if runtime.get("application") != manifest["version"] or any(
            str(runtime.get(k)) != str(manifest["runtime"][k]) for k in RUNTIME_KEYS):
        raise ValueError("更新包内的版本信息不一致")


def retry(action, seconds: float = 15):
    deadline = time.monotonic() + seconds
    while True:
        try:
            return action()
        except OSError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def remove(path: Path) -> None:
    if path.is_dir():
        retry(lambda: shutil.rmtree(path))
    elif path.exists():
        retry(path.unlink)


def copy(source: Path, target: Path) -> None:
    if source.is_dir():
        shutil.copytree(source, target)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def apply_files(transaction: dict, journal: Path) -> None:
    install, stage, backup = (Path(transaction[k]) for k in ("install", "stage", "backup"))
    for external in (stage, backup, journal.parent):
        if external.resolve().is_relative_to(install.resolve()) or install.resolve().is_relative_to(external.resolve()):
            raise ValueError("暂存及备份目录必须独立于安装目录")
    manifest = transaction["manifest"]
    validate_payload(stage, manifest)  # 重启前再次校验，不能使用被篡改的暂存文件。
    runtime = read_json(install / "runtime-manifest.json")
    if version_key(manifest["version"]) <= version_key(runtime["application"]):
        raise ValueError("安装版本已经变化，已阻止重复更新或降级")
    if any(str(runtime.get(k)) != str(manifest["runtime"][k]) for k in RUNTIME_KEYS):
        raise ValueError("安装目录的运行环境已改变，请重新下载匹配的更新包")
    # 完整暂存目录是最终状态，也删除新版已不再提供的脚本或整个资源目录。
    roots = sorted(DIRECTORIES | FILES)
    protected = [Path(p).resolve() for p in transaction.get("protected", []) if p]
    for name in roots:
        target = within(install, name)
        within(stage, name)
        within(backup, name)
        if any(target.resolve().is_relative_to(p) or p.is_relative_to(target.resolve()) for p in protected):
            raise ValueError("更新目录与登录态、设置或商品数据目录重叠，已停止更新")
    transaction.update(phase="backing_up", roots=roots, existed={})
    write_json(journal, transaction)
    for name in roots:
        target = within(install, name)
        transaction["existed"][name] = target.exists()
        if target.exists():
            copy(target, within(backup, name))
    # 所有备份完成后才触碰安装目录；这一记录先落盘。
    transaction["phase"] = "applying"
    write_json(journal, transaction)
    for name in roots:
        target = within(install, name)
        remove(target)
        source = within(stage, name)
        if source.exists():
            copy(source, target)
    transaction["phase"] = "verifying"
    write_json(journal, transaction)
    # 同时检查复制过程中出现的磁盘错误。
    for name, info in manifest["files"].items():
        target = within(install, name)
        if target.stat().st_size != info["size"] or digest(target) != info["sha256"]:
            raise ValueError(f"安装后文件校验失败：{name}")


def rollback(transaction: dict) -> None:
    if transaction.get("phase") not in {"applying", "verifying", "starting"}:
        return  # 备份尚未完成时，安装目录完全没有改动。
    install, backup = (Path(transaction[k]) for k in ("install", "backup"))
    for name in transaction["roots"]:
        if name not in DIRECTORIES | FILES:
            raise ValueError("回滚路径不合法")
        target = within(install, name)
        remove(target)
        if transaction["existed"][name]:
            copy(within(backup, name), target)


def wait_parent(pid: int, timeout: float = 120) -> None:
    if os.name == "nt":
        import ctypes
        from ctypes import wintypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.OpenProcess(0x00100000, False, pid)
        if not handle:
            if ctypes.get_last_error() == 87:  # 进程已经退出。
                return
            raise OSError("无法等待主程序退出")
        try:
            if kernel.WaitForSingleObject(handle, int(timeout * 1000)) != 0:
                raise TimeoutError("主程序未能退出，安装目录未修改")
        finally:
            kernel.CloseHandle(handle)
    else:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return
            time.sleep(0.1)
        raise TimeoutError("主程序未能退出")


def launch(transaction: dict, *, updated: bool):
    env = os.environ.copy()
    # PyInstaller 6.9+：重启进程必须作为独立应用启动，不能继承旧进程的运行目录。
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    env.pop("QIANNIU_UPDATE_TRANSACTION", None)
    if updated:
        env["QIANNIU_UPDATE_TRANSACTION"] = transaction["journal"]
    options = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
    return subprocess.Popen([str(Path(transaction["install"]) / EXE_NAME)],
                            cwd=transaction["install"], env=env, **options)


def terminate(process) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=20)
    else:
        process.terminate()
    process.wait(timeout=20)


def perform_update(journal: Path, *, launcher=launch, health_timeout: float = 90) -> bool:
    """替换、启动并等待真实前端确认；任何失败都先恢复旧文件，再重启旧版。"""
    transaction = read_json(journal)
    child = None
    try:
        apply_files(transaction, journal)
        transaction["phase"] = "starting"
        write_json(journal, transaction)
        child = launcher(transaction, updated=True)
        deadline = time.monotonic() + health_timeout
        healthy_since = None
        while time.monotonic() < deadline:
            if child.poll() is not None:
                raise RuntimeError("新版本启动后提前退出")
            ack = journal.parent / "healthy.json"
            if ack.is_file():
                ready = read_json(ack)
                if ready.get("token") == transaction["token"] and ready.get("version") == transaction["manifest"]["version"]:
                    healthy_since = healthy_since or time.monotonic()
                    if time.monotonic() - healthy_since >= min(2, health_timeout / 4):
                        transaction["phase"] = "success"
                        write_json(journal, transaction)
                        write_json(journal.parent / "result.json", {"status": "success", "message": "更新成功", "version": ready["version"]})
                        return True
            time.sleep(0.2)
        raise TimeoutError("新版本未能正常加载界面，已触发回滚")
    except Exception as exc:
        try:
            if child is not None:
                terminate(child)
            rollback(transaction)
            transaction["phase"] = "rolled_back"
            write_json(journal, transaction)
            write_json(journal.parent / "result.json", {"status": "rolled_back", "message": "更新失败，已恢复旧版本", "error": str(exc)})
            launcher(transaction, updated=False)
        except Exception as recovery:
            write_json(journal.parent / "result.json", {"status": "rollback_failed", "message": "回滚未完成，旧版本备份已保留", "error": f"{exc}；{recovery}", "backup": transaction["backup"]})
        return False


def main(journal_name: str) -> int:
    journal = Path(journal_name).resolve()
    try:
        transaction = read_json(journal)
        write_json(journal.parent / "worker-ready.json", {"pid": os.getpid()})
        wait_parent(int(transaction["parent_pid"]))
        if (journal.parent / "cancelled").exists():
            return 1
        return 0 if perform_update(journal) else 1
    except Exception as exc:
        write_json(journal.parent / "result.json", {"status": "error", "message": "更新未执行，安装目录未修改", "error": str(exc)})
        return 1
