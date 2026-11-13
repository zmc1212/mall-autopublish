"""一键部署 Cloudflare Workers 更新下载地址；只上传现有 ZIP，不打包程序。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desktop.update_worker import digest, read_json, validate_manifest, version_key, write_json
from desktop.updater import open_url
from desktop.version import VERSION

WRANGLER_VERSION = "4.149.0"
CHUNK_SIZE = 24 * 1024**2
MAX_CHUNKS = 40  # 预留元数据请求，保持在免费计划单次调用的请求数限制以内。
WORK = ROOT / ".work" / "cloudflare-updates"
WORKER = ROOT / "cloudflare" / "update-download" / "worker.mjs"
EMPTY_FEED = {"schema": 1, "version": "0.0.0", "url": "", "sha256": "", "size": 0, "notes": "尚未发布更新"}


def say(message):
    print(message, flush=True)


def load_state(work: Path) -> dict:
    path = work / "deployment.json"
    return read_json(path) if path.is_file() else {}


def remove_temporary(path: Path, work: Path):
    target, root = path.resolve(), work.resolve()
    if target == root or not target.is_relative_to(root) or path.is_symlink():
        raise ValueError("拒绝删除部署工作目录以外的路径")
    if path.exists():
        shutil.rmtree(path)


def npx_command() -> list[str]:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("未找到 Node.js，请先安装带 npm 的 Node.js 后重试")
    # 直接运行 npx 的 JavaScript 入口，不通过 cmd 拼接带路径的命令。
    candidates = [Path(node).parent / "node_modules/npm/bin/npx-cli.js",
                  Path(os.environ.get("APPDATA", "")) / "npm/node_modules/npm/bin/npx-cli.js"]
    npx = next((p for p in candidates if p.is_file()), None)
    if not npx:
        raise RuntimeError("未找到 npm/npx，请修复 Node.js 的 npm 安装后重试")
    return [node, str(npx), "--yes", f"wrangler@{WRANGLER_VERSION}"]


class Wrangler:
    def __init__(self, prefix=None):
        self.prefix = prefix or npx_command()

    def run(self, *arguments, timeout=900, input_text=None):
        env = os.environ.copy()
        env["WRANGLER_SEND_METRICS"] = "false"
        env["WRANGLER_WRITE_LOGS"] = "false"  # auth token 的输出不能进入 Wrangler 调试日志。
        process = subprocess.run(self.prefix + list(arguments), cwd=ROOT, env=env, input=input_text,
                                 capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        if process.returncode:
            if arguments[:2] == ("auth", "token"):
                raise RuntimeError("Cloudflare 授权获取失败，请重新登录后重试")
            detail = (process.stderr or process.stdout).strip()
            raise RuntimeError(f"Cloudflare 命令执行失败（{arguments[0]}）：\n{detail}")
        return process.stdout

    def ensure_kv_namespace(self, title: str) -> str:
        """按标题复用 KV namespace，不存在时创建；返回 namespace id。"""
        listing = json.loads(self.run("kv", "namespace", "list", timeout=120) or "[]")
        for item in listing if isinstance(listing, list) else []:
            if str(item.get("title")) == title and item.get("id"):
                return str(item["id"])
        output = self.run("kv", "namespace", "create", title, timeout=180)
        try:
            data = json.loads(output)
        except ValueError:
            data = {}
        namespace_id = str(data.get("id") or data.get("uuid") or "")
        if not namespace_id:
            match = re.search(r'\b([0-9a-f]{32})\b', output)
            namespace_id = match[1] if match else ""
        if not namespace_id:
            raise RuntimeError("Cloudflare 未返回 KV namespace id；请检查账户的 Workers KV 权限")
        return namespace_id

    def put_secret(self, worker_name: str, name: str, value: str, config_file: Path) -> None:
        """以标准输入写入 Worker secret，避免出现在命令行参数与日志里。"""
        self.run("secret", "put", name, "--config", str(config_file), timeout=180, input_text=value + "\n")
        say(f"已写入 Worker secret：{worker_name} / {name}")

    def account(self, requested: str = "") -> str:
        try:
            info = json.loads(self.run("whoami", "--json", timeout=120))
        except RuntimeError as exc:
            # 只有确实未登录才打开授权；网络或权限错误保留原错误。
            if not re.search(r"not (?:logged in|authenticated)|未登录|authentication required", str(exc), re.I):
                raise
            say("首次运行需要授权 Cloudflare；正在使用默认浏览器打开授权页面。")
            subprocess.run(self.prefix + ["login"], cwd=ROOT, check=True)
            info = json.loads(self.run("whoami", "--json", timeout=120))
        if not info.get("loggedIn"):
            raise RuntimeError("Cloudflare 尚未登录，请运行 npx wrangler login 后重试")
        accounts = info.get("accounts") or []
        if requested:
            if not any(a["id"] == requested for a in accounts):
                raise RuntimeError("指定的 Cloudflare 账户不在当前登录账户列表中")
            return requested
        if len(accounts) != 1:
            choices = "\n".join(f"{a['name']}：{a['id']}" for a in accounts)
            raise RuntimeError("当前有多个或没有可用账户，请使用 --account-id 指定：\n" + choices)
        return accounts[0]["id"]

    def api(self, method: str, path: str, body=None):
        # 官方认证入口自动刷新 OAuth；凭据只用于本次请求，不输出、不写文件。
        credentials = json.loads(self.run("auth", "token", "--json", timeout=120))
        headers = {"User-Agent": f"QianniuDeployment/{VERSION}", "Content-Type": "application/json"}
        if credentials.get("type") in {"oauth", "api_token"}:
            headers["Authorization"] = "Bearer " + credentials["token"]
        elif credentials.get("type") == "api_key":
            headers.update({"X-Auth-Key": credentials["key"], "X-Auth-Email": credentials["email"]})
        else:
            raise RuntimeError("不支持当前 Cloudflare 授权方式")
        if not path.startswith("/accounts/") or ".." in path:
            raise ValueError("无效的 Cloudflare 账户 API 路径")
        payload = json.dumps(body).encode("utf-8") if body is not None else None
        request = Request("https://api.cloudflare.com/client/v4" + path, data=payload,
                          headers=headers, method=method)
        try:
            with urlopen(request, timeout=30) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Cloudflare 域名检查失败（HTTP {exc.code}）；请检查当前账户的 Workers 权限") from None
        if result.get("success") is not True:
            errors = "; ".join(str(e.get("message", "")) for e in result.get("errors", []))
            raise RuntimeError("Cloudflare 域名检查失败：" + errors)
        return result["result"]

    def check_domain(self, account: str, worker_name: str, domain: str):
        # Wrangler 非交互部署会自动覆盖冲突 DNS；先调用其只读变更预览，拒绝这种覆盖。
        root = f"/accounts/{account}/workers/scripts/{worker_name}"
        changes = self.api("POST", root + "/domains/changeset?replace_state=true", [{"hostname": domain}])
        if not isinstance(changes, dict) or any(not isinstance(changes.get(k), list)
                                               for k in ("added", "removed", "updated", "conflicting")):
            raise RuntimeError("Cloudflare 未返回有效的域名变更预览，已停止绑定")
        if changes["conflicting"]:
            raise RuntimeError(f"{domain} 已有冲突 DNS 记录，已停止绑定；请选择空闲的子域名")
        if changes["removed"]:
            raise RuntimeError("本次绑定会移除现有 Worker 域名，已停止；请先核对 Cloudflare 域名配置")
        for update in changes["updated"]:
            if update.get("modified"):
                existing = self.api("GET", f"/accounts/{account}/workers/domains/records/{update['id']}")
                if existing.get("service") != worker_name:
                    raise RuntimeError(f"{domain} 已被其他 Worker 使用，已停止绑定")


def verified_package(feed_file: Path, delta: dict | None = None) -> tuple[dict, Path]:
    feed = read_json(feed_file)
    if feed.get("schema") != 1:
        raise ValueError("不支持的 latest.json 格式")
    version_key(feed.get("version"))
    target_version = feed["version"]
    if delta is not None:
        if not isinstance(delta, dict):
            raise ValueError("差量下载信息无效")
        version_key(delta.get("base_version"))
        if version_key(delta["base_version"]) >= version_key(target_version):
            raise ValueError("差量基线版本无效")
        feed = dict(delta, version=target_version)
    # 仅发布与 latest.json 同目录的现成 ZIP，拒绝外部 URL 和路径跳转。
    filename = feed.get("url", "")
    expected = (f"QianniuApp-{target_version}-from-{delta['base_version']}.delta.zip" if delta is not None
                else f"QianniuApp-{target_version}.zip")
    if not isinstance(filename, str) or filename != expected:
        raise ValueError("latest.json 的 url 必须是同目录的 QianniuApp-<版本>.zip 文件名")
    package = feed_file.parent / filename
    if not package.is_file() or package.is_symlink():
        raise ValueError("latest.json 对应的 ZIP 不存在或是链接")
    if (not isinstance(feed.get("size"), int) or isinstance(feed["size"], bool)
            or feed["size"] != package.stat().st_size or not 0 < feed["size"] <= CHUNK_SIZE * MAX_CHUNKS):
        raise ValueError("更新包大小不匹配或超过免费下载服务的 960 MiB 限制")
    if not re.fullmatch(r"[0-9a-f]{64}", str(feed.get("sha256", ""))) or digest(package) != feed["sha256"]:
        raise ValueError("更新 ZIP 的 SHA-256 校验失败，不会发布")
    # 确认内部清单存在且声明的版本一致；完整逐文件校验由客户端执行。
    import zipfile
    with zipfile.ZipFile(package) as archive:
        info = archive.getinfo("update.json")
        if info.file_size > 8 * 1024**2:
            raise ValueError("更新 ZIP 的内部清单过大")
        inner = json.loads(archive.read(info).decode("utf-8-sig"))
        validate_manifest(inner)
        if (inner.get("schema") != (2 if delta is not None else 1)
                or inner.get("version") != feed["version"]
                or (delta is not None and inner["base"]["version"] != delta["base_version"])):
            raise ValueError("更新 ZIP 内部版本与 latest.json 不一致")
    return feed, package


def prepare_assets(assets: Path, feed_file: Path | None, *, existing: Path | None = None) -> dict:
    if existing and existing.is_dir():
        shutil.copytree(existing, assets)
        manifest = read_json(assets / "__updates" / "index.json")
        if manifest.get("schema") != 1 or manifest.get("application") != "QianniuUpdater":
            raise ValueError("部署缓存格式错误，已保留原缓存")
    else:
        assets.mkdir()
        manifest = {"schema": 1, "application": "QianniuUpdater", "feed": dict(EMPTY_FEED), "releases": {}}
    if feed_file:
        feed, package = verified_package(feed_file)
        old = manifest["feed"]
        if version_key(feed["version"]) < version_key(old["version"]):
            raise ValueError("拒绝把已发布的版本回退到旧版本")
        if feed["version"] == old["version"] and feed["sha256"] != old["sha256"]:
            raise ValueError("同一个版本不能发布不同内容，请重新构建以生成新版本号")
        deltas = feed.get("deltas", [])
        if (not isinstance(deltas, list) or len(deltas) > 32
                or not all(isinstance(item, dict) for item in deltas)):
            raise ValueError("差量下载清单无效")
        entries = [(feed, package)] + [verified_package(feed_file, item) for item in deltas]
        published = []
        for entry, item_package in entries:
            sha = entry["sha256"]
            chunk_dir = assets / "__updates" / "chunks" / sha
            chunk_dir.mkdir(parents=True, exist_ok=True)
            chunks = []
            transferred = 0
            checksum = hashlib.sha256()
            with item_package.open("rb") as source:
                for number in range(MAX_CHUNKS):
                    data = source.read(CHUNK_SIZE)
                    if not data:
                        break
                    transferred += len(data)
                    checksum.update(data)
                    target = chunk_dir / f"{number:04d}.bin"
                    target.write_bytes(data)
                    chunks.append("/" + target.relative_to(assets).as_posix())
                if source.read(1) or transferred != entry["size"] or checksum.hexdigest() != sha:
                    raise ValueError("准备上传时更新 ZIP 发生变化，请等待打包完成后重试")
            remote = dict(entry, url=f"/releases/{sha}/{item_package.name}")
            manifest["releases"][sha] = dict(remote, chunks=chunks)
            published.append(remote)
        feed = dict(published[0], deltas=published[1:])
        manifest["feed"] = feed
    # 无新版 ZIP 时也能验收真实的分块下载；此固定测试数据不作为应用更新发布。
    probe = bytes(range(256)) * 256
    probe_sha = hashlib.sha256(probe).hexdigest()
    probe_paths = []
    for number, offset in enumerate(range(0, len(probe), len(probe) // 2)):
        target = assets / "__updates" / "chunks" / probe_sha / f"{number:04d}.bin"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(probe[offset:offset + len(probe) // 2])
        probe_paths.append("/" + target.relative_to(assets).as_posix())
    manifest["download_probe"] = {"url": "/download-check.bin", "size": len(probe),
                                  "sha256": probe_sha, "chunks": probe_paths}
    if sum(1 for p in assets.rglob("*") if p.is_file()) > 19998:
        raise ValueError("部署缓存接近 Workers 免费计划文件数上限，请先归档旧版本")
    write_json(assets / "__updates" / "index.json", manifest)
    return manifest


def normalize_domain(value: str) -> str:
    try:
        domain = value.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except (AttributeError, UnicodeError):
        raise ValueError("请输入完整的更新子域名，例如 updates.example.com") from None
    labels = domain.split(".")
    if (len(labels) < 3 or len(domain) > 253
            or any(not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)):
        raise ValueError("请输入完整的更新子域名，例如 updates.example.com；不能包含协议、端口或路径")
    return domain


def config(account: str, worker_name: str, assets: Path, domain: str = "") -> dict:
    if not re.fullmatch(r"[a-z][a-z0-9-]{2,62}", worker_name):
        raise ValueError("Worker 名称须为 3-63 位小写英文、数字或连字符")
    value = {"name": worker_name, "account_id": account, "main": str(WORKER),
            "compatibility_date": "2026-10-01", "workers_dev": True, "preview_urls": False,
            "assets": {"directory": str(assets), "binding": "ASSETS", "run_worker_first": True}}
    if domain:
        value["routes"] = [{"pattern": normalize_domain(domain), "custom_domain": True}]
    return value


def verify_live(base: str, manifest: dict, attempts: int = 8):
    last = None
    for _ in range(attempts):
        try:
            with open_url(base + "/latest.json", timeout=20) as response:
                online = json.load(response)
            expected = manifest["feed"]
            if online["version"] != expected["version"] or online.get("sha256") != expected.get("sha256"):
                raise RuntimeError("线上版本信息尚未切换完成")
            if expected["version"] != "0.0.0":
                with open_url(base + expected["url"], method="HEAD", timeout=20) as response:
                    if int(response.headers.get("Content-Length", 0)) != expected["size"]:
                        raise RuntimeError("线上 ZIP 大小不匹配")
            probe = manifest.get("download_probe")
            if probe:
                with open_url(base + "/download-check.bin", timeout=20) as response:
                    content = response.read(probe["size"] + 1)
                    if int(response.headers.get("Content-Length", 0)) != probe["size"]:
                        raise RuntimeError("线上测试下载的 Content-Length 不匹配")
                if len(content) != probe["size"] or hashlib.sha256(content).hexdigest() != probe["sha256"]:
                    raise RuntimeError("线上分块下载完整性校验失败")
            return
        except HTTPError as exc:
            if exc.code in (401, 403, 429):
                detail = exc.read(2048).decode("utf-8", "replace").strip()
                ray = exc.headers.get("CF-RAY", "")
                raise RuntimeError(f"公开下载被拒绝（HTTP {exc.code}，{detail}，CF-RAY: {ray}）。"
                                   "请先在 Cloudflare 侧解决访问限制，再重试部署；本次没有写入程序更新地址。") from exc
            last = exc
            time.sleep(2)
        except (OSError, ValueError, KeyError, RuntimeError) as exc:
            last = exc
            time.sleep(2)
    raise RuntimeError(f"Cloudflare 已部署，但线上验证暂未通过，请重试同一个脚本：{last}")


def configure_client(feed_url: str):
    from desktop.paths import settings_path

    path = settings_path()
    data = read_json(path) if path.is_file() else {}
    data["update_feed_url"] = feed_url
    write_json(path, data)  # 只改下载地址，保留所有已有设置字段。


def deploy(args, cli: Wrangler | None = None, work: Path = WORK) -> dict:
    feed_file = args.updates_dir / "latest.json"
    publish = not args.setup_only and feed_file.is_file()
    if publish:
        verified_package(feed_file)  # 本地输入不合格时，不能创建或修改云端资源。
    elif not args.setup_only:
        say("尚无 dist/updates/latest.json：本次只部署下载地址，不生成或发布更新包。")
    work.mkdir(parents=True, exist_ok=True)
    state = load_state(work)
    domain = getattr(args, "domain", None)
    domain = normalize_domain(domain) if domain else state.get("custom_domain", "")
    cli = cli or Wrangler()
    say("[1/4] 检查已有 Cloudflare 登录（首次使用时 npx 可能需要下载部署工具）…")
    account = cli.account(args.account_id or state.get("account_id", ""))
    worker_name = args.name or state.get("worker_name") or "qianniu-updates-" + hashlib.sha256(str(ROOT).encode()).hexdigest()[:6]
    say("已复用 Cloudflare 授权，无需填写 API Key。")
    if domain:
        say("检查更新子域名是否有现有 DNS 或 Worker 冲突：" + domain)
        cli.check_domain(account, worker_name, domain)
    stage = Path(tempfile.mkdtemp(prefix="deploy-", dir=work))
    try:
        say("[2/4] 校验现有更新文件并准备下载服务…")
        cache = work / "assets"
        if state and not cache.is_dir():
            raise RuntimeError("本机部署缓存丢失，已停止部署以免覆盖已发布版本；请恢复 .work/cloudflare-updates/assets")
        manifest = prepare_assets(stage / "assets", feed_file if publish else None, existing=cache)
        config_file = stage / "wrangler.json"
        write_json(config_file, config(account, worker_name, stage / "assets", domain))
        say("[3/4] 部署 Workers 免费下载服务，上传完成后统一切换版本…")
        output = cli.run("deploy", "--config", str(config_file))
        match = re.search(r"https://" + re.escape(worker_name) + r"\.[a-z0-9-]+\.workers\.dev", output)
        if not match:
            raise RuntimeError("部署命令未返回 workers.dev 地址；请确认账户已配置 workers.dev 子域名")
        workers_dev_url = match[0]
        base = "https://" + domain if domain else workers_dev_url
        # 云端切换成功后先保存本机缓存与地址，验证暂时失败也能安全重试。
        previous = work / "assets.previous"
        remove_temporary(previous, work)
        if cache.exists():
            cache.replace(previous)
        (stage / "assets").replace(cache)
        state = {"schema": 1, "account_id": account, "worker_name": worker_name,
                 "url": base, "feed_url": base + "/latest.json", "version": manifest["feed"]["version"],
                 "custom_domain": domain, "workers_dev_url": workers_dev_url,
                 "verified": False,
                 "updated_at": datetime.now(timezone.utc).isoformat()}
        write_json(work / "deployment.json", state)
        remove_temporary(previous, work)
        say("[4/4] 验证公开下载地址…")
        evidence = work / "verification-error.json"
        try:
            verify_live(base, manifest)
        except Exception as exc:
            write_json(evidence, {"url": state["feed_url"], "error": str(exc),
                                  "checked_at": datetime.now(timezone.utc).isoformat()})
            raise
        evidence.unlink(missing_ok=True)
        state["verified"] = True
        write_json(work / "deployment.json", state)
        if not args.no_configure_client:
            configure_client(state["feed_url"])
        say("\n部署成功！程序更新地址：\n" + state["feed_url"])
        if manifest["feed"]["version"] == "0.0.0":
            say("目前尚未发布更新。以后手动完成增量打包，再双击本脚本即可发布。")
        else:
            say("已发布版本：" + manifest["feed"]["version"])
        if not args.no_configure_client:
            say("已写入本机程序的更新地址；后续构建也会自动使用此地址。")
        return state
    finally:
        # 只删除已核验的本次临时目录，保留发布缓存。
        remove_temporary(stage, work)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--updates-dir", type=Path, default=ROOT / "dist" / "updates")
    parser.add_argument("--account-id", default="")
    parser.add_argument("--name", default="")
    parser.add_argument("--domain", help="绑定空闲的 Cloudflare 更新子域名，之后双击脚本会自动复用")
    parser.add_argument("--setup-only", action="store_true", help="只创建/验证下载服务，保留已发布版本")
    parser.add_argument("--no-configure-client", action="store_true", help="不修改本机程序更新地址")
    args = parser.parse_args()
    try:
        deploy(args)
    except Exception as exc:
        say("\n部署未完成：" + str(exc))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
