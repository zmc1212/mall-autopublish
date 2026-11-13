"""程序内更新：检查、下载、校验、等待任务收尾、交给独立进程安装。"""

from __future__ import annotations

import json
import lzma
import os
import re
import shutil
import stat
import subprocess
import sys
import threading
import time
import uuid
import zipfile
import zlib
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from . import paths
from .update_worker import (DIRECTORIES, FILES, EXE_NAME, RUNTIME_KEYS, digest, full_manifest,
                            payload_files, read_json, safe_relative, validate_manifest,
                            validate_payload, version_key, within, write_json)
from .version import VERSION

MAX_DOWNLOAD = 2 * 1024**3
BUSY = {"checking", "downloading", "preparing", "waiting", "restarting"}


def current_version() -> str:
    try:
        value = read_json(paths.install_dir() / "runtime-manifest.json")["application"]
        version_key(value)
        return value
    except (OSError, ValueError, KeyError):
        return VERSION


def download_url(value: str) -> str:
    value = value.strip()
    parsed = urlparse(value)
    if (not parsed.hostname or parsed.username or parsed.password or parsed.fragment
            or (parsed.scheme != "https" and not (
                parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}))):
        raise ValueError("更新地址须使用 HTTPS（本机测试地址允许 HTTP）")
    return value


def open_url(value: str, *, method: str = "GET", timeout: float = 30):
    response = urlopen(Request(download_url(value), headers={
        "User-Agent": f"QianniuUpdater/{VERSION}", "Cache-Control": "no-cache",
    }, method=method), timeout=timeout)
    try:
        download_url(response.geturl())  # 重定向也不能降级到明文 HTTP。
    except Exception:
        response.close()
        raise
    return response


def validate_base(install: Path, manifest: dict) -> None:
    """基线的所有受管文件都匹配时才复用本机内容，不修改安装目录。"""
    try:
        installed = read_json(install / "runtime-manifest.json")
        if installed.get("application") != manifest["version"]:
            raise ValueError("基线版本不同")
        for name, info in manifest["files"].items():
            source = within(install, name)
            if not source.is_file() or source.stat().st_size != info["size"] or digest(source) != info["sha256"]:
                raise ValueError(f"基线文件不匹配：{name}")
    except (OSError, ValueError) as exc:
        raise ValueError(f"差量包基线不匹配，请使用完整应用更新包：{exc}") from exc


def extract_package(package: Path, destination: Path, *, base_dir: Path | None = None) -> dict:
    if package.stat().st_size > MAX_DOWNLOAD:
        raise ValueError("更新包超过 2 GB")
    with zipfile.ZipFile(package) as archive:
        entries = archive.infolist()
        if len(entries) > 60000:
            raise ValueError("更新包文件数量过多")
        headers = [info for info in entries if info.filename == "update.json"]
        if len(headers) != 1 or headers[0].file_size > 8 * 1024**2:
            raise ValueError("更新 ZIP 缺少有效的 update.json")
        manifest = validate_manifest(json.loads(archive.read(headers[0]).decode("utf-8-sig")))
        declared = payload_files(manifest)
        install = base_dir or paths.install_dir()
        if manifest["schema"] == 2:
            validate_base(install, manifest["base"])
        seen, content = set(), []
        for info in entries:
            if stat.S_ISLNK(info.external_attr >> 16) or info.flag_bits & 1:
                raise ValueError("更新 ZIP 不能包含链接或加密文件")
            if info.filename == "update.json":
                continue
            if info.is_dir():
                # 构建器不产生目录项；第三方重新压缩时仍要求目录属于合法文件树。
                name = info.filename.rstrip("/")
                if not any(p.startswith(name + "/") for p in declared):
                    raise ValueError("更新 ZIP 包含未声明目录")
                continue
            name = safe_relative(info.filename)
            if name.casefold() in seen or name not in declared or info.file_size != declared[name]["size"]:
                raise ValueError(f"更新 ZIP 文件清单不匹配：{name}")
            seen.add(name.casefold())
            content.append((info, name))
        if len(content) != len(declared):
            raise ValueError("更新 ZIP 文件不完整")
        required = sum(item["size"] for item in manifest["files"].values())
        if shutil.disk_usage(destination.parent).free < required * 2 + 64 * 1024**2:
            raise ValueError("暂存目录磁盘空间不足")
        destination.mkdir()
        for info, name in content:
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    if manifest["schema"] == 2:
        # 删除项不会进入最终目录；未变化文件复制到暂存目录后一起校验。
        for name in manifest["files"].keys() - declared.keys():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(within(install, name), target)
    complete = full_manifest(manifest)
    validate_payload(destination, complete)
    return complete


def download_info(info: dict, feed: str) -> dict:
    if (not isinstance(info, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(info.get("sha256", "")))
            or not isinstance(info.get("size"), int) or isinstance(info["size"], bool)
            or not 0 < info["size"] <= MAX_DOWNLOAD
            or not isinstance(info.get("url"), str) or not info["url"].strip()):
        raise ValueError("版本信息中的更新包地址、大小或 SHA-256 无效")
    return info | {"url": download_url(urljoin(feed, info["url"]))}


class UpdateManager:
    def __init__(self, directory: Path | None = None):
        self.lock = threading.RLock()
        self.directory_override = directory
        self._directory = None
        self.state = {}
        self.jobs = None
        self.close_window = None
        self._watcher = None
        self._operation = None

    def _load(self):
        directory = self.directory_override or paths.appdata_dir() / "updates"
        if directory == self._directory:
            return
        directory.mkdir(parents=True, exist_ok=True)
        self._directory = directory
        try:
            self.state = read_json(directory / "state.json")
        except (OSError, ValueError):
            self.state = {"status": "idle", "message": "尚未检查更新"}
        if self.state.get("status") in {"checking", "downloading", "preparing"}:
            self.state.update(status="error", message="上次准备更新被中断，请重新检查或导入更新包")

    def _set(self, **values):
        self._load()
        self.state.update(values)
        write_json(self._directory / "state.json", self.state)

    def configure(self, jobs, close_window):
        self.jobs, self.close_window = jobs, close_window
        resume = False
        with self.lock:
            self._load()
            if os.environ.get("QIANNIU_UPDATE_TRANSACTION"):
                self._set(status="restarting", message="新版本已启动，正在确认界面是否正常")
                jobs.update_pending = True
            elif self.state.get("status") == "waiting":
                resume = True
            elif self.state.get("status") == "restarting":
                journal = self.state.get("transaction")
                if journal and Path(journal).is_file():
                    # 结果由独立进程写入。未完成的事务不可被新更新覆盖。
                    jobs.update_pending = True
                    self._sync_result()
                else:
                    # 状态已写入但更新进程从未启动（例如强制结束程序），保留更新包并允许重试。
                    self._set(status="ready", message="上次立即重启未执行，更新包仍保留，可再次重启更新", error="")
        if resume:
            self.schedule()
        if self.state.get("status") in {"idle", "up_to_date", "available", "success"} and paths.load_settings().update_feed_url:
            try:
                self.check()
            except (ValueError, RuntimeError):
                pass

    def _sync_result(self):
        journal = self.state.get("transaction")
        if not journal:
            return
        result = Path(journal).parent / "result.json"
        if result.is_file():
            data = read_json(result)
            if self.state.get("result_transaction") != journal:
                self._set(**data, result_transaction=journal, progress=0)
                if self.jobs:
                    self.jobs.update_pending = False

    def snapshot(self):
        with self.lock:
            self._load()
            try:
                self._sync_result()
            except (OSError, ValueError):
                pass
            return {key: self.state.get(key, default) for key, default in {
                "status": "idle", "version": "", "notes": "", "message": "", "error": "", "progress": 0,
            }.items()} | {
                "current_version": current_version(),
                "feed_url": paths.load_settings().update_feed_url,
                "can_restart": bool(paths.is_frozen() and self.close_window and self.jobs),
            }

    def _start(self, status: str, message: str, action):
        with self.lock:
            self._load()
            self._sync_result()
            if self.state.get("status") in BUSY:
                raise RuntimeError("已有更新操作进行中")
            self._set(status=status, message=message, error="", progress=0)

            def work():
                try:
                    action()
                except Exception as exc:
                    with self.lock:
                        self._set(status="error", message="更新准备失败，现有程序未修改", error=str(exc), progress=0)

            self._operation = threading.Thread(target=work, daemon=True, name="qianniu-update-download")
            self._operation.start()
        return self.snapshot()

    def check(self):
        feed = download_url(paths.load_settings().update_feed_url)

        def action():
            with open_url(feed) as response:
                raw = response.read(1024 * 1024 + 1)
                resolved_feed = response.geturl()
            if len(raw) > 1024 * 1024:
                raise ValueError("更新版本信息过大")
            info = json.loads(raw.decode("utf-8-sig"))
            if not isinstance(info, dict) or info.get("schema") != 1:
                raise ValueError("不支持的版本信息格式")
            newer = version_key(info.get("version")) > version_key(current_version())
            if newer:
                info = download_info(info, resolved_feed)
                # 可选差量元数据无效时仍保留完整包，旧客户端也一直读取主地址。
                candidates = info.get("deltas", [])
                info["deltas"] = []
                if isinstance(candidates, list):
                    for candidate in candidates[:32]:
                        try:
                            if version_key(candidate.get("base_version")) < version_key(info["version"]):
                                info["deltas"].append(download_info(candidate, resolved_feed))
                        except (AttributeError, ValueError, TypeError):
                            continue
            with self.lock:
                self._set(status="available" if newer else "up_to_date", version=info["version"],
                          notes=str(info.get("notes", ""))[:10000], available=info if newer else None,
                          message="发现新版本" if newer else "当前已是最新版本")

        return self._start("checking", "正在检查更新", action)

    def _prepare(self, package: Path, directory: Path, expected_version: str = ""):
        manifest = extract_package(package, directory / "payload")
        if expected_version and manifest["version"] != expected_version:
            raise ValueError("更新包与在线版本信息不一致")
        if version_key(manifest["version"]) <= version_key(current_version()):
            raise ValueError("更新版本必须高于当前版本")
        runtime_file = paths.install_dir() / "runtime-manifest.json"
        if paths.is_frozen() or runtime_file.is_file():
            installed = read_json(runtime_file)
            differences = [
                f"{key}：当前 {installed.get(key) or '缺失'}，更新包要求 {manifest['runtime'][key]}"
                for key in RUNTIME_KEYS
                if str(installed.get(key)) != str(manifest["runtime"][key])
            ]
            if differences:
                raise ValueError(
                    "更新包需要不同的浏览器或运行环境，请使用对应完整安装包。"
                    "增量包不包含这些运行环境，版本差异：" + "；".join(differences)
                )
        write_json(directory / "package.json", manifest)
        with self.lock:
            self._set(status="ready", message="更新已校验，重启后生效", version=manifest["version"],
                      prepared=str(directory), notes=str(manifest.get("notes", ""))[:10000], progress=100)

    def import_package(self, filename: str):
        source = Path(filename).expanduser().resolve()
        if not source.is_file() or source.suffix.lower() != ".zip":
            raise ValueError("请选择程序内更新 ZIP 文件")

        def action():
            directory = self._directory / uuid.uuid4().hex
            directory.mkdir()
            # 固定输入副本，避免用户移动或覆盖原 ZIP 影响正在进行的校验。
            if source.stat().st_size > MAX_DOWNLOAD:
                raise ValueError("更新包超过 2 GB")
            package = directory / "download.zip"
            shutil.copy2(source, package)
            self._prepare(package, directory)
            package.unlink()

        return self._start("preparing", "正在导入并校验更新包", action)

    def download(self):
        with self.lock:
            self._load()
            if self.state.get("status") != "available" or not self.state.get("available"):
                raise ValueError("请先检查新版本")
            info = dict(self.state["available"])

        def action():
            directory = self._directory / uuid.uuid4().hex
            directory.mkdir()
            delta = next((item for item in info.get("deltas", [])
                          if item["base_version"] == current_version() and item["size"] < info["size"]), None)
            fallback = False
            for number, candidate in enumerate(([delta] if delta else []) + [info]):
                attempt = directory / str(number)
                attempt.mkdir()
                package = attempt / "download.zip"
                try:
                    self._download_package(candidate, package)
                    self._prepare(package, attempt, info["version"])
                    package.unlink()
                    with self.lock:
                        self._set(package_kind="delta" if candidate is delta else "full",
                                  message="差量更新已校验，重启后生效" if candidate is delta else
                                  "已改用完整应用更新包并校验，重启后生效" if fallback else "更新已校验，重启后生效")
                    return
                except HTTPError as exc:
                    # 明确访问拒绝时保留证据，不借由其他地址重试。
                    if exc.code in {401, 403} or candidate is not delta:
                        raise
                except (OSError, ValueError, RuntimeError, EOFError, zipfile.BadZipFile, lzma.LZMAError, zlib.error):
                    if candidate is not delta:
                        raise
                fallback = True
                with self.lock:
                    self._set(status="downloading", progress=0, message="差量包不可用，正在下载完整应用更新包")

        return self._start("downloading", "正在后台下载更新，当前入库任务继续运行", action)

    def _download_package(self, info: dict, package: Path):
        count = 0
        with open_url(info["url"]) as response, package.open("wb") as output:
            while chunk := response.read(1024 * 1024):
                count += len(chunk)
                if count > info["size"]:
                    raise ValueError("更新包大小超出版本信息")
                output.write(chunk)
                with self.lock:
                    self.state["progress"] = round(count * 100 / info["size"])
        if count != info["size"] or digest(package) != info["sha256"]:
            raise ValueError("更新包下载不完整或 SHA-256 校验失败")

    def schedule(self):
        if not paths.is_frozen() or not self.jobs or not self.close_window:
            raise RuntimeError("源码开发模式支持检查和校验；自动替换及重启仅在安装后的客户端启用")
        with self.jobs.lock, self.lock:
            self._load()
            if self.state.get("status") not in {"ready", "waiting"}:
                raise RuntimeError("请先下载或导入并校验更新包")
            prepared = Path(self.state["prepared"])
            if not (prepared / "package.json").is_file():
                raise RuntimeError("暂存更新包已丢失，请重新下载")
            self._set(status="waiting", message="已安排更新：当前任务结束并保存结果后自动重启")
            self.jobs.update_pending = True
            if not self._watcher or not self._watcher.is_alive():
                self._watcher = threading.Thread(target=self._wait_idle, daemon=True, name="qianniu-update-wait")
                self._watcher.start()
        return self.snapshot()

    def restart_now(self):
        """不等待任务收尾，立即交给独立进程替换并重启；未完成条目重启后可继续。"""
        if not paths.is_frozen() or not self.jobs or not self.close_window:
            raise RuntimeError("源码开发模式支持检查和校验；自动替换及重启仅在安装后的客户端启用")
        with self.jobs.lock, self.lock:
            self._load()
            if self.state.get("status") not in {"ready", "waiting"}:
                raise RuntimeError("请先下载或导入并校验更新包")
            prepared = Path(self.state["prepared"])
            if not (prepared / "package.json").is_file():
                raise RuntimeError("暂存更新包已丢失，请重新下载")
            self._set(status="restarting", message="正在立即重启更新，未完成任务在重启后可继续", error="")
            self.jobs.update_pending = True
            stop = getattr(self.jobs, "stop_job", None)
        if callable(stop):
            # 只发出中断请求，不等待任务结束：卡死的任务不能阻断更新。
            stop()
        try:
            self._launch_worker()
            self.close_window()
        except Exception as exc:
            with self.jobs.lock, self.lock:
                journal = self.state.get("transaction")
                if journal:
                    (Path(journal).parent / "cancelled").touch()
                self.jobs.update_pending = False
                self._set(status="ready", message="立即重启未能启动，更新包仍保留，可重试", error=str(exc))
        return self.snapshot()

    def cancel(self):
        if not self.jobs:
            raise RuntimeError("没有待执行的重启更新")
        with self.jobs.lock, self.lock:
            if self.state.get("status") != "waiting":
                raise RuntimeError("仅等待任务结束时可以取消自动重启")
            self._set(status="ready", message="已取消自动重启，更新包仍保留")
            self.jobs.update_pending = False
        return self.snapshot()

    def _wait_idle(self):
        # 不仅看状态：任务线程结束之前还会保存结果和回收执行槽。
        time.sleep(1)
        while True:
            with self.jobs.lock, self.lock:
                if self.state.get("status") != "waiting":
                    return
                active = self.jobs.status in {"running", "stopping"} or (
                    self.jobs.thread is not None and self.jobs.thread.is_alive())
                if not active:
                    self._set(status="restarting", message="任务已结束，正在准备重启更新")
                    break
            time.sleep(0.5)
        try:
            self._launch_worker()
            self.close_window()
        except Exception as exc:
            with self.jobs.lock, self.lock:
                journal = self.state.get("transaction")
                if journal:
                    (Path(journal).parent / "cancelled").touch()
                self.jobs.update_pending = False
                self._set(status="error", message="重启更新未能启动，现有程序未修改", error=str(exc))

    def _launch_worker(self):
        directory = Path(self.state["prepared"])
        manifest = read_json(directory / "package.json")
        validate_payload(directory / "payload", manifest)
        install = paths.install_dir().resolve()
        probe = install / (".qianniu-update-write-" + uuid.uuid4().hex)
        try:
            probe.touch(exist_ok=False)
            probe.unlink()
        except OSError as exc:
            raise RuntimeError("程序安装目录没有写入权限，请先调整目录权限后再更新") from exc
        settings = paths.load_settings()
        runner = directory / "runner"
        runner.mkdir(exist_ok=True)
        internal = install / "_internal"
        runner_size = sum(p.stat().st_size for p in internal.rglob("*") if p.is_file()) + (install / EXE_NAME).stat().st_size
        backup_size = 0
        for name in DIRECTORIES | FILES:
            old = install / name
            backup_size += (sum(p.stat().st_size for p in old.rglob("*") if p.is_file())
                            if old.is_dir() else old.stat().st_size if old.is_file() else 0)
        new_size = sum(info["size"] for info in manifest["files"].values())
        if shutil.disk_usage(directory).free < runner_size + backup_size + new_size + 64 * 1024**2:
            raise RuntimeError("磁盘空间不足以保存更新进程和旧版本备份")
        shutil.copy2(install / EXE_NAME, runner / EXE_NAME)
        shutil.copytree(internal, runner / "_internal", dirs_exist_ok=True)
        journal = directory / "transaction.json"
        transaction = {
            "journal": str(journal), "install": str(install), "stage": str(directory / "payload"),
            "backup": str(directory / "backup"), "manifest": manifest, "parent_pid": os.getpid(),
            "token": uuid.uuid4().hex, "phase": "prepared",
            "protected": [str(paths.appdata_dir()), settings.chrome_profile, settings.results_dir,
                          str(getattr(self.jobs, "workspace_path", "") or "")],
        }
        write_json(journal, transaction)
        with self.lock:
            self._set(transaction=str(journal))
        options = {"creationflags": subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS} if os.name == "nt" else {"start_new_session": True}
        worker_env = os.environ.copy()
        worker_env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        process = subprocess.Popen([str(runner / EXE_NAME), "--apply-update", str(journal)],
                                   cwd=str(runner), env=worker_env, **options)
        deadline = time.monotonic() + 30
        while not (directory / "worker-ready.json").is_file():
            if process.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError("独立更新进程未能启动")
            time.sleep(0.1)


def confirm_boot() -> dict:
    """由已挂载的 React 界面调用；后端进程存活本身不算启动成功。"""
    filename = os.environ.get("QIANNIU_UPDATE_TRANSACTION")
    if not filename:
        return {"ok": True}
    journal = Path(filename).resolve()
    updates = (paths.appdata_dir() / "updates").resolve()
    if not journal.is_relative_to(updates):
        raise RuntimeError("启动确认事务路径无效")
    transaction = read_json(journal)
    if Path(transaction["install"]).resolve() != paths.install_dir().resolve():
        raise RuntimeError("启动确认安装目录不匹配")
    version = current_version()
    if version != transaction["manifest"]["version"]:
        raise RuntimeError("启动的版本与更新版本不匹配")
    write_json(journal.parent / "healthy.json", {"token": transaction["token"], "version": version})
    return {"ok": True, "version": version}


UPDATER = UpdateManager()
